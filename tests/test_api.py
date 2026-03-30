import pytest
from unittest.mock import MagicMock, patch
from custom_components.zte_router_5g.api import ZTERouterAPI, ZTEAuthError, ZTEConnectionError

def test_api_hash():
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    # sha256 of "test" is 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
    assert api._hash("test") == "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"

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
@patch("requests.Session.post")
def test_api_login_success(mock_post, mock_get):
    api = ZTERouterAPI("192.168.0.1", "admin", "password")
    
    # Mock LD and version responses
    mock_ld_res = MagicMock()
    mock_ld_res.json.return_value = {"LD": "test_ld"}
    mock_get.side_effect = [mock_ld_res, MagicMock()] # Second one for version
    
    # Mock login response
    mock_login_res = MagicMock()
    mock_login_res.cookies = {"stok": "test_stok"}
    mock_post.return_value = mock_login_res
    
    stok = api.login()
    assert stok == "stok=test_stok"
    assert api.stok == "stok=test_stok"

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
