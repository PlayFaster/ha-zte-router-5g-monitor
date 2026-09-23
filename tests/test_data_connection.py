"""The Data Connection switch, the connection-state sensors, and refusals.

The switch turns the router's data connection on or off. The router answers
the command before the change completes, so the switch confirms from one
immediate read of `ppp_status` and, on turn-off, opens the expected-outage
window. While a window is open every other action is refused with an
on-screen error naming the reason; those mappings are covered here too.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import ServiceCall
from homeassistant.exceptions import HomeAssistantError

from custom_components.zte_router_5g.api import (
    ZTEConnectionError,
    ZTERouterAPI,
    ZTERouterExpectedUnavailableError,
)
from custom_components.zte_router_5g.button import (
    DELETE_SMS_DESCRIPTION,
    REBOOT_DESCRIPTION,
    REFRESH_DESCRIPTION,
    ZTEDeleteAllSMSButton,
    ZTERebootButton,
    ZTERefreshButton,
)
from custom_components.zte_router_5g.const import (
    OUTAGE_CAP_DATA_DISCONNECT,
    OUTAGE_CAP_REBOOT,
    OUTAGE_REASON_DATA_DISCONNECT,
    OUTAGE_REASON_REBOOT,
)
from custom_components.zte_router_5g.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.zte_router_5g.helpers import expected_outage_error
from custom_components.zte_router_5g.select import (
    ZTERouterSelect,
    ZTESelectEntityDescription,
)
from custom_components.zte_router_5g.sensor import SENSOR_TYPES
from custom_components.zte_router_5g.switch import (
    _ENTITY_CLASS,
    SWITCH_TYPES,
    ZTEDataConnectionSwitch,
    ZTERouterSwitch,
    ZTESwitchEntityDescription,
)

_DATA_CONNECTION = next(d for d in SWITCH_TYPES if d.key == "data_connection")
_REFUSED_REBOOT = ZTERouterExpectedUnavailableError(OUTAGE_REASON_REBOOT, 42)
_REFUSED_DATA = ZTERouterExpectedUnavailableError(OUTAGE_REASON_DATA_DISCONNECT, 17)


def _sensor(key: str) -> Any:
    return next(d for d in SENSOR_TYPES if d.key == key)


def _switch(
    mock_coordinator, mock_config_entry, status: Any
) -> ZTEDataConnectionSwitch:
    """A Data Connection switch whose immediate read returns `status`."""
    mock_coordinator.api = MagicMock()
    mock_coordinator.api.set_data_connection = AsyncMock()
    if isinstance(status, Exception):
        mock_coordinator.api.get_params = AsyncMock(side_effect=status)
    else:
        mock_coordinator.api.get_params = AsyncMock(return_value={"ppp_status": status})
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_coordinator.async_open_expected_outage = MagicMock()
    switch = ZTEDataConnectionSwitch(
        mock_coordinator, mock_config_entry, _DATA_CONNECTION
    )
    # What the entity reports at the moment it publishes, not afterwards.
    switch.published = []
    switch.async_write_ha_state = MagicMock(
        side_effect=lambda: switch.published.append(switch.is_on)
    )
    return switch


# --------------------------------------------------------------------------
# The switch
# --------------------------------------------------------------------------


def test_the_data_connection_switch_is_built_by_its_own_class() -> None:
    """The generic entity would verify by read-back and report a refusal."""
    assert _ENTITY_CLASS["data_connection"] is ZTEDataConnectionSwitch
    assert _DATA_CONNECTION.verify_after_write is False
    assert _DATA_CONNECTION.state_key == "ppp_status"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ppp_connected", True),
        ("ipv6_connected", True),
        ("ipv4_ipv6_connected", True),
        ("ppp_connecting", False),
        ("ppp_disconnecting", False),
        ("ppp_disconnected", False),
    ],
)
def test_the_switch_reads_on_only_for_a_connected_value(status, expected) -> None:
    """The three values the router's own page treats as connected."""
    assert _DATA_CONNECTION.value_fn({"ppp_status": status}) is expected


def test_the_switch_reads_off_without_data() -> None:
    """No payload is no connection to report."""
    assert _DATA_CONNECTION.value_fn({}) is False
    assert _DATA_CONNECTION.value_fn(None) is False


async def test_turning_off_confirms_and_opens_the_window(
    mock_coordinator, mock_config_entry
) -> None:
    """`ppp_disconnecting` confirms the command; the router then goes quiet."""
    switch = _switch(mock_coordinator, mock_config_entry, "ppp_disconnecting")
    switch._last_known = True

    await switch.async_turn_off()

    mock_coordinator.api.set_data_connection.assert_awaited_once_with(False)
    assert switch.published == [False]
    mock_coordinator.async_open_expected_outage.assert_called_once_with(
        OUTAGE_REASON_DATA_DISCONNECT, OUTAGE_CAP_DATA_DISCONNECT
    )
    # The refresh would land in the silent period; the window replaces it.
    mock_coordinator.async_force_refresh.assert_not_awaited()


async def test_turning_on_confirms_from_connecting_and_refreshes(
    mock_coordinator, mock_config_entry
) -> None:
    """Reconnecting has no silent period, so no window opens."""
    switch = _switch(mock_coordinator, mock_config_entry, "ppp_connecting")

    await switch.async_turn_on()

    mock_coordinator.api.set_data_connection.assert_awaited_once_with(True)
    assert switch.published == [True]
    mock_coordinator.async_force_refresh.assert_awaited_once()
    mock_coordinator.async_open_expected_outage.assert_not_called()


@pytest.mark.parametrize(
    "status", [ZTEConnectionError("no answer"), None, "ppp_connected"]
)
async def test_an_unconfirmed_turn_off_still_opens_the_window(
    mock_coordinator, mock_config_entry, status
) -> None:
    """A failed, empty or contradicting read leaves the write unconfirmed.

    The router accepted the command, so it is going offline either way. The
    position is left for the next poll to settle.
    """
    switch = _switch(mock_coordinator, mock_config_entry, status)
    switch._last_known = True

    await switch.async_turn_off()

    assert switch.is_on is True
    assert switch.published == []
    mock_coordinator.async_open_expected_outage.assert_called_once()


async def test_a_refused_data_connection_write_shows_the_outage_message(
    mock_coordinator, mock_config_entry
) -> None:
    """Refused before anything was sent, during another window."""
    switch = _switch(mock_coordinator, mock_config_entry, "ppp_connected")
    mock_coordinator.api.set_data_connection = AsyncMock(side_effect=_REFUSED_REBOOT)

    with pytest.raises(HomeAssistantError) as err:
        await switch.async_turn_on()

    assert err.value.translation_key == "router_restarting"
    mock_coordinator.async_open_expected_outage.assert_not_called()


async def test_a_generic_switch_maps_a_refusal(
    mock_coordinator, mock_config_entry
) -> None:
    """Every router switch shows the outage message, not a generic failure."""

    async def refused(api, state, data):
        raise _REFUSED_DATA

    mock_coordinator.api = MagicMock()
    switch = ZTERouterSwitch(
        mock_coordinator,
        mock_config_entry,
        ZTESwitchEntityDescription(
            key="odu_led_switch", translation_key="t", setter_fn=refused
        ),
    )

    with pytest.raises(HomeAssistantError) as err:
        await switch.async_turn_on()

    assert err.value.translation_key == "router_disconnecting"
    assert err.value.translation_placeholders == {"seconds": "17"}


# --------------------------------------------------------------------------
# The API method
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("on", "command"), [(True, "CONNECT_NETWORK"), (False, "DISCONNECT_NETWORK")]
)
async def test_a_failed_data_connection_write_is_recorded(on, command) -> None:
    """Only the SMS delete path recorded failures before; this one does too."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")

    with (
        patch.object(api, "ad_suffix", AsyncMock(return_value="&AD=x")),
        patch.object(
            api, "_request", AsyncMock(side_effect=ZTEConnectionError("down"))
        ),
        pytest.raises(ZTEConnectionError),
    ):
        await api.set_data_connection(on)

    assert api.write_failures[-1]["command"] == command


async def test_a_refused_data_connection_write_records_nothing() -> None:
    """A refusal sent nothing, so there is no failed write to record."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")

    with (
        patch.object(api, "ad_suffix", AsyncMock(return_value="&AD=x")),
        patch.object(api, "_request", AsyncMock(side_effect=_REFUSED_REBOOT)),
        pytest.raises(ZTERouterExpectedUnavailableError),
    ):
        await api.set_data_connection(False)

    assert api.write_failures == []


async def test_an_accepted_data_connection_write_returns_the_reply() -> None:
    """The router's reply is passed back once it has been checked."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")

    with (
        patch.object(api, "ad_suffix", AsyncMock(return_value="&AD=x")),
        patch.object(api, "_request", AsyncMock(return_value={"result": "success"})),
        patch.object(api, "_require_write_success", AsyncMock()),
    ):
        assert await api.set_data_connection(True) == {"result": "success"}


# --------------------------------------------------------------------------
# Sensors
# --------------------------------------------------------------------------


def test_the_renamed_sensor_reads_the_data_connection_state() -> None:
    """Formerly "Bridge Mode"; the value is the data connection's state."""
    description = _sensor("data_connection_status")

    assert (
        description.value_fn({"ppp_status": "ppp_disconnected"}) == "ppp_disconnected"
    )
    assert not any(d.key == "ppp_status" for d in SENSOR_TYPES)


def test_connection_mode_status_shows_the_raw_value() -> None:
    """Raw values, as every sensor here; the note explains them."""
    description = _sensor("connection_mode_status")

    assert description.value_fn({"dial_mode": "auto_dial"}) == "auto_dial"
    assert description.value_fn({"dial_mode": ""}) is None


# --------------------------------------------------------------------------
# The error
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("refusal", "key"),
    [(_REFUSED_REBOOT, "router_restarting"), (_REFUSED_DATA, "router_disconnecting")],
)
def test_each_reason_has_its_own_message(refusal, key) -> None:
    """A whole translated sentence per reason, with the time left."""
    error = expected_outage_error(refusal)

    assert error.translation_key == key
    assert error.translation_placeholders == {"seconds": str(refusal.seconds_remaining)}


# --------------------------------------------------------------------------
# Buttons and select
# --------------------------------------------------------------------------


async def test_a_confirmed_reboot_opens_the_window(
    mock_coordinator, mock_config_entry
) -> None:
    """`reboot()` returns only once the router has gone quiet."""
    mock_coordinator.api = MagicMock()
    mock_coordinator.api.reboot = AsyncMock(return_value=200)
    mock_coordinator.async_open_expected_outage = MagicMock()
    button = ZTERebootButton(mock_coordinator, mock_config_entry, REBOOT_DESCRIPTION)

    await button.async_press()

    mock_coordinator.async_open_expected_outage.assert_called_once_with(
        OUTAGE_REASON_REBOOT, OUTAGE_CAP_REBOOT
    )


async def test_a_refused_reboot_opens_nothing(
    mock_coordinator, mock_config_entry
) -> None:
    """Pressed again during a window, it shows the message instead."""
    mock_coordinator.api = MagicMock()
    mock_coordinator.api.reboot = AsyncMock(side_effect=_REFUSED_REBOOT)
    mock_coordinator.async_open_expected_outage = MagicMock()
    button = ZTERebootButton(mock_coordinator, mock_config_entry, REBOOT_DESCRIPTION)

    with pytest.raises(HomeAssistantError) as err:
        await button.async_press()

    assert err.value.translation_key == "router_restarting"
    mock_coordinator.async_open_expected_outage.assert_not_called()


async def test_refresh_now_is_refused_rather_than_skipped(
    mock_coordinator, mock_config_entry
) -> None:
    """A skipped poll would return held values and look like it worked."""
    mock_coordinator.api = MagicMock()
    mock_coordinator.api.refuse_during_outage = MagicMock(side_effect=_REFUSED_DATA)
    mock_coordinator.async_force_refresh = AsyncMock()
    button = ZTERefreshButton(mock_coordinator, mock_config_entry, REFRESH_DESCRIPTION)

    with pytest.raises(HomeAssistantError) as err:
        await button.async_press()

    assert err.value.translation_key == "router_disconnecting"
    mock_coordinator.async_force_refresh.assert_not_awaited()


async def test_delete_all_maps_a_refusal(mock_coordinator, mock_config_entry) -> None:
    """The delete-all button shows the outage message too."""
    mock_coordinator.api = MagicMock()
    mock_coordinator.api.delete_all = AsyncMock(side_effect=_REFUSED_REBOOT)
    button = ZTEDeleteAllSMSButton(
        mock_coordinator, mock_config_entry, DELETE_SMS_DESCRIPTION
    )

    with pytest.raises(HomeAssistantError) as err:
        await button.async_press()

    assert err.value.translation_key == "router_restarting"


async def test_a_select_maps_a_refusal(mock_coordinator, mock_config_entry) -> None:
    """The APN and network selects show the outage message."""

    def refused(api, option, data):
        raise _REFUSED_REBOOT

    mock_coordinator.data = {}
    mock_coordinator.api = MagicMock()
    select = ZTERouterSelect(
        mock_coordinator,
        mock_config_entry,
        ZTESelectEntityDescription(
            key="apn_profile",
            translation_key="signal_apn_profile",
            options_fn=lambda data: [],
            value_fn=lambda data: None,
            setter_fn=refused,
        ),
    )

    with pytest.raises(HomeAssistantError) as err:
        await select.async_select_option("any")

    assert err.value.translation_key == "router_restarting"


# --------------------------------------------------------------------------
# Services
# --------------------------------------------------------------------------


@pytest.fixture
def service_hass(mock_config_entry):
    """A hass stand-in whose only entry holds a mocked coordinator."""
    hass = MagicMock()
    hass.data = {}
    coordinator = MagicMock()
    coordinator.async_force_refresh = AsyncMock()
    coordinator.api = AsyncMock()
    coordinator.api.note_delete_parameter = MagicMock()
    mock_config_entry.runtime_data = coordinator
    hass.config_entries.async_entries.return_value = [mock_config_entry]
    return hass, coordinator


def _call(data: dict[str, Any]) -> MagicMock:
    call = MagicMock(spec=ServiceCall)
    call.data = data
    return call


async def test_send_sms_refused_before_anything_went(service_hass) -> None:
    """Nothing sent, so the outage message is the whole story."""
    from custom_components.zte_router_5g import async_send_sms

    hass, coordinator = service_hass
    coordinator.api.send_sms.side_effect = _REFUSED_REBOOT

    with pytest.raises(HomeAssistantError) as err:
        await async_send_sms(hass, _call({"target": ["+1"], "message": "hi"}))

    assert err.value.translation_key == "router_restarting"


async def test_send_sms_refused_part_way_reports_what_went(service_hass) -> None:
    """Once a message has gone, the partial result matters more."""
    from custom_components.zte_router_5g import async_send_sms

    hass, coordinator = service_hass
    coordinator.api.send_sms.side_effect = [None, _REFUSED_REBOOT]

    with pytest.raises(HomeAssistantError) as err:
        await async_send_sms(hass, _call({"target": ["+1", "+2"], "message": "hi"}))

    assert err.value.translation_key == "send_sms_failed"


@pytest.mark.parametrize(
    ("service", "method", "data"),
    [
        ("async_delete_sms", "delete_sms", {"index": 5}),
        ("async_delete_all_sms", "delete_all", {"keep_last": 0}),
        (
            "async_get_sms_list",
            "get_sms_messages",
            {"page": 1, "count": 10, "box_type": 1},
        ),
    ],
)
async def test_sms_services_map_a_refusal(service_hass, service, method, data) -> None:
    """Every SMS service shows the outage message."""
    import custom_components.zte_router_5g as integration

    hass, coordinator = service_hass
    getattr(coordinator.api, method).side_effect = _REFUSED_DATA

    with pytest.raises(HomeAssistantError) as err:
        await getattr(integration, service)(hass, _call(data))

    assert err.value.translation_key == "router_disconnecting"


# --------------------------------------------------------------------------
# Diagnostics
# --------------------------------------------------------------------------


async def _download(mock_coordinator, mock_config_entry) -> dict[str, Any]:
    mock_coordinator.data = {}
    mock_coordinator.api.write_failures = []
    mock_config_entry.runtime_data = mock_coordinator
    with patch(
        "custom_components.zte_router_5g.web_sources.crawl",
        new=AsyncMock(return_value={"files": {}, "sources": {}, "fetched": 0}),
    ):
        return await async_get_config_entry_diagnostics(None, mock_config_entry)


async def test_the_last_window_is_published(
    mock_coordinator, mock_config_entry
) -> None:
    """A download taken after a reboot can explain the polls it skipped."""
    record = {
        "reason": OUTAGE_REASON_REBOOT,
        "opened": "2026-09-23T06:00:00+00:00",
        "cap_seconds": OUTAGE_CAP_REBOOT,
        "checks": 9,
        "closed": "2026-09-23T06:01:10+00:00",
        "closed_by": "answer",
    }
    mock_coordinator.last_expected_outage = record

    result = await _download(mock_coordinator, mock_config_entry)

    assert result["expected_outage"] == record
    assert result["expected_outage"] is not record


async def test_no_window_publishes_nothing(mock_coordinator, mock_config_entry) -> None:
    """A stand-in value is not a window."""
    mock_coordinator.last_expected_outage = None

    result = await _download(mock_coordinator, mock_config_entry)

    assert result["expected_outage"] is None
