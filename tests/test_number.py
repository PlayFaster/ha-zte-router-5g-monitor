from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from custom_components.zte_router_5g.const import CONF_SCAN_INTERVAL, DOMAIN, COORDINATOR
from custom_components.zte_router_5g.number import (
    POLLING_INTERVAL_DESCRIPTION,
    ZTEPollingInterval,
    async_setup_entry,
)


@pytest.mark.asyncio
async def test_polling_interval_number(mock_coordinator, mock_config_entry):
    """Test polling interval number entity."""
    number = ZTEPollingInterval(
        mock_coordinator, mock_config_entry, POLLING_INTERVAL_DESCRIPTION, 180
    )
    number.hass = MagicMock()
    number._entry.entry_id = "test_entry_id"

    # Mock coordinator refresh
    mock_coordinator.async_request_refresh = AsyncMock()

    # Mock hass.data and config_entries
    number.hass.data = {DOMAIN: {"test_entry_id": {CONF_SCAN_INTERVAL: 180}}}
    number.hass.config_entries.async_update_entry = MagicMock()

    assert number.native_value == 180

    with (
        patch.object(number, "async_write_ha_state"),
        patch("asyncio.sleep", return_value=None),
    ):
        await number.async_set_native_value(300)
        if number._refresh_task:
            await number._refresh_task

    assert number.native_value == 300
    assert number.hass.data[DOMAIN]["test_entry_id"][CONF_SCAN_INTERVAL] == 300
    assert mock_coordinator.update_interval.total_seconds() == 300
    number.hass.config_entries.async_update_entry.assert_called_once()


@pytest.mark.asyncio
async def test_polling_interval_error_handling(mock_coordinator, mock_config_entry):
    """Test exception handling in debounced task."""
    number = ZTEPollingInterval(mock_coordinator, mock_config_entry, POLLING_INTERVAL_DESCRIPTION, 180)
    number.hass = MagicMock()
    number.hass.data = {DOMAIN: {mock_config_entry.entry_id: {}}}
    
    with patch("asyncio.sleep", side_effect=Exception("Async Error")):
        # This will trigger the exception block in _async_debounced_apply
        await number._async_debounced_apply(300)
        # Should catch and log error


def test_number_device_info(mock_coordinator, mock_config_entry):
    """Test device_info."""
    number = ZTEPollingInterval(mock_coordinator, mock_config_entry, POLLING_INTERVAL_DESCRIPTION, 180)
    assert number.device_info["identifiers"] == {(DOMAIN, "192.168.0.1")}


@pytest.mark.asyncio
async def test_number_setup_entry():
    """Test platform setup."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test"
    hass.data = {DOMAIN: {"test": {COORDINATOR: MagicMock(), CONF_SCAN_INTERVAL: 180}}}
    
    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)
    async_add_entities.assert_called_once()
