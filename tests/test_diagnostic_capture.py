"""Evidence retained for the diagnostics download, and the absent-key rule.

`coordinator.data` is `None` until the first successful poll, so an
integration that has never succeeded produces an empty `data` block — which
is the case the download is most often requested for. Three captures fill
that gap: the payload behind a non-live verdict, the verdict and key map, and
what the login response looked like.

The absent-key rule is here too because it decides what counts as a rejection.
Its premise was measured on MC7010 firmware `IRL_H3G_MC7010DV1.0.0B03` on
2026-08-30: a cookieless batch read returned 80 of 80 core and 36 of 36
extended keys with none absent, so a dead session echoes its request back
rather than dropping it.
"""

import asyncio
import json
from datetime import UTC, datetime
from time import monotonic
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.zte_router_5g.api import (
    _CORE_PARAMS,
    ZTEAuthError,
    ZTEConnectionError,
    ZTERouterAPI,
    _classify_session,
)
from custom_components.zte_router_5g.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import MockResponse


def _dead_core(populated: dict[str, str] | None = None) -> dict[str, str]:
    """A dead-session response: every requested key echoed back, blank."""
    payload = dict.fromkeys(_CORE_PARAMS, "")
    payload["imei"] = "864155042229309"
    payload["model_name"] = "MC7010"
    if populated:
        payload.update(populated)
    return payload


@pytest.fixture
def diagnostics_entry(mock_config_entry):
    """A config entry whose coordinator has never produced data."""
    coordinator = MagicMock()
    coordinator.data = None
    coordinator.consecutive_failures = 3
    coordinator.last_update_success = False
    coordinator.last_update_success_time = None
    coordinator.update_interval = None
    coordinator.health_snapshot = {"problem": True, "issues": [], "severity": "error"}
    coordinator.endpoint_failures = {}
    coordinator.api.last_rejection = None
    coordinator.api.login_metadata = {}
    mock_config_entry.runtime_data = coordinator
    object.__setattr__(mock_config_entry, "data", {"model": "MC7010"})
    object.__setattr__(
        mock_config_entry, "options", {"host": "192.168.0.1", "password": "hunter2"}
    )
    return mock_config_entry


# ---------------------------------------------------------------------------
# The absent-key rule
# ---------------------------------------------------------------------------


def test_a_complete_dead_session_response_is_still_expired() -> None:
    """The rule must not blunt the detection it guards."""
    assert _classify_session(_dead_core(), _CORE_PARAMS) == "expired"


def test_a_response_missing_most_of_its_request_is_not_ruled_on() -> None:
    """Losing most of what was asked for is truncation or drift, not expiry."""
    partial = {"network_type": "", "signalbar": "", "imei": "864155042229309"}
    assert _classify_session(partial, _CORE_PARAMS) == "undecidable"


def test_the_rule_is_skipped_when_the_request_is_unknown() -> None:
    """Every caller but the two batch reads passes no key list."""
    partial = {"network_type": "", "signalbar": "", "imei": "864155042229309"}
    assert _classify_session(partial) == "expired"


def test_a_booting_router_is_not_ready_even_when_keys_are_absent() -> None:
    """The absent-key rule suppresses `expired` alone.

    A router still starting up answers blank. Were the rule to run first, a
    device that also omitted keys would be scored as a dead session and
    re-logged-in pointlessly.
    """
    blank = {"network_type": "", "signalbar": "", "imei": ""}
    assert _classify_session(blank, _CORE_PARAMS) == "not_ready"


def test_a_populated_response_is_live_however_much_is_absent() -> None:
    """A working session is never withheld by the guard."""
    partial = {"network_type": "ENDC", "signalbar": "4"}
    assert _classify_session(partial, _CORE_PARAMS) == "live"


# ---------------------------------------------------------------------------
# A and B — what was rejected, and why
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_rejected_payload_is_retained_with_its_verdict(mock_aiohttp_client):
    """The response that caused the failure is otherwise discarded."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "dead"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data=_dead_core()),
        MockResponse(json_data={"LD": "LD"}),
        MockResponse(json_data={"wa_inner_version": "MC7010_V1"}),
        MockResponse(json_data={"RD": "RD"}),
        MockResponse(json_data={"wa_inner_version": "MC7010_V1"}),
        MockResponse(json_data=_dead_core()),
    ]
    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": MagicMock(value="fresh")}
    )

    with pytest.raises(ZTEConnectionError):
        await api.get_all_data()

    assert api.last_rejection is not None
    assert api.last_rejection["verdict"] == "expired"
    assert "imei" in api.last_rejection["keys_populated"]
    assert "network_type" in api.last_rejection["keys_empty"]
    assert api.last_rejection["keys_absent"] == []
    assert api.last_rejection["payload"]["model_name"] == "MC7010"


@pytest.mark.asyncio
async def test_a_live_response_clears_a_previous_rejection(mock_aiohttp_client):
    """A stale rejection must not outlive the fault it describes."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    api.last_rejection = {"verdict": "expired"}
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"network_type": "ENDC", "signalbar": "4"}
    )

    await api.get_all_data()

    assert api.last_rejection is None


@pytest.mark.asyncio
async def test_a_response_that_is_not_json_is_retained_as_a_preview(
    mock_aiohttp_client,
):
    """There is no payload to keep, so the body preview is the evidence."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    # HTML on both passes: the first triggers a renewal, the second has no
    # retry left and raises.
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data=None, headers={"Content-Type": "text/html"}
    )
    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": MagicMock(value="fresh")}
    )

    with pytest.raises(ZTEConnectionError):
        await api.get_all_data()

    assert api.last_rejection is not None
    assert api.last_rejection["verdict"] == "unparsable"
    assert "body_preview" in api.last_rejection


# ---------------------------------------------------------------------------
# C — what the login response looked like
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_metadata_records_the_cookie_name_and_source(
    mock_aiohttp_client,
):
    """Answers, from a diagnostics file alone, whether a cookie was issued."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", None, "password")
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "LD"}),
        MockResponse(json_data={"wa_inner_version": "MC888_V1"}),
        MockResponse(json_data={"wa_inner_version": "MC888_V1"}),
    ]
    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": MagicMock(value="secret_session_value")}
    )

    await api.login()

    meta = api.login_metadata
    assert meta["form_used"] == "LOGIN"
    assert meta["session_cookie_issued"] is True
    assert meta["cookie_names"] == ["stok"]
    assert meta["cookies_replayed"] == ["stok"]
    assert meta["cookies_found_in"] == "response_cookies"


@pytest.mark.asyncio
async def test_login_metadata_records_a_cookieless_login(mock_aiohttp_client):
    """The MC888 Pro case: a session established with no cookie at all."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", None, "password")
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "LD"}),
        MockResponse(json_data={"wa_inner_version": "MC888_V1"}),
        MockResponse(json_data={"wa_inner_version": "MC888_V1"}),
    ]
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "0"}, cookies={}
    )

    await api.login()

    assert api.login_metadata["session_cookie_issued"] is False
    assert api.login_metadata["cookie_names"] == []
    assert api.login_metadata["cookies_replayed"] == []
    assert api.login_metadata["cookies_found_in"] == "none"


@pytest.mark.asyncio
async def test_login_metadata_never_carries_a_cookie_value(mock_aiohttp_client):
    """A session cookie is a live credential and must never be recorded.

    Asserted against the whole serialized structure rather than one field, so
    that a future change routing the value in by another path fails here.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", None, "password")
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "LD"}),
        MockResponse(json_data={"wa_inner_version": "MC888_V1"}),
        MockResponse(json_data={"wa_inner_version": "MC888_V1"}),
    ]
    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": MagicMock(value="secret_session_value")}
    )

    await api.login()

    assert "secret_session_value" not in json.dumps(api.login_metadata)


def test_a_request_of_only_unauthenticated_keys_skips_the_guard() -> None:
    """Nothing authenticated was asked for, so there is no proportion to take."""
    payload = {"network_type": "", "signalbar": "", "imei": "864155042229309"}
    assert _classify_session(payload, ["imei", "model_name"]) == "expired"


@pytest.mark.asyncio
async def test_a_caller_that_declined_recovery_still_gets_an_auth_error(
    mock_aiohttp_client,
):
    """`scripts/hardware_check.py` probes a dead session this way.

    Its assertion on `ZTEAuthError` is the standing hardware proof that expiry
    is detectable, so the refutation path must not take this case with it: a
    caller passing `_retry=False` asked for no recovery, and no re-login has
    been spent.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "dead"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data=_dead_core())

    with pytest.raises(ZTEAuthError, match="Session expired/unauthorized"):
        await api._request(
            "GET", "goform/goform_get_cmd_process", requested=_CORE_PARAMS, _retry=False
        )


@pytest.mark.asyncio
async def test_the_download_carries_the_rejection_sanitized(diagnostics_entry):
    """The retained payload is walked exactly as `data` is.

    A rejected payload is therefore no more revealing than an accepted one,
    which is what makes retaining it acceptable to attach to an issue.
    """
    diagnostics_entry.runtime_data.data = None
    diagnostics_entry.runtime_data.api.last_rejection = {
        "verdict": "expired",
        "keys_populated": ["imei"],
        "keys_empty": ["network_type"],
        "keys_absent": [],
        "payload": {"wan_ipaddr": "10.11.12.13", "network_type": ""},
    }
    diagnostics_entry.runtime_data.api.login_metadata = {
        "form_used": "LOGIN",
        "session_cookie_issued": False,
    }

    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)

    assert result["last_rejection"]["verdict"] == "expired"
    assert result["last_rejection"]["payload"]["wan_ipaddr"] != "10.11.12.13"
    assert result["login"]["session_cookie_issued"] is False
    assert "10.11.12.13" not in json.dumps(result)


@pytest.mark.asyncio
async def test_the_download_carries_a_body_preview_sanitized(diagnostics_entry):
    """A response that was never JSON has a preview instead of a payload."""
    diagnostics_entry.runtime_data.api.last_rejection = {
        "verdict": "unparsable",
        "status": 200,
        "body_preview": "<html>redirect to 10.11.12.13</html>",
    }

    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)

    assert result["last_rejection"]["verdict"] == "unparsable"
    assert "10.11.12.13" not in json.dumps(result)


# ---------------------------------------------------------------------------
# Discovery: names outside the request list
# ---------------------------------------------------------------------------


def test_every_discovery_candidate_is_classified() -> None:
    """An unclassified candidate would be published with its value intact.

    `_sanitize_payload` matches on exact key name, and these are names it does
    not know. The allow-list is the gate: a candidate is either judged safe to
    publish or reported as shape and length. Neither is a default.
    """
    from custom_components.zte_router_5g.const import (
        DISCOVERY_CANDIDATES,
        DISCOVERY_VALUE_SAFE,
    )

    assert set(DISCOVERY_CANDIDATES) >= DISCOVERY_VALUE_SAFE


def test_no_discovery_candidate_is_already_requested() -> None:
    """Discovery exists for names the poll does not carry."""
    from custom_components.zte_router_5g.api import _CORE_PARAMS, _EXTENDED_PARAMS
    from custom_components.zte_router_5g.const import DISCOVERY_CANDIDATES

    requested = set(_CORE_PARAMS) | set(_EXTENDED_PARAMS)
    assert not requested & set(DISCOVERY_CANDIDATES)


def test_a_safe_candidate_publishes_its_value() -> None:
    """Identifying an element needs its value; a name alone will not do it."""
    from custom_components.zte_router_5g.diagnostics import (
        _sanitize_discovery,
        _Tokenizer,
    )

    out = _sanitize_discovery({"lte_band": "20"}, _Tokenizer())
    assert out["values"] == {"lte_band": "20"}
    assert out["verdicts"]["lte_band"] == "vetted"


def test_a_name_matching_a_credential_pattern_is_withheld() -> None:
    """The allow-list cannot gate a mined name — it has no entry by construction.

    Denying by name pattern is what makes publish-by-default safe. The
    2026-07-29 mining artefact contains `pppoe_password`, `wifi_wds_WPAPSK1`,
    `gps_lat` and `msisdn` among the names it recovered.
    """
    from custom_components.zte_router_5g.diagnostics import (
        _sanitize_discovery,
        _Tokenizer,
    )

    out = _sanitize_discovery({"pppoe_password": "hunter2"}, _Tokenizer())
    assert "hunter2" not in str(out)
    assert out["verdicts"]["pppoe_password"] == "denied-name"


def test_a_vetted_name_is_still_swept_for_addresses() -> None:
    """Being vetted is not a licence to publish an address."""
    from custom_components.zte_router_5g.diagnostics import (
        _sanitize_discovery,
        _Tokenizer,
    )

    out = _sanitize_discovery({"lte_band": "10.11.12.13"}, _Tokenizer())
    assert "10.11.12.13" not in str(out)
    assert out["verdicts"]["lte_band"] == "vetted"


def test_an_unvetted_name_carrying_an_address_is_tokenized() -> None:
    """The existing walker runs on every name, vetted or not."""
    from custom_components.zte_router_5g.diagnostics import (
        _sanitize_discovery,
        _Tokenizer,
    )

    out = _sanitize_discovery({"some_new_field": "10.11.12.13"}, _Tokenizer())
    assert "10.11.12.13" not in str(out)
    assert out["verdicts"]["some_new_field"] == "tokenized"


def test_a_non_string_discovery_value_survives() -> None:
    """The router answers numbers on some keys; they are not text to describe."""
    from custom_components.zte_router_5g.diagnostics import (
        _sanitize_discovery,
        _Tokenizer,
    )

    out = _sanitize_discovery({"tx_power": 23}, _Tokenizer())
    assert out["values"] == {"tx_power": 23}


def test_a_missing_discovery_block_is_empty(diagnostics_entry) -> None:
    """Diagnostics must survive an api stand-in without a discovery mapping."""
    from custom_components.zte_router_5g.diagnostics import (
        _sanitize_discovery,
        _Tokenizer,
    )

    assert _sanitize_discovery(None, _Tokenizer()) == {}


def test_shape_descriptions_distinguish_the_three_kinds() -> None:
    """Shape has to carry enough to identify what an element is.

    A counter, an identifier-ish token and free text must not all render the
    same, or the fallback tells the reader nothing.
    """
    from custom_components.zte_router_5g.diagnostics import _describe

    assert _describe("12345") == "<digits, 5 chars>"
    assert _describe("band-20_ca") == "<alphanumeric, 10 chars>"
    assert _describe("Some Carrier Ltd") == "<mixed, 16 chars>"


@pytest.mark.asyncio
async def test_a_failing_discovery_chunk_does_not_stop_the_rest(mock_aiohttp_client):
    """`zte_how_to_access.md` records a chunk timing out and taking a key with it.

    Each chunk is tolerated independently for that reason: one refusing must
    not cost the answers the others already gave.
    """
    from custom_components.zte_router_5g.api import ZTEConnectionError
    from custom_components.zte_router_5g.const import DISCOVERY_CANDIDATES

    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    names = list(DISCOVERY_CANDIDATES[:32])
    answers = [MockResponse(json_data={names[0]: "20"})]
    answers += [ZTEConnectionError("chunk refused")] * 60
    mock_aiohttp_client.get.side_effect = answers

    found, notes = await api.probe_names(
        names, chunk_size=16, deadline=monotonic() + 30
    )

    assert found == {names[0]: "20"}
    assert any("re-probed singly" in note for note in notes)


@pytest.mark.asyncio
async def test_a_non_dict_discovery_response_is_skipped(mock_aiohttp_client):
    """A list or scalar body is not a payload to harvest."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data=["not", "a", "dict"])

    found, _notes = await api.probe_names(
        ["lte_band"], chunk_size=8, deadline=monotonic() + 30
    )
    assert found == {}


# ---------------------------------------------------------------------------
# The download must never fail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagnostics_never_raises_when_every_router_call_fails(
    diagnostics_entry,
):
    """Home Assistant does not wrap `config_entry_diagnostics`.

    An exception escaping is an HTTP 500 and no file at all — worse than any
    partial download, because the user has nothing to attach to the issue.
    """
    coordinator = diagnostics_entry.runtime_data
    coordinator.async_run_discovery = AsyncMock(side_effect=OSError("router gone"))
    coordinator.health_snapshot = {"problem": True}

    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)

    assert isinstance(result, dict)
    assert any("discovery" in err for err in result["errors"])


@pytest.mark.asyncio
async def test_diagnostics_survives_a_closed_aiohttp_session(diagnostics_entry):
    """`RuntimeError("Session is closed")` is neither a ClientError nor a Timeout.

    Home Assistant tears its shared session down on reload, and a download
    taken at that moment used to see the error escape as itself.
    """
    coordinator = diagnostics_entry.runtime_data
    coordinator.async_run_discovery = AsyncMock(
        side_effect=RuntimeError("Session is closed")
    )

    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)

    assert any("RuntimeError" in err for err in result["errors"])


@pytest.mark.asyncio
async def test_the_download_is_json_serializable(diagnostics_entry):
    """Serialization happens after every guard has passed.

    A value that cannot be encoded fails the whole file at the last moment,
    which is why anything read off a collaborator goes through `_scalar`.
    """
    coordinator = diagnostics_entry.runtime_data
    coordinator.async_run_discovery = AsyncMock(return_value={"values": {"a": "1"}})

    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)

    # Round-tripped, not merely dumped: the assertion is that the file a user
    # attaches to an issue survives encoding with its content intact.
    assert json.loads(json.dumps(result)) == result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "pppoe_password",
        "tr069_ServerPassword",
        "tr069_ConnectionRequestPassword",
        "wifi_wds_WPAPSK1",
        "gps_lat",
        "gps_lon",
        "msisdn",
    ],
)
async def test_a_mined_credential_name_is_never_published_with_its_value(name):
    """All seven are in the 2026-07-29 mining artefact.

    `_sweep` catches none of them — an IMSI is bare digits, a password is
    arbitrary text — so the name deny-pattern is what makes publish-by-default
    safe rather than reckless.
    """
    from custom_components.zte_router_5g.diagnostics import (
        _sanitize_discovery,
        _Tokenizer,
    )

    out = _sanitize_discovery({name: "s3cr3t-value"}, _Tokenizer())

    assert "s3cr3t-value" not in json.dumps(out)
    assert out["verdicts"][name] in ("denied-name", "denied-shape", "blob")


def test_a_mined_name_that_is_not_an_identifier_is_never_probed() -> None:
    """The artefact contains the literal `1`.

    Both probe paths interpolate names straight into a URL, so a token
    carrying `&` or `=` would corrupt or inject request parameters.
    """
    from custom_components.zte_router_5g.api import _SAFE_CMD_RE

    for junk in ("1", "ab", "a&b=c", "", "x=1"):
        assert not _SAFE_CMD_RE.fullmatch(junk), junk
    for good in ("lte_band", "wa_inner_version", "Z5g_rsrp"):
        assert _SAFE_CMD_RE.fullmatch(good), good


@pytest.mark.asyncio
async def test_a_timed_out_chunk_is_reprobed_singly(mock_aiohttp_client):
    """A timed-out chunk answers empty defaults for every name in it.

    Per-chunk tolerance saves the other chunks and does nothing for the names
    inside the failed one — which is how a real value was once recorded as
    absent. Re-probing singly converts a timeout into per-name truth.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    names = ["a_one", "b_two", "c_three"]
    mock_aiohttp_client.get.side_effect = [
        TimeoutError("chunk timed out"),
        MockResponse(json_data={"a_one": ""}),
        MockResponse(json_data={"b_two": "42"}),
        MockResponse(json_data={"c_three": ""}),
    ]

    # A timed-out request clears the session, so the re-probe would otherwise
    # spend the queued responses on a fresh login. The stand-in restores the
    # session without touching the transport.
    async def _relogin(*_args, **_kwargs):
        api.session_active = True

    with patch.object(api, "login", side_effect=_relogin):
        found, notes = await api.probe_names(names, chunk_size=3)

    assert found == {"b_two": "42"}
    assert any("re-probed singly" in note for note in notes)


@pytest.mark.asyncio
async def test_the_discovery_budget_curtails_and_records_it(mock_aiohttp_client):
    """A timed-out chunk clears the session, so the next pays a full login.

    Without a ceiling a slow firmware could make a download take minutes.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data={})

    found, notes = await api.probe_names(
        ["a_one", "b_two"], chunk_size=1, deadline=monotonic() - 1
    )

    assert found == {}
    assert any("budget exhausted" in note for note in notes)


# ---------------------------------------------------------------------------
# Mining the router's own web UI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mining_reads_cmd_names_from_the_bundles(mock_aiohttp_client):
    """The UI is a client of this same API; its `cmd` literals are the names.

    A comma-separated `cmd` is split, because the bundles batch reads exactly
    as this integration does.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data=None, text_body="cmd='lte_band' ... cmd=\"a_one,b_two\""
    )

    names, notes = await api.mine_candidate_names()

    assert {"lte_band", "a_one", "b_two"} <= names
    assert any("names" in note for note in notes)


@pytest.mark.asyncio
async def test_mining_records_a_bundle_that_is_missing(mock_aiohttp_client):
    """Not every firmware serves every bundle; a 404 is a note, not a failure."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    mock_aiohttp_client.get.return_value = MockResponse(json_data=None, status=404)

    names, notes = await api.mine_candidate_names()

    assert names == set()
    # The index page is read first and answers 404 too, so its note precedes
    # the per-bundle ones.
    assert any("HTTP 404" in note for note in notes)
    assert any("static list" in note for note in notes)


@pytest.mark.asyncio
async def test_mining_records_a_transport_failure(mock_aiohttp_client):
    """An unreachable bundle must not stop the ones that answer."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    mock_aiohttp_client.get.side_effect = OSError("no route")

    names, notes = await api.mine_candidate_names()

    assert names == set()
    assert any("OSError" in note for note in notes)


@pytest.mark.asyncio
async def test_mining_drops_tokens_that_are_not_cmd_names(mock_aiohttp_client):
    """The 2026-07-29 artefact contains the literal `1`."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data=None, text_body="cmd='1' cmd='ok' cmd='real_name'"
    )

    names, _notes = await api.mine_candidate_names()

    assert names == {"real_name"}


@pytest.mark.asyncio
async def test_run_discovery_logs_in_when_no_session_is_active(mock_aiohttp_client):
    """The user pressed Download Diagnostics; that authorises using the router.

    Declining to log in would return less exactly when the download matters
    most — on a device whose session is broken.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.session_active = False
    mock_aiohttp_client.get.return_value = MockResponse(json_data={})

    async def _login(*_args, **_kwargs):
        api.session_active = True

    with patch.object(api, "login", side_effect=_login):
        result = await api.run_discovery()

    assert result["session"] == "fresh login"


@pytest.mark.asyncio
async def test_run_discovery_reuses_a_live_session(mock_aiohttp_client):
    """No reason to evict anyone when we already hold the session."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data={})

    result = await api.run_discovery()

    assert result["session"] == "existing"


@pytest.mark.asyncio
async def test_run_discovery_records_an_abort_rather_than_raising(
    mock_aiohttp_client,
):
    """It runs inside a download that must produce a file whatever happens."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.session_active = True
    with patch.object(api, "mine_candidate_names", side_effect=OSError("boom")):
        result = await api.run_discovery()

    assert any("discovery aborted" in note for note in result["notes"])


def test_a_coordinate_is_withheld_whatever_the_key_is_called() -> None:
    """A decimal-degree value is location even under an innocuous name."""
    from custom_components.zte_router_5g.diagnostics import (
        _sanitize_discovery,
        _Tokenizer,
    )

    out = _sanitize_discovery({"some_reading": "51.507351"}, _Tokenizer())

    assert "51.507351" not in json.dumps(out)
    assert out["verdicts"]["some_reading"] == "denied-shape"


def test_a_long_value_is_reported_as_a_blob() -> None:
    """Above the blob threshold a value is not a reading and is described."""
    from custom_components.zte_router_5g.diagnostics import (
        _sanitize_discovery,
        _Tokenizer,
    )

    out = _sanitize_discovery({"some_reading": "x" * 300}, _Tokenizer())

    assert out["verdicts"]["some_reading"] == "blob"


def test_a_published_value_is_capped() -> None:
    """A long value is identifiable from its start; an uncapped one bloats."""
    from custom_components.zte_router_5g.diagnostics import (
        _sanitize_discovery,
        _Tokenizer,
    )

    out = _sanitize_discovery({"some_reading": "y" * 150}, _Tokenizer())

    assert len(out["values"]["some_reading"]) == 120


def test_discovery_notes_are_carried_into_the_download() -> None:
    """A note explaining a gap is as diagnostic as a value."""
    from custom_components.zte_router_5g.diagnostics import (
        _sanitize_discovery,
        _Tokenizer,
    )

    out = _sanitize_discovery(
        {"values": {}, "notes": ["service.js: 40 names"], "mined_count": 40},
        _Tokenizer(),
    )

    assert out["notes"] == ["service.js: 40 names"]
    assert out["mined_count"] == 40


def test_a_malformed_discovery_result_is_survivable() -> None:
    """`values` may be absent or the wrong type without costing the file."""
    from custom_components.zte_router_5g.diagnostics import (
        _sanitize_discovery,
        _Tokenizer,
    )

    out = _sanitize_discovery({"values": "not a mapping"}, _Tokenizer())

    assert out["values"] == {}


@pytest.mark.asyncio
async def test_the_budget_stops_the_single_name_reprobe_too(mock_aiohttp_client):
    """The re-probe is one request per name and must respect the same ceiling.

    A chunk that fails queues every name in it for a single re-probe, so a
    failing batch turns one request into many — which is exactly where an
    unbounded pass would run away.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    async def _fail_then_stall(chunk):
        # The first chunk fails, queueing its names; by the time the re-probe
        # starts the deadline has passed.
        await asyncio.sleep(0.05)

    with patch.object(api, "_probe_chunk", side_effect=_fail_then_stall):
        found, notes = await api.probe_names(
            ["a_one", "b_two", "c_three"],
            chunk_size=3,
            deadline=monotonic() + 0.02,
        )

    assert found == {}
    assert any("re-probe" in note for note in notes)


def test_a_section_that_raises_is_recorded_not_raised() -> None:
    """`_guarded` is the synchronous half of the never-fail guarantee.

    Home Assistant does not wrap `config_entry_diagnostics`, so a section that
    raises would otherwise cost the whole file.
    """
    from custom_components.zte_router_5g.diagnostics import _guarded

    errors: list[str] = []

    def _explode():
        raise ValueError("payload is not walkable")

    assert _guarded("data", _explode, errors) is None
    assert errors == ["data: ValueError: payload is not walkable"]


# ---------------------------------------------------------------------------
# Carrier identity in discovery
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "profile_name_ui",
        "m_profile_name",
        "strFullName",
        "strShortName",
        "network_provider_fullname",
        "spn_name_data",
        "rplmn_num",
    ],
)
def test_a_carrier_identity_name_is_never_published(name) -> None:
    """`network_provider` and `wan_apn` are redacted in the payload block.

    Publishing their discovery equivalents was inconsistent as well as
    revealing: an MC7010 answered `profile_name_ui` with the operator's own
    APN profile name, and `rplmn_num` carries MCC and MNC in one value.
    """
    from custom_components.zte_router_5g.diagnostics import (
        _sanitize_discovery,
        _Tokenizer,
    )

    out = _sanitize_discovery({name: "3FWA.ie"}, _Tokenizer())

    assert "3FWA.ie" not in json.dumps(out)
    assert out["verdicts"][name] == "denied-name"


@pytest.mark.asyncio
async def test_a_goform_response_key_is_never_probed(mock_aiohttp_client):
    """`result` reads as a `cmd` literal in the bundles and is not a field."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data=None, text_body="cmd='result' cmd='goformId' cmd='lte_band'"
    )

    names, _notes = await api.mine_candidate_names()

    assert names == {"lte_band"}


@pytest.mark.asyncio
async def test_a_goform_response_key_is_never_harvested(mock_aiohttp_client):
    """A refused chunk echoes `result` back, and it is not telemetry.

    Excluding it from the mined names is not enough: the router returns it in
    the probe response itself.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"result": "failure", "lte_band": "20"}
    )

    found, _notes = await api.probe_names(["lte_band"], chunk_size=1)

    assert found == {"lte_band": "20"}


# ---------------------------------------------------------------------------
# Wider extraction (v3.3.9-dev2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_names_in_array_and_object_literals_are_found(mock_aiohttp_client):
    """The bundles write field names three ways and we read one.

    Measured on the MC7010 bundle: 383 names from the `cmd=` form against 642
    unioned. `lte_rsrq`, `lte_snr`, `signalbar` and `cell_id` appear only in
    the other two — the LTE metrics missing on the MC888 are exactly what the
    narrower extraction cannot reach.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    body = (
        'var a=["wan_active_band","nr5g_pci","lte_snr"];'
        'var b={cell_id:"",lte_rsrq:"",signalbar:""};'
        "cmd='wa_inner_version'"
    )
    mock_aiohttp_client.get.return_value = MockResponse(json_data=None, text_body=body)

    names, _notes = await api.mine_candidate_names()

    assert {"lte_snr", "cell_id", "lte_rsrq", "signalbar"} <= names
    assert "wa_inner_version" in names


@pytest.mark.asyncio
async def test_javascript_scaffolding_is_never_probed(mock_aiohttp_client):
    """A wider net catches function names, CSS classes and element ids."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    body = '"function","prototype","undefined","click","lte_snr"'
    mock_aiohttp_client.get.return_value = MockResponse(json_data=None, text_body=body)

    names, _notes = await api.mine_candidate_names()

    assert names == {"lte_snr"}


@pytest.mark.asyncio
async def test_the_bundle_list_comes_from_the_index_page(mock_aiohttp_client):
    """The static list is a guess: `js/statusBar.js` 404s on both devices."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    index = '<script src="js/unexpected_bundle.js"></script>'
    mock_aiohttp_client.get.return_value = MockResponse(json_data=None, text_body=index)

    _names, notes = await api.mine_candidate_names()

    assert any("scripts named" in note for note in notes)
    requested = [call[0][0] for call in mock_aiohttp_client.get.call_args_list]
    assert any("unexpected_bundle.js" in url for url in requested)


@pytest.mark.asyncio
async def test_an_unreadable_index_falls_back_to_the_static_list(
    mock_aiohttp_client,
):
    """Losing the index must not lose the mining."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    mock_aiohttp_client.get.side_effect = OSError("no route")

    _names, notes = await api.mine_candidate_names()

    assert any("static list" in note for note in notes)


# ---------------------------------------------------------------------------
# Reporting what did not answer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probed_names_that_answered_nothing_are_published(
    mock_aiohttp_client,
):
    """A name the UI uses that the device leaves empty is its own fact.

    It is different from a name that does not exist, and only the first was
    visible before: 406 of 602 probed on the MC888 answered nothing and none
    of them appeared in the download.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data={})

    result = await api.run_discovery()

    assert "probed_no_answer" in result
    assert all(name not in result["values"] for name in result["probed_no_answer"])


def test_the_measurement_note_is_set_before_anything_runs() -> None:
    """An empty key set says nothing about why it is empty.

    The field was published for a release while never being set, so a download
    carried `null` where it should have carried a reason.
    """
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")

    assert isinstance(api.measurement_note, str)
    assert api.measurement_note
    assert api.setup_completed is False


@pytest.mark.asyncio
async def test_the_single_name_reprobe_is_capped(mock_aiohttp_client):
    """A wider net makes most chunks legitimately empty.

    Each queues every name in it for a single re-probe, and 208 were queued on
    one MC7010 run — enough to exhaust the budget before the remaining chunks
    had run. The cap stops the re-probe crowding out work not yet done.
    """
    from custom_components.zte_router_5g.const import DISCOVERY_REPROBE_LIMIT

    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    names = [f"a_name_{i:04d}" for i in range(DISCOVERY_REPROBE_LIMIT * 2)]
    probed: list[list[str]] = []

    async def _record(chunk):
        probed.append(chunk)
        return {}

    with patch.object(api, "_probe_chunk", side_effect=_record):
        _found, notes = await api.probe_names(names, chunk_size=8)

    singles = [c for c in probed if len(c) == 1]
    assert len(singles) == DISCOVERY_REPROBE_LIMIT
    assert any("capped at" in note for note in notes)
