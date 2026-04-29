"""Tests for the ZTE Router button."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.zte_router_5g.button import (
    DELETE_SMS_DESCRIPTION,
    REBOOT_DESCRIPTION,
    ZTEDeleteAllSMSButton,
    ZTERebootButton,
    async_setup_entry,
)
from custom_components.zte_router_5g.const import DOMAIN


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
    mock_coordinator.async_request_refresh.assert_called_once()


def test_button_device_info(mock_coordinator, mock_config_entry):
    """Test device_info for router and SMS group."""
    mock_api = MagicMock()
    mock_coordinator.api = mock_api
    reboot = ZTERebootButton(mock_coordinator, mock_config_entry, REBOOT_DESCRIPTION)
    delete = ZTEDeleteAllSMSButton(
        mock_coordinator, mock_config_entry, DELETE_SMS_DESCRIPTION
    )

    assert reboot.device_info["identifiers"] == {(DOMAIN, "00:11:22:33:44:55_system")}
    assert delete.device_info["identifiers"] == {(DOMAIN, "00:11:22:33:44:55_sms")}


@pytest.mark.asyncio
async def test_button_setup_entry():
    """Test platform setup."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test"
    coordinator = MagicMock()
    coordinator.api = MagicMock()
    hass.data = {DOMAIN: {"test": coordinator}}

    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)
    async_add_entities.assert_called_once()
