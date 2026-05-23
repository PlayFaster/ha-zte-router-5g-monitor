"""Tests for the ZTE Router init."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import ServiceCall
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.zte_router_5g import async_setup_entry, async_unload_entry
from custom_components.zte_router_5g.api import ZTEAuthError
from custom_components.zte_router_5g.const import (
    CONF_STOP_POLLING,
)
from custom_components.zte_router_5g.coordinator import ZTERouterDataUpdateCoordinator


@pytest.fixture(autouse=True)
def mock_report_usage():
    """Mock report_usage to avoid 'Frame helper not set up' error."""
    with patch("homeassistant.helpers.frame.report_usage"):
        yield


@pytest.fixture
def mock_hass():
    """Create a mock HomeAssistant instance with necessary async methods."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_update_entry = MagicMock()
    return hass


@pytest.mark.asyncio
async def test_setup_entry_success(mock_hass, mock_config_entry):
    """Test successful setup of the integration."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI"),
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        assert await async_setup_entry(mock_hass, mock_config_entry) is True

        coordinator = mock_config_entry.runtime_data
        assert isinstance(coordinator, ZTERouterDataUpdateCoordinator)

        mock_hass.config_entries.async_forward_entry_setups.assert_called_once()
        mock_config_entry.async_create_background_task.assert_called_once()


@pytest.mark.asyncio
async def test_unload_entry_success(mock_hass, mock_config_entry):
    """Test successful unloading of the integration."""
    mock_config_entry.runtime_data = MagicMock()
    assert await async_unload_entry(mock_hass, mock_config_entry) is True


@pytest.mark.asyncio
async def test_async_update_data_success(mock_hass, mock_config_entry):
    """Test the coordinator's update method success path."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI") as mock_api_class,
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        mock_api = mock_api_class.return_value
        mock_api.get_all_data = AsyncMock(return_value={"network_type": "LTE"})
        mock_api.get_sms_capacity = AsyncMock(return_value={"total": 10})
        mock_api.get_last_sms_content = AsyncMock(return_value={"content": "hello"})

        # Setup to get the coordinator
        await async_setup_entry(mock_hass, mock_config_entry)
        coordinator = mock_config_entry.runtime_data

        data = await coordinator._async_update_data()

        assert data["network_type"] == "LTE"
        assert data["total"] == 10
        assert data["last_sms"] == {"content": "hello"}
        assert coordinator.consecutive_failures == 0


@pytest.mark.asyncio
async def test_async_update_data_paused(mock_hass, mock_config_entry):
    """Test update data when paused."""
    # Use object.__setattr__ to bypass the read-only protection of ConfigEntry
    # and ensure required connection options are preserved
    new_options = dict(mock_config_entry.options)
    new_options[CONF_STOP_POLLING] = True
    object.__setattr__(mock_config_entry, "options", new_options)

    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI"),
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        await async_setup_entry(mock_hass, mock_config_entry)
        coordinator = mock_config_entry.runtime_data

        # Case 1: Paused but NOT first run
        coordinator.data = {"cached": "data"}
        data = await coordinator._async_update_data()
        assert data == {"cached": "data"}

        # Case 2: Paused and first run -> attempts fetch (mock failure)
        coordinator.data = None
        coordinator.api.get_all_data = AsyncMock(side_effect=Exception("Fail"))

        data = await coordinator._async_update_data()
        assert data == {}


@pytest.mark.asyncio
async def test_async_update_data_resilience(mock_hass, mock_config_entry):
    """Test failure resilience."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI"),
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        await async_setup_entry(mock_hass, mock_config_entry)
        coordinator = mock_config_entry.runtime_data
        coordinator.data = {"old": "data"}

        coordinator.api.get_all_data = AsyncMock(
            side_effect=Exception("Persistent Fail")
        )

        # First, second and third failures: should return old data
        data = await coordinator._async_update_data()
        assert data == {"old": "data"}
        assert coordinator.consecutive_failures == 1

        data = await coordinator._async_update_data()
        assert data == {"old": "data"}
        assert coordinator.consecutive_failures == 2

        data = await coordinator._async_update_data()
        assert data == {"old": "data"}
        assert coordinator.consecutive_failures == 3

        # Fourth failure: should raise UpdateFailed
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
        assert coordinator.consecutive_failures == 4


@pytest.mark.asyncio
async def test_background_setup_failure(mock_hass, mock_config_entry):
    """Test that background setup failure is handled gracefully."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI") as mock_api_class,
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        mock_api = mock_api_class.return_value
        mock_api.try_set_protocol = AsyncMock(side_effect=Exception("Background Fail"))

        background_coro = None

        def mock_capture_task(hass, coro, name):
            nonlocal background_coro
            background_coro = coro
            return MagicMock()

        mock_config_entry.async_create_background_task = mock_capture_task

        await async_setup_entry(mock_hass, mock_config_entry)

        if background_coro:
            await background_coro


@pytest.mark.asyncio
async def test_background_setup_success(mock_hass, mock_config_entry):
    """Test that background setup success path is covered."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI") as mock_api_class,
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        mock_api = mock_api_class.return_value
        mock_api.try_set_protocol = AsyncMock(return_value=None)
        mock_api.login = AsyncMock(return_value="stok=test")

        background_coro = None

        def mock_capture_task(hass, coro, name):
            nonlocal background_coro
            background_coro = coro
            return MagicMock()

        mock_config_entry.async_create_background_task = mock_capture_task

        await async_setup_entry(mock_hass, mock_config_entry)

        if background_coro:
            await background_coro


@pytest.mark.asyncio
async def test_async_update_data_reauth_trigger(mock_hass, mock_config_entry):
    """Test that ZTEAuthError triggers reauth after 3 consecutive failures."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI"),
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
        patch.object(mock_config_entry, "async_start_reauth") as mock_reauth,
    ):
        await async_setup_entry(mock_hass, mock_config_entry)
        coordinator = mock_config_entry.runtime_data
        coordinator.data = {"old": "data"}
        coordinator.api.get_all_data = AsyncMock(side_effect=ZTEAuthError("Auth fail"))

        # First 3 failures return cached data (resilience)
        for i in range(3):
            data = await coordinator._async_update_data()
            assert data == {"old": "data"}
            assert coordinator.consecutive_failures == i + 1

        # 4th failure raises UpdateFailed and triggers reauth
        with pytest.raises(UpdateFailed, match="Authentication failed"):
            await coordinator._async_update_data()

        mock_reauth.assert_called_once_with(mock_hass)


@pytest.mark.asyncio
async def test_async_setup_registers_services(mock_hass):
    """Test that async_setup registers the integration services."""
    from custom_components.zte_router_5g import async_setup

    with patch.object(mock_hass.services, "async_register") as mock_register:
        assert await async_setup(mock_hass, {}) is True
        assert mock_register.call_count == 4
        # Verify the service names registered
        registered_services = [call[0][1] for call in mock_register.call_args_list]
        assert "send_sms" in registered_services
        assert "delete_sms" in registered_services
        assert "delete_all_sms" in registered_services
        assert "get_sms_list" in registered_services


@pytest.mark.asyncio
async def test_service_send_sms(mock_hass, mock_config_entry):
    """Test the send_sms service call."""
    from custom_components.zte_router_5g import async_send_sms

    mock_api = AsyncMock()
    mock_coordinator = MagicMock()
    mock_coordinator.api = mock_api
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"target": ["+123456"], "message": "test msg"}

    await async_send_sms(mock_hass, call)
    mock_api.send_sms.assert_called_once_with("+123456", "test msg")


@pytest.mark.asyncio
async def test_service_delete_sms(mock_hass, mock_config_entry):
    """Test the delete_sms service call."""
    from custom_components.zte_router_5g import async_delete_sms

    mock_api = AsyncMock()
    mock_coordinator = MagicMock()
    mock_coordinator.api = mock_api
    mock_coordinator.async_request_refresh = AsyncMock()
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"index": 5}

    await async_delete_sms(mock_hass, call)
    mock_api.delete_sms.assert_called_once_with("5")
    mock_coordinator.async_request_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_service_delete_all_sms_simple(mock_hass, mock_config_entry):
    """Test the delete_all_sms service call with keep_last = 0."""
    from custom_components.zte_router_5g import async_delete_all_sms

    mock_api = AsyncMock()
    mock_coordinator = MagicMock()
    mock_coordinator.api = mock_api
    mock_coordinator.async_request_refresh = AsyncMock()
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"keep_last": 0}

    await async_delete_all_sms(mock_hass, call)
    mock_api.delete_all.assert_called_once()
    mock_api.get_sms_messages.assert_not_called()
    mock_coordinator.async_request_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_service_delete_all_sms_keep_last(mock_hass, mock_config_entry):
    """Test the delete_all_sms service call with keep_last > 0."""
    from custom_components.zte_router_5g import async_delete_all_sms

    mock_api = AsyncMock()
    mock_api.get_sms_messages.return_value = [
        {"id": "4"},
        {"id": "3"},
        {"id": "2"},
        {"id": "1"},
    ]
    mock_coordinator = MagicMock()
    mock_coordinator.api = mock_api
    mock_coordinator.async_request_refresh = AsyncMock()
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"keep_last": 2}

    await async_delete_all_sms(mock_hass, call)
    mock_api.get_sms_messages.assert_called_once_with(mem_store="1")
    mock_api.delete_sms.assert_called_once_with("2;1")
    mock_coordinator.async_request_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_service_get_sms_list(mock_hass, mock_config_entry):
    """Test the get_sms_list service call with response."""
    from custom_components.zte_router_5g import async_get_sms_list

    mock_api = AsyncMock()
    mock_api.get_sms_messages.return_value = [
        {
            "id": "10",
            "number_decoded": "123",
            "content_decoded": "text1",
            "date_decoded": "2026-05-23T01:27:08",
            "tag": "1",
        },
        {
            "id": "9",
            "number_decoded": "456",
            "content_decoded": "text2",
            "date_decoded": "2026-05-23T01:25:08",
            "tag": "0",
        },
        {
            "id": "8",
            "number_decoded": "789",
            "content_decoded": "text3",
            "date_decoded": "2026-05-23T01:20:08",
            "tag": "2",
        },
    ]
    mock_coordinator = MagicMock()
    mock_coordinator.api = mock_api
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {
        "page": 1,
        "count": 10,
        "box_type": 1,
    }

    result = await async_get_sms_list(mock_hass, call)
    messages = result["messages"]

    assert len(messages) == 2
    assert messages[0]["index"] == 10
    assert messages[0]["phone"] == "123"
    assert messages[0]["content"] == "text1"
    assert messages[0]["read"] is False

    assert messages[1]["index"] == 9
    assert messages[1]["phone"] == "456"
    assert messages[1]["content"] == "text2"
    assert messages[1]["read"] is True
