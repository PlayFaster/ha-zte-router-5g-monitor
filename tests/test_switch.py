"""Tests for the ZTE Router switch."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.zte_router_5g.const import CONF_STOP_POLLING, DOMAIN
from custom_components.zte_router_5g.switch import (
    PAUSE_POLLING_DESCRIPTION,
    SWITCH_TYPES,
    ZTEPausePollingSwitch,
    ZTERouterSwitch,
    ZTESwitchEntityDescription,
    async_setup_entry,
)


@pytest.mark.asyncio
async def test_pause_polling_switch(mock_coordinator, mock_config_entry):
    """Test turning the pause switch on and off."""
    # Start with False (not paused)
    new_options = dict(mock_config_entry.options)
    new_options[CONF_STOP_POLLING] = False
    object.__setattr__(mock_config_entry, "options", new_options)

    switch = ZTEPausePollingSwitch(
        mock_coordinator, mock_config_entry, PAUSE_POLLING_DESCRIPTION, False
    )
    switch.hass = MagicMock()
    # Mock hass.data structure
    switch.hass.data = {DOMAIN: {mock_config_entry.entry_id: mock_coordinator}}
    switch.async_write_ha_state = MagicMock()

    # 1. Turn ON (Pause)
    await switch.async_turn_on()
    switch.hass.config_entries.async_update_entry.assert_called()
    _args, kwargs = switch.hass.config_entries.async_update_entry.call_args
    assert kwargs["options"][CONF_STOP_POLLING] is True

    # 2. Turn OFF (Resume)
    await switch.async_turn_off()
    _args, kwargs = switch.hass.config_entries.async_update_entry.call_args
    assert kwargs["options"][CONF_STOP_POLLING] is False
    mock_coordinator.async_force_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_switch_setup_entry():
    """Test platform setup."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test"
    entry.options = {CONF_STOP_POLLING: False}
    entry.runtime_data = MagicMock()

    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)
    async_add_entities.assert_called_once()


def test_router_switch_is_on_no_data(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.is_on returns False when no data."""
    mock_coordinator.data = None
    desc = SWITCH_TYPES[0]
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    assert switch.is_on is False


def test_router_switch_is_on_no_value_fn(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.is_on returns False when value_fn is None."""
    mock_coordinator.data = {}
    desc = ZTESwitchEntityDescription(
        key="test_switch",
        translation_key="test_switch",
        value_fn=None,
    )
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    assert switch.is_on is False


def test_router_switch_is_on_true(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.is_on returns True when data matches."""
    mock_coordinator.data = {"ODU_led_switch": "1"}
    desc = SWITCH_TYPES[0]
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    assert switch.is_on is True


def test_router_switch_is_on_false(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.is_on returns False when data doesn't match."""
    mock_coordinator.data = {"ODU_led_switch": "0"}
    desc = SWITCH_TYPES[0]
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    assert switch.is_on is False


@pytest.mark.asyncio
async def test_router_switch_turn_on_no_setter(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.async_turn_on returns early when setter_fn is None."""
    desc = ZTESwitchEntityDescription(
        key="test_switch",
        translation_key="test_switch",
        setter_fn=None,
    )
    mock_coordinator.api = MagicMock()
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    await switch.async_turn_on()
    mock_coordinator.api.async_request_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_router_switch_turn_off_no_setter(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.async_turn_off returns early when setter_fn is None."""
    desc = ZTESwitchEntityDescription(
        key="test_switch",
        translation_key="test_switch",
        setter_fn=None,
    )
    mock_coordinator.api = MagicMock()
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    await switch.async_turn_off()
    mock_coordinator.api.async_request_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_router_switch_turn_on_success(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.async_turn_on calls setter and refreshes."""
    mock_coordinator.api = AsyncMock()
    setter_fn = AsyncMock()

    desc = ZTESwitchEntityDescription(
        key="test_switch",
        translation_key="test_switch",
        setter_fn=setter_fn,
    )
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    await switch.async_turn_on()
    setter_fn.assert_called_once_with(mock_coordinator.api, True)
    mock_coordinator.async_force_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_router_switch_turn_off_success(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.async_turn_off calls setter and refreshes."""
    mock_coordinator.api = AsyncMock()
    setter_fn = AsyncMock()

    desc = ZTESwitchEntityDescription(
        key="test_switch",
        translation_key="test_switch",
        setter_fn=setter_fn,
    )
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    await switch.async_turn_off()
    setter_fn.assert_called_once_with(mock_coordinator.api, False)
    mock_coordinator.async_force_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_router_switch_turn_on_exception(
    mock_coordinator, mock_config_entry, caplog
):
    """Test ZTERouterSwitch.async_turn_on catches and logs exception."""
    mock_coordinator.api = MagicMock()

    async def failing_setter(api, state):
        raise ValueError("test turn on error")

    desc = ZTESwitchEntityDescription(
        key="odu_led_switch",
        translation_key="test_switch",
        setter_fn=failing_setter,
    )
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    await switch.async_turn_on()
    assert "Failed to turn on" in caplog.text
    assert "odu_led_switch" in caplog.text


@pytest.mark.asyncio
async def test_router_switch_turn_off_exception(
    mock_coordinator, mock_config_entry, caplog
):
    """Test ZTERouterSwitch.async_turn_off catches and logs exception."""
    mock_coordinator.api = MagicMock()

    async def failing_setter(api, state):
        raise ValueError("test turn off error")

    desc = ZTESwitchEntityDescription(
        key="odu_led_switch",
        translation_key="test_switch",
        setter_fn=failing_setter,
    )
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    await switch.async_turn_off()
    assert "Failed to turn off" in caplog.text
    assert "odu_led_switch" in caplog.text


def test_router_switch_device_info(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.device_info."""
    desc = SWITCH_TYPES[0]
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    info = switch.device_info
    assert info["identifiers"] == {("zte_router_5g", "864155042229309_system")}
    assert info["manufacturer"] == "ZTE"


def test_router_switch_device_info_data_group(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.device_info for data group."""
    desc = SWITCH_TYPES[1]
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    info = switch.device_info
    assert info["identifiers"] == {("zte_router_5g", "864155042229309_data")}
    assert "via_device" in info


def test_pause_polling_switch_is_on(mock_coordinator, mock_config_entry):
    """Test ZTEPausePollingSwitch.is_on."""
    switch = ZTEPausePollingSwitch(
        mock_coordinator, mock_config_entry, PAUSE_POLLING_DESCRIPTION, True
    )
    switch.hass = MagicMock()
    assert (
        switch.is_on is False
    )  # Because entry.options doesn't have CONF_STOP_POLLING=True
