"""Tests for ZTE Router 5G API."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qsl

import aiohttp
import pytest

from custom_components.zte_router_5g import sensor
from custom_components.zte_router_5g.api import (
    _BATCH_PATH_PREFIX,
    _CORE_PARAMS,
    _EXTENDED_PARAMS,
    ZTEAuthError,
    ZTEConnectionError,
    ZTERouterAPI,
)
from custom_components.zte_router_5g.const import BATCH_URL_MAX_CHARS

from .conftest import MockResponse, scripted


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
        MockResponse(json_data={"RD": "test_rd"}),
        MockResponse(json_data={"wa_inner_version": "test_v"}),
    ]

    mock_stok_cookie = MagicMock()
    mock_stok_cookie.value = "test_stok"
    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": mock_stok_cookie}
    )

    await api.login()
    assert api.cookies == {"stok": "test_stok"}
    assert api.session_active
    assert api.cookies == {"stok": "test_stok"}


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
        MockResponse(json_data={"RD": "test_rd"}),
    ]
    mock_aiohttp_client.post.return_value = MockResponse(json_data={}, cookies={})

    with pytest.raises(
        ZTEConnectionError, match="Failed to establish a session at login"
    ):
        await api.login()


@pytest.mark.asyncio
async def test_api_get_all_data_expired_session(mock_aiohttp_client):
    """Test session expiry handling in get_all_data."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "old_stok"}
    api.session_active = True

    # 1. Expired response (empty network_type/signalbar)
    # 2. Success response after re-login
    mock_aiohttp_client.get.side_effect = scripted(
        MockResponse(json_data={"network_type": "", "signalbar": ""}),
        MockResponse(json_data={"network_type": "LTE", "signalbar": "4"}),
    )

    with patch.object(api, "login") as mock_login:
        data = await api.get_all_data()
        assert data["network_type"] == "LTE"
        assert mock_login.called


@pytest.mark.asyncio
async def test_api_get_all_data_retry_exhausted(mock_aiohttp_client):
    """Test get_all_data when re-login also returns empty data."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "old_stok"}
    api.session_active = True

    # Both calls return the same empty shape. The re-login still happens; the
    # second identical response refutes the expiry rather than confirming it,
    # so the failure is reported as a reachability problem.
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"network_type": "", "signalbar": ""}),
        MockResponse(json_data={"network_type": "", "signalbar": ""}),
    ]

    with patch.object(api, "login") as mock_login:
        with pytest.raises(ZTEConnectionError, match="freshly established session"):
            await api.get_all_data()
        assert mock_login.called


@pytest.mark.asyncio
async def test_api_get_all_data_error(mock_aiohttp_client):
    """Test technical data fetch error."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    mock_aiohttp_client.get.side_effect = aiohttp.ClientError("Network Error")
    with pytest.raises(ZTEConnectionError, match="Request failed: Network Error"):
        await api.get_all_data()
    assert not api.cookies


@pytest.mark.asyncio
async def test_api_get_sms_capacity(mock_aiohttp_client):
    """Test SMS capacity fetch."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
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
    api.cookies = {"stok": "test"}
    api.session_active = True
    mock_aiohttp_client.get.side_effect = aiohttp.ClientError("Fail")
    with pytest.raises(ZTEConnectionError):
        await api.get_sms_capacity()


@pytest.mark.asyncio
async def test_api_get_last_sms_content(mock_aiohttp_client):
    """Test last SMS fetching and decoding."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
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
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.post.return_value = MockResponse(json_data={"messages": []})
    assert await api.get_last_sms_content() == {}


@pytest.mark.asyncio
async def test_api_reboot_success(mock_aiohttp_client):
    """Test reboot command success."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
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
    api.cookies = {"stok": "test"}
    api.session_active = True
    with (
        patch.object(api, "login"),
        patch.object(api, "get_ad", return_value="test_ad"),
    ):
        mock_aiohttp_client.post.side_effect = aiohttp.ClientError("Fail")
        with pytest.raises(ZTEConnectionError, match="Request failed: Fail"):
            await api.reboot()
    assert not api.cookies


@pytest.mark.asyncio
async def test_api_delete_sms(mock_aiohttp_client):
    """Test single SMS deletion."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
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
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    with patch.object(api, "get_ad", return_value="test_ad"):
        mock_aiohttp_client.post.side_effect = aiohttp.ClientError("Delete Fail")
        with pytest.raises(ZTEConnectionError, match="Request failed: Delete Fail"):
            await api.delete_sms("1")
        assert not api.cookies


@pytest.mark.asyncio
async def test_api_delete_all_success(mock_aiohttp_client):
    """Test bulk SMS deletion logic."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True

    mock_aiohttp_client.post.side_effect = [
        MockResponse(json_data={"messages": [{"id": "1"}, {"id": "2"}]}),
        MockResponse(json_data={"result": "ok"}, status=200),
        # The post-delete re-list. `delete_all` verifies rather than trusting
        # the result code, because this API answers success for a delete it
        # does not carry out.
        MockResponse(json_data={"messages": []}),
    ]

    with patch.object(api, "login"), patch.object(api, "get_ad", return_value="ad"):
        assert await api.delete_all() == 200
    assert api.last_delete == {
        "ids_requested": ["1", "2"],
        "result": {"result": "ok"},
        "ids_surviving": [],
    }


@pytest.mark.asyncio
async def test_api_delete_all_empty(mock_aiohttp_client):
    """Test bulk SMS deletion when no messages exist."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    mock_aiohttp_client.post.return_value = MockResponse(json_data={"messages": []})
    with patch.object(api, "login"):
        assert await api.delete_all() == 200


@pytest.mark.asyncio
async def test_api_get_ad_new_gen(mock_aiohttp_client):
    """Test AD hash generation for new generation models (MC888/MC889)."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    with (
        # `get_ad` now assures the session first — see the stale-session tests.
        patch.object(api, "_ensure_session", AsyncMock()),
        patch.object(api, "get_version", return_value="MC888_VER"),
        patch.object(api, "get_rd", return_value="test_rd"),
    ):
        ad = await api.get_ad()
        assert len(ad) == 64


@pytest.mark.asyncio
async def test_api_get_rd_error(mock_aiohttp_client):
    """Test RD fetch error."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "fake"}
    api.session_active = True
    mock_aiohttp_client.get.side_effect = aiohttp.ClientError("Fail")
    with pytest.raises(ZTEConnectionError):
        await api.get_rd()


@pytest.mark.asyncio
async def test_api_send_sms_success(mock_aiohttp_client):
    """Test successful SMS sending."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
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
    api.cookies = {"stok": "test"}
    api.session_active = True
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
    api.cookies = {"stok": "fake"}
    api.session_active = True
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
    api.cookies = {"stok": "existing"}
    api.session_active = True
    api.last_activity = datetime.now(UTC) - timedelta(seconds=elapsed)

    # `login()` establishes the session pair rather than returning a token,
    # so the stand-in has to do the same: a `return_value` would leave the
    # idle-reset path looking like a login that changed nothing.
    async def _fake_login(*_args, **_kwargs):
        api.cookies = {"stok": "new"}
        api.session_active = True

    with patch.object(api, "login", side_effect=_fake_login) as mock_login:
        mock_aiohttp_client.get.return_value = MockResponse(
            json_data={"network_type": "LTE", "signalbar": "4"}
        )
        await api.get_all_data()
        if stok_cleared:
            mock_login.assert_called_once()
            assert api.cookies == {"stok": "new"}
            assert api.session_active
        else:
            mock_login.assert_not_called()
            assert api.cookies == {"stok": "existing"}


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
    api.cookies = {"stok": "test"}
    api.session_active = True
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


# Profile shapes taken verbatim from the reference MC7010 (2026-07-31). Slot 6
# duplicates the network default so it is selectable manually — a deliberate
# user setup, not a router quirk, and the reason `wan_apn` matching succeeds
# there at all.
_IP = "($)manual($)*99#($)none($)($)($)IP"
_APN_PROFILES = {
    "APN_config0": "Default($)($)manual($)*99#($)none($)($)($)IPv4v6",
    "APN_config1": "3broadband.ie($)3broadband.ie" + _IP,
    "APN_config5": "open.internet.public($)open.internet.public" + _IP,
    "APN_config6": "3FWA.ie($)3fwa.ie" + _IP,
}

_MANUAL_ON_1 = {
    **_APN_PROFILES,
    "apn_mode": "manual",
    "apn_index": "1",
    "wan_apn": "3broadband.ie",
}

# The state that made the first fix dangerous: auto mode, `apn_index` left at a
# stale manual choice, traffic actually running over a different APN.
_AUTO_INDEX_DISAGREES = {
    **_APN_PROFILES,
    "apn_mode": "auto",
    "apn_index": "5",
    "wan_apn": "3FWA.ie",
}


@pytest.mark.asyncio
async def test_api_set_apn_mode_manual_sends_the_complete_form(mock_aiohttp_client):
    """Manual needs all five fields; four of them are refused by the router.

    Measured 2026-07-31: `apn_mode=manual` alone, and with `apn_action` but
    without `set_default_flag`/`pdp_type`, are both refused. Asserting only the
    mode — as this test originally did — passed against a payload the router
    had never once accepted.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        await api.set_apn_mode("manual", _MANUAL_ON_1)
        data = mock_aiohttp_client.post.call_args[1]["data"]
        assert "apn_mode=manual" in data
        assert "apn_action=set_default" in data
        assert "set_default_flag=1" in data
        assert "pdp_type=IP" in data
        assert "index=1" in data


@pytest.mark.asyncio
async def test_apn_mode_manual_follows_the_active_apn_not_the_stale_index(
    mock_aiohttp_client,
):
    """The regression test for a hazard introduced while fixing this method.

    In auto mode `apn_index` is a leftover manual choice, not a description of
    what the router is doing: observed live as `apn_index=5`
    (`open.internet.public`) while traffic ran over `3FWA.ie`, which is slot 6.
    Building the manual switch from `apn_index` would quietly move the
    connection to a different APN — worse than the refusal being fixed.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        await api.set_apn_mode("manual", _AUTO_INDEX_DISAGREES)
        data = mock_aiohttp_client.post.call_args[1]["data"]
        assert "index=6" in data, "must follow wan_apn, the authoritative value"
        assert "index=5" not in data, "apn_index is stale in auto mode"


@pytest.mark.asyncio
async def test_apn_mode_manual_refuses_when_no_profile_matches(mock_aiohttp_client):
    """The normal case on a router without a hand-added duplicate profile.

    In auto mode the router uses the network-provided default, which need not
    exist in the manual list at all. There is then no honest answer to "which
    profile?", so this refuses and points at the workflow that does work.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    state = {
        "APN_config1": "3broadband.ie($)3broadband.ie" + _IP,
        "apn_mode": "auto",
        "apn_index": "1",
        "wan_apn": "some.carrier.default",
    }
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
        pytest.raises(ZTEConnectionError, match="Choose an APN Profile"),
    ):
        await api.set_apn_mode("manual", state)

    mock_aiohttp_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_apn_mode_manual_trusts_the_index_when_already_manual(
    mock_aiohttp_client,
):
    """`wan_apn` is blank for the Default profile, whose APN field is empty.

    Selecting Default is legitimate — the router's own page shows a blank APN
    for it — so a blank `wan_apn` must not be read as "cannot resolve" when the
    router is already in manual mode and `apn_index` is therefore authoritative.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    state = {**_APN_PROFILES, "apn_mode": "manual", "apn_index": "0", "wan_apn": ""}
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        await api.set_apn_mode("manual", state)
        data = mock_aiohttp_client.post.call_args[1]["data"]
        assert "index=0" in data
        assert "pdp_type=IPv4v6" in data


@pytest.mark.asyncio
async def test_api_set_apn_mode_auto_falls_back_to_the_bare_form(mock_aiohttp_client):
    """Auto needs no profile, and the bare form is accepted for it.

    Verified on hardware: `apn_mode=auto` alone returns success. Keeping the
    fallback means a poll that has not yet supplied the profile list can still
    return the router to auto — the direction that gets someone out of trouble.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        await api.set_apn_mode("auto", {})
        data = mock_aiohttp_client.post.call_args[1]["data"]
        assert "apn_mode=auto" in data
        assert "index=" not in data


@pytest.mark.asyncio
async def test_api_set_apn_mode_auto_prefers_the_complete_form(mock_aiohttp_client):
    """With a profile resolvable, auto uses the form verified to actually apply.

    The bare form is only *accepted*; the complete form was observed to change
    the mode and carry `wan_apn` with it. Where both are available, prefer the
    one with evidence behind it.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        await api.set_apn_mode("auto", _MANUAL_ON_1)
        data = mock_aiohttp_client.post.call_args[1]["data"]
        assert "apn_mode=auto" in data
        assert "set_default_flag=1" in data
        assert "index=1" in data


@pytest.mark.asyncio
async def test_api_set_apn_mode_error(mock_aiohttp_client):
    """Test set_apn_mode propagates connection error."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
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
    api.cookies = {"stok": "test"}
    api.session_active = True
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
    api.cookies = {"stok": "test"}
    api.session_active = True
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
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        result = await api.set_data_limit_switch("1", _DATA_VOLUME_STATE)
        assert result == {"result": "ok"}
        _args, kwargs = mock_aiohttp_client.post.call_args
        data = kwargs["data"]
        assert "data_volume_limit_switch=1" in data
        # The whole form, not just the field being changed — the router
        # refuses a partial payload.
        assert "data_volume_limit_size=2_1048576" in data
        assert "data_volume_alert_percent=80" in data
        assert "traffic_clear_date=1" in data
        assert "wan_auto_clear_flow_data_switch=on" in data


@pytest.mark.asyncio
async def test_api_set_data_limit_switch_off(mock_aiohttp_client):
    """Test set_data_limit_switch disables data limit."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        result = await api.set_data_limit_switch("0", _DATA_VOLUME_STATE)
        assert result == {"result": "ok"}
        _args, kwargs = mock_aiohttp_client.post.call_args
        data = kwargs["data"]
        assert "data_volume_limit_switch=0" in data


@pytest.mark.asyncio
async def test_api_set_bearer_preference(mock_aiohttp_client):
    """Test set_bearer_preference calls the right endpoint."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
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
    api.cookies = {"stok": "test"}
    api.session_active = True
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
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.side_effect = aiohttp.ClientError("Bearer pref fail")
        with pytest.raises(ZTEConnectionError, match="Request failed"):
            await api.set_bearer_preference("Only_LTE")


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
    api.cookies = {"stok": "dead"}
    api.session_active = True
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
    api.cookies = {"stok": "dead"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    mock_aiohttp_client.post = MagicMock(
        side_effect=[
            MockResponse(json_data=DEAD_SMS_LIST, headers={"Content-Type": "text/html"})
            for _ in range(4)
        ]
    )

    with (
        patch.object(ZTERouterAPI, "login", return_value="stok=fresh"),
        pytest.raises((ZTEAuthError, ZTEConnectionError)),
    ):
        await api.get_sms_messages()


@pytest.mark.asyncio
async def test_missing_contract_key_raises_even_if_expiry_undetected(
    mock_aiohttp_client,
):
    """Second line of defense, independent of the expiry detector.

    If the router ever answers with a shape the detector does not recognise,
    the endpoint contract must still refuse to report it as "no messages".
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
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
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    mock_aiohttp_client.post = MagicMock(
        return_value=MockResponse(
            json_data=LIVE_SMS_EMPTY_INBOX, headers={"Content-Type": "text/html"}
        )
    )

    assert await api.get_sms_messages() == []


def _stok_cookie(value="test_stok"):
    """Build a mock stok cookie as aiohttp would expose it."""
    cookie = MagicMock()
    cookie.value = value
    return cookie


def _login_forms(mock_client):
    """Extract the goformId of each login POST, in order."""
    return [
        call.kwargs["data"]["goformId"]
        for call in mock_client.post.mock_calls
        if "data" in call.kwargs and isinstance(call.kwargs["data"], dict)
    ]


@pytest.mark.asyncio
async def test_login_falls_back_to_the_alternate_form(mock_aiohttp_client):
    """An unlisted model rejecting the primary form is retried once."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "LD"}),
        # An unlisted model: neither MC801 nor MC7010, so is_multi stays True.
        MockResponse(json_data={"wa_inner_version": "MF286_V1"}),
        MockResponse(json_data={"RD": "test_rd"}),
        MockResponse(json_data={"wa_inner_version": "MF286_V1"}),
    ]
    mock_aiohttp_client.post.side_effect = [
        MockResponse(json_data={"result": "failure"}, cookies={}),
        MockResponse(cookies={"stok": _stok_cookie()}),
    ]

    await api.login()
    assert api.cookies == {"stok": "test_stok"}
    assert _login_forms(mock_aiohttp_client) == ["LOGIN_MULTI_USER", "LOGIN"]


@pytest.mark.asyncio
async def test_login_fallback_is_the_other_form_either_way_round(mock_aiohttp_client):
    """Whichever form is primary, the fallback is its opposite."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "LD"}),
        # MC7010 with a username selects LOGIN as primary.
        MockResponse(json_data={"wa_inner_version": "MC7010_V1"}),
        MockResponse(json_data={"RD": "test_rd"}),
        MockResponse(json_data={"wa_inner_version": "MC7010_V1"}),
    ]
    mock_aiohttp_client.post.side_effect = [
        MockResponse(json_data={"result": "failure"}, cookies={}),
        MockResponse(cookies={"stok": _stok_cookie("fb")}),
    ]

    await api.login()
    assert api.cookies == {"stok": "fb"}
    assert _login_forms(mock_aiohttp_client) == ["LOGIN", "LOGIN_MULTI_USER"]


@pytest.mark.asyncio
async def test_login_does_not_fall_back_on_a_credentials_rejection(
    mock_aiohttp_client,
):
    """A wrong password is wrong on either form; retrying only burns an attempt."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "LD"}),
        MockResponse(json_data={"wa_inner_version": "MF286_V1"}),
        MockResponse(json_data={"RD": "test_rd"}),
    ]
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "password_error"}, cookies={}
    )

    with pytest.raises(ZTEAuthError):
        await api.login()

    assert mock_aiohttp_client.post.call_count == 1


@pytest.mark.asyncio
async def test_login_fallback_reports_the_credentials_error_it_uncovers(
    mock_aiohttp_client,
):
    """If only the fallback form gets far enough to be rejected, report that."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "LD"}),
        MockResponse(json_data={"wa_inner_version": "MF286_V1"}),
        MockResponse(json_data={"RD": "test_rd"}),
    ]
    mock_aiohttp_client.post.side_effect = [
        MockResponse(json_data={"result": "failure"}, cookies={}),
        MockResponse(json_data={"result": "password_error"}, cookies={}),
    ]

    with pytest.raises(ZTEAuthError, match="invalid credentials"):
        await api.login()

    assert mock_aiohttp_client.post.call_count == 2


@pytest.mark.asyncio
async def test_login_fallback_failure_stays_a_connection_error(mock_aiohttp_client):
    """Both forms failing unclassified must not be reported as bad credentials."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "LD"}),
        MockResponse(json_data={"wa_inner_version": "MF286_V1"}),
        MockResponse(json_data={"RD": "test_rd"}),
    ]
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "failure"}, cookies={}
    )

    with pytest.raises(ZTEConnectionError):
        await api.login()

    assert mock_aiohttp_client.post.call_count == 2


@pytest.mark.asyncio
async def test_login_success_on_the_primary_form_makes_no_second_attempt(
    mock_aiohttp_client,
):
    """The fallback must not fire for the hardware that already works."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "LD"}),
        MockResponse(json_data={"wa_inner_version": "MC7010_V1"}),
        MockResponse(json_data={"RD": "test_rd"}),
        MockResponse(json_data={"wa_inner_version": "MC7010_V1"}),
    ]
    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": _stok_cookie()}
    )

    await api.login()
    assert api.cookies == {"stok": "test_stok"}
    assert mock_aiohttp_client.post.call_count == 1


@pytest.mark.asyncio
async def test_send_sms_declares_gsm7_for_plain_text(mock_aiohttp_client):
    """Plain text gets 160 characters per segment instead of 70."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    with patch.object(api, "get_ad", return_value="test_ad"):
        mock_aiohttp_client.post.return_value = MockResponse(
            json_data={"result": "ok"}, status=200
        )
        await api.send_sms("+123456", "Router rebooted")

    payload = mock_aiohttp_client.post.call_args.kwargs["data"]
    assert "encode_type=GSM7_default" in payload
    # The body format does not change with the encoding: always UTF-16BE hex.
    expected_body = "Router rebooted".encode("utf-16-be").hex()
    assert f"MessageBody={expected_body}" in payload


@pytest.mark.asyncio
async def test_send_sms_declares_unicode_when_the_text_needs_it(mock_aiohttp_client):
    """One character outside GSM 03.38 forces UNICODE for the whole message."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    with patch.object(api, "get_ad", return_value="test_ad"):
        mock_aiohttp_client.post.return_value = MockResponse(
            json_data={"result": "ok"}, status=200
        )
        await api.send_sms("+123456", "Signal restored \U0001f4f6")

    assert "encode_type=UNICODE" in mock_aiohttp_client.post.call_args.kwargs["data"]


def _requested_params(mock_client):
    """Split the batch-poll URL back into the list of requested cmd keys."""
    return mock_client.get.call_args.args[0].split("cmd=")[1].split(",")


@pytest.mark.asyncio
async def test_get_all_data_requests_every_aliased_key(mock_aiohttp_client):
    """An alias in sensor.py can never fire if the key is not asked for here."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data={"cell_id": "1"})

    await api.get_all_data()

    await api.get_extended_data()
    requested = set(_requested_params(mock_aiohttp_client))
    # Both halves of the split poll count — an alias satisfied by either is
    # reachable, and which batch a key sits in is a separate decision.
    requested |= set(_CORE_PARAMS) | set(_EXTENDED_PARAMS)

    # Derived from the alias tuples themselves rather than restated here, so a
    # new `_ALIAS_*` constant is covered the moment it is added. The previous
    # hand-maintained list could only catch aliases someone remembered to copy.
    aliased = {
        key
        for name in dir(sensor)
        if name.startswith("_ALIAS_")
        for key in getattr(sensor, name)
    }
    assert aliased, "no alias tuples found — has the naming convention changed?"

    # Thermal keys are a fixed set rather than aliases of one another, so they
    # are named explicitly. See `test_thermal_sensor_set_matches_the_descriptions`.
    thermal = {
        "pm_sensor_pa1",
        "pm_sensor_ambient",
        "pm_sensor_mdm",
        "pm_modem_5g",
        "pm_sensor_5g",
    }

    for key in sorted(aliased | thermal):
        assert key in requested, f"{key} is aliased but never requested"


@pytest.mark.asyncio
async def test_get_all_data_params_have_no_duplicates(mock_aiohttp_client):
    """A duplicated key lengthens every poll URL and buys nothing."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data={"cell_id": "1"})

    await api.get_all_data()

    requested = _requested_params(mock_aiohttp_client)
    duplicates = {key for key in requested if requested.count(key) > 1}
    assert not duplicates, f"duplicated batch-poll keys: {sorted(duplicates)}"


# --- Session activity clock: only authenticated calls count -----------------


@pytest.mark.asyncio
async def test_unauthenticated_call_does_not_refresh_the_session_clock(
    mock_aiohttp_client,
):
    """Regression: an action after a long pause used to reuse a dead session.

    Every write calls `get_ad()` -> `get_version()` first, and `get_version()`
    is unauthenticated. When that stamped `last_activity`, the idle check on
    the very next authenticated call saw a session that had been idle for
    hours as "active 0 seconds ago" and kept the stale `stok`. Reported from
    the field: with Pause Polling on, `send_sms` reported success and no
    message arrived.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "stale"}
    api.session_active = True
    stale = datetime.now(UTC) - timedelta(seconds=10_000)
    api.last_activity = stale

    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"wa_inner_version": "MC7010_V1"}
    )
    await api.get_version()

    assert api.last_activity == stale, (
        "an unauthenticated call must not count as session activity"
    )


@pytest.mark.asyncio
async def test_authenticated_call_does_refresh_the_session_clock(mock_aiohttp_client):
    """The other half: a real authenticated call proves the session is alive."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    stale = datetime.now(UTC) - timedelta(seconds=10)
    api.last_activity = stale

    mock_aiohttp_client.get.return_value = MockResponse(json_data={"RD": "abc"})
    await api.get_rd()

    assert api.last_activity > stale


@pytest.mark.asyncio
async def test_idle_session_is_reset_before_a_write_after_a_long_pause(
    mock_aiohttp_client,
):
    """End-to-end shape of the reported bug: pause, idle out, then send."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "stale"}
    api.session_active = True
    api.last_activity = datetime.now(UTC) - timedelta(seconds=10_000)

    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"wa_inner_version": "MC7010_V1", "RD": "abc", "LD": "LD"}
    )
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "success"}
    )

    with patch.object(api, "login", return_value="stok=fresh") as mock_login:
        await api.send_sms("+123456", "Hello")

    assert mock_login.called, "a write after a long pause must re-authenticate"


# A complete data-volume form, as the last successful poll would supply it.
# `DATA_LIMIT_SETTING` replaces the whole form, so a write needs all six.
_DATA_VOLUME_STATE = {
    "data_volume_limit_switch": "0",
    "data_volume_limit_unit": "data",
    "data_volume_limit_size": "2_1048576",
    "data_volume_alert_percent": "80",
    "wan_auto_clear_flow_data_switch": "on",
    "traffic_clear_date": "1",
}


# --- Write commands must not report a refused command as success ------------

_WRITE_CALLS = [
    ("send_sms", ("+123456", "Hello")),
    ("delete_sms", ("1",)),
    ("set_apn", (1, "IP")),
    ("set_apn_mode", ("auto",)),
    ("set_odu_led_switch", ("1",)),
    ("set_data_limit_switch", ("1", _DATA_VOLUME_STATE)),
    ("set_bearer_preference", ("Only_5G",)),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "args"), _WRITE_CALLS)
async def test_write_commands_raise_when_the_router_refuses(
    mock_aiohttp_client, method, args
):
    """A refused write comes back as 200 OK with `result=failure`.

    Without an explicit check every one of these reported success while the
    router did nothing — the failure mode the user actually hit.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    with patch.object(api, "get_ad", return_value="ad"):
        mock_aiohttp_client.post.return_value = MockResponse(
            json_data={"result": "failure"}, status=200
        )
        with pytest.raises(ZTEConnectionError, match="rejected"):
            await getattr(api, method)(*args)


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "args"), _WRITE_CALLS)
async def test_write_commands_accept_success(mock_aiohttp_client, method, args):
    """An accepted write reaches the router and reports what it answered.

    The name is a promise (§11 rule 3), so this checks acceptance rather than
    merely that nothing raised: the command was actually posted, it carried the
    `AD` token every state-changing `goform` call needs, and the router's own
    answer came back to the caller. A `_require_success` widened to raise on
    everything would pass a bare "it did not raise" test only by never being
    reached.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    with patch.object(api, "get_ad", return_value="ad"):
        mock_aiohttp_client.post.return_value = MockResponse(
            json_data={"result": "success"}, status=200
        )
        result = await getattr(api, method)(*args)

    # Two return contracts: the SMS commands answer with a status code, the
    # rest hand back the router's body. Neither may come back `None`, which is
    # what a write that silently stopped reporting would look like.
    assert result in ({"result": "success"}, 200)
    mock_aiohttp_client.post.assert_called_once()
    # Some commands post a dict and some a pre-encoded body (SMS has to, to
    # keep its hex payload intact), so read whichever form was sent.
    sent = mock_aiohttp_client.post.call_args.kwargs["data"]
    payload = sent if isinstance(sent, dict) else dict(parse_qsl(sent))
    assert payload["goformId"]
    assert payload["AD"] == "ad"


def test_require_success_ignores_a_non_dict_response():
    """A body with no `result` to read is passed over; an explicit refusal is not.

    "It must not raise" is the contract, and the way to make that checkable is
    to assert the distinction rather than the silence: the same helper must
    still raise on the one shape it exists to catch. A `_require_success`
    stubbed out entirely satisfies the first two lines and fails the third.
    """
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")

    assert api._require_success(["not", "a", "dict"], "SOME_CMD") is None
    assert api._require_success(None, "SOME_CMD") is None

    with pytest.raises(ZTEConnectionError, match="rejected"):
        api._require_success({"result": "failure"}, "SOME_CMD")


@pytest.mark.asyncio
async def test_write_commands_tolerate_a_response_with_no_result_key(
    mock_aiohttp_client,
):
    """Not every goformId returns `result`; absence must not become an error.

    The distinction is between "no verdict given" and "a verdict of failure".
    Treating a missing key as refusal would turn every one of these commands
    into a permanent error, so the body must come back to the caller intact.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    with patch.object(api, "get_ad", return_value="ad"):
        mock_aiohttp_client.post.return_value = MockResponse(
            json_data={"apn_mode": "auto"}, status=200
        )
        result = await api.set_apn_mode("auto")

    assert result == {"apn_mode": "auto"}


# --- Reboot ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_reboot_still_raises_on_an_explicit_refusal(mock_aiohttp_client):
    """An intact `result=failure` means the router declined, not that it restarted."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    with patch.object(api, "get_ad", return_value="ad"):
        mock_aiohttp_client.post.return_value = MockResponse(
            json_data={"result": "failure"}, status=200
        )
        with pytest.raises(ZTEConnectionError, match="rejected"):
            await api.reboot()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "params"),
    [("get_all_data", _CORE_PARAMS), ("get_extended_data", _EXTENDED_PARAMS)],
)
async def test_batch_poll_urls_stay_within_the_router_budget(
    mock_aiohttp_client, method, params
):
    """The batch limit is the URL length, not the number of names.

    The router accepts a GET of roughly 2,048 characters and truncates past
    it — which presents as missing fields and is indistinguishable from
    firmware key changes. `_batch_get` now splits a list that would exceed
    `BATCH_URL_MAX_CHARS`, so this asserts the property that matters: **every
    request issued** stays inside the ceiling, however long the list grows.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data={"cell_id": "1"})

    await getattr(api, method)()

    # Every request, not just the last: a split list issues several.
    paths = [call[0][0] for call in mock_aiohttp_client.get.call_args_list]
    # A hostname is longer than the dotted-quad used here, so leave room for one.
    url_length = max(
        len(path) + len("http://a-long-router-hostname.local/") for path in paths
    )

    assert url_length < 2048, (
        f"{method} URL is {url_length} characters, over the router's ~2048 "
        "limit. Remove a key before adding one."
    )
    assert url_length < 1700, (
        f"{method} URL is {url_length} characters, leaving under 350 for "
        "growth. Move a key to the other batch rather than raising this "
        f"number — {len(params)} names are currently requested."
    )


# --- The data-volume form is all-or-nothing ---------------------------------


@pytest.mark.asyncio
async def test_data_volume_write_sends_every_field(mock_aiohttp_client):
    """A partial payload is refused by the router, so all six must be sent."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        await api.set_data_volume_settings(_DATA_VOLUME_STATE, traffic_clear_date="15")

    body = mock_aiohttp_client.post.call_args[1]["data"]
    for field in (
        "data_volume_limit_switch=0",
        "data_volume_limit_unit=data",
        "data_volume_limit_size=2_1048576",
        "data_volume_alert_percent=80",
        "wan_auto_clear_flow_data_switch=on",
        "traffic_clear_date=15",
    ):
        assert field in body, f"{field} missing from the payload"


@pytest.mark.asyncio
async def test_data_volume_write_reads_the_clear_day_aliases(mock_aiohttp_client):
    """Hardware spelling the reset day differently must still be writable."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    current = {
        **{k: v for k, v in _DATA_VOLUME_STATE.items() if k != "traffic_clear_date"},
        "data_volume_clear_date": "9",
    }
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
    ):
        mock_aiohttp_client.post.return_value = MockResponse(json_data={"result": "ok"})
        await api.set_data_volume_settings(current)

    # Read under an alias, written back under the name the router expects.
    assert "traffic_clear_date=9" in mock_aiohttp_client.post.call_args[1]["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("dropped", list(_DATA_VOLUME_STATE))
async def test_data_volume_write_refuses_to_guess_a_missing_field(
    mock_aiohttp_client, dropped
):
    """Better to raise than send a form the router will reject anyway.

    A user's data cap is not something to invent a value for, and every field
    is load-bearing — so each one missing must block the write, not just the
    obvious ones.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    current = {k: v for k, v in _DATA_VOLUME_STATE.items() if k != dropped}

    with pytest.raises(ZTEConnectionError, match=dropped):
        await api.set_data_volume_settings(current)

    mock_aiohttp_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_data_volume_write_treats_empty_as_missing(mock_aiohttp_client):
    """A present-but-empty field is not a usable value to echo back.

    The router answers `""` for names it knows but does not populate, so
    `in current` alone is not a test that a field can be preserved.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    current = {**_DATA_VOLUME_STATE, "data_volume_limit_size": ""}

    with pytest.raises(ZTEConnectionError, match="data_volume_limit_size"):
        await api.set_data_volume_settings(current)


@pytest.mark.asyncio
async def test_data_limit_switch_routes_through_the_form(mock_aiohttp_client):
    """One write path for this form, so the two cannot drift apart."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
        patch.object(api, "set_data_volume_settings") as mock_form,
    ):
        await api.set_data_limit_switch("1", _DATA_VOLUME_STATE)

    mock_form.assert_awaited_once_with(_DATA_VOLUME_STATE, data_volume_limit_switch="1")


def test_every_data_volume_field_is_polled():
    """A field neither batch fetches can never be echoed back.

    Without this, adding a field to the form silently produces a write that
    always raises "the last poll did not supply it".
    """
    polled = set(_CORE_PARAMS) | set(_EXTENDED_PARAMS)
    for aliases in ZTERouterAPI.DATA_VOLUME_FIELDS.values():
        assert polled.intersection(aliases), (
            f"none of {aliases} is requested by either batch"
        )


# --- Stale-session recovery on writes ---------------------------------------
#
# Verified against an MC7010 on 2026-07-30 by replaying an invalidated stok.
# A read signals a dead session by echoing every requested key back empty, which
# `_request` already recovers from. A *write* answers `{"result":"failure"}`,
# which is indistinguishable from a command the router declined on its merits —
# so nothing recovered it, and a control failed on every attempt until some read
# happened to re-login. That was the reported fault.
#
# The recovery has to happen *before* the write. Recovering afterwards — renew
# the session, replay the payload — was implemented first and verified NOT to
# work against hardware. The reason is not established; the tidy explanation
# (that `RD` rotates on re-login, staling the `AD`) was disproved by
# `scripts/hardware_check.py`. These tests therefore assert the *ordering* that
# was measured to work, and deliberately do not encode a mechanism.
#
# A caution about this file: the earlier version of these tests passed while the
# code failed on hardware, because the mock was written from the same wrong
# model as the code. Mocks cannot falsify an assumption about the device — only
# `scripts/hardware_check.py` can.


@pytest.mark.asyncio
async def test_a_write_checks_the_session_before_deriving_its_token(
    mock_aiohttp_client,
):
    """`get_ad` is the choke point every write passes through."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"wan_connect_status": "ppp_connected"}),  # probe
        MockResponse(json_data={"wa_inner_version": "MC7010V1"}),
        MockResponse(json_data={"RD": "abc"}),
    ]

    await api.get_ad()

    probe_url = mock_aiohttp_client.get.call_args_list[0][0][0]
    assert "wan_connect_status" in probe_url, "the session was not checked first"


@pytest.mark.asyncio
async def test_a_dead_session_is_renewed_before_the_token_is_built(
    mock_aiohttp_client,
):
    """The whole point: the token must come from the *new* session.

    `RD` changes when a session is created, so deriving `AD` first and
    re-logging-in afterwards produces a token the router will reject — which is
    exactly how the original attempt at this failed on hardware.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "stale"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"wan_connect_status": ""}),  # dead session
        MockResponse(json_data={"wan_connect_status": "ppp_connected"}),  # after
        MockResponse(json_data={"wa_inner_version": "MC7010V1"}),
        MockResponse(json_data={"RD": "post-login-value"}),
    ]
    login = AsyncMock(return_value="stok=fresh")

    with patch.object(api, "login", login):
        await api.get_ad()

    login.assert_awaited_once()
    # The RD read must come after the re-login, or the token is stale.
    rd_call = mock_aiohttp_client.get.call_args_list[-1][0][0]
    assert "RD" in rd_call


@pytest.mark.asyncio
async def test_a_refused_write_is_still_reported_not_retried(mock_aiohttp_client):
    """The hazard this design avoids.

    `{"result":"failure"}` is what the router returns for a command it declined
    on its merits. Resending it would deliver a `send_sms` twice. With the
    session assured up front there is no reason to retry, and nothing does.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"wan_connect_status": "ppp_connected"}),
        MockResponse(json_data={"wa_inner_version": "MC7010V1"}),
        MockResponse(json_data={"RD": "abc"}),
    ]
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "failure"}
    )

    with pytest.raises(ZTEConnectionError):
        await api.set_odu_led_switch("1")

    assert mock_aiohttp_client.post.call_count == 1, "a declined write was resent"


# --- Targeted reads must not be mistaken for a dead session -----------------
#
# The dead-session rule — "every value in the response is empty" — was written
# when every read was a 75-key poll, where something is always populated. The
# targeted reads added for write confirmation broke that assumption: on the
# reference MC7010, `sms_nv_send_total` and `sms_nv_total` are legitimately
# empty, so reading just those two produced an all-empty response, a spurious
# re-login, and a `ZTEAuthError` on a perfectly healthy session.


@pytest.mark.asyncio
async def test_targeted_read_of_empty_keys_is_not_a_dead_session(mock_aiohttp_client):
    """Legitimately empty fields must not look like an expired session."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={
            "sms_nv_send_total": "",
            "sms_nv_total": "",
            "wan_connect_status": "ppp_connected",
        }
    )

    result = await api.get_params(["sms_nv_send_total", "sms_nv_total"])

    assert result["sms_nv_send_total"] == ""
    requested = mock_aiohttp_client.get.call_args[0][0]
    assert "wan_connect_status" in requested, (
        "the sentinel key is what distinguishes 'these fields are empty' from "
        "'this session is gone' — without it this read raises ZTEAuthError"
    )


@pytest.mark.asyncio
async def test_the_sentinel_is_not_added_twice(mock_aiohttp_client):
    """Asking for the sentinel explicitly must not duplicate it in the URL."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"wan_connect_status": "ppp_connected"}
    )

    await api.get_params(["wan_connect_status"])

    requested = mock_aiohttp_client.get.call_args[0][0]
    assert requested.count("wan_connect_status") == 1


@pytest.mark.asyncio
async def test_a_genuinely_dead_session_is_still_detected(mock_aiohttp_client):
    """The sentinel must not blunt the rule it exists to protect.

    With the session gone the sentinel comes back empty too, so the response is
    all-empty and the expiry path fires exactly as before.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "stale"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"ODU_led_switch": "", "wan_connect_status": ""}
    )

    # A fresh session producing the same shape refutes the verdict rather
    # than confirming it, so this is reported as a reachability problem. What
    # matters for this test is unchanged: it raises rather than handing back
    # an empty result that reads as "the setting is blank".
    with (
        patch.object(api, "login", AsyncMock(return_value="stok=fresh")),
        pytest.raises(ZTEConnectionError, match="freshly established session"),
    ):
        await api.get_params(["ODU_led_switch"])


# ---------------------------------------------------------------------------
# Branch coverage — each of these closes a partial branch recorded on
# 2026-08-05. All four were missing tests; none was dead code.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_non_dict_json_body_skips_the_session_check(mock_aiohttp_client):
    """A JSON list is returned as-is rather than tripping the expiry rule.

    The dead-session rule reads "every value is empty", which is only
    answerable for a mapping. The distinction that earns this test: a list
    body must reach the caller untouched, not be mistaken for a dead session
    and not raise on the `.values()` the dict path would call.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data=[])

    assert await api._request("GET", "goform/anything") == []


@pytest.mark.asyncio
async def test_protocol_detection_falls_through_to_https(mock_aiohttp_client):
    """An http port answering 4xx is not a usable protocol — try https.

    Separates "the port answered" from "the router is served here". A router
    refusing plain http returns a status, not an error, so a check that only
    catches exceptions would settle on http and every later request would fail.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    mock_aiohttp_client.get.side_effect = [
        MockResponse(status=404),
        MockResponse(status=200),
    ]

    await api.try_set_protocol()

    assert api.protocol == "https"
    assert api.referer == "https://192.168.0.1/"


@pytest.mark.asyncio
async def test_login_omits_the_username_field_when_none_is_configured(
    mock_aiohttp_client,
):
    """Password-only routers must not receive an empty `username` key.

    The distinction is the key's presence, not its value: several models in
    this family reject a form carrying a field they do not expect, so sending
    `username=""` is not the same as sending nothing.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "", "password")
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "test_ld"}),
        MockResponse(json_data={"wa_inner_version": "test_v"}),
        MockResponse(json_data={"RD": "test_rd"}),
        MockResponse(json_data={"wa_inner_version": "test_v"}),
    ]
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "0"}, cookies={"stok": MagicMock(value="abc")}
    )

    await api.login()

    payload = mock_aiohttp_client.post.call_args.kwargs["data"]
    assert "username" not in payload
    assert payload["password"]


def test_manual_apn_with_an_unknown_index_resolves_to_nothing():
    """An `apn_index` naming a slot the router did not report yields `None`.

    Separates "manual mode, profile found" from "manual mode, profile gone".
    Returning a stale or arbitrary profile here would let a control publish a
    position the router never reported — §22's "never render a missing key as
    a confident position", one level up.
    """
    current = {
        "apn_mode": "manual",
        "apn_index": "7",
        "wan_apn": "",
        "APN_config0": "home($)three.ie",
    }

    assert ZTERouterAPI._resolve_apn_profile(current) is None
    # And the same input with an index the router did report resolves, so the
    # `None` above is the missing slot rather than the method never matching.
    assert ZTERouterAPI._resolve_apn_profile({**current, "apn_index": "0"}) == (
        "0",
        "IP",
    )


# ---------------------------------------------------------------------------
# Hex decoding — UTF-16BE, whole-string. See `_hex_decode`.
# ---------------------------------------------------------------------------


def _utf16_hex(text: str) -> str:
    """Encode as the router does, so the fixture cannot drift from the format."""
    return text.encode("utf-16-be").hex()


def test_an_emoji_survives_the_round_trip():
    """A non-BMP character must decode to itself, not to two lone surrogates.

    The distinction this pins is not "the text looks wrong". Decoding a
    surrogate pair one code unit at a time produces a string that **cannot be
    encoded to UTF-8 at all**, so the recorder, a webhook or a file log handler
    raises `UnicodeEncodeError` on a message the user cannot identify. The
    integration sends emoji deliberately, so reading one back is a real path.
    """
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    text = "Signal restored \U0001f4f6"

    decoded = api._hex_decode(_utf16_hex(text))

    assert decoded == text
    # The half that a length or content assertion alone would miss.
    decoded.encode("utf-8")


def test_hex_decoding_handles_the_whole_bmp_range():
    """Plain, accented and CJK text all still decode — the fix is not emoji-only."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    for text in ("Hello", "Café £5 à Ωmega", "テスト", "1234567890"):
        assert api._hex_decode(_utf16_hex(text)) == text


def test_truncated_hex_is_reported_not_half_decoded():
    """An odd-length payload is a decode failure, not a partial message.

    The previous loop consumed four characters at a time and silently dropped
    whatever did not fit, so `"0041 00"` rendered as `"A"` — a message the user
    would read as complete. A truncated payload is not something to half-render.
    """
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    assert api._hex_decode("004100") == "[Decoding Error]"
    assert api._hex_decode("004") == "[Decoding Error]"


def test_undecodable_hex_is_reported():
    """Non-hex input, and a lone surrogate the router should never send."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    assert api._hex_decode("zzzz") == "[Decoding Error]"
    assert api._hex_decode("d83d") == "[Decoding Error]"


def test_empty_hex_is_empty_not_an_error():
    """An absent field is not a failure — it is an empty message body."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    assert api._hex_decode("") == ""


# ---------------------------------------------------------------------------
# Splitting a mandatory batch by URL budget
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_list_within_the_budget_is_one_request(mock_aiohttp_client):
    """Splitting must not cost a round trip where none is needed."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(json_data={"a_one": "1"})

    await api._batch_get(["a_one", "b_two"])

    assert mock_aiohttp_client.get.call_count == 1


@pytest.mark.asyncio
async def test_a_list_past_the_budget_is_split_and_merged(mock_aiohttp_client):
    """The caller sees one mapping however many requests it took."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    names = [f"a_long_parameter_name_{i:03d}" for i in range(120)]
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={names[0]: "first"}),
        MockResponse(json_data={names[-1]: "last"}),
        MockResponse(json_data={"extra": "third"}),
    ]

    merged = await api._batch_get(names)

    assert mock_aiohttp_client.get.call_count > 1
    assert merged[names[0]] == "first"
    assert merged[names[-1]] == "last"


def test_no_chunk_exceeds_the_budget() -> None:
    """The budget is a property of every request, not of the list."""
    api = ZTERouterAPI(MagicMock(), "a-long-router-hostname.local", None, "pw")
    names = [f"a_long_parameter_name_{i:03d}" for i in range(200)]

    for chunk in api._split_by_url_budget(names):
        url = f"{api.referer}{_BATCH_PATH_PREFIX}{','.join(chunk)}"
        assert len(url) <= BATCH_URL_MAX_CHARS, f"{len(url)} characters"


def test_a_single_name_longer_than_the_budget_still_gets_a_request() -> None:
    """A chunk is never empty, or the name would be dropped silently."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", None, "pw")

    chunks = api._split_by_url_budget(["x" * (BATCH_URL_MAX_CHARS * 2)])

    assert chunks == [["x" * (BATCH_URL_MAX_CHARS * 2)]]


@pytest.mark.asyncio
async def test_a_failing_chunk_fails_the_whole_batch(mock_aiohttp_client):
    """Per-chunk tolerance belongs to discovery, not to a mandatory read.

    Tolerating a failed chunk here would serve half the entities from a
    partial response and score the poll a success — the silent-failure shape
    this integration has closed twice.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    names = [f"a_long_parameter_name_{i:03d}" for i in range(120)]
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={names[0]: "first"}),
        aiohttp.ClientError("chunk refused"),
    ]

    with pytest.raises(ZTEConnectionError):
        await api._batch_get(names)


@pytest.mark.asyncio
async def test_a_non_object_chunk_response_contributes_nothing(mock_aiohttp_client):
    """A JSON list or scalar is not a payload to merge.

    `_request` returns the body as it parsed it, and a batch that answered
    something other than an object has nothing to contribute — merging it
    would raise inside the read path rather than at the call site.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data=["not", "an", "object"]
    )

    assert await api._batch_get(["a_one"]) == {}
