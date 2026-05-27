"""Tests for ZTE Router 5G API."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from custom_components.zte_router_5g.api import (
    ZTEAuthError,
    ZTEConnectionError,
    ZTERouterAPI,
)

from .conftest import MockResponse


def test_api_hash():
    """Test the SHA256 hashing helper."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    assert (
        api._hash("test")
        == "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    )


def test_api_hash_none():
    """Test _hash with None input."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    with pytest.raises(ValueError, match="Input to hash function cannot be None"):
        api._hash(None)


def test_api_hex_decode():
    """Test hex decoding helper."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    assert api._hex_decode("00480065006c006c006f") == "Hello"
    assert api._hex_decode("") == ""
    assert api._hex_decode("invalid") == "[Decoding Error]"


def test_api_parse_date():
    """Test date parsing helper."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    assert api._parse_date("23,10,10,10,0,0,+1") == "2023-10-10T10:00:00"
    assert api._parse_date("") is None
    assert api._parse_date("invalid") == "invalid"


def test_api_parse_date_error():
    """Test date parsing with a string that splits but fails int conversion."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    assert api._parse_date("23,fail,10,10,00,00") == "23,fail,10,10,00,00"


@pytest.mark.asyncio
async def test_api_try_set_protocol(mock_aiohttp_client):
    """Test protocol detection logic."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    # Success on first attempt (http)
    mock_aiohttp_client.get.side_effect = [MockResponse(status=200)]

    await api.try_set_protocol()
    assert api.protocol == "http"
    assert api.referer == "http://192.168.0.1/"


@pytest.mark.asyncio
async def test_api_try_set_protocol_error(mock_aiohttp_client):
    """Test protocol detection with connection errors."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    # Fail both http and https
    mock_aiohttp_client.get.side_effect = Exception("Connect Fail")
    await api.try_set_protocol()
    assert api.protocol == "http"


@pytest.mark.asyncio
async def test_api_get_version(mock_aiohttp_client):
    """Test version fetching."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"wa_inner_version": "test_v"}
    )
    assert await api.get_version() == "test_v"


@pytest.mark.asyncio
async def test_api_get_version_error(mock_aiohttp_client):
    """Test version fetching error."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    mock_aiohttp_client.get.side_effect = Exception("Fail")
    assert await api.get_version() is None


@pytest.mark.asyncio
async def test_api_login_success(mock_aiohttp_client):
    """Test successful login."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    # LD, Version, then Post for Login
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "test_ld"}),
        MockResponse(json_data={"wa_inner_version": "test_v"}),
    ]

    mock_stok_cookie = MagicMock()
    mock_stok_cookie.value = "test_stok"
    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": mock_stok_cookie}
    )

    stok = await api.login()
    assert stok == "stok=test_stok"
    assert api.stok == "stok=test_stok"


@pytest.mark.asyncio
async def test_api_login_no_password(mock_aiohttp_client):
    """Test login failure when no password provided."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "")
    with (
        patch.object(api, "get_ld", return_value="LD"),
        patch.object(api, "get_version", return_value="VER"),
        pytest.raises(Exception, match="No password provided"),
    ):
        await api.login()


@pytest.mark.asyncio
async def test_api_login_failure_no_stok(mock_aiohttp_client):
    """Test login failure when response missing stok."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "pass")

    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "LD"}),
        MockResponse(json_data={"wa_inner_version": "VER"}),
    ]
    mock_aiohttp_client.post.return_value = MockResponse(cookies={})

    with pytest.raises(ZTEConnectionError, match="Failed to obtain stok"):
        await api.login()


@pytest.mark.asyncio
async def test_api_get_all_data_expired_session(mock_aiohttp_client):
    """Test session expiry handling in get_all_data."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=old_stok"

    # 1. Expired response (empty network_type/signalbar)
    # 2. Success response after re-login
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"network_type": "", "signalbar": ""}),
        MockResponse(json_data={"network_type": "LTE", "signalbar": "4"}),
    ]

    with patch.object(api, "login") as mock_login:
        data = await api.get_all_data()
        assert data["network_type"] == "LTE"
        assert mock_login.called


@pytest.mark.asyncio
async def test_api_get_all_data_retry_exhausted(mock_aiohttp_client):
    """Test get_all_data when re-login also returns empty data."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=old_stok"

    # Both calls return empty data — retry is exhausted, raises ZTEAuthError
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"network_type": "", "signalbar": ""}),
        MockResponse(json_data={"network_type": "", "signalbar": ""}),
    ]

    with patch.object(api, "login") as mock_login:
        with pytest.raises(ZTEAuthError, match="Session expired/unauthorized"):
            await api.get_all_data()
        assert mock_login.called


@pytest.mark.asyncio
async def test_api_get_all_data_error(mock_aiohttp_client):
    """Test technical data fetch error."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_aiohttp_client.get.side_effect = Exception("Network Error")
    with pytest.raises(ZTEConnectionError, match="Request failed: Network Error"):
        await api.get_all_data()
    assert api.stok is None


@pytest.mark.asyncio
async def test_api_get_sms_capacity(mock_aiohttp_client):
    """Test SMS capacity fetch."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    mock_aiohttp_client.get.return_value = MockResponse(json_data={"cap": 100})
    assert await api.get_sms_capacity() == {"cap": 100}


@pytest.mark.asyncio
async def test_api_get_sms_capacity_error(mock_aiohttp_client):
    """Test SMS capacity fetch error."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_aiohttp_client.get.side_effect = Exception("Fail")
    with pytest.raises(ZTEConnectionError):
        await api.get_sms_capacity()


@pytest.mark.asyncio
async def test_api_get_last_sms_content(mock_aiohttp_client):
    """Test last SMS fetching and decoding."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={
            "messages": [
                {
                    "id": "1",
                    "content": "00480065006c006c006f",
                    "number": "003100320033",
                    "date": "23,10,10,10,0,0,+1",
                }
            ]
        }
    )

    msg = await api.get_last_sms_content()
    assert msg["content_decoded"] == "Hello"
    assert msg["number_decoded"] == "123"
    assert msg["date_decoded"] == "2023-10-10T10:00:00"


@pytest.mark.asyncio
async def test_api_get_last_sms_content_empty(mock_aiohttp_client):
    """Test last SMS fetching when mailbox is empty."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    mock_aiohttp_client.post.return_value = MockResponse(json_data={"messages": []})
    assert await api.get_last_sms_content() == {}


@pytest.mark.asyncio
async def test_api_reboot_success(mock_aiohttp_client):
    """Test reboot command success."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    with (
        patch.object(api, "login"),
        patch.object(api, "get_ad", return_value="test_ad"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(status=200)
        assert await api.reboot() == 200


@pytest.mark.asyncio
async def test_api_reboot_error(mock_aiohttp_client):
    """Test reboot command failure."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    with (
        patch.object(api, "login"),
        patch.object(api, "get_ad", return_value="test_ad"),
        pytest.raises(ZTEConnectionError, match="Request failed: Fail"),
    ):
        mock_aiohttp_client.post.side_effect = RuntimeError("Fail")
        await api.reboot()
    assert api.stok is None


@pytest.mark.asyncio
async def test_api_delete_sms(mock_aiohttp_client):
    """Test single SMS deletion."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    with patch.object(api, "get_ad", return_value="test_ad"):
        mock_aiohttp_client.post.return_value = MockResponse(status=200)
        assert await api.delete_sms("1") == 200


@pytest.mark.asyncio
async def test_api_delete_sms_exception(mock_aiohttp_client):
    """Test single SMS deletion exception handling."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    with patch.object(api, "get_ad", return_value="test_ad"):
        mock_aiohttp_client.post.side_effect = RuntimeError("Delete Fail")
        with pytest.raises(ZTEConnectionError, match="Request failed: Delete Fail"):
            await api.delete_sms("1")
        assert api.stok is None


@pytest.mark.asyncio
async def test_api_delete_all_success(mock_aiohttp_client):
    """Test bulk SMS deletion logic."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"

    mock_aiohttp_client.post.side_effect = [
        MockResponse(json_data={"messages": [{"id": "1"}, {"id": "2"}]}),
        MockResponse(status=200),
    ]

    with patch.object(api, "login"), patch.object(api, "get_ad", return_value="ad"):
        assert await api.delete_all() == 200


@pytest.mark.asyncio
async def test_api_delete_all_empty(mock_aiohttp_client):
    """Test bulk SMS deletion when no messages exist."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_aiohttp_client.post.return_value = MockResponse(json_data={"messages": []})
    with patch.object(api, "login"):
        assert await api.delete_all() == 200


@pytest.mark.asyncio
async def test_api_get_ad_new_gen(mock_aiohttp_client):
    """Test AD hash generation for new generation models (MC888/MC889)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    with (
        patch.object(api, "get_version", return_value="MC888_VER"),
        patch.object(api, "get_rd", return_value="test_rd"),
    ):
        ad = await api.get_ad()
        assert len(ad) == 64


@pytest.mark.asyncio
async def test_api_get_rd_error(mock_aiohttp_client):
    """Test RD fetch error."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=fake"
    mock_aiohttp_client.get.side_effect = Exception("Fail")
    with pytest.raises(ZTEConnectionError):
        await api.get_rd()


@pytest.mark.asyncio
async def test_api_send_sms_success(mock_aiohttp_client):
    """Test successful SMS sending."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    with patch.object(api, "get_ad", return_value="test_ad"):
        mock_aiohttp_client.post.return_value = MockResponse(status=200)
        assert await api.send_sms("+123456", "Hello") == 200


@pytest.mark.asyncio
async def test_api_get_sms_messages_success(mock_aiohttp_client):
    """Test fetching and decoding list of SMS messages."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={
            "messages": [
                {
                    "id": "1",
                    "content": "00480065006c006c006f",  # "Hello"
                    "number": "003100320033",  # "123"
                    "date": "23,10,10,10,0,0,+1",
                    "tag": "1",
                }
            ]
        }
    )
    msgs = await api.get_sms_messages(mem_store="1", tags="10")
    assert len(msgs) == 1
    assert msgs[0]["content_decoded"] == "Hello"
    assert msgs[0]["number_decoded"] == "123"
    assert msgs[0]["date_decoded"] == "2023-10-10T10:00:00"


@pytest.mark.asyncio
async def test_api_get_sms_messages_error(mock_aiohttp_client):
    """Test get_sms_messages error handling."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=fake"
    mock_aiohttp_client.post.side_effect = Exception("Fetch Fail")
    with pytest.raises(ZTEConnectionError):
        await api.get_sms_messages(mem_store="1", tags="10")


# ── Strategy 1: Boundary Value Analysis ────────────────────────────────────


@pytest.mark.parametrize(
    "elapsed,stok_cleared",
    [
        (149, False),
        (151, True),
    ],
)
@pytest.mark.asyncio
async def test_request_inactivity_threshold(elapsed, stok_cleared, mock_aiohttp_client):
    """1F: Stok is cleared only when last_activity gap is strictly greater than 150s."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=existing"
    api.last_activity = datetime.now() - timedelta(seconds=elapsed)

    with patch.object(api, "login", return_value="stok=new") as mock_login:
        mock_aiohttp_client.get.return_value = MockResponse(
            json_data={"network_type": "LTE", "signalbar": "4"}
        )
        await api.get_all_data()
        if stok_cleared:
            mock_login.assert_called_once()
            assert api.stok == "stok=new"
        else:
            mock_login.assert_not_called()
            assert api.stok == "stok=existing"


# ── Strategy 3: Error State & Negative Path Engineering ─────────────────────


@pytest.mark.parametrize(
    "date_str,expected",
    [
        ("23,13,01,10,0,0,+1", "23,13,01,10,0,0,+1"),
        ("23,10,32,10,0,0,+1", "23,10,32,10,0,0,+1"),
        ("23,02,30,10,0,0,+1", "23,02,30,10,0,0,+1"),
    ],
)
def test_api_parse_date_invalid_calendar_values(date_str, expected):
    """3D: Dates with valid format but invalid calendar values are returned as-is."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    assert api._parse_date(date_str) == expected


# ── Coverage: api.py setter methods (lines 674-744) ─────────────────────────


@pytest.mark.asyncio
async def test_api_set_apn_success(mock_aiohttp_client):
    """Test set_apn calls the right endpoint."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        result = await api.set_apn(3, "IPV4V6")
        assert result == {"result": "ok"}
        mock_aiohttp_client.post.assert_called_once()
        # Verify payload includes the right params
        _args, kwargs = mock_aiohttp_client.post.call_args
        data = kwargs["data"]
        assert "apn_action=set_default" in data
        assert "index=3" in data
        assert "pdp_type=IPV4V6" in data


@pytest.mark.asyncio
async def test_api_set_apn_mode_success(mock_aiohttp_client):
    """Test set_apn_mode calls the right endpoint."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        result = await api.set_apn_mode("manual")
        assert result == {"result": "ok"}
        _args, kwargs = mock_aiohttp_client.post.call_args
        data = kwargs["data"]
        assert "apn_mode=manual" in data


@pytest.mark.asyncio
async def test_api_set_apn_mode_error(mock_aiohttp_client):
    """Test set_apn_mode propagates connection error."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
        pytest.raises(ZTEConnectionError, match="Request failed"),
    ):
        mock_aiohttp_client.post.side_effect = RuntimeError("APN mode fail")
        await api.set_apn_mode("auto")


@pytest.mark.asyncio
async def test_api_set_odu_led_switch_on(mock_aiohttp_client):
    """Test set_odu_led_switch turns the LED on."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        result = await api.set_odu_led_switch("1")
        assert result == {"result": "ok"}
        _args, kwargs = mock_aiohttp_client.post.call_args
        data = kwargs["data"]
        assert "ODU_led_switch=1" in data


@pytest.mark.asyncio
async def test_api_set_odu_led_switch_off(mock_aiohttp_client):
    """Test set_odu_led_switch turns the LED off."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        result = await api.set_odu_led_switch("0")
        assert result == {"result": "ok"}
        _args, kwargs = mock_aiohttp_client.post.call_args
        data = kwargs["data"]
        assert "ODU_led_switch=0" in data


@pytest.mark.asyncio
async def test_api_set_data_limit_switch_on(mock_aiohttp_client):
    """Test set_data_limit_switch enables data limit."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        result = await api.set_data_limit_switch("1")
        assert result == {"result": "ok"}
        _args, kwargs = mock_aiohttp_client.post.call_args
        data = kwargs["data"]
        assert "data_volume_limit_switch=1" in data


@pytest.mark.asyncio
async def test_api_set_data_limit_switch_off(mock_aiohttp_client):
    """Test set_data_limit_switch disables data limit."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        result = await api.set_data_limit_switch("0")
        assert result == {"result": "ok"}
        _args, kwargs = mock_aiohttp_client.post.call_args
        data = kwargs["data"]
        assert "data_volume_limit_switch=0" in data


@pytest.mark.asyncio
async def test_api_set_bearer_preference(mock_aiohttp_client):
    """Test set_bearer_preference calls the right endpoint."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        result = await api.set_bearer_preference("4G_AND_5G")
        assert result == {"result": "ok"}
        _args, kwargs = mock_aiohttp_client.post.call_args
        data = kwargs["data"]
        assert "BearerPreference=4G_AND_5G" in data


@pytest.mark.asyncio
async def test_api_set_bearer_preference_only_5g(mock_aiohttp_client):
    """Test set_bearer_preference with Only_5G."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        result = await api.set_bearer_preference("Only_5G")
        assert result == {"result": "ok"}
        _args, kwargs = mock_aiohttp_client.post.call_args
        data = kwargs["data"]
        assert "BearerPreference=Only_5G" in data


@pytest.mark.asyncio
async def test_api_set_bearer_preference_error(mock_aiohttp_client):
    """Test set_bearer_preference propagates connection error."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
        pytest.raises(ZTEConnectionError, match="Request failed"),
    ):
        mock_aiohttp_client.post.side_effect = RuntimeError("Bearer pref fail")
        await api.set_bearer_preference("Only_LTE")


@pytest.mark.asyncio
async def test_api_set_apn_mode_manual(mock_aiohttp_client):
    """Test set_apn_mode with 'manual'."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now()
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        result = await api.set_apn_mode("manual")
        assert result == {"result": "ok"}
        _args, kwargs = mock_aiohttp_client.post.call_args
        data = kwargs["data"]
        assert "apn_mode=manual" in data
