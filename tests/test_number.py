from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.zte_router_5g.const import CONF_SCAN_INTERVAL, DOMAIN
from custom_components.zte_router_5g.number import (
    POLLING_INTERVAL_DESCRIPTION,
    ZTEPollingInterval,
)


@pytest.mark.asyncio
async def test_polling_interval_number(mock_coordinator, mock_config_entry):
    """Test polling interval number entity."""
    number = ZTEPollingInterval(
        mock_coordinator, mock_config_entry, POLLING_INTERVAL_DESCRIPTION, 180
    )
    number.hass = MagicMock()
    number._entry.entry_id = "test_entry_id"

    # Mock coordinator refresh to be an awaitable
    mock_coordinator.async_request_refresh = AsyncMock()

    # Mock hass.data and config_entries
    number.hass.data = {DOMAIN: {"test_entry_id": {CONF_SCAN_INTERVAL: 180}}}
    number.hass.config_entries.async_update_entry = MagicMock()

    assert number.native_value == 180

    # FIX: Patch async_write_ha_state to prevent it from looking
    # up the non-existent integration registry
    with (
        patch.object(number, "async_write_ha_state"),
        patch("asyncio.sleep", return_value=None),
    ):  # Skip the 2s debounce wait
        await number.async_set_native_value(300)

        # Wait for the debounced task to complete
        if number._refresh_task:
            await number._refresh_task

    assert number.native_value == 300
    assert number.hass.data[DOMAIN]["test_entry_id"][CONF_SCAN_INTERVAL] == 300
    assert mock_coordinator.update_interval.total_seconds() == 300
    number.hass.config_entries.async_update_entry.assert_called_once()
