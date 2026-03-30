from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from custom_components.zte_router_5g.const import CONF_STOP_POLLING, DOMAIN, COORDINATOR
from custom_components.zte_router_5g.switch import (
    PAUSE_POLLING_DESCRIPTION,
    ZTEPausePollingSwitch,
    async_setup_entry,
)


@pytest.mark.asyncio
async def test_pause_polling_switch(mock_coordinator, mock_config_entry):
    """Test pause polling switch."""
    switch = ZTEPausePollingSwitch(
        mock_coordinator, mock_config_entry, PAUSE_POLLING_DESCRIPTION, False
    )
    switch.hass = MagicMock()
    switch._entry.entry_id = "test_entry_id"

    # Mock coordinator refresh
    mock_coordinator.async_request_refresh = AsyncMock()

    # Mock hass.data
    switch.hass.data = {DOMAIN: {"test_entry_id": {CONF_STOP_POLLING: False}}}

    assert switch.is_on is False

    # Mock config_entries.async_update_entry
    switch.hass.config_entries.async_update_entry = MagicMock()

    with patch.object(switch, "async_write_ha_state"):
        await switch.async_turn_on()

    assert switch.hass.data[DOMAIN]["test_entry_id"][CONF_STOP_POLLING] is True
    switch.hass.config_entries.async_update_entry.assert_called()

    with patch.object(switch, "async_write_ha_state"):
        await switch.async_turn_off()

    assert switch.hass.data[DOMAIN]["test_entry_id"][CONF_STOP_POLLING] is False
    # The refresh is only triggered when turning polling back OFF
    mock_coordinator.async_request_refresh.assert_called_once()


def test_switch_device_info(mock_coordinator, mock_config_entry):
    """Test device_info."""
    switch = ZTEPausePollingSwitch(mock_coordinator, mock_config_entry, PAUSE_POLLING_DESCRIPTION, False)
    assert switch.device_info["identifiers"] == {(DOMAIN, "192.168.0.1")}


@pytest.mark.asyncio
async def test_switch_setup_entry():
    """Test platform setup."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test"
    hass.data = {DOMAIN: {"test": {COORDINATOR: MagicMock(), CONF_STOP_POLLING: False}}}
    
    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)
    async_add_entities.assert_called_once()
