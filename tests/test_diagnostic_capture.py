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
    _REQUEST_REFUSED,
    _SESSION_LOST,
    ZTEAuthError,
    ZTEConnectionError,
    ZTERouterAPI,
    _classify_session,
)
from custom_components.zte_router_5g.const import (
    CANARY_FALLBACK_EVERY,
    DISCOVERY_MAX_ROUNDS,
    DISCOVERY_RELOGIN_LIMIT,
)
from custom_components.zte_router_5g.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.zte_router_5g.known_names import REFUSABLE_NAMES

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

    found, notes, _unasked, _refused = await api.probe_names(
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

    found, _notes, _unasked, _refused = await api.probe_names(
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
        found, notes, _unasked, _refused = await api.probe_names(names, chunk_size=3)

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

    found, notes, _unasked, _refused = await api.probe_names(
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
async def test_run_discovery_always_starts_a_fresh_session(mock_aiohttp_client):
    """`session_active` is a flag, not a fact.

    The router can discard a session without telling us, and the probe
    suppresses the classification that would otherwise discover it. A pass run
    on a discarded session answered 3 names instead of 90 and still reported
    the session alive at the end.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data={})

    with (
        patch.object(api, "logout", AsyncMock()) as logout,
        patch.object(api, "login", AsyncMock()) as login,
    ):
        result = await api.run_discovery()

    assert result["session"] == "fresh login"
    logout.assert_awaited_once()
    login.assert_awaited_once()


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

    async def _fail_then_stall(chunk, canaries=()):
        # The first chunk fails, queueing its names; by the time the re-probe
        # starts the deadline has passed.
        await asyncio.sleep(0.05)

    with patch.object(api, "_probe_chunk", side_effect=_fail_then_stall):
        found, notes, _unasked, _refused = await api.probe_names(
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
    """A refused chunk echoes `result` back, and it is not sensor data.

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

    found, _notes, _unasked, _refused = await api.probe_names(
        ["lte_band"], chunk_size=1
    )

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

    with (
        patch.object(api, "logout", AsyncMock()),
        patch.object(api, "login", AsyncMock()),
    ):
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
async def test_every_queued_name_is_re_probed(mock_aiohttp_client):
    """No count cap: the wall-clock budget is the only bound that scales.

    A wider net makes most chunks legitimately empty, and each queues every
    name in it for a single re-probe. `DISCOVERY_REPROBE_LIMIT` used to discard
    the queue past 120 names, and those names were then published in
    `probed_no_answer` as though the device had been asked and had said
    nothing. On the reference MC7010 that discarded about a hundred names on
    every pass, and the MC888 key list this work exists to grow was read off
    downloads that did it.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    names = [f"a_name_{i:04d}" for i in range(240)]
    probed: list[list[str]] = []

    async def _record(chunk, canaries=()):
        probed.append(chunk)
        return {}

    with patch.object(api, "_probe_chunk", side_effect=_record):
        _found, notes, unasked, _refused = await api.probe_names(names, chunk_size=8)

    singles = [c for c in probed if len(c) == 1]
    assert len(singles) == len(names), "every queued name is asked on its own"
    assert unasked == [], "nothing was left unasked, so nothing is unproven"
    assert any("re-probed singly over 1 rounds" in note for note in notes)


@pytest.mark.asyncio
async def test_a_name_left_unasked_is_never_reported_as_absent(mock_aiohttp_client):
    """Out of budget is not an answer, and must not read like one."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    async def _blank(chunk, canaries=()):
        return {}

    with patch.object(api, "_probe_chunk", side_effect=_blank):
        _found, notes, unasked, _refused = await api.probe_names(
            [f"a_name_{i:03d}" for i in range(64)],
            chunk_size=8,
            # Already spent: the chunk loop runs, the re-probe cannot.
            deadline=monotonic() - 1,
        )

    assert unasked == [f"a_name_{i:03d}" for i in range(64)]
    assert any("budget exhausted" in note for note in notes)
    # The names come back as unasked, not as absent — an exhausted budget is
    # not an answer and must not read like one.


@pytest.mark.asyncio
async def test_a_failing_name_is_retried_to_the_rounds_ceiling(mock_aiohttp_client):
    """Another round would ask the same names the same way."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    attempts: list[list[str]] = []

    async def _fail(chunk, canaries=()):
        attempts.append(chunk)
        # A failed request is not an answer, so the name goes round again.
        return None if len(chunk) == 1 else {}

    with patch.object(api, "_probe_chunk", side_effect=_fail):
        _found, notes, unasked, _refused = await api.probe_names(
            [f"a_name_{i:03d}" for i in range(16)], chunk_size=8
        )

    singles = [c for c in attempts if len(c) == 1]
    # Every single request fails, so the queue never shortens and the rounds
    # ceiling is what stops it. The names are reported as unasked, because a
    # request that failed is not an answer about the firmware.
    assert len(singles) == 16 * DISCOVERY_MAX_ROUNDS
    assert len(unasked) == 16
    assert any(f"over {DISCOVERY_MAX_ROUNDS} rounds, resolving 0" in n for n in notes)


@pytest.mark.asyncio
async def test_a_round_that_settles_names_earns_another(mock_aiohttp_client):
    """Progress is the queue shortening, by any route.

    A round that establishes fifty names are silent has settled fifty names.
    Ending the loop because none of them *answered* would abandon the few whose
    requests merely failed, which are the ones a retry exists for — and they
    would then be reported as unasked despite being retryable.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    seen: list[str] = []

    async def _one_stubborn_name(chunk, canaries=()):
        if len(chunk) > 1:
            return {}
        seen.append(chunk[0])
        # Everything settles as silent except one, which fails until round 3.
        if chunk[0] != "a_name_003":
            return {}
        return None if seen.count("a_name_003") < 3 else {"a_name_003": "42"}

    with patch.object(api, "_probe_chunk", side_effect=_one_stubborn_name):
        found, notes, unasked, _refused = await api.probe_names(
            [f"a_name_{i:03d}" for i in range(16)], chunk_size=8
        )

    assert found == {"a_name_003": "42"}
    assert unasked == []
    assert any("over 3 rounds" in note for note in notes)


@pytest.mark.asyncio
async def test_write_commands_are_recorded_and_never_probed(mock_aiohttp_client):
    """`goformId` names are write commands, not read fields.

    The wider extraction harvests them as quoted strings like any other name,
    and 81 of 520 probed on an MC7010 were write commands answering nothing.
    They cost probe budget and re-probe slots, and a name the firmware does
    not accept as a `cmd` can time out the chunk carrying it.

    Subtracted by name rather than by shape: excluding every uppercase token
    would risk dropping a genuine read name.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    body = (
        "goformId='ADD_PORT_MAP' goformId:\"ALG_SETTING\" "
        '"ADD_PORT_MAP","ALG_SETTING","lte_snr"'
    )
    mock_aiohttp_client.get.return_value = MockResponse(json_data=None, text_body=body)

    names, notes = await api.mine_candidate_names()

    assert names == {"lte_snr"}
    assert set(api.goform_ids) == {"ADD_PORT_MAP", "ALG_SETTING"}
    assert any("write commands excluded" in note for note in notes)


@pytest.mark.asyncio
async def test_an_uppercase_read_name_is_not_excluded(mock_aiohttp_client):
    """Only names the bundles declare as `goformId` are subtracted.

    `Z5g_CELL_ID` and `ODU_led_switch` are read fields this integration
    already requests, and a shape rule would have dropped them.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    body = 'goformId=\'ADD_PORT_MAP\' "Z5g_CELL_ID","ODU_led_switch","DIAG_URL"'
    mock_aiohttp_client.get.return_value = MockResponse(json_data=None, text_body=body)

    names, _notes = await api.mine_candidate_names()

    assert {"Z5g_CELL_ID", "ODU_led_switch", "DIAG_URL"} <= names
    assert "ADD_PORT_MAP" not in names


# ---------------------------------------------------------------------------
# Discovery probes are not session evidence (v3.3.9-dev4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_empty_probe_response_is_not_read_as_an_expired_session(
    mock_aiohttp_client,
):
    """A chunk of names the firmware does not implement answers blank.

    That is the expected answer — "this device does not report these" — and
    classifying it cost a re-login and a replay per chunk. On the reference
    MC7010, 142 of 187 chunks failed that way; suppressing the verdict took a
    pass from 63 seconds to 16 with the same 90 names answered.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"a_one": "", "b_two": ""}
    )

    found, _notes, _unasked, _refused = await api.probe_names(
        ["a_one", "b_two"], chunk_size=2
    )

    assert found == {}
    # No login was posted, and the session was left alone. The chunk and its
    # two single re-probes are the only reads; the four-request shape was one
    # chunk plus a login plus a replay.
    assert mock_aiohttp_client.post.call_count == 0
    assert api.session_active
    assert api.cookies == {"stok": "live"}


@pytest.mark.asyncio
async def test_the_poll_still_classifies_an_empty_response(mock_aiohttp_client):
    """Suppression is for the probe alone, never for a mandatory read."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "dead"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data=dict.fromkeys(_CORE_PARAMS, "")
    )
    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": MagicMock(value="fresh")}
    )

    with pytest.raises(ZTEConnectionError):
        await api.get_all_data()


@pytest.mark.asyncio
async def test_the_session_is_checked_after_a_discovery_pass(mock_aiohttp_client):
    """The pass runs unclassified, so a death partway would go unnoticed.

    Everything after it would record as "no answer", which reads as firmware
    that does not report those names. One classified read at the end says
    which happened.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={_CORE_PARAMS[0]: "value", "wan_connect_status": "connected"}
    )

    with (
        patch.object(api, "logout", AsyncMock()),
        patch.object(api, "login", AsyncMock()),
    ):
        result = await api.run_discovery()

    assert result["session_alive_after"] is True
    # The canary is chosen from what the device answered, never hardcoded.
    assert result["canaries"][0] == _CORE_PARAMS[0]


@pytest.mark.asyncio
async def test_a_dead_session_after_the_pass_is_recorded_not_raised(
    mock_aiohttp_client,
):
    """The download must produce a file whatever the answer."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    with (
        patch.object(api, "logout", AsyncMock()),
        patch.object(api, "login", AsyncMock()),
        patch.object(api, "get_params", side_effect=OSError("gone")),
    ):
        result = await api.run_discovery()

    assert result["session_alive_after"] is False


# ---------------------------------------------------------------------------
# A pass must never be silently degraded (v3.3.9-dev5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_chunk_read_without_a_session_is_not_recorded_as_absent(
    mock_aiohttp_client,
):
    """The defect this closes, from two downloads taken a minute apart.

    One answered 3 names and the other 90, from the same device with the same
    code. The first ran on a session the router had discarded: every chunk
    came back blank, and with classification suppressed nothing noticed. It
    recorded 559 names as "this firmware does not report these" when the truth
    was "we were not logged in".
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    # The canary is blank, which is what an unauthenticated read looks like.
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"a_one": "", "b_two": "", "lte_rsrp": ""}
    )

    with patch.object(
        api, "_reestablish_session", AsyncMock(return_value=True)
    ) as recover:
        found, notes, _unasked, _refused = await api.probe_names(
            ["a_one", "b_two"], chunk_size=2, canaries=["lte_rsrp"]
        )

    # A detected loss is not merely recorded — the pass tries to recover it.
    assert recover.await_count == 1
    assert found == {}
    assert any("without a session" in note for note in notes)


@pytest.mark.asyncio
async def test_a_live_canary_lets_a_blank_chunk_stand(mock_aiohttp_client):
    """A blank answer beside a live canary is a real answer about the firmware."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"a_one": "", "b_two": "", "lte_rsrp": "-96"}
    )

    found, notes, _unasked, _refused = await api.probe_names(
        ["a_one", "b_two"], chunk_size=2, canaries=["lte_rsrp"]
    )

    assert found == {}
    assert not any("without a session" in note for note in notes)


@pytest.mark.asyncio
async def test_the_canary_is_never_published_as_a_discovered_value(
    mock_aiohttp_client,
):
    """It rides in every chunk and is not part of the answer."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"a_one": "20", "lte_rsrp": "-96"}
    )

    found, _notes, _unasked, _refused = await api.probe_names(
        ["a_one"], chunk_size=1, canaries=["lte_rsrp"]
    )

    assert found == {"a_one": "20"}


@pytest.mark.asyncio
async def test_no_canary_is_recorded_rather_than_assumed(mock_aiohttp_client):
    """A device answering almost nothing has no canary to offer.

    Recorded, because a pass without one cannot detect a session lost partway
    and a reader should know that.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data=dict.fromkeys(_CORE_PARAMS, "")
    )

    with (
        patch.object(api, "logout", AsyncMock()),
        patch.object(api, "login", AsyncMock()),
    ):
        result = await api.run_discovery()

    assert result["canaries"] == []


@pytest.mark.asyncio
async def test_an_unauthenticated_key_is_never_chosen_as_the_canary(
    mock_aiohttp_client,
):
    """A key the device answers without a session proves nothing about one."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    api.unauthenticated_keys = frozenset({"imei", "model_name"})
    payload = dict.fromkeys(_CORE_PARAMS, "")
    payload["imei"] = "864155042229309"
    payload["signalbar"] = "4"
    mock_aiohttp_client.get.return_value = MockResponse(json_data=payload)

    canary, _census = await api._pick_canaries(None)

    assert canary == ["signalbar"]


@pytest.mark.asyncio
async def test_the_measured_set_overrides_the_stored_one_for_the_canary(
    mock_aiohttp_client,
):
    """The measurement taken this pass wins over the one taken at setup.

    The stored set falls back to five names measured on a single MC7010 when
    no measurement was ever trusted. An MC888 Pro answers `network_type` and
    `ppp_status` without a session (issue #56), so against the constant those
    look like valid canaries — and a canary the device serves unauthenticated
    answers in every chunk, reporting a healthy session for the whole of a
    pass that lost one.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    # What setup stored, and what this device actually does, disagree.
    api.unauthenticated_keys = frozenset({"imei"})
    payload = dict.fromkeys(_CORE_PARAMS, "")
    payload["network_type"] = "LTE"
    payload["signalbar"] = "4"
    mock_aiohttp_client.get.return_value = MockResponse(json_data=payload)

    against_stored, _s = await api._pick_canaries(None)
    against_measured, _m = await api._pick_canaries(
        None, sessionless=frozenset({"imei", "network_type"})
    )

    assert against_stored[0] == "network_type", "the stored set allows it"
    assert "network_type" not in against_measured, "the measurement rules it out"


@pytest.mark.asyncio
async def test_a_pass_measures_the_sessionless_keys_before_logging_back_in(
    mock_aiohttp_client,
):
    """The measurement is only honest inside the pass's own logout window."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get_response = MockResponse(
        json_data={_CORE_PARAMS[0]: "value", "wan_connect_status": "connected"}
    )
    order: list[str] = []

    async def _measure(timeout_sec=None):
        order.append("measured")
        api.measurement_note = "measured: 6 keys"
        return frozenset({"imei"})

    async def _login(*_args, **_kwargs):
        order.append("login")

    with (
        patch.object(api, "logout", AsyncMock()),
        patch.object(api, "login", side_effect=_login),
        patch.object(api, "measure_unauthenticated_keys", side_effect=_measure),
    ):
        result = await api.run_discovery()

    assert order[:2] == ["measured", "login"]
    assert result["sessionless_measurement"] == "measured: 6 keys"
    # The fresh reading replaces whatever setup left behind.
    assert api.unauthenticated_keys == frozenset({"imei"})


@pytest.mark.asyncio
async def test_one_canary_going_quiet_is_not_a_lost_session(mock_aiohttp_client):
    """A single key emptying is a radio changing state, not an eviction.

    With one canary that reads as a lost session, and several hundred names
    are re-probed for nothing. Requiring every canary to go silent makes a
    false positive need a simultaneous coincidence across unrelated keys.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"a_one": "", "b_two": "", "lte_rsrp": "", "signalbar": "4"}
    )

    found, notes, _unasked, _refused = await api.probe_names(
        ["a_one", "b_two"], chunk_size=2, canaries=["lte_rsrp", "signalbar"]
    )

    assert found == {}
    assert not any("read without a session" in note for note in notes)


@pytest.mark.asyncio
async def test_every_canary_going_quiet_is_a_lost_session(mock_aiohttp_client):
    """All silent together is the signature an eviction actually leaves."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"a_one": "", "b_two": "", "lte_rsrp": "", "signalbar": ""}
    )

    with patch.object(api, "_reestablish_session", AsyncMock(return_value=True)):
        _found, notes, _unasked, _refused = await api.probe_names(
            ["a_one", "b_two"], chunk_size=2, canaries=["lte_rsrp", "signalbar"]
        )

    assert any("2 names read without a session" in note for note in notes)
    assert any("session re-established 1 times" in note for note in notes)


@pytest.mark.asyncio
async def test_the_canary_census_says_why_none_was_found(mock_aiohttp_client):
    """No canary has two causes, and they call for different responses."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    payload = dict.fromkeys(_CORE_PARAMS, "")
    payload["network_type"] = "LTE"
    payload["ppp_status"] = "connected"
    mock_aiohttp_client.get.return_value = MockResponse(json_data=payload)

    canaries, census = await api._pick_canaries(
        None, sessionless=frozenset({"network_type", "ppp_status"})
    )

    assert canaries == []
    assert census["populated"] == 2
    assert census["served_without_a_session"] == 2
    assert census["chosen"] == 0


@pytest.mark.asyncio
async def test_a_canaryless_device_confirms_the_session_out_of_band(
    mock_aiohttp_client,
):
    """No canary means no proof inside the request, so the check leaves it.

    Such a device answers every key it has without a session — which is why
    nothing qualified as a canary — so a blank chunk is indistinguishable from
    an evicted one until something else is asked.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data={"a": "", "b": ""})

    with (
        patch.object(api, "_session_still_alive", AsyncMock(return_value=False)),
        patch.object(api, "_reestablish_session", AsyncMock(return_value=False)),
    ):
        _found, notes, _unasked, _refused = await api.probe_names(
            [f"name_{n}" for n in range(CANARY_FALLBACK_EVERY * 2)],
            chunk_size=2,
            canaries=[],
        )

    assert any("session confirmed out of band" in note for note in notes)
    assert any("read without a session" in note for note in notes)


@pytest.mark.asyncio
async def test_the_out_of_band_check_is_rate_limited(mock_aiohttp_client):
    """Blank chunks are the common case; checking every one doubles the pass."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data={"a": "", "b": ""})
    alive = AsyncMock(return_value=True)

    with patch.object(api, "_session_still_alive", alive):
        await api.probe_names(
            [f"name_{n}" for n in range(CANARY_FALLBACK_EVERY * 4)],
            chunk_size=2,
            canaries=[],
        )

    # Two checks for sixteen blank chunks, not sixteen.
    assert alive.await_count == 2


@pytest.mark.asyncio
async def test_a_device_with_canaries_never_pays_for_the_fallback(
    mock_aiohttp_client,
):
    """The extra round trip is confined to devices that cannot be guarded."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"a": "", "b": "", "signalbar": "4"}
    )
    alive = AsyncMock(return_value=True)

    with patch.object(api, "_session_still_alive", alive):
        await api.probe_names(
            [f"name_{n}" for n in range(CANARY_FALLBACK_EVERY * 4)],
            chunk_size=2,
            canaries=["signalbar"],
        )

    assert alive.await_count == 0


@pytest.mark.asyncio
async def test_a_re_established_session_is_proved_before_it_is_believed(
    mock_aiohttp_client,
):
    """`session_active` is a flag this code sets; the canaries are evidence.

    Believing the flag is the whole class of fault this release is unpicking,
    so a login is read back through the same canaries that detected the loss.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data={"signalbar": "4"})

    with (
        patch.object(api, "logout", AsyncMock()),
        patch.object(api, "login", AsyncMock()),
    ):
        assert await api._reestablish_session(["signalbar"]) is True


@pytest.mark.asyncio
async def test_a_login_whose_canaries_stay_silent_is_not_a_session(
    mock_aiohttp_client,
):
    """A login that returns cleanly and changes nothing is still a failure."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data={"signalbar": ""})

    with (
        patch.object(api, "logout", AsyncMock()),
        patch.object(api, "login", AsyncMock()),
    ):
        assert await api._reestablish_session(["signalbar"]) is False


@pytest.mark.asyncio
async def test_a_failed_recovery_is_recorded_and_the_pass_continues(
    mock_aiohttp_client,
):
    """A download must produce a file whatever the router does."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"a_one": "", "b_two": "", "lte_rsrp": ""}
    )

    with patch.object(api, "_reestablish_session", AsyncMock(return_value=False)):
        _found, notes, _unasked, _refused = await api.probe_names(
            ["a_one", "b_two"], chunk_size=2, canaries=["lte_rsrp"]
        )

    assert any("could not be re-established 1 times" in note for note in notes)


@pytest.mark.asyncio
async def test_the_relogin_limit_is_reported_when_it_is_reached(
    mock_aiohttp_client,
):
    """A sustained competitor is reported, not fought to the budget's end.

    Something else holding the single session this hardware permits will win
    every race, and the names read after that point were read without a
    confirmed session — which the file has to say.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data=dict.fromkeys(["a", "b", "lte_rsrp"], "")
    )

    with patch.object(
        api, "_reestablish_session", AsyncMock(return_value=False)
    ) as recover:
        _found, notes, _unasked, _refused = await api.probe_names(
            [f"name_{n}" for n in range(DISCOVERY_RELOGIN_LIMIT * 4)],
            chunk_size=2,
            canaries=["lte_rsrp"],
        )

    assert recover.await_count == DISCOVERY_RELOGIN_LIMIT
    assert any("re-login limit reached" in note for note in notes)


@pytest.mark.asyncio
async def test_a_canaryless_device_recovers_through_the_out_of_band_check(
    mock_aiohttp_client,
):
    """No canary still gets a recovery — it is just proved differently."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data={"a": "", "b": ""})

    with (
        patch.object(api, "_session_still_alive", AsyncMock(return_value=False)),
        patch.object(api, "_reestablish_session", AsyncMock(return_value=True)),
    ):
        _found, notes, _unasked, _refused = await api.probe_names(
            [f"name_{n}" for n in range(CANARY_FALLBACK_EVERY * 4)],
            chunk_size=2,
            canaries=[],
        )

    assert any("session re-established" in note for note in notes)


# ---------------------------------------------------------------------------
# A router that declines a request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_declined_chunk_is_not_read_as_a_lost_session(mock_aiohttp_client):
    """A refusal blanks the canaries too, and would otherwise look identical.

    Measured on the reference MC7010 on 2026-09-02: `tr069_CPEPortNo` answers
    `{"result": "failure"}` in 40-60 ms and carries none of the requested keys,
    including the canaries. Before this was handled, every pass re-established
    a session it had never lost, twice.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data={"result": "failure"})

    with patch.object(
        api, "_reestablish_session", AsyncMock(return_value=True)
    ) as recover:
        _found, notes, _unasked, refused = await api.probe_names(
            ["a_one", "b_two"], chunk_size=2, canaries=["lte_rsrp"]
        )

    assert recover.await_count == 0, "a refusal is not a session problem"
    assert not any("read without a session" in note for note in notes)
    assert any("declined by the router" in note for note in notes)
    # Both names were asked singly afterwards and both were declined.
    assert refused == ["a_one", "b_two"]


@pytest.mark.asyncio
async def test_a_declined_name_is_neither_silent_nor_unasked(mock_aiohttp_client):
    """The firmware knows the name and will not serve it, which is a statement.

    An unknown name is echoed back empty by this API, so a refusal is the
    opposite fact from an absence and must not be filed as one.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data={"result": "failure"})

    found, _notes, unasked, refused = await api.probe_names(
        ["tr069_ServerURL"], chunk_size=1
    )

    assert refused == ["tr069_ServerURL"]
    assert found == {}
    assert unasked == [], "it was asked, and answered"


@pytest.mark.asyncio
async def test_a_refusable_name_that_answers_is_published(mock_aiohttp_client):
    """Holding a name out of a chunk is not a claim that it will be declined."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"tr069_CPEPortNo": "7547"}
    )

    found, _notes, _unasked, refused = await api.probe_names(
        ["tr069_CPEPortNo"], chunk_size=1
    )

    assert found == {"tr069_CPEPortNo": "7547"}
    assert refused == []


@pytest.mark.asyncio
async def test_refusable_names_never_share_a_request(mock_aiohttp_client):
    """One declined name takes the whole request with it, so they go alone."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    mock_aiohttp_client.get_response = MockResponse(
        json_data={_CORE_PARAMS[0]: "value", "wan_connect_status": "connected"}
    )
    requests: list[list[str]] = []

    async def _record(chunk, canaries=()):
        requests.append(list(chunk))
        return {}

    with (
        patch.object(api, "logout", AsyncMock()),
        patch.object(api, "login", AsyncMock()),
        patch.object(api, "_probe_chunk", side_effect=_record),
        patch.object(api, "mine_candidate_names", AsyncMock(return_value=(set(), []))),
    ):
        await api.run_discovery()

    shared = [
        request
        for request in requests
        if len(request) > 1 and set(request) & REFUSABLE_NAMES
    ]
    assert shared == [], f"a refusable name shared a request: {shared[:2]}"


def test_the_two_sentinels_are_distinguished_by_identity() -> None:
    """Both are empty dicts, so equality would conflate them with a real answer.

    A successful chunk whose only populated keys were the canaries also returns
    an empty dict, and comparing with `==` reported it as a lost session.
    """
    assert _SESSION_LOST is not _REQUEST_REFUSED
    assert _SESSION_LOST == _REQUEST_REFUSED == {}
