"""The expected-outage window.

A command the router accepted, a reboot or a data disconnect, takes it offline
for a known reason. For that window the coordinator skips its polls, and every
other router request is refused at once instead of waiting out a 15-second
timeout. A check reads one key every few seconds; when the router answers, a
full poll runs, and the window closes only when that poll succeeds. A cap
closes it regardless, so a router that never returns is still reported.

These tests cover the gate in the API client and the window in the
coordinator. The entities that open the window are covered in
`test_data_connection.py`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g import web_sources
from custom_components.zte_router_5g.api import (
    ExpectedOutage,
    ZTEConnectionError,
    ZTERouterAPI,
    ZTERouterExpectedUnavailableError,
)
from custom_components.zte_router_5g.const import (
    CONF_STOP_POLLING,
    DOMAIN,
    OUTAGE_CAP_DATA_DISCONNECT,
    OUTAGE_HOLD,
    OUTAGE_REASON_DATA_CONNECT,
    OUTAGE_REASON_DATA_DISCONNECT,
    OUTAGE_REASON_REBOOT,
)
from custom_components.zte_router_5g.coordinator import ZTERouterDataUpdateCoordinator
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .conftest import MockResponse

GOOD_DATA = {
    "network_type": "ENDC",
    "signalbar": "4",
    "wa_inner_version": "xx_xxx_MC7010DV1.0.0B01",
    "realtime_time": "3600",
    "wan_connect_status": "pdp_connected",
}

_CALL_LATER = "custom_components.zte_router_5g.coordinator.async_call_later"


def _api(session: MagicMock | None = None) -> ZTERouterAPI:
    """A real client, holding a session it never reaches unless told to."""
    return ZTERouterAPI(session or MagicMock(), "192.168.0.1", "admin", "password")


# --------------------------------------------------------------------------
# The window record
# --------------------------------------------------------------------------


def test_a_window_reports_the_seconds_left_and_expires_at_its_cap() -> None:
    """Whole seconds, rounded up, and never negative."""
    with patch("custom_components.zte_router_5g.api.monotonic", return_value=100.0):
        outage = ExpectedOutage(
            reason=OUTAGE_REASON_REBOOT, opened_at=MagicMock(), deadline=130.4
        )
        assert outage.seconds_remaining() == 31
        assert outage.expired is False

    with patch("custom_components.zte_router_5g.api.monotonic", return_value=131.0):
        assert outage.seconds_remaining() == 0
        assert outage.expired is True


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------


def test_nothing_is_refused_without_a_window() -> None:
    """The gate is inert until a window opens."""
    api = _api()

    api.refuse_during_outage()

    assert api.expected_outage is None


def test_an_open_window_refuses_with_its_reason_and_time_left() -> None:
    """The refusal carries what the on-screen message needs."""
    api = _api()
    api.open_expected_outage(OUTAGE_REASON_DATA_DISCONNECT, 60)

    with pytest.raises(ZTERouterExpectedUnavailableError) as err:
        api.refuse_during_outage()

    assert err.value.reason == OUTAGE_REASON_DATA_DISCONNECT
    assert 0 < err.value.seconds_remaining <= 60
    # A subclass, so every handler of an unreachable router handles it.
    assert isinstance(err.value, ZTEConnectionError)


def test_a_window_past_its_cap_refuses_nothing() -> None:
    """A lost timer must not leave requests refused indefinitely."""
    api = _api()
    api.open_expected_outage(OUTAGE_REASON_REBOOT, -1)

    api.refuse_during_outage()

    assert api.expected_outage is not None


def test_the_bypass_lets_only_its_own_block_through() -> None:
    """The window's own check and closing poll pass; nothing after them does."""
    api = _api()
    api.open_expected_outage(OUTAGE_REASON_REBOOT, 60)

    with api.outage_bypass():
        api.refuse_during_outage()

    with pytest.raises(ZTERouterExpectedUnavailableError):
        api.refuse_during_outage()


def test_closing_the_window_accepts_requests_again() -> None:
    """Closing clears the record the gate reads."""
    api = _api()
    api.open_expected_outage(OUTAGE_REASON_REBOOT, 60)

    api.close_expected_outage()

    api.refuse_during_outage()
    assert api.expected_outage is None


async def test_a_request_is_refused_before_anything_is_sent(
    mock_aiohttp_client,
) -> None:
    """Sending would only wait out the full timeout on a silent router."""
    api = _api(mock_aiohttp_client)
    api.open_expected_outage(OUTAGE_REASON_REBOOT, 60)

    with pytest.raises(ZTERouterExpectedUnavailableError):
        await api._request("GET", "goform/goform_get_cmd_process?cmd=signalbar")

    mock_aiohttp_client.get.assert_not_called()
    mock_aiohttp_client.post.assert_not_called()


async def test_a_login_is_refused_without_ending_the_current_session() -> None:
    """The refusal comes before `login` clears the session it would replace."""
    api = _api()
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.open_expected_outage(OUTAGE_REASON_DATA_DISCONNECT, 60)

    with pytest.raises(ZTERouterExpectedUnavailableError):
        await api.login()

    assert api.session_active is True
    assert api.cookies == {"stok": "live"}


async def test_protocol_detection_is_refused(mock_aiohttp_client) -> None:
    """One of the router calls that bypasses `_request`, so gated separately."""
    api = _api(mock_aiohttp_client)
    api.open_expected_outage(OUTAGE_REASON_REBOOT, 60)

    with pytest.raises(ZTERouterExpectedUnavailableError):
        await api.try_set_protocol()

    mock_aiohttp_client.get.assert_not_called()


async def test_a_web_source_fetch_is_recorded_as_missed(mock_aiohttp_client) -> None:
    """The crawl records a fetch that did not complete; a refusal is one."""
    api = _api(mock_aiohttp_client)
    api.open_expected_outage(OUTAGE_REASON_REBOOT, 60)

    status, headers, body = await web_sources._fetch_text(api, "js/service.js")

    assert status is None
    assert headers == []
    assert "ZTERouterExpectedUnavailableError" in body
    mock_aiohttp_client.get.assert_not_called()


# --------------------------------------------------------------------------
# The check
# --------------------------------------------------------------------------


async def test_the_check_passes_the_gate_and_reports_an_answer(
    mock_aiohttp_client,
) -> None:
    """One key, answered without a session, while the window is open."""
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"opms_wan_mode": "LTE_BRIDGE"}
    )
    api = _api(mock_aiohttp_client)
    api.open_expected_outage(OUTAGE_REASON_REBOOT, 60)

    assert await api.outage_probe() is True

    url = mock_aiohttp_client.get.call_args[0][0]
    assert "cmd=opms_wan_mode" in url
    # The bypass ends with the check.
    with pytest.raises(ZTERouterExpectedUnavailableError):
        api.refuse_during_outage()


async def test_a_silent_router_is_a_no_not_an_error(mock_aiohttp_client) -> None:
    """A check that cannot reach the router answers `False`."""
    mock_aiohttp_client.get.side_effect = aiohttp.ClientConnectionError("down")
    api = _api(mock_aiohttp_client)
    api.open_expected_outage(OUTAGE_REASON_REBOOT, 60)

    assert await api.outage_probe() is False


async def test_an_answer_that_is_not_a_mapping_is_no_answer() -> None:
    """Only a parsed response counts as the router answering."""
    api = _api()

    with patch.object(api, "_request", AsyncMock(return_value="<html>")):
        assert await api.outage_probe() is False


# --------------------------------------------------------------------------
# The coordinator's window
# --------------------------------------------------------------------------


@pytest.fixture
def entry() -> MockConfigEntry:
    """A config entry with credentials in options."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="864155042229309",
        title="ZTE 5G",
        data={"imei": "864155042229309"},
        options={
            CONF_HOST: "192.168.0.1",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "password",
        },
    )


def _wired_api() -> MagicMock:
    """A mocked client whose window methods behave like the real ones."""
    real = _api()
    api = MagicMock(spec=ZTERouterAPI)
    api.expected_outage = None
    api.get_all_data = AsyncMock(return_value=dict(GOOD_DATA))
    api.get_extended_data = AsyncMock(return_value={})
    api.get_sms_capacity = AsyncMock(return_value={})
    api.get_sms_messages = AsyncMock(return_value=[])
    api.login = AsyncMock(return_value="stok=test")
    api.outage_probe = AsyncMock(return_value=True)

    def _open(reason: str, cap: float) -> ExpectedOutage:
        api.expected_outage = real.open_expected_outage(reason, cap)
        return api.expected_outage

    def _close() -> None:
        api.expected_outage = None

    api.open_expected_outage.side_effect = _open
    api.close_expected_outage.side_effect = _close
    api.outage_bypass.side_effect = real.outage_bypass
    return api


async def _ready(
    hass: HomeAssistant, entry: MockConfigEntry, **options: object
) -> ZTERouterDataUpdateCoordinator:
    """A coordinator that has completed one successful poll."""
    if options:
        entry = MockConfigEntry(
            domain=entry.domain,
            version=entry.version,
            unique_id=entry.unique_id,
            title=entry.title,
            data=dict(entry.data),
            options={**entry.options, **options},
        )
    entry.add_to_hass(hass)
    coordinator = ZTERouterDataUpdateCoordinator(hass, entry, _wired_api())
    await coordinator.async_refresh()
    assert coordinator.last_update_success_time is not None
    coordinator.api.get_all_data.reset_mock()
    return coordinator


async def test_a_poll_during_the_window_touches_nothing(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Held values, no fetch, no timestamp, no strike."""
    coordinator = await _ready(hass, entry)
    before = coordinator.last_update_success_time
    held = dict(coordinator.data)
    with patch(_CALL_LATER, return_value=MagicMock()):
        coordinator.async_open_expected_outage(OUTAGE_REASON_REBOOT, 60)

    await coordinator.async_refresh()

    coordinator.api.get_all_data.assert_not_awaited()
    assert coordinator.data == held
    assert coordinator.last_update_success_time == before
    assert coordinator.consecutive_failures == 0
    assert coordinator.outage_active is True


async def test_opening_records_the_window_and_arms_the_check(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The record is what the diagnostics download publishes."""
    coordinator = await _ready(hass, entry)

    with patch(_CALL_LATER, return_value=MagicMock()) as call_later:
        coordinator.async_open_expected_outage(
            OUTAGE_REASON_DATA_DISCONNECT, OUTAGE_CAP_DATA_DISCONNECT
        )

    call_later.assert_called_once()
    record = coordinator.last_expected_outage
    assert record is not None
    assert record["reason"] == OUTAGE_REASON_DATA_DISCONNECT
    assert record["cap_seconds"] == OUTAGE_CAP_DATA_DISCONNECT
    assert record["checks"] == 0
    assert record["closed"] is None


async def test_the_window_closes_when_the_router_answers_and_a_poll_succeeds(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A successful full poll is the one close condition for every reason."""
    coordinator = await _ready(hass, entry)
    with patch(_CALL_LATER, return_value=MagicMock()):
        coordinator.async_open_expected_outage(OUTAGE_REASON_REBOOT, 60)

    with patch(_CALL_LATER, return_value=MagicMock()) as call_later:
        await coordinator._async_outage_check()

    coordinator.api.get_all_data.assert_awaited()
    assert coordinator.api.expected_outage is None
    record = coordinator.last_expected_outage
    assert record is not None
    assert record["closed_by"] == "answer"
    assert record["checks"] == 1
    assert record["closed"] is not None
    call_later.assert_not_called()


async def test_a_failed_closing_poll_keeps_the_window_and_counts_nothing(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A router still starting up fails the poll; that is not a fault."""
    coordinator = await _ready(hass, entry)
    held = dict(coordinator.data)
    with patch(_CALL_LATER, return_value=MagicMock()):
        coordinator.async_open_expected_outage(OUTAGE_REASON_REBOOT, 60)
    coordinator.api.get_all_data.side_effect = ZTEConnectionError("starting up")

    with patch(_CALL_LATER, return_value=MagicMock()) as call_later:
        await coordinator._async_outage_check()

    assert coordinator.api.expected_outage is not None
    assert coordinator.consecutive_failures == 0
    assert coordinator.health_snapshot.get("problem") is False
    assert coordinator.data == held
    call_later.assert_called_once()


async def test_a_silent_router_rearms_the_check_without_polling(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """No answer, no poll; the next check is armed."""
    coordinator = await _ready(hass, entry)
    with patch(_CALL_LATER, return_value=MagicMock()):
        coordinator.async_open_expected_outage(OUTAGE_REASON_REBOOT, 60)
    coordinator.api.outage_probe.return_value = False

    with patch(_CALL_LATER, return_value=MagicMock()) as call_later:
        await coordinator._async_outage_check()

    coordinator.api.get_all_data.assert_not_awaited()
    assert coordinator.last_expected_outage["checks"] == 1
    call_later.assert_called_once()


async def test_the_cap_closes_the_window_and_resumes_polling(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """After the cap, normal failure counting reports a router that never returned."""
    coordinator = await _ready(hass, entry)
    with patch(_CALL_LATER, return_value=MagicMock()):
        coordinator.async_open_expected_outage(OUTAGE_REASON_REBOOT, -1)
    coordinator.async_request_refresh = AsyncMock()

    await coordinator._async_outage_check()

    assert coordinator.api.expected_outage is None
    assert coordinator.last_expected_outage["closed_by"] == "cap"
    coordinator.api.outage_probe.assert_not_awaited()
    coordinator.async_request_refresh.assert_awaited_once()


async def test_a_check_after_the_window_closed_does_nothing(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A timer that fires late finds no window and leaves."""
    coordinator = await _ready(hass, entry)

    await coordinator._async_outage_check()

    coordinator.api.outage_probe.assert_not_awaited()
    assert coordinator.last_expected_outage is None


async def test_the_closing_poll_runs_while_polling_is_paused(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A paused entry would otherwise hold the window open until the cap."""
    coordinator = await _ready(hass, entry, **{CONF_STOP_POLLING: True})
    with patch(_CALL_LATER, return_value=MagicMock()):
        coordinator.async_open_expected_outage(OUTAGE_REASON_REBOOT, 60)

    await coordinator._async_outage_check()

    coordinator.api.get_all_data.assert_awaited()
    assert coordinator.api.expected_outage is None


async def test_opening_again_replaces_the_armed_check(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """One check armed at a time."""
    coordinator = await _ready(hass, entry)
    first = MagicMock()
    with patch(_CALL_LATER, side_effect=[first, MagicMock()]):
        coordinator.async_open_expected_outage(OUTAGE_REASON_DATA_DISCONNECT, 60)
        coordinator.async_open_expected_outage(OUTAGE_REASON_REBOOT, 240)

    first.assert_called_once()
    assert coordinator.last_expected_outage["reason"] == OUTAGE_REASON_REBOOT


async def test_shutdown_disarms_the_check(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """No timer outlives the coordinator."""
    coordinator = await _ready(hass, entry)
    unsub = MagicMock()
    with patch(_CALL_LATER, return_value=unsub):
        coordinator.async_open_expected_outage(OUTAGE_REASON_REBOOT, 60)

    await coordinator.async_shutdown()

    unsub.assert_called_once()
    assert coordinator._outage_unsub is None


async def test_a_value_that_is_not_a_window_is_no_window(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A stand-in client never reads as an open window."""
    coordinator = await _ready(hass, entry)
    coordinator.api.expected_outage = MagicMock()

    assert coordinator.outage_active is False


async def test_a_window_opened_without_its_record_still_closes(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A window opened on the client directly has no record to update."""
    coordinator = await _ready(hass, entry)
    coordinator.api.open_expected_outage(OUTAGE_REASON_REBOOT, 60)

    await coordinator._async_outage_check()

    assert coordinator.api.expected_outage is None
    assert coordinator.last_expected_outage is None


# --------------------------------------------------------------------------
# 3.4.1-dev5: two phases, history, follow-up
# --------------------------------------------------------------------------
#
# Measured on the MC7010 on 2026-09-23: the router kept answering for 11 to
# 12 s after `CONNECT_NETWORK` and 4 to 8 s after `DISCONNECT_NETWORK`, then
# stopped. A window that closed on the first answer closed before the outage.

_MONOTONIC = "custom_components.zte_router_5g.coordinator.monotonic"


async def _data_window(hass, entry, reason=OUTAGE_REASON_DATA_CONNECT):
    coordinator = await _ready(hass, entry)
    # Settled for a turn-on, so a close arms no follow-up unless a test says so.
    coordinator.api.get_all_data.return_value = {
        **GOOD_DATA,
        "ppp_status": "ppp_connected",
    }
    with patch(_CALL_LATER, return_value=MagicMock()):
        coordinator.async_open_expected_outage(
            reason,
            60,
            command="CONNECT_NETWORK",
            reply={"result": "success", "extra": "dropped"},
            ppp_status_after_reply="ppp_connecting",
        )
    return coordinator


async def test_a_command_window_waits_for_the_drop_and_probes_fast(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """An answer before the drop is the router not yet gone, not back."""
    coordinator = await _data_window(hass, entry)

    with patch(_CALL_LATER, return_value=MagicMock()) as call_later:
        await coordinator._async_outage_check()

    coordinator.api.get_all_data.assert_not_awaited()
    assert coordinator.api.expected_outage is not None
    assert call_later.call_args[0][1] == 1.0


async def test_the_first_silence_records_the_drop_and_slows_the_probe(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """From the drop on, the window waits for the return as before."""
    coordinator = await _data_window(hass, entry)
    coordinator.api.outage_probe.return_value = False

    with patch(_CALL_LATER, return_value=MagicMock()) as call_later:
        await coordinator._async_outage_check()

    assert coordinator.last_expected_outage["down_at"] is not None
    assert call_later.call_args[0][1] == 5.0

    coordinator.api.outage_probe.return_value = True
    await coordinator._async_outage_check()

    record = coordinator.last_expected_outage
    assert coordinator.api.expected_outage is None
    assert record["closed_by"] == "answer"
    assert record["back_at"] is not None
    assert record["outage_seconds"] is not None
    assert record["after"]["ppp_status"] == "ppp_connected"


async def test_no_drop_within_the_hold_closes_as_no_outage(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A router that never went away is not held to the cap."""
    coordinator = await _data_window(hass, entry)

    with patch(_MONOTONIC, return_value=coordinator._outage_opened_mono + OUTAGE_HOLD):
        await coordinator._async_outage_check()

    record = coordinator.last_expected_outage
    assert coordinator.api.expected_outage is None
    assert record["closed_by"] == "no_outage"
    assert record["down_at"] is None
    assert record["outage_seconds"] is None


async def test_the_hold_ends_at_twenty_seconds(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """20 s covers the MC7010's latest measured drop, 12.4 s after the command.

    The MC888 Pro did not drop on either command in the issue #79 3.4.2
    download, so its windows close here; a longer hold only refuses its
    controls for longer.
    """
    coordinator = await _data_window(hass, entry)

    with patch(_MONOTONIC, return_value=coordinator._outage_opened_mono + 20.0):
        await coordinator._async_outage_check()

    record = coordinator.last_expected_outage
    assert coordinator.api.expected_outage is None
    assert record["closed_by"] == "no_outage"


async def test_a_failed_closing_poll_after_the_hold_keeps_the_window(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The hold ends the wait for a drop, not the need for a good poll."""
    coordinator = await _data_window(hass, entry)
    coordinator.api.get_all_data.side_effect = ZTEConnectionError("not yet")

    with (
        patch(_MONOTONIC, return_value=coordinator._outage_opened_mono + OUTAGE_HOLD),
        patch(_CALL_LATER, return_value=MagicMock()) as call_later,
    ):
        await coordinator._async_outage_check()

    assert coordinator.api.expected_outage is not None
    call_later.assert_called_once()


async def test_a_reboot_window_starts_with_the_drop_recorded(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """`reboot()` returns only after the router went away."""
    coordinator = await _ready(hass, entry)
    with patch(_CALL_LATER, return_value=MagicMock()) as call_later:
        coordinator.async_open_expected_outage(OUTAGE_REASON_REBOOT, 240)

    record = coordinator.last_expected_outage
    assert record["down_at"] == record["opened"]
    assert call_later.call_args[0][1] == 5.0


async def test_the_record_keeps_the_command_and_the_state_before(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The reply is reduced to its `result`; nothing else a firmware adds."""
    coordinator = await _data_window(hass, entry)

    record = coordinator.last_expected_outage
    assert record["command"] == "CONNECT_NETWORK"
    assert record["reply"] == {"result": "success"}
    assert record["ppp_status_after_reply"] == "ppp_connecting"
    assert set(record["before"]) == {
        "ppp_status",
        "network_type",
        "dial_mode",
        "opms_wan_mode",
    }


async def test_a_reply_that_is_not_a_dict_is_recorded_as_none(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A mocked or odd reply leaves no field."""
    coordinator = await _ready(hass, entry)
    coordinator.data = None
    with patch(_CALL_LATER, return_value=MagicMock()):
        coordinator.async_open_expected_outage(OUTAGE_REASON_REBOOT, 60, reply="ok")

    assert coordinator.last_expected_outage["reply"] is None
    assert coordinator.last_expected_outage["before"] is None


async def test_only_the_last_five_windows_are_kept(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A bounded history, oldest dropped first."""
    coordinator = await _ready(hass, entry)
    with patch(_CALL_LATER, return_value=MagicMock()):
        for cap in range(7):
            coordinator.async_open_expected_outage(OUTAGE_REASON_REBOOT, 60 + cap)

    caps = [r["cap_seconds"] for r in coordinator.expected_outages]
    assert caps == [62, 63, 64, 65, 66]


async def test_a_data_window_closing_on_connecting_arms_one_follow_up(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Connected came up to 15 s after the router answered again."""
    coordinator = await _data_window(hass, entry)
    coordinator.api.get_all_data.return_value = {
        **GOOD_DATA,
        "ppp_status": "ppp_connecting",
    }
    coordinator.api.outage_probe.return_value = False
    with patch(_CALL_LATER, return_value=MagicMock()):
        await coordinator._async_outage_check()
    coordinator.api.outage_probe.return_value = True
    unsub = MagicMock()

    with patch(_CALL_LATER, return_value=unsub) as call_later:
        await coordinator._async_outage_check()

    delay, callback = call_later.call_args[0][1:]
    assert delay == 10.0
    coordinator.async_force_refresh = AsyncMock()
    await callback(None)
    coordinator.async_force_refresh.assert_awaited_once()
    assert coordinator._outage_followup_unsub is None


async def test_no_follow_up_once_connected_or_for_a_reboot(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A settled state, or a window that is not the switch's, needs none."""
    coordinator = await _ready(hass, entry)
    coordinator.api.get_all_data.return_value = {
        **GOOD_DATA,
        "ppp_status": "ppp_connecting",
    }
    with patch(_CALL_LATER, return_value=MagicMock()):
        coordinator.async_open_expected_outage(OUTAGE_REASON_REBOOT, 60)

    with patch(_CALL_LATER, return_value=MagicMock()) as call_later:
        await coordinator._async_outage_check()

    call_later.assert_not_called()


async def test_a_new_window_and_shutdown_cancel_the_follow_up(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """No follow-up outlives the next command or the coordinator."""
    coordinator = await _ready(hass, entry)
    first, second = MagicMock(), MagicMock()
    coordinator._outage_followup_unsub = first
    with patch(_CALL_LATER, return_value=MagicMock()):
        coordinator.async_open_expected_outage(OUTAGE_REASON_DATA_CONNECT, 60)
    first.assert_called_once()

    coordinator._outage_followup_unsub = second
    await coordinator.async_shutdown()
    second.assert_called_once()


async def test_the_open_reason_and_the_closing_flag_are_exposed(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The switch reads both to decide whether to hold its position."""
    coordinator = await _ready(hass, entry)
    assert coordinator.outage_reason is None
    assert coordinator.outage_closing is False

    with patch(_CALL_LATER, return_value=MagicMock()):
        coordinator.async_open_expected_outage(OUTAGE_REASON_DATA_CONNECT, 60)

    assert coordinator.outage_reason == OUTAGE_REASON_DATA_CONNECT


async def test_a_drop_without_a_record_still_moves_to_the_return_phase(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The phase follows the router; the record only reports it."""
    coordinator = await _data_window(hass, entry)
    coordinator.expected_outages.clear()
    coordinator.api.outage_probe.return_value = False

    with patch(_CALL_LATER, return_value=MagicMock()) as call_later:
        await coordinator._async_outage_check()

    assert coordinator._outage_awaiting_drop is False
    assert call_later.call_args[0][1] == 5.0


# --------------------------------------------------------------------------
# 3.4.2-dev6: a follow-up whenever the closing poll is not settled
# --------------------------------------------------------------------------
#
# Measured on the MC7010 on 2026-09-23: one turn-off's closing poll read
# `ppp_connected`, and the next refresh, 5 s later, read `ppp_disconnected`.


@pytest.mark.parametrize(
    ("reason", "status", "armed"),
    [
        (OUTAGE_REASON_DATA_CONNECT, "ppp_connected", False),
        (OUTAGE_REASON_DATA_CONNECT, "ipv6_connected", False),
        (OUTAGE_REASON_DATA_CONNECT, "ppp_connecting", True),
        (OUTAGE_REASON_DATA_CONNECT, "ppp_disconnected", True),
        (OUTAGE_REASON_DATA_DISCONNECT, "ppp_disconnected", False),
        (OUTAGE_REASON_DATA_DISCONNECT, "ppp_connected", True),
        (OUTAGE_REASON_DATA_DISCONNECT, "ppp_disconnecting", True),
        (OUTAGE_REASON_DATA_DISCONNECT, None, True),
    ],
)
async def test_a_follow_up_is_armed_only_when_the_close_is_unsettled(
    hass: HomeAssistant, entry: MockConfigEntry, reason, status, armed
) -> None:
    """Settled means the state the command leads to; anything else is re-read."""
    coordinator = await _data_window(hass, entry, reason)
    coordinator.api.get_all_data.return_value = {**GOOD_DATA, "ppp_status": status}
    coordinator.api.outage_probe.return_value = False
    with patch(_CALL_LATER, return_value=MagicMock()):
        await coordinator._async_outage_check()
    coordinator.api.outage_probe.return_value = True

    with patch(_CALL_LATER, return_value=MagicMock()) as call_later:
        await coordinator._async_outage_check()

    assert coordinator.api.expected_outage is None
    assert call_later.called is armed


async def test_an_unsettled_close_still_closes_the_window(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The follow-up never holds controls refused: a failed turn-on closes too."""
    coordinator = await _data_window(hass, entry)
    coordinator.api.get_all_data.return_value = {
        **GOOD_DATA,
        "ppp_status": "ppp_disconnected",
    }
    coordinator.api.outage_probe.return_value = False
    with patch(_CALL_LATER, return_value=MagicMock()):
        await coordinator._async_outage_check()
    coordinator.api.outage_probe.return_value = True

    with patch(_CALL_LATER, return_value=MagicMock()):
        await coordinator._async_outage_check()

    assert coordinator.outage_reason is None
    assert coordinator.last_expected_outage["closed_by"] == "answer"
    assert coordinator.last_expected_outage["after"]["ppp_status"] == "ppp_disconnected"
