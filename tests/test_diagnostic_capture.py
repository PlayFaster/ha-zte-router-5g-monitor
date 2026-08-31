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

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

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
    api.stok = "stok=dead"
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
    api.stok = "stok=live"
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
    api.stok = "stok=live"
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
    assert meta["stok_found_in"] == "response_cookie"


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
    assert api.login_metadata["stok_found_in"] == "none"


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
    api.stok = "stok=dead"
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
