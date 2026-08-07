"""Additional tests to improve code coverage for ZTE Router 5G."""

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
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
from custom_components.zte_router_5g.const import DOMAIN

from .conftest import MockResponse, assert_links_to_parent

_LOGGER = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_api_get_ld_exception(mock_aiohttp_client):
    """Test get_ld exception handling."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    mock_aiohttp_client.get.side_effect = aiohttp.ClientError("LD Fail")
    with pytest.raises(ZTEConnectionError):
        await api.get_ld()


@pytest.mark.asyncio
async def test_api_login_mc801(mock_aiohttp_client):
    """Test login for MC801 (non-multi)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    # LD, Version (MC801), then Login, then session init
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "test_ld"}),
        MockResponse(json_data={"wa_inner_version": "MC801_VER"}),
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
        mock_aiohttp_client.post.side_effect = aiohttp.ClientError("Conn Error")
        with pytest.raises(
            ZTEConnectionError, match="Login failed due to connection error"
        ):
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

    # Real capacity shape — the endpoint now asserts its contract key, so a
    # fabricated payload would fail here for the wrong reason.
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"sms_nv_total": "100", "sms_sim_total": "20"}
    )

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
    mock_aiohttp_client.get.return_value = MockResponse(json_data={"LD": "test_ld"})
    mock_aiohttp_client.post.side_effect = aiohttp.ClientError("SMS Fail")

    with pytest.raises(ZTEConnectionError):
        await api.get_last_sms_content()
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
        mock_aiohttp_client.post.return_value = MockResponse(
            json_data={"result": "ok"}, status=200
        )
        await api.delete_sms("1")
        assert mock_login.called


@pytest.mark.asyncio
async def test_api_delete_all_exception(mock_aiohttp_client):
    """Test delete_all exception handling."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"

    with patch.object(api, "login", return_value="stok=test"):
        # Fail on first call (list messages)
        mock_aiohttp_client.post.side_effect = aiohttp.ClientError("Delete All Fail")

        with pytest.raises(ZTEConnectionError, match="Request failed: Delete All Fail"):
            await api.delete_all()
        assert api.stok is None


@pytest.mark.asyncio
async def test_api_get_ad_empty_version(mock_aiohttp_client):
    """Test get_ad when version is empty."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    with (
        patch.object(api, "_ensure_session", AsyncMock()),
        patch.object(api, "get_version", return_value=""),
    ):
        ad = await api.get_ad()
        assert ad == ""


@pytest.mark.asyncio
async def test_api_get_rd_success(mock_aiohttp_client):
    """Test get_rd success path."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=fake"
    api.last_activity = datetime.now(UTC)
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


def _assert_looked_up_the_root_device(mock_dev_reg) -> None:
    """Assert the registry lookup happened, whichever branch HA takes.

    `_compat.device_by_identifier` calls `async_get_device_by_identifier` on
    2026.8+ and `async_get_device` below it. Asserting either one by name locks
    the test to one Home Assistant version — which is how these two came to
    fail the moment the devcontainer took 2026.8.0b0, while the production code
    was doing exactly the right thing.
    """
    from custom_components.zte_router_5g import _compat

    if _compat._HAS_BY_IDENTIFIER:
        mock_dev_reg.async_get_device_by_identifier.assert_called_once()
        mock_dev_reg.async_get_device.assert_not_called()
    else:
        _assert_looked_up_the_root_device(mock_dev_reg)


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
        patch.object(api, "get_sms_messages", return_value=[]),
        patch(
            "custom_components.zte_router_5g.coordinator.get_router_model",
            return_value="MC888",
        ),
        patch(
            "custom_components.zte_router_5g.coordinator.dr.async_get"
        ) as mock_dr_get,
    ):
        mock_dev_reg = MagicMock()
        mock_dr_get.return_value = mock_dev_reg
        # Set both: `_compat.device_by_identifier` calls the scoped
        # `async_get_device_by_identifier` on 2026.8+ and `async_get_device`
        # below it. Stubbing only one locks the test to one HA version.
        mock_dev_reg.async_get_device.return_value = None  # device doesn't exist yet
        mock_dev_reg.async_get_device_by_identifier.return_value = None

        await coordinator._async_update_data()
        assert coordinator.sw_version == "NEW_VER"
        assert coordinator.model == "MC888"
        # sw_version is no longer written to entry.data; it's updated in device registry
        _assert_looked_up_the_root_device(mock_dev_reg)


@pytest.mark.asyncio
async def test_coordinator_metadata_update_device_exists(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test coordinator updating device registry when device already exists."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)

    new_data = {"wa_inner_version": "NEW_VER", "model_name": "MC888"}

    with (
        patch.object(api, "get_all_data", return_value=new_data),
        patch.object(api, "get_sms_capacity", return_value={}),
        patch.object(api, "get_sms_messages", return_value=[]),
        patch(
            "custom_components.zte_router_5g.coordinator.get_router_model",
            return_value="MC888",
        ),
        patch(
            "custom_components.zte_router_5g.coordinator.dr.async_get"
        ) as mock_dr_get,
    ):
        mock_dev_reg = MagicMock()
        mock_dr_get.return_value = mock_dev_reg
        mock_device = MagicMock()
        # Both, for the same reason as above.
        mock_dev_reg.async_get_device.return_value = mock_device
        mock_dev_reg.async_get_device_by_identifier.return_value = mock_device

        await coordinator._async_update_data()
        assert coordinator.sw_version == "NEW_VER"
        assert coordinator.model == "MC888"
        mock_dev_reg.async_update_device.assert_called_once_with(
            mock_device.id, model="MC888", sw_version="NEW_VER"
        )


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
    """The background task runs to completion against a real `hass`.

    The sibling in `test_init.py` covers the same path against a mock `hass`;
    this one exists because `async_forward_entry_setups` and the entity
    platforms are real here, so it separates "the coroutine completed" from
    "it completed with platforms actually set up underneath it".
    """
    mock_config_entry.add_to_hass(hass)

    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI") as mock_api_class,
        patch.object(
            hass.config_entries, "async_forward_entry_setups", return_value=True
        ),
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

        mock_api.get_all_data = AsyncMock(return_value={"network_type": "ENDC"})

        # Trigger setup
        assert await async_setup_entry(hass, mock_config_entry) is True

        assert background_coro is not None, "setup created no background task"
        await background_coro
        await hass.async_block_till_done()

        mock_api.login.assert_awaited_once_with(5)
        assert mock_config_entry.runtime_data.data["network_type"] == "ENDC"
        assert mock_config_entry.runtime_data.last_update_success is True


@pytest.mark.asyncio
async def test_button_reboot_exception(
    hass: HomeAssistant, mock_config_entry, mock_coordinator
):
    """Test reboot button exception raises HomeAssistantError."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.zte_router_5g.button import REBOOT_DESCRIPTION

    mock_coordinator.api.reboot.side_effect = Exception("Reboot Fail")
    button = ZTERebootButton(mock_coordinator, mock_config_entry, REBOOT_DESCRIPTION)

    with pytest.raises(HomeAssistantError) as err:
        await button.async_press()
    assert err.value.translation_key == "reboot_failed"
    mock_coordinator.api.reboot.assert_called_once()


@pytest.mark.asyncio
async def test_button_delete_sms_exception(
    hass: HomeAssistant, mock_config_entry, mock_coordinator
):
    """Test delete SMS button exception raises HomeAssistantError."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.zte_router_5g.button import DELETE_SMS_DESCRIPTION

    mock_coordinator.api.delete_all.side_effect = Exception("Delete Fail")
    button = ZTEDeleteAllSMSButton(
        mock_coordinator, mock_config_entry, DELETE_SMS_DESCRIPTION
    )

    with pytest.raises(HomeAssistantError) as err:
        await button.async_press()
    assert err.value.translation_key == "delete_all_button_failed"
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
    mock_coordinator.data = {"dummy": "value"}
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
    assert_links_to_parent(info_signal, DOMAIN, "864155042229309_system")


@pytest.mark.asyncio
async def test_coordinator_sms_storage_full_creates_issue(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test that a full NV SMS store raises a repair issue."""
    from unittest.mock import patch

    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)

    full_data = {"nv_sms_able": "20", "sms_nv_total": "20"}

    with (
        patch.object(api, "get_all_data", return_value=full_data),
        patch.object(api, "get_sms_capacity", return_value={}),
        patch.object(api, "get_sms_messages", return_value=[]),
        patch(
            "custom_components.zte_router_5g.coordinator.ir.async_create_issue"
        ) as mock_create,
        patch("custom_components.zte_router_5g.coordinator.ir.async_delete_issue"),
    ):
        await coordinator._async_update_data()
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        # Entry-scoped id, bare translation_key — the two are deliberately
        # different: the registry needs uniqueness, the user-facing text does not.
        assert call_kwargs.args[2] == coordinator._repair_ids["sms_storage_full"]
        assert call_kwargs.kwargs["translation_key"] == "sms_storage_full"


@pytest.mark.asyncio
async def test_coordinator_sms_storage_not_full_deletes_issue(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test that non-full NV SMS store clears any existing repair issue."""
    from unittest.mock import patch

    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)

    partial_data = {"nv_sms_able": "20", "sms_nv_total": "5"}

    with (
        patch.object(api, "get_all_data", return_value=partial_data),
        patch.object(api, "get_sms_capacity", return_value={}),
        patch.object(api, "get_sms_messages", return_value=[]),
        patch("custom_components.zte_router_5g.coordinator.ir.async_create_issue"),
        patch(
            "custom_components.zte_router_5g.coordinator.ir.async_delete_issue"
        ) as mock_delete,
    ):
        await coordinator._async_update_data()
        mock_delete.assert_called_once_with(
            hass, "zte_router_5g", coordinator._repair_ids["sms_storage_full"]
        )


# ---------------------------------------------------------------------------
# Coverage Expansion: api.py uncovered lines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_ip_with_protocol_prefix(mock_aiohttp_client):
    """Test API initialization strips protocol prefix from IP (api.py:36)."""
    api = ZTERouterAPI(mock_aiohttp_client, "https://192.168.0.1", "admin", "password")
    assert api.ip == "192.168.0.1"


@pytest.mark.asyncio
async def test_api_request_html_via_url_no_retry(mock_aiohttp_client):
    """Test _request HTML detection via URL, no retry (api.py:122,133-163)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={}, url="http://192.168.0.1/index.html"
    )
    with pytest.raises(ZTEConnectionError, match="Received unexpected HTML response"):
        await api._request("GET", "some/path", authenticated=False)


@pytest.mark.asyncio
async def test_api_request_html_via_url_with_retry(mock_aiohttp_client):
    """Test _request HTML detection via URL with retry and relogin (api.py:133-147)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={}, url="http://192.168.0.1/index.html"
    )
    with patch.object(api, "login", return_value="stok=new") as mock_login:
        with pytest.raises(
            ZTEConnectionError, match="Received unexpected HTML response"
        ):
            await api._request("GET", "some/path", authenticated=True)
        assert mock_login.called


@pytest.mark.asyncio
async def test_api_request_html_via_content_type(mock_aiohttp_client):
    """Test _request HTML detection via Content-Type header (api.py:123-130)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_response = MockResponse(json_data=None, headers={"Content-Type": "text/html"})
    mock_aiohttp_client.get.return_value = mock_response
    with (
        patch.object(
            mock_response, "text", return_value="<html><body>test</body></html>"
        ),
        pytest.raises(ZTEConnectionError, match="Received unexpected HTML response"),
    ):
        await api._request("GET", "some/path", authenticated=False)


@pytest.mark.asyncio
async def test_api_request_html_via_content_type_starts_with_angle(mock_aiohttp_client):
    """Test _request HTML detection when text body starts with '<' (api.py:127)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_response = MockResponse(
        json_data=None,
        headers={"Content-Type": "text/html"},
    )
    mock_aiohttp_client.get.return_value = mock_response
    with (
        patch.object(
            mock_response, "text", return_value="<html><body>test</body></html>"
        ),
        pytest.raises(ZTEConnectionError, match="Received unexpected HTML response"),
    ):
        await api._request("GET", "some/path", authenticated=False)


@pytest.mark.asyncio
async def test_api_request_json_parse_retry(mock_aiohttp_client):
    """Test _request JSON parse failure with retry (api.py:170-184)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"

    # First response fails json(), second response succeeds
    fail_response = MockResponse(json_data=None)
    success_response = MockResponse(json_data={"result": "ok"})
    mock_aiohttp_client.get.side_effect = [fail_response, success_response]

    with (
        patch.object(api, "login", return_value="stok=new") as mock_login,
        patch.object(fail_response, "json", side_effect=ValueError("Bad JSON")),
    ):
        result = await api._request("GET", "some/path", authenticated=True)
        assert result == {"result": "ok"}
        assert mock_login.called


@pytest.mark.asyncio
async def test_api_request_json_parse_no_retry(mock_aiohttp_client):
    """Test _request JSON parse failure without retry (api.py:184-186)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_response = MockResponse(json_data=None)
    mock_aiohttp_client.get.return_value = mock_response
    with (
        patch.object(mock_response, "json", side_effect=ValueError("Bad JSON")),
        pytest.raises(ZTEConnectionError, match="Failed to parse JSON response"),
    ):
        await api._request("GET", "some/path", authenticated=False)


@pytest.mark.asyncio
async def test_api_login_password_error_result(mock_aiohttp_client):
    """Test login with password_error result in body (api.py:322)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "LD"}),
        MockResponse(json_data={"wa_inner_version": "VER"}),
    ]
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "password_error"}, cookies={}
    )

    with pytest.raises(ZTEAuthError, match="Login failed due to invalid credentials"):
        await api.login()


@pytest.mark.asyncio
async def test_api_request_reauth_error_in_outer_except(mock_aiohttp_client):
    """Test _request re-raises ZTEAuthError in outer except (api.py:225)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"

    with (
        patch.object(api, "session", create=True) as mock_session,
    ):
        mock_session.request.side_effect = ZTEAuthError("Test auth fail")
        with pytest.raises(ZTEAuthError, match="Test auth fail"):
            await api._request("GET", "some/path", authenticated=True)


# ---------------------------------------------------------------------------
# Coverage Expansion: coordinator.py uncovered lines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coordinator_boot_time_calculated(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test coordinator boot_time from realtime_time (coordinator.py:79-90)."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)

    with (
        patch.object(api, "get_all_data", return_value={"realtime_time": "3600"}),
        patch.object(api, "get_sms_capacity", return_value={}),
        patch.object(api, "get_sms_messages", return_value=[]),
        patch("custom_components.zte_router_5g.coordinator.dr.async_get"),
    ):
        data = await coordinator._async_update_data()
        assert "boot_time" in data
        assert data["boot_time"] is not None


@pytest.mark.asyncio
async def test_coordinator_boot_time_value_error(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test coordinator boot_time handles ValueError (coordinator.py:91-92)."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)

    with (
        patch.object(
            api, "get_all_data", return_value={"realtime_time": "not_a_number"}
        ),
        patch.object(api, "get_sms_capacity", return_value={}),
        patch.object(api, "get_sms_messages", return_value=[]),
        patch("custom_components.zte_router_5g.coordinator.dr.async_get"),
    ):
        data = await coordinator._async_update_data()
        assert data.get("boot_time") is None


@pytest.mark.asyncio
async def test_coordinator_boot_time_missing(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test boot_time when realtime_time is missing (coordinator.py:93-94)."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)

    with (
        patch.object(api, "get_all_data", return_value={"network_type": "LTE"}),
        patch.object(api, "get_sms_capacity", return_value={}),
        patch.object(api, "get_sms_messages", return_value=[]),
        patch("custom_components.zte_router_5g.coordinator.dr.async_get"),
    ):
        data = await coordinator._async_update_data()
        assert data.get("boot_time") is None


@pytest.mark.asyncio
async def test_coordinator_reconnection_log(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test reconnection log when _was_available flips (coordinator.py:129-130)."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)
    coordinator._was_available = False  # Simulate previous failure

    with (
        patch.object(api, "get_all_data", return_value={"network_type": "LTE"}),
        patch.object(api, "get_sms_capacity", return_value={}),
        patch.object(api, "get_sms_messages", return_value=[]),
        patch("custom_components.zte_router_5g.coordinator.dr.async_get"),
    ):
        data = await coordinator._async_update_data()
        assert coordinator._was_available is True
        assert data["network_type"] == "LTE"


@pytest.mark.asyncio
async def test_coordinator_sms_storage_check_exception(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test _check_sms_storage handles int errors (coordinator.py:229-230)."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)

    with (
        patch.object(
            api,
            "get_all_data",
            return_value={"nv_sms_able": "invalid", "sms_nv_total": "20"},
        ),
        patch.object(api, "get_sms_capacity", return_value={}),
        patch.object(api, "get_sms_messages", return_value=[]),
        patch("custom_components.zte_router_5g.coordinator.dr.async_get"),
    ):
        # Should not raise, just return silently
        data = await coordinator._async_update_data()
        assert data is not None


@pytest.mark.asyncio
async def test_api_request_html_text_exception(mock_aiohttp_client):
    """Test _request HTML detection when r.text() raises (api.py:129-130).

    The exception is caught by the except pass block; execution continues
    to JSON parsing. This test validates that the pass block is entered.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_response = MockResponse(json_data={}, headers={"Content-Type": "text/html"})
    mock_aiohttp_client.get.return_value = mock_response
    with patch.object(
        mock_response, "text", side_effect=aiohttp.ClientError("Read error")
    ):
        # text() raises, pass suppresses it, then JSON parse returns {}
        result = await api._request("GET", "some/path", authenticated=False)
        assert result == {}


@pytest.mark.asyncio
async def test_api_request_html_body_preview_exception(mock_aiohttp_client):
    """Test _request body preview exception handler (api.py:152-153).

    Triggered when is_html_page is True, authenticated is False or _retry is False,
    and r.text() raises during body_preview extraction.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_response = MockResponse(json_data={}, url="http://192.168.0.1/index.html")
    mock_aiohttp_client.get.return_value = mock_response
    with (
        patch.object(mock_response, "text", side_effect=Exception("Body read error")),
        pytest.raises(ZTEConnectionError, match="Received unexpected HTML response"),
    ):
        await api._request("GET", "some/path", authenticated=False)


# ---------------------------------------------------------------------------
# Phase 2 Coverage Expansion: api.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_login_session_init_success(mock_aiohttp_client):
    """Test login where session init GET succeeds (api.py:368)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    mock_stok_cookie = MagicMock()
    mock_stok_cookie.value = "test_stok"

    # Three GET calls: LD, version, session-init
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "test_ld"}),
        MockResponse(json_data={"wa_inner_version": "test_v"}),
        MockResponse(json_data={"wa_inner_version": "test_v"}),
    ]

    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": mock_stok_cookie}
    )

    stok = await api.login()
    assert stok == "stok=test_stok"
    assert api.stok == "stok=test_stok"


@pytest.mark.asyncio
async def test_api_get_sms_capacity_other_exception(mock_aiohttp_client):
    """Test get_sms_capacity defensive handler for non-auth errors (api.py:464-465)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now(UTC)

    with patch.object(api, "_request", side_effect=ValueError("Unexpected value")):
        result = await api.get_sms_capacity()
        assert result == {}


@pytest.mark.asyncio
async def test_api_get_last_sms_content_other_exception(mock_aiohttp_client):
    """Test get_last_sms_content defensive handler (api.py:543-544)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now(UTC)

    with patch.object(api, "_request", side_effect=TimeoutError("Timeout")):
        result = await api.get_last_sms_content()
        assert result == {}


@pytest.mark.asyncio
async def test_api_get_sms_messages_other_exception(mock_aiohttp_client):
    """Test get_sms_messages defensive handler (api.py:652-654)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now(UTC)

    with patch.object(api, "_request", side_effect=TimeoutError("Timeout")):
        result = await api.get_sms_messages()
        assert result == []


@pytest.mark.asyncio
async def test_api_get_rd_other_exception(mock_aiohttp_client):
    """Test get_rd defensive handler (api.py:631-632)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now(UTC)

    with patch.object(api, "_request", side_effect=ValueError("Unexpected value")):
        result = await api.get_rd()
        assert result == ""


# ---------------------------------------------------------------------------
# Phase 2 Coverage Expansion: coordinator.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coordinator_boot_time_restored(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test coordinator restores boot_time from entry.data (coordinator.py:47-48)."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    # Add boot_time to entry.data so coordinator picks it up
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, "boot_time": "2024-01-15T10:00:00"},
    )
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)
    assert coordinator._boot_time is not None
    assert coordinator._boot_time.isoformat() == "2024-01-15T10:00:00"


@pytest.mark.asyncio
async def test_coordinator_boot_time_restored_bad_value(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test coordinator suppresses bad boot_time string (coordinator.py:47-48)."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, "boot_time": "not_a_valid_datetime"},
    )
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)
    assert coordinator._boot_time is None


@pytest.mark.asyncio
async def test_coordinator_last_uptime_restored(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test coordinator restores last_uptime from entry.data (coordinator.py:51-52)."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, "last_uptime": "12345"},
    )
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)
    assert coordinator._last_uptime == 12345


@pytest.mark.asyncio
async def test_coordinator_last_uptime_restored_bad_value(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test coordinator suppresses bad last_uptime (coordinator.py:51-52)."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, "last_uptime": "not_a_number"},
    )
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)
    assert coordinator._last_uptime is None


@pytest.mark.asyncio
async def test_coordinator_sms_auth_retry(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test coordinator retries SMS fetch after ZTEAuthError (coord:100-101)."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)

    with (
        patch.object(api, "get_all_data", return_value={"network_type": "LTE"}),
        patch.object(api, "get_sms_capacity", return_value={"sms_cap": 100}),
        patch.object(
            api,
            "get_sms_messages",
            side_effect=[
                ZTEAuthError("Session expired"),
                [
                    {
                        "id": "1",
                        "content_decoded": "hi",
                        "number_decoded": "123",
                        "date_decoded": "2024-01-01T00:00:00",
                    }
                ],
            ],
        ),
        patch.object(api, "login", return_value="stok=new"),
        patch("custom_components.zte_router_5g.coordinator.dr.async_get"),
    ):
        data = await coordinator._async_update_data()
        assert data["network_type"] == "LTE"
        assert data.get("sms_cap") == 100
        assert data.get("last_sms", {}).get("content_decoded") == "hi"


@pytest.mark.asyncio
async def test_coordinator_check_new_sms_no_date_decoded(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test _check_new_sms early return no date_decoded (coord:310)."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)

    with (
        patch.object(api, "get_all_data", return_value={"network_type": "LTE"}),
        patch.object(api, "get_sms_capacity", return_value={}),
        patch.object(
            api,
            "get_sms_messages",
            return_value=[{"id": "1"}],
        ),
        patch("custom_components.zte_router_5g.coordinator.dr.async_get"),
    ):
        data = await coordinator._async_update_data()
        assert data["network_type"] == "LTE"


@pytest.mark.asyncio
async def test_coordinator_check_new_sms_same_timestamp(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Test _check_new_sms adds hash when same timestamp (coordinator.py:357)."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)

    # Pre-set baseline so we get past first-run guard
    coordinator.last_sms_timestamp = "2024-01-01T00:00:00"
    coordinator.fired_sms_hashes = {"2_2024-01-01T00:00:00"}

    with (
        patch.object(api, "get_all_data", return_value={"network_type": "LTE"}),
        patch.object(api, "get_sms_capacity", return_value={}),
        patch.object(
            api,
            "get_sms_messages",
            return_value=[
                {
                    "id": "1",
                    "content_decoded": "hi",
                    "number_decoded": "123",
                    "date_decoded": "2024-01-01T00:00:00",
                },
            ],
        ),
        patch("custom_components.zte_router_5g.coordinator.dr.async_get"),
    ):
        data = await coordinator._async_update_data()
        assert data["network_type"] == "LTE"
        assert "1_2024-01-01T00:00:00" in coordinator.fired_sms_hashes


@pytest.mark.asyncio
async def test_coordinator_config_entry_associated(
    hass: HomeAssistant, mock_config_entry, mock_aiohttp_client
):
    """Coordinator passes config_entry to base so HA honours pref_disable_polling."""
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    mock_config_entry.add_to_hass(hass)
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    coordinator = ZTERouterDataUpdateCoordinator(hass, mock_config_entry, api)

    assert coordinator.config_entry is mock_config_entry


@pytest.mark.asyncio
async def test_api_login_json_parse_failure(mock_aiohttp_client):
    """Test login when stok missing and r.json() raises ValueError (api.py:333-334)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "test_ld"}),
        MockResponse(json_data={"wa_inner_version": "test_v"}),
    ]

    # Login response: no stok cookie, json() raises ValueError
    login_response = MockResponse(cookies={})
    with patch.object(login_response, "json", side_effect=ValueError("Bad JSON")):
        mock_aiohttp_client.post.return_value = login_response
        with pytest.raises(
            ZTEConnectionError, match="Failed to obtain stok from login"
        ):
            await api.login()


@pytest.mark.asyncio
async def test_api_login_session_init_failure(mock_aiohttp_client):
    """Test login where session init GET fails gracefully (api.py:373-374)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    mock_stok_cookie = MagicMock()
    mock_stok_cookie.value = "test_stok"

    # LD, version, then session init fails
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "test_ld"}),
        MockResponse(json_data={"wa_inner_version": "test_v"}),
        TimeoutError("Init timeout"),
    ]

    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": mock_stok_cookie}
    )

    stok = await api.login()
    assert stok == "stok=test_stok"
    assert api.stok == "stok=test_stok"


@pytest.mark.asyncio
async def test_api_delete_all_list_timeout(mock_aiohttp_client):
    """Test delete_all when delete_sms raises TimeoutError (api.py:593-595)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now(UTC)

    with (
        patch.object(api, "_request") as mock_req,
        patch.object(api, "login", return_value="stok=test"),
        patch.object(api, "get_ad", return_value="test_ad"),
    ):
        mock_req.side_effect = [
            {"messages": [{"id": "1"}, {"id": "2"}]},
            TimeoutError("Delete SMS timeout"),
        ]
        with pytest.raises(
            ZTEConnectionError, match="Failed to delete all SMS: Delete SMS timeout"
        ):
            await api.delete_all()
