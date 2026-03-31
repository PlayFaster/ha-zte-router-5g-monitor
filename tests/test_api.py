from unittest.mock import MagicMock, patch

import pytest

from custom_components.zte_router_5g.api import (
    ZTEAuthError,
    ZTERouterAPI,
)


def test_api_hash():
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    # sha256 of "test" is
    #   9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
    assert (
        api._hash("test")
        == "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    )


def test_api_hash_none():
    """Test _hash with None input."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    with pytest.raises(ValueError, match="Input to hash function cannot be None"):
        api._hash(None)


def test_api_hex_decode():
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    assert api._hex_decode("00480065006c006c006f") == "Hello"
    assert api._hex_decode("") == ""
    assert api._hex_decode("invalid") == "[Decoding Error]"


def test_api_parse_date():
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    # "23,10,10,10,00,00" -> 2023-10-10T10:00:00
    assert api._parse_date("23,10,10,10,0,0,+1") == "2023-10-10T10:00:00"
    assert api._parse_date("") is None
    assert api._parse_date("invalid") == "invalid"


def test_api_parse_date_error():
    """Test date parsing with a string that splits but fails int conversion."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    # This should trigger the exception block in _parse_date
    assert api._parse_date("23,fail,10,10,00,00") == "23,fail,10,10,00,00"


@patch("requests.Session.get")
def test_api_try_set_protocol(mock_get):
    api = ZTERouterAPI("192.168.0.1", "admin", "password")

    # Success on first attempt (http)
    mock_response = MagicMock()
    mock_response.ok = True
    mock_get.return_value = mock_response

    api.try_set_protocol()
    assert api.protocol == "http"
    assert api.referer == "http://192.168.0.1/"


@patch("requests.Session.get")
def test_api_try_set_protocol_error(mock_get):
    """Test protocol detection with connection errors."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    # Fail both http and https
    mock_get.side_effect = Exception("Connect Fail")
    api.try_set_protocol()
    # Should default back to original values or handle without raising
    assert api.protocol == "http"


@patch("requests.Session.get")
def test_api_get_version(mock_get):
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    mock_res = MagicMock()
    mock_res.json.return_value = {"wa_inner_version": "test_v"}
    mock_get.return_value = mock_res
    assert api.get_version() == "test_v"


@patch("requests.Session.get")
def test_api_get_version_error(mock_get):
    """Test version fetching error."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    mock_get.side_effect = Exception("Fail")
    assert api.get_version() == ""


@patch("requests.Session.get")
@patch("requests.Session.post")
def test_api_login_success(mock_post, mock_get):
    api = ZTERouterAPI("192.168.0.1", "admin", "password")

    # Mock LD and version responses
    mock_ld_res = MagicMock()
    mock_ld_res.json.return_value = {"LD": "test_ld"}
    mock_ver_res = MagicMock()
    mock_ver_res.json.return_value = {"wa_inner_version": "test_v"}
    mock_get.side_effect = [mock_ld_res, mock_ver_res]

    # Mock login response
    mock_login_res = MagicMock()
    mock_login_res.cookies = {"stok": "test_stok"}
    mock_post.return_value = mock_login_res

    stok = api.login()
    assert stok == "stok=test_stok"
    assert api.stok == "stok=test_stok"


def test_api_login_no_password():
    """Test login failure when no password provided."""
    api = ZTERouterAPI("192.168.0.1", "admin", "")
    # Patch get_LD to avoid socket error
    with (
        patch.object(api, "get_LD", return_value="LD"),
        patch.object(api, "get_version", return_value="VER"),
        pytest.raises(Exception, match="No password provided"),
    ):
        api.login()


@patch("requests.Session.get")
@patch("requests.Session.post")
def test_api_login_failure_no_stok(mock_post, mock_get):
    """Test login failure when response missing stok."""
    api = ZTERouterAPI("192.168.0.1", "admin", "pass")

    # Mock responses so it doesn't return MagicMocks to hashing functions
    mock_ld_res = MagicMock()
    mock_ld_res.json.return_value = {"LD": "LD"}
    mock_ver_res = MagicMock()
    mock_ver_res.json.return_value = {"wa_inner_version": "VER"}
    mock_get.side_effect = [mock_ld_res, mock_ver_res]

    mock_login_res = MagicMock()
    mock_login_res.cookies = {}  # Empty
    mock_login_res.status_code = 200
    mock_post.return_value = mock_login_res

    with pytest.raises(ZTEAuthError, match="Login failed"):
        api.login()


@patch("requests.Session.get")
def test_api_get_all_data_expired_session(mock_get):
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    api.stok = "stok=old_stok"

    # 1. Expired response (empty network_type/signalbar)
    mock_expired_res = MagicMock()
    mock_expired_res.json.return_value = {"network_type": "", "signalbar": ""}

    # 2. Success response after re-login
    mock_success_res = MagicMock()
    mock_success_res.json.return_value = {"network_type": "LTE", "signalbar": "4"}

    mock_get.side_effect = [mock_expired_res, mock_success_res]

    with patch.object(api, "login") as mock_login:
        data = api.get_all_data()
        assert data["network_type"] == "LTE"
        assert mock_login.called


@patch("requests.Session.get")
def test_api_get_all_data_error(mock_get):
    """Test technical data fetch error."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_get.side_effect = Exception("Network Error")
    with pytest.raises(Exception, match="Network Error"):
        api.get_all_data()
    assert api.stok is None


@patch("requests.Session.get")
def test_api_get_sms_capacity(mock_get):
    """Test SMS capacity fetch."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_res = MagicMock()
    mock_res.json.return_value = {"cap": 100}
    mock_get.return_value = mock_res
    assert api.get_sms_capacity() == {"cap": 100}


@patch("requests.Session.get")
def test_api_get_sms_capacity_error(mock_get):
    """Test SMS capacity fetch error."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_get.side_effect = Exception("Fail")
    assert api.get_sms_capacity() == {}


@patch("requests.Session.post")
def test_api_get_last_sms_content(mock_post):
    """Test last SMS fetching and decoding."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_res = MagicMock()
    mock_res.json.return_value = {
        "messages": [
            {
                "id": "1",
                "content": "00480065006c006c006f",  # "Hello"
                "number": "003100320033",  # "123"
                "date": "23,10,10,10,0,0,+1",
            }
        ]
    }
    mock_post.return_value = mock_res

    msg = api.get_last_sms_content()
    assert msg["content_decoded"] == "Hello"
    assert msg["number_decoded"] == "123"
    assert msg["date_decoded"] == "2023-10-10T10:00:00"


@patch("requests.Session.post")
def test_api_get_last_sms_content_empty(mock_post):
    """Test last SMS fetching when mailbox is empty."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_res = MagicMock()
    mock_res.json.return_value = {"messages": []}
    mock_post.return_value = mock_res
    assert api.get_last_sms_content() == {}


@patch("requests.Session.post")
def test_api_reboot_success(mock_post):
    """Test reboot command success."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    with (
        patch.object(api, "login"),
        patch.object(api, "get_AD", return_value="test_ad"),
    ):
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_post.return_value = mock_res
        assert api.reboot() == 200


@patch("requests.Session.post")
def test_api_reboot_error(mock_post):
    """Test reboot command failure."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    with (
        patch.object(api, "login"),
        patch.object(api, "get_AD", return_value="test_ad"),
        pytest.raises(RuntimeError, match="Fail"),
    ):
        mock_post.side_effect = RuntimeError("Fail")
        api.reboot()
    assert api.stok is None


@patch("requests.Session.post")
def test_api_delete_sms(mock_post):
    """Test single SMS deletion."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    with patch.object(api, "get_AD", return_value="test_ad"):
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_post.return_value = mock_res
        assert api.delete_sms("1") == 200


@patch("requests.Session.post")
def test_api_delete_all_success(mock_post):
    """Test bulk SMS deletion logic."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    api.stok = "stok=test"

    # 1. Mock the "Read" (fetching message IDs)
    mock_read_res = MagicMock()
    mock_read_res.json.return_value = {"messages": [{"id": "1"}, {"id": "2"}]}

    # 2. Mock the "Write" (deletion)
    mock_delete_res = MagicMock()
    mock_delete_res.status_code = 200

    mock_post.side_effect = [mock_read_res, mock_delete_res]

    with patch.object(api, "login"), patch.object(api, "get_AD", return_value="ad"):
        assert api.delete_all() == 200


@patch("requests.Session.post")
def test_api_delete_all_empty(mock_post):
    """Test bulk SMS deletion when no messages exist."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    api.stok = "stok=test"
    mock_read_res = MagicMock()
    mock_read_res.json.return_value = {"messages": []}
    mock_post.return_value = mock_read_res
    with patch.object(api, "login"):
        assert api.delete_all() == 200


def test_api_get_AD_new_gen():
    """Test AD hash generation for new generation models (MC888/MC889)."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    with (
        patch.object(api, "get_version", return_value="MC888_VER"),
        patch.object(api, "get_RD", return_value="test_rd"),
    ):
        # This should use SHA256 (new gen logic)
        ad = api.get_AD()
        assert len(ad) == 64  # SHA256 length in hex


@patch("requests.Session.get")
def test_api_get_RD_error(mock_get):
    """Test RD fetch error."""
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    mock_get.side_effect = Exception("Fail")
    assert api.get_RD() == ""
