from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.zte_router_5g.const import CONF_STOP_POLLING, DOMAIN
from custom_components.zte_router_5g.switch import (
    PAUSE_POLLING_DESCRIPTION,
    ZTEPausePollingSwitch,
)


@pytest.mark.asyncio
async def test_pause_polling_switch(mock_coordinator, mock_config_entry):
    """Test pause polling switch."""
    switch = ZTEPausePollingSwitch(
        mock_coordinator, mock_config_entry, PAUSE_POLLING_DESCRIPTION, False
    )
    switch.hass = MagicMock()
    switch._entry.entry_id = "test_entry_id"

    # Mock coordinator refresh to be an awaitable AsyncMock
    mock_coordinator.async_request_refresh = AsyncMock()

    # Mock hass.data
    switch.hass.data = {DOMAIN: {"test_entry_id": {CONF_STOP_POLLING: False}}}

    assert switch.is_on is False

    # Mock config_entries.async_update_entry
    switch.hass.config_entries.async_update_entry = MagicMock()

    # FIX: Patch async_write_ha_state to prevent it from looking
    # up the non-existent integration registry
    with patch.object(switch, "async_write_ha_state"):
        await switch.async_turn_on()

    assert switch.hass.data[DOMAIN]["test_entry_id"][CONF_STOP_POLLING] is True
    switch.hass.config_entries.async_update_entry.assert_called()

    # FIX: Patch async_write_ha_state for turning off as well
    with patch.object(switch, "async_write_ha_state"):
        await switch.async_turn_off()

    assert switch.hass.data[DOMAIN]["test_entry_id"][CONF_STOP_POLLING] is False
    # The refresh is only triggered when turning polling back OFF
    mock_coordinator.async_request_refresh.assert_called_once()
