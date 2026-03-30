from unittest.mock import MagicMock, AsyncMock
import pytest
from custom_components.zte_router_5g.button import (
    DELETE_SMS_DESCRIPTION,
    REBOOT_DESCRIPTION,
    ZTEDeleteAllSMSButton,
    ZTERebootButton,
    async_setup_entry,
)
from custom_components.zte_router_5g.const import DOMAIN, COORDINATOR


@pytest.mark.asyncio
async def test_reboot_button_press(mock_coordinator, mock_config_entry):
    """Test reboot button press."""
    mock_api = MagicMock()
    button = ZTERebootButton(
        mock_api, mock_coordinator, mock_config_entry, REBOOT_DESCRIPTION
    )
    button.hass = MagicMock()

    # Mock hass.async_add_executor_job
    async def mock_executor(func, *args):
        return func(*args)
    button.hass.async_add_executor_job = mock_executor

    await button.async_press()
    mock_api.reboot.assert_called_once()

    # Test exception handling
    mock_api.reboot.side_effect = Exception("Fail")
    await button.async_press() # Should catch and log


@pytest.mark.asyncio
async def test_delete_sms_button_press(mock_coordinator, mock_config_entry):
    """Test delete all SMS button press."""
    mock_api = MagicMock()
    button = ZTEDeleteAllSMSButton(
        mock_api, mock_coordinator, mock_config_entry, DELETE_SMS_DESCRIPTION
    )
    button.hass = MagicMock()

    # Mock hass.async_add_executor_job
    async def mock_executor(func, *args):
        return func(*args)
    button.hass.async_add_executor_job = mock_executor

    await button.async_press()
    mock_api.delete_all.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()

    # Test exception handling
    mock_api.delete_all.side_effect = Exception("Fail")
    await button.async_press() # Should catch and log


def test_button_device_info(mock_coordinator, mock_config_entry):
    """Test device_info properties."""
    mock_api = MagicMock()
    reboot_btn = ZTERebootButton(mock_api, mock_coordinator, mock_config_entry, REBOOT_DESCRIPTION)
    delete_btn = ZTEDeleteAllSMSButton(mock_api, mock_coordinator, mock_config_entry, DELETE_SMS_DESCRIPTION)

    assert reboot_btn.device_info["identifiers"] == {(DOMAIN, "192.168.0.1")}
    assert delete_btn.device_info["identifiers"] == {(DOMAIN, "192.168.0.1_sms")}


@pytest.mark.asyncio
async def test_button_setup_entry():
    """Test platform setup."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test"
    hass.data = {DOMAIN: {"test": {"api": MagicMock(), COORDINATOR: MagicMock()}}}
    
    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)
    async_add_entities.assert_called_once()
