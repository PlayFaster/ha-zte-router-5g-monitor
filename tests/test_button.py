import pytest
from unittest.mock import MagicMock, patch
from custom_components.zte_router_5g.button import ZTERebootButton, ZTEDeleteAllSMSButton, REBOOT_DESCRIPTION, DELETE_SMS_DESCRIPTION

@pytest.mark.asyncio
async def test_reboot_button_press(mock_coordinator, mock_config_entry):
    """Test reboot button press."""
    mock_api = MagicMock()
    button = ZTERebootButton(mock_api, mock_coordinator, mock_config_entry, REBOOT_DESCRIPTION)
    button.hass = MagicMock()
    
    # Mock hass.async_add_executor_job to call the function directly
    async def mock_executor(func, *args):
        return func(*args)
    button.hass.async_add_executor_job = mock_executor
    
    await button.async_press()
    mock_api.reboot.assert_called_once()

@pytest.mark.asyncio
async def test_delete_sms_button_press(mock_coordinator, mock_config_entry):
    """Test delete all SMS button press."""
    mock_api = MagicMock()
    button = ZTEDeleteAllSMSButton(mock_api, mock_coordinator, mock_config_entry, DELETE_SMS_DESCRIPTION)
    button.hass = MagicMock()
    
    # Mock hass.async_add_executor_job
    async def mock_executor(func, *args):
        return func(*args)
    button.hass.async_add_executor_job = mock_executor
    
    await button.async_press()
    mock_api.delete_all.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()
