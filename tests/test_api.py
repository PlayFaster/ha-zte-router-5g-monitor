"""Tests for ZTE Router 5G API."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import aiohttp
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
    assert api._parse_date("23,10,10,10,0,0,+1") == "2023-10-10T10:00:00+00:00"
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
    mock_aiohttp_client.get.side_effect = TimeoutError("Connect Fail")
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
    mock_aiohttp_client.get.side_effect = aiohttp.ClientError("Fail")
    assert await api.get_version() is None


@pytest.mark.asyncio
async def test_api_login_success(mock_aiohttp_client):
    """Test successful login."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    # LD, Version, session init, then Post for Login
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "test_ld"}),
        MockResponse(json_data={"wa_inner_version": "test_v"}),
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
    mock_aiohttp_client.post.return_value = MockResponse(json_data={}, cookies={})

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
    mock_aiohttp_client.get.side_effect = aiohttp.ClientError("Network Error")
    with pytest.raises(ZTEConnectionError, match="Request failed: Network Error"):
        await api.get_all_data()
    assert api.stok is None


@pytest.mark.asyncio
async def test_api_get_sms_capacity(mock_aiohttp_client):
    """Test SMS capacity fetch."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now(UTC)
    # Real capacity shape, captured from an MC7010 on 2026-07-27. The previous
    # fixture was `{"cap": 100}` — a shape this router never returns, which let
    # the endpoint's contract go unasserted.
    capacity = {
        "sms_nv_total": "100",
        "sms_sim_total": "20",
        "sms_nv_rev_total": "2",
    }
    mock_aiohttp_client.get.return_value = MockResponse(json_data=capacity)
    assert await api.get_sms_capacity() == capacity


@pytest.mark.asyncio
async def test_api_get_sms_capacity_error(mock_aiohttp_client):
    """Test SMS capacity fetch error."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_aiohttp_client.get.side_effect = aiohttp.ClientError("Fail")
    with pytest.raises(ZTEConnectionError):
        await api.get_sms_capacity()


@pytest.mark.asyncio
async def test_api_get_last_sms_content(mock_aiohttp_client):
    """Test last SMS fetching and decoding."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now(UTC)
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
    assert msg["date_decoded"] == "2023-10-10T10:00:00+00:00"


@pytest.mark.asyncio
async def test_api_get_last_sms_content_empty(mock_aiohttp_client):
    """Test last SMS fetching when mailbox is empty."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.post.return_value = MockResponse(json_data={"messages": []})
    assert await api.get_last_sms_content() == {}


@pytest.mark.asyncio
async def test_api_reboot_success(mock_aiohttp_client):
    """Test reboot command success."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    with (
        patch.object(api, "login", return_value="stok=test"),
        patch.object(api, "get_ad", return_value="test_ad"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(
            json_data={"result": "ok"}, status=200
        )
        assert await api.reboot() == 200


@pytest.mark.asyncio
async def test_api_reboot_error(mock_aiohttp_client):
    """Test reboot command failure."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    with (
        patch.object(api, "login"),
        patch.object(api, "get_ad", return_value="test_ad"),
    ):
        mock_aiohttp_client.post.side_effect = aiohttp.ClientError("Fail")
        with pytest.raises(ZTEConnectionError, match="Request failed: Fail"):
            await api.reboot()
    assert api.stok is None


@pytest.mark.asyncio
async def test_api_delete_sms(mock_aiohttp_client):
    """Test single SMS deletion."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now(UTC)
    with patch.object(api, "get_ad", return_value="test_ad"):
        mock_aiohttp_client.post.return_value = MockResponse(
            json_data={"result": "ok"}, status=200
        )
        assert await api.delete_sms("1") == 200


@pytest.mark.asyncio
async def test_api_delete_sms_exception(mock_aiohttp_client):
    """Test single SMS deletion exception handling."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now(UTC)
    with patch.object(api, "get_ad", return_value="test_ad"):
        mock_aiohttp_client.post.side_effect = aiohttp.ClientError("Delete Fail")
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
        MockResponse(json_data={"result": "ok"}, status=200),
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
    mock_aiohttp_client.get.side_effect = aiohttp.ClientError("Fail")
    with pytest.raises(ZTEConnectionError):
        await api.get_rd()


@pytest.mark.asyncio
async def test_api_send_sms_success(mock_aiohttp_client):
    """Test successful SMS sending."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now(UTC)
    with patch.object(api, "get_ad", return_value="test_ad"):
        mock_aiohttp_client.post.return_value = MockResponse(
            json_data={"result": "ok"}, status=200
        )
        assert await api.send_sms("+123456", "Hello") == 200


@pytest.mark.asyncio
async def test_api_get_sms_messages_success(mock_aiohttp_client):
    """Test fetching and decoding list of SMS messages."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now(UTC)
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
    assert msgs[0]["date_decoded"] == "2023-10-10T10:00:00+00:00"


@pytest.mark.asyncio
async def test_api_get_sms_messages_error(mock_aiohttp_client):
    """Test get_sms_messages error handling."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=fake"
    mock_aiohttp_client.get.return_value = MockResponse(json_data={"LD": "test_ld"})
    mock_aiohttp_client.post.side_effect = aiohttp.ClientError("Fetch Fail")
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
    api.last_activity = datetime.now(UTC) - timedelta(seconds=elapsed)

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
    api.last_activity = datetime.now(UTC)
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
    api.last_activity = datetime.now(UTC)
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
    api.last_activity = datetime.now(UTC)
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.side_effect = aiohttp.ClientError("APN mode fail")
        with pytest.raises(ZTEConnectionError, match="Request failed"):
            await api.set_apn_mode("auto")


@pytest.mark.asyncio
async def test_api_set_odu_led_switch_on(mock_aiohttp_client):
    """Test set_odu_led_switch turns the LED on."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now(UTC)
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
    api.last_activity = datetime.now(UTC)
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
    api.last_activity = datetime.now(UTC)
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
    api.last_activity = datetime.now(UTC)
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
    api.last_activity = datetime.now(UTC)
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
    api.last_activity = datetime.now(UTC)
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
    api.last_activity = datetime.now(UTC)
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.side_effect = aiohttp.ClientError("Bearer pref fail")
        with pytest.raises(ZTEConnectionError, match="Request failed"):
            await api.set_bearer_preference("Only_LTE")


@pytest.mark.asyncio
async def test_api_set_apn_mode_manual(mock_aiohttp_client):
    """Test set_apn_mode with 'manual'."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    api.last_activity = datetime.now(UTC)
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


# --------------------------------------------------------------------------
# Expired-session detection — regression guard
#
# Payloads below are REAL, captured from an MC7010 on firmware V1.0.0B03 on
# 2026-07-27 by replaying an invalidated stok. Do not "tidy" them into
# something more plausible-looking; their exact shape is the whole point.
# --------------------------------------------------------------------------

# What the router returns to an authenticated request on a DEAD session:
# HTTP 200, Content-Type text/html, requested keys echoed back empty.
DEAD_SMS_LIST = {"sms_data_total": ""}
DEAD_SMS_CAPACITY = {"sms_capacity_info": ""}
DEAD_BATCH_POLL = {"network_type": "", "signalbar": "", "wan_ipaddr": ""}

# What it returns on a LIVE session — note the empty inbox, which must never
# be confused with the dead-session shape above.
LIVE_SMS_EMPTY_INBOX = {"messages": []}
LIVE_SMS_WITH_MESSAGE = {
    "messages": [
        {
            "id": "2",
            "number": "002B00330035",
            "content": "0054006500730074",
            "tag": "0",
            "date": "26,07,26,23,52,23,+4",
        }
    ]
}


@pytest.mark.parametrize(
    "dead_payload",
    [DEAD_SMS_LIST, DEAD_SMS_CAPACITY, DEAD_BATCH_POLL],
    ids=["sms_list", "sms_capacity", "batch_poll"],
)
def test_dead_session_payloads_are_all_detected(dead_payload):
    """Every dead-session shape must satisfy the expiry rule in `_request`.

    The rule is "every value is an empty string". The previous rule named the
    batch-poll keys explicitly, so it could not fire on an SMS response —
    `.get("network_type")` is None there and `None == ""` is False. That gap
    is why an expired session surfaced as "no SMS" rather than an error.
    """
    assert bool(dead_payload) and all(v == "" for v in dead_payload.values())


@pytest.mark.parametrize(
    "live_payload",
    [LIVE_SMS_EMPTY_INBOX, LIVE_SMS_WITH_MESSAGE],
    ids=["empty_inbox", "has_message"],
)
def test_live_session_payloads_are_not_mistaken_for_expiry(live_payload):
    """An empty inbox is a valid answer and must not trigger a re-login."""
    assert not (bool(live_payload) and all(v == "" for v in live_payload.values()))


@pytest.mark.asyncio
async def test_expired_session_on_sms_relogs_in_and_returns_messages(
    mock_aiohttp_client,
):
    """The reported bug, end to end: dead session -> re-login -> real messages.

    Before the fix this returned `[]` with no error and no re-login attempt,
    which is indistinguishable from an empty inbox. Pressing Refresh Now
    recovered it only because the batch poll's keys *were* recognised.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=dead"
    api.last_activity = datetime.now(UTC)  # inside the 150s guard, so it stays quiet

    responses = [
        MockResponse(json_data=DEAD_SMS_LIST, headers={"Content-Type": "text/html"}),
        MockResponse(
            json_data=LIVE_SMS_WITH_MESSAGE, headers={"Content-Type": "text/html"}
        ),
    ]
    mock_aiohttp_client.post = MagicMock(side_effect=responses)

    with patch.object(ZTERouterAPI, "login", return_value="stok=fresh") as mock_login:
        messages = await api.get_sms_messages()

    mock_login.assert_awaited_once()
    assert len(messages) == 1
    assert messages[0]["content_decoded"] == "Test"


@pytest.mark.asyncio
async def test_persistently_dead_session_raises_instead_of_returning_empty(
    mock_aiohttp_client,
):
    """A session still dead after re-login must raise, never return `[]`.

    This is the masked-errors rule: an empty default on a failure path is
    indistinguishable from a legitimately empty result, so the user is told
    "no SMS" when the truth is "we could not talk to the router".
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=dead"
    api.last_activity = datetime.now(UTC)

    mock_aiohttp_client.post = MagicMock(
        side_effect=[
            MockResponse(json_data=DEAD_SMS_LIST, headers={"Content-Type": "text/html"})
            for _ in range(4)
        ]
    )

    with (
        patch.object(ZTERouterAPI, "login", return_value="stok=fresh"),
        pytest.raises(ZTEAuthError),
    ):
        await api.get_sms_messages()


@pytest.mark.asyncio
async def test_missing_contract_key_raises_even_if_expiry_undetected(
    mock_aiohttp_client,
):
    """Second line of defence, independent of the expiry detector.

    If the router ever answers with a shape the detector does not recognise,
    the endpoint contract must still refuse to report it as "no messages".
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=live"
    api.last_activity = datetime.now(UTC)

    # Non-empty values, so the expiry rule does NOT fire — but no `messages`.
    mock_aiohttp_client.post = MagicMock(
        return_value=MockResponse(
            json_data={"unexpected": "shape"}, headers={"Content-Type": "text/html"}
        )
    )

    with pytest.raises(ZTEConnectionError, match="missing 'messages'"):
        await api.get_sms_messages()


@pytest.mark.asyncio
async def test_empty_inbox_still_returns_empty_list(mock_aiohttp_client):
    """Guard against over-correction: a real empty inbox must not raise."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=live"
    api.last_activity = datetime.now(UTC)

    mock_aiohttp_client.post = MagicMock(
        return_value=MockResponse(
            json_data=LIVE_SMS_EMPTY_INBOX, headers={"Content-Type": "text/html"}
        )
    )

    assert await api.get_sms_messages() == []
