"""Additional tests to improve code coverage for ZTE Router 5G."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.zte_router_5g import async_setup_entry
from custom_components.zte_router_5g.api import (
    ZTEAuthError,
    ZTEConnectionError,
    ZTERouterAPI,
)
from custom_components.zte_router_5g.button import (
    ZTEDeleteAllSMSButton,
    ZTERebootButton,
)

from .conftest import MockResponse

_LOGGER = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_api_get_ld_exception(mock_aiohttp_client):
    """Test get_ld exception handling."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    mock_aiohttp_client.get.side_effect = Exception("LD Fail")
    with pytest.raises(ZTEConnectionError):
        await api.get_ld()


@pytest.mark.asyncio
async def test_api_login_mc801(mock_aiohttp_client):
    """Test login for MC801 (non-multi)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    # LD, Version (MC801), then Login
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "test_ld"}),
        MockResponse(json_data={"wa_inner_version": "MC801_VER"}),
    ]

    mock_stok_cookie = MagicMock()
    mock_stok_cookie.value = "test_stok"
    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": mock_stok_cookie}
    )

    await api.login()
    assert api.is_multi is False


@pytest.mark.asyncio
async def test_api_login_connection_error(mock_aiohttp_client):
    """Test login connection error handling."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    with (
        patch.object(api, "get_ld", return_value="LD"),
        patch.object(api, "get_version", return_value="VER"),
    ):
        mock_aiohttp_client.post.side_effect = Exception("Conn Error")
        with pytest.raises(Exception, match="Conn Error"):
            await api.login()
        assert api.stok is None


@pytest.mark.asyncio
async def test_api_auto_login_get_all_data(mock_aiohttp_client):
    """Test auto-login in get_all_data when stok is missing."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = None

    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"network_type": "LTE", "signalbar": "3"}
    )

    with patch.object(api, "login", return_value="stok=new") as mock_login:
        await api.get_all_data()
        assert mock_login.called


@pytest.mark.asyncio
async def test_api_auto_login_get_sms_capacity(mock_aiohttp_client):
    """Test auto-login in get_sms_capacity when stok is missing."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = None

    mock_aiohttp_client.get.return_value = MockResponse(json_data={"cap": 100})

    with patch.object(api, "login", return_value="stok=new") as mock_login:
        await api.get_sms_capacity()
        assert mock_login.called


@pytest.mark.asyncio
async def test_api_auto_login_get_last_sms_content(mock_aiohttp_client):
    """Test auto-login in get_last_sms_content when stok is missing."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = None

    mock_aiohttp_client.post.return_value = MockResponse(json_data={"messages": []})

    with patch.object(api, "login", return_value="stok=new") as mock_login:
        await api.get_last_sms_content()
        assert mock_login.called


@pytest.mark.asyncio
async def test_api_get_last_sms_content_exception(mock_aiohttp_client):
    """Test get_last_sms_content exception handling."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_aiohttp_client.post.side_effect = Exception("SMS Fail")

    assert await api.get_last_sms_content() == {}
    assert api.stok is None


@pytest.mark.asyncio
async def test_api_auto_login_delete_sms(mock_aiohttp_client):
    """Test auto-login in delete_sms when stok is missing."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = None

    with (
        patch.object(api, "login", return_value="stok=new") as mock_login,
        patch.object(api, "get_ad", return_value="ad"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(status=200)
        await api.delete_sms("1")
        assert mock_login.called


@pytest.mark.asyncio
async def test_api_delete_all_exception(mock_aiohttp_client):
    """Test delete_all exception handling."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"

    with patch.object(api, "login", return_value="stok=test"):
        # Fail on first call (list messages)
        mock_aiohttp_client.post.side_effect = Exception("Delete All Fail")

        with pytest.raises(Exception, match="Delete All Fail"):
            await api.delete_all()
        assert api.stok is None


@pytest.mark.asyncio
async def test_api_get_ad_empty_version(mock_aiohttp_client):
    """Test get_ad when version is empty."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    with patch.object(api, "get_version", return_value=""):
        ad = await api.get_ad()
        assert ad == ""


@pytest.mark.asyncio
async def test_api_get_rd_success(mock_aiohttp_client):
    """Test get_rd success path."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    mock_aiohttp_client.get.return_value = MockResponse(json_data={"RD": "test_rd"})
    assert await api.get_rd() == "test_rd"


@pytest.mark.asyncio
async def test_config_flow_options_auth_error(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test auth error in options flow."""
    from custom_components.zte_router_5g.config_flow import ZTEOptionsFlow

    mock_config_entry.add_to_hass(hass)
    flow = ZTEOptionsFlow(mock_config_entry)
    flow.hass = hass

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        side_effect=ZTEAuthError("Auth Fail"),
    ):
        result = await flow.async_step_init(
            user_input={"host": "1.1.1.1", "password": "p"}
        )
        assert result["type"] == "form"
        assert result["errors"]["base"] == "invalid_auth"


@pytest.mark.asyncio
async def test_coordinator_metadata_change(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test coordinator updating config entry data when hardware metadata changes."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)

    # Current data in entry: model="ZTE Router", sw_version=None (usually)
    # New data from API
    new_data = {"wa_inner_version": "NEW_VER", "model_name": "MC888"}

    with (
        patch.object(api, "get_all_data", return_value=new_data),
        patch.object(api, "get_sms_capacity", return_value={}),
        patch.object(api, "get_last_sms_content", return_value={}),
        patch(
            "custom_components.zte_router_5g.coordinator.get_router_model",
            return_value="MC888",
        ),
    ):
        await coordinator._async_update_data()
        assert coordinator.sw_version == "NEW_VER"
        assert coordinator.model == "MC888"
        assert mock_config_entry.data["sw_version"] == "NEW_VER"


@pytest.mark.asyncio
async def test_coordinator_timeout_resilience(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test coordinator resilience on TimeoutError."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)
    coordinator.data = {"old": "data"}

    with patch("asyncio.timeout", side_effect=TimeoutError("Timeout")):
        # First failure
        data = await coordinator._async_update_data()
        assert data == {"old": "data"}
        assert coordinator.consecutive_failures == 1

        # Second failure
        data = await coordinator._async_update_data()
        assert data == {"old": "data"}
        assert coordinator.consecutive_failures == 2

        # Third failure
        data = await coordinator._async_update_data()
        assert data == {"old": "data"}
        assert coordinator.consecutive_failures == 3

        # Fourth failure - should raise UpdateFailed
        from homeassistant.helpers.update_coordinator import UpdateFailed

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_init_background_setup_success(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test background setup success path in __init__."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI") as mock_api_class,
        patch.object(
            hass.config_entries, "async_forward_entry_setups", return_value=True
        ),
    ):
        mock_api = mock_api_class.return_value
        mock_api.try_set_protocol.return_value = None
        mock_api.login.return_value = "stok=test"

        # Trigger setup
        await async_setup_entry(hass, mock_config_entry)
        await hass.async_block_till_done()

        # We need to wait for the background task
        # async_create_background_task doesn't provide an easy way to wait,
        # but we can check if the methods were called.
        # Since it's a task, it might run after block_till_done if not careful.
        # But in tests, it usually runs quickly.

        # To be sure, we can wait a bit or use a more direct test for
        # _async_background_setup if it was exposed.
        # Since it's nested, we'll just check calls.
        mock_api.try_set_protocol.assert_called()


@pytest.mark.asyncio
async def test_button_reboot_exception(
    hass: HomeAssistant, mock_config_entry, mock_coordinator
):
    """Test reboot button exception handling."""
    from custom_components.zte_router_5g.button import REBOOT_DESCRIPTION

    mock_coordinator.api.reboot.side_effect = Exception("Reboot Fail")
    button = ZTERebootButton(mock_coordinator, mock_config_entry, REBOOT_DESCRIPTION)

    # Should not raise exception, just log error
    await button.async_press()
    mock_coordinator.api.reboot.assert_called_once()


@pytest.mark.asyncio
async def test_button_delete_sms_exception(
    hass: HomeAssistant, mock_config_entry, mock_coordinator
):
    """Test delete SMS button exception handling."""
    from custom_components.zte_router_5g.button import DELETE_SMS_DESCRIPTION

    mock_coordinator.api.delete_all.side_effect = Exception("Delete Fail")
    button = ZTEDeleteAllSMSButton(
        mock_coordinator, mock_config_entry, DELETE_SMS_DESCRIPTION
    )

    # Should not raise exception, just log error
    await button.async_press()
    mock_coordinator.api.delete_all.assert_called_once()


def test_sensor_utils_errors():
    """Test sensor utility functions with error inputs."""
    from custom_components.zte_router_5g.sensor import (
        _get_bytes_to_gb,
        _get_total_sms,
        _get_uptime,
        _safe_float,
        _safe_int,
    )

    # _get_total_sms error
    assert _get_total_sms({"sms_nv_rev_total": "fail"}) is None

    # _safe_float error
    assert _safe_float("") is None
    assert _safe_float("fail") is None

    # _safe_int error
    assert _safe_int("") is None
    assert _safe_int("fail") is None

    # _get_uptime error
    assert _get_uptime({"realtime_time": "fail"}) is None

    # _get_bytes_to_gb error
    assert _get_bytes_to_gb("fail") is None


@pytest.mark.asyncio
async def test_sensor_native_value_guards(
    hass: HomeAssistant, mock_config_entry, mock_coordinator
):
    """Test sensor value guards and exceptions."""
    from custom_components.zte_router_5g.sensor import (
        ZTERouterSensor,
        ZTESensorEntityDescription,
    )

    # Min limit guard
    desc_min = ZTESensorEntityDescription(
        key="test_min", name="Test Min", value_fn=lambda x: 10, min_limit=20
    )
    sensor_min = ZTERouterSensor(mock_coordinator, mock_config_entry, desc_min)
    assert sensor_min.native_value is None

    # Max limit guard
    desc_max = ZTESensorEntityDescription(
        key="test_max", name="Test Max", value_fn=lambda x: 100, max_limit=50
    )
    sensor_max = ZTERouterSensor(mock_coordinator, mock_config_entry, desc_max)
    assert sensor_max.native_value is None

    # Exception handling in value_fn
    desc_err = ZTESensorEntityDescription(
        key="test_err", name="Test Err", value_fn=lambda x: x["missing"]
    )
    sensor_err = ZTERouterSensor(mock_coordinator, mock_config_entry, desc_err)
    mock_coordinator.data = {}
    assert sensor_err.native_value is None


@pytest.mark.asyncio
async def test_sensor_extra_attributes_errors(
    hass: HomeAssistant, mock_config_entry, mock_coordinator
):
    """Test sensor extra_state_attributes error paths."""
    from custom_components.zte_router_5g.sensor import (
        ZTERouterSensor,
        ZTESensorEntityDescription,
    )

    # msg_total with bad data
    desc_msg = ZTESensorEntityDescription(
        key="msg_total", name="Test Msg", value_fn=lambda x: 0
    )
    sensor_msg = ZTERouterSensor(mock_coordinator, mock_config_entry, desc_msg)
    mock_coordinator.data = {"sms_nv_total": "fail"}
    assert sensor_msg.extra_state_attributes == {}

    # msg_recent with missing last_sms
    desc_recent = ZTESensorEntityDescription(
        key="msg_recent", name="Test Recent", value_fn=lambda x: 0
    )
    sensor_recent = ZTERouterSensor(mock_coordinator, mock_config_entry, desc_recent)
    mock_coordinator.data = {}
    assert sensor_recent.extra_state_attributes == {
        "id": None,
        "number": None,
        "date": None,
    }

    # No data
    mock_coordinator.data = None
    assert sensor_msg.extra_state_attributes == {}


@pytest.mark.asyncio
async def test_switch_properties(
    hass: HomeAssistant, mock_config_entry, mock_coordinator
):
    """Test switch properties and device_info."""
    from custom_components.zte_router_5g.switch import (
        PAUSE_POLLING_DESCRIPTION,
        ZTEPausePollingSwitch,
    )

    switch = ZTEPausePollingSwitch(
        mock_coordinator, mock_config_entry, PAUSE_POLLING_DESCRIPTION, False
    )
    switch.hass = hass

    # Test is_on property
    assert switch.is_on is False

    # Test device_info
    info = switch.device_info
    assert info["name"] == "My ZTE Router System"
    assert info["manufacturer"] == "ZTE"

    # Test via_device for non-system group (just to be sure)
    pause_polling_description_signal = PAUSE_POLLING_DESCRIPTION.__class__(
        key="test", translation_key="test", group="signal"
    )
    switch_signal = ZTEPausePollingSwitch(
        mock_coordinator,
        mock_config_entry,
        pause_polling_description_signal,
        False,
    )
    info_signal = switch_signal.device_info
    assert "via_device" in info_signal
