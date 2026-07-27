"""Tests for the ZTE Router button."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.zte_router_5g.button import (
    DELETE_SMS_DESCRIPTION,
    REBOOT_DESCRIPTION,
    REFRESH_DESCRIPTION,
    ZTEDeleteAllSMSButton,
    ZTERebootButton,
    ZTERefreshButton,
    async_setup_entry,
)
from custom_components.zte_router_5g.const import DOMAIN


@pytest.mark.asyncio
async def test_refresh_button_press(mock_coordinator, mock_config_entry):
    """Test refresh button triggers an immediate coordinator refresh."""
    button = ZTERefreshButton(mock_coordinator, mock_config_entry, REFRESH_DESCRIPTION)

    await button.async_press()
    mock_coordinator.async_force_refresh.assert_called_once()


def test_refresh_button_device_info(mock_coordinator, mock_config_entry):
    """Test refresh button is attached to the system sub-device."""
    button = ZTERefreshButton(mock_coordinator, mock_config_entry, REFRESH_DESCRIPTION)

    assert button.device_info["identifiers"] == {(DOMAIN, "864155042229309_system")}


@pytest.mark.asyncio
async def test_reboot_button_press(mock_coordinator, mock_config_entry):
    """Test reboot button trigger."""
    mock_api = MagicMock()
    mock_api.reboot = AsyncMock()
    mock_coordinator.api = mock_api
    button = ZTERebootButton(mock_coordinator, mock_config_entry, REBOOT_DESCRIPTION)

    await button.async_press()
    mock_api.reboot.assert_called_once()


@pytest.mark.asyncio
async def test_delete_sms_button_press(mock_coordinator, mock_config_entry):
    """Test delete SMS button trigger."""
    mock_api = MagicMock()
    mock_api.delete_all = AsyncMock()
    mock_coordinator.api = mock_api
    button = ZTEDeleteAllSMSButton(
        mock_coordinator, mock_config_entry, DELETE_SMS_DESCRIPTION
    )

    await button.async_press()
    mock_api.delete_all.assert_called_once()
    mock_coordinator.async_force_refresh.assert_called_once()


def test_button_device_info(mock_coordinator, mock_config_entry):
    """Test device_info for router and SMS group."""
    mock_api = MagicMock()
    mock_coordinator.api = mock_api
    reboot = ZTERebootButton(mock_coordinator, mock_config_entry, REBOOT_DESCRIPTION)
    delete = ZTEDeleteAllSMSButton(
        mock_coordinator, mock_config_entry, DELETE_SMS_DESCRIPTION
    )

    assert reboot.device_info["identifiers"] == {(DOMAIN, "864155042229309_system")}
    assert delete.device_info["identifiers"] == {(DOMAIN, "864155042229309_sms")}


@pytest.mark.asyncio
async def test_button_setup_entry():
    """Test platform setup."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test"
    entry.runtime_data = MagicMock()

    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)
    async_add_entities.assert_called_once()


@pytest.mark.asyncio
async def test_reboot_button_raises_on_failure(mock_coordinator, mock_config_entry):
    """Test that reboot button raises HomeAssistantError on API failure."""
    mock_api = MagicMock()
    mock_api.reboot = AsyncMock(side_effect=Exception("Connection lost"))
    mock_coordinator.api = mock_api
    button = ZTERebootButton(mock_coordinator, mock_config_entry, REBOOT_DESCRIPTION)

    with pytest.raises(HomeAssistantError, match="Reboot failed"):
        await button.async_press()


@pytest.mark.asyncio
async def test_delete_sms_button_raises_on_failure(mock_coordinator, mock_config_entry):
    """Test that delete SMS button raises HomeAssistantError on API failure."""
    mock_api = MagicMock()
    mock_api.delete_all = AsyncMock(side_effect=Exception("Connection lost"))
    mock_coordinator.api = mock_api
    button = ZTEDeleteAllSMSButton(
        mock_coordinator, mock_config_entry, DELETE_SMS_DESCRIPTION
    )

    with pytest.raises(HomeAssistantError, match="Delete SMS failed"):
        await button.async_press()
