"""Tests for the ZTE Router config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import AbortFlow, FlowResultType

from custom_components.zte_router_5g.api import ZTEAuthError, ZTEConnectionError
from custom_components.zte_router_5g.config_flow import (
    ZTEConfigFlow,
    ZTEOptionsFlow,
    _clean_host,
    _merge_credentials,
    _validate_credentials,
)
from custom_components.zte_router_5g.const import DEFAULT_NAME


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("192.168.0.1", "192.168.0.1"),
        ("  192.168.0.1  ", "192.168.0.1"),
        ("http://192.168.0.1", "192.168.0.1"),
        ("https://192.168.0.1/", "192.168.0.1"),
        ("https://192.168.0.1///", "192.168.0.1"),
    ],
)
def test_clean_host(raw, expected):
    """Test that host entries are normalised to a bare host."""
    assert _clean_host(raw) == expected


def test_merge_credentials_blank_password_uses_stored():
    """A blank password falls back to the stored value."""
    merged = _merge_credentials(
        {CONF_HOST: "1.1.1.1", CONF_PASSWORD: ""},
        {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "stored"},
    )
    assert merged[CONF_PASSWORD] == "stored"


def test_merge_credentials_new_password_overrides_stored():
    """A supplied password replaces the stored value."""
    merged = _merge_credentials(
        {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "new"},
        {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "stored"},
    )
    assert merged[CONF_PASSWORD] == "new"


@pytest.mark.asyncio
async def test_validate_credentials_success():
    """Test _validate_credentials success."""
    hass = MagicMock()
    user_input = {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "pass"}

    with (
        patch(
            "custom_components.zte_router_5g.config_flow.ZTERouterAPI"
        ) as mock_api_class,
        patch("custom_components.zte_router_5g.config_flow.async_get_clientsession"),
    ):
        mock_api = mock_api_class.return_value
        mock_api.try_set_protocol = AsyncMock()
        mock_api.login = AsyncMock()
        mock_api.get_all_data = AsyncMock(return_value={"wa_inner_version": "1.2.3"})

        await _validate_credentials(hass, user_input)
        mock_api.login.assert_called_once()
        mock_api.get_all_data.assert_called_once()


@pytest.mark.asyncio
async def test_config_flow_user_step_success():
    """Test successful config flow user step."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}
    flow.hass.config_entries.async_entry_for_domain_unique_id.return_value = None

    user_input = {
        CONF_HOST: "192.168.0.1",
        CONF_USERNAME: "admin",
        CONF_PASSWORD: "password",
    }

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        return_value={"imei": "test_imei", "model": "test_model", "sw_version": "1.0"},
    ):
        result = await flow.async_step_user(user_input)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == DEFAULT_NAME
    assert result["options"] == user_input


@pytest.mark.asyncio
async def test_config_flow_user_step_errors():
    """Test error branches in config flow user step."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}

    # Test ZTEAuthError
    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        side_effect=ZTEAuthError,
    ):
        result = await flow.async_step_user({CONF_HOST: "1.1.1.1", CONF_PASSWORD: "p"})
        assert result["errors"] == {"base": "invalid_auth"}

    # Test ZTEConnectionError
    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        side_effect=ZTEConnectionError,
    ):
        result = await flow.async_step_user({CONF_HOST: "1.1.1.1", CONF_PASSWORD: "p"})
        assert result["errors"] == {"base": "cannot_connect"}

    # Test AbortFlow
    with (
        patch(
            "custom_components.zte_router_5g.config_flow._validate_credentials",
            side_effect=AbortFlow("already_configured"),
        ),
        pytest.raises(AbortFlow),
    ):
        await flow.async_step_user({CONF_HOST: "1.1.1.1", CONF_PASSWORD: "p"})

    # Test Exception (unknown)
    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        side_effect=Exception("Unknown"),
    ):
        result = await flow.async_step_user({CONF_HOST: "1.1.1.1", CONF_PASSWORD: "p"})
        assert result["errors"] == {"base": "unknown"}


def test_async_get_options_flow():
    """Test getting the options flow."""
    flow = ZTEConfigFlow()
    entry = MagicMock()
    options_flow = flow.async_get_options_flow(entry)
    assert isinstance(options_flow, ZTEOptionsFlow)


@pytest.mark.asyncio
async def test_options_flow_init_success():
    """Test successful options flow init step."""
    entry = MagicMock()
    entry.options = {CONF_HOST: "192.168.0.1", CONF_PASSWORD: "old_password"}
    flow = ZTEOptionsFlow(entry)
    flow.hass = MagicMock()

    user_input = {CONF_HOST: "192.168.0.1", CONF_PASSWORD: "new_password"}

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        return_value=None,
    ):
        result = await flow.async_step_init(user_input)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: "192.168.0.1", CONF_PASSWORD: "new_password"}


@pytest.mark.asyncio
async def test_options_flow_errors():
    """Test error branches in options flow."""
    entry = MagicMock()
    entry.options = {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "p"}
    flow = ZTEOptionsFlow(entry)
    flow.hass = MagicMock()

    # Test ZTEConnectionError
    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        side_effect=ZTEConnectionError,
    ):
        result = await flow.async_step_init({CONF_HOST: "1.1.1.1", CONF_PASSWORD: "p"})
        assert result["errors"] == {"base": "cannot_connect"}

    # Test Exception
    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        side_effect=Exception,
    ):
        result = await flow.async_step_init({CONF_HOST: "1.1.1.1", CONF_PASSWORD: "p"})
        assert result["errors"] == {"base": "unknown"}


@pytest.mark.asyncio
async def test_config_flow_user_step_show_form():
    """Test that user step shows form when no input provided."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}

    result = await flow.async_step_user(user_input=None)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert "data_schema" in result


@pytest.mark.asyncio
async def test_options_flow_init_show_form():
    """Test that options step shows form when no input provided."""
    entry = MagicMock()
    entry.options = {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "p"}
    flow = ZTEOptionsFlow(entry)
    flow.hass = MagicMock()

    result = await flow.async_step_init(user_input=None)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    assert "data_schema" in result


@pytest.mark.asyncio
async def test_options_flow_init_auth_error():
    """Test options flow ZTEAuthError branch."""
    entry = MagicMock()
    entry.options = {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "p"}
    flow = ZTEOptionsFlow(entry)
    flow.hass = MagicMock()

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        side_effect=ZTEAuthError,
    ):
        result = await flow.async_step_init({CONF_HOST: "1.1.1.1", CONF_PASSWORD: "p"})

    assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.asyncio
async def test_reauth_flow_show_form():
    """Test reauth step shows form when entry exists."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"entry_id": "test_entry"}

    mock_entry = MagicMock()
    mock_entry.options = {CONF_HOST: "192.168.0.1", CONF_PASSWORD: "old"}
    flow.hass.config_entries.async_get_entry.return_value = mock_entry

    result = await flow.async_step_reauth()

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"


@pytest.mark.asyncio
async def test_reauth_flow_success():
    """Test successful reauthentication."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"entry_id": "test_entry"}

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry"
    mock_entry.options = {CONF_HOST: "192.168.0.1", CONF_PASSWORD: "old"}
    flow.hass.config_entries.async_get_entry.return_value = mock_entry
    flow.hass.config_entries.async_reload = AsyncMock()

    user_input = {CONF_HOST: "192.168.0.1", CONF_PASSWORD: "new_password"}

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        return_value=None,
    ):
        result = await flow.async_step_reauth_confirm(user_input)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    flow.hass.config_entries.async_reload.assert_called_once_with("test_entry")


@pytest.mark.asyncio
async def test_reauth_flow_invalid_auth():
    """Test reauth with invalid auth returns error."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"entry_id": "test_entry"}

    mock_entry = MagicMock()
    flow.hass.config_entries.async_get_entry.return_value = mock_entry

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        side_effect=ZTEAuthError,
    ):
        result = await flow.async_step_reauth_confirm(
            {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "wrong"}
        )

    assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.asyncio
async def test_reauth_flow_cannot_connect():
    """Test reauth with connection error returns error."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"entry_id": "test_entry"}

    mock_entry = MagicMock()
    flow.hass.config_entries.async_get_entry.return_value = mock_entry

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        side_effect=ZTEConnectionError,
    ):
        result = await flow.async_step_reauth_confirm(
            {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "pass"}
        )

    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_reauth_confirm_unknown_error():
    """Test reauth confirm with unexpected exception returns error."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"entry_id": "test_entry"}

    mock_entry = MagicMock()
    flow.hass.config_entries.async_get_entry.return_value = mock_entry

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        side_effect=Exception("unexpected"),
    ):
        result = await flow.async_step_reauth_confirm(
            {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "pass"}
        )

    assert result["errors"] == {"base": "unknown"}


@pytest.mark.asyncio
async def test_reauth_confirm_entry_gone():
    """Test reauth confirm aborts when entry disappears before update."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"entry_id": "test_entry"}
    flow.hass.config_entries.async_get_entry.return_value = None

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        return_value={"imei": "test_imei", "model": "test_model", "sw_version": "1.0"},
    ):
        result = await flow.async_step_reauth_confirm(
            {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "pass"}
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"


@pytest.mark.asyncio
async def test_reauth_flow_no_entry():
    """Test reauth aborts when entry is missing."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"entry_id": "test_entry"}
    flow.hass.config_entries.async_get_entry.return_value = None

    result = await flow.async_step_reauth()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"


@pytest.mark.asyncio
async def test_reconfigure_show_form():
    """Test reconfigure step shows form when no input provided."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}

    mock_entry = MagicMock()
    mock_entry.options = {CONF_HOST: "192.168.0.1", CONF_PASSWORD: "old"}
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)

    result = await flow.async_step_reconfigure(user_input=None)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert "data_schema" in result


@pytest.mark.asyncio
async def test_reconfigure_success():
    """Test successful reconfigure updates entry and reloads."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}
    flow.async_update_reload_and_abort = MagicMock(
        return_value={"type": FlowResultType.ABORT, "reason": "reconfigure_successful"}
    )

    mock_entry = MagicMock()
    mock_entry.options = {CONF_HOST: "192.168.0.1", CONF_PASSWORD: "old"}
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)

    user_input = {CONF_HOST: "192.168.0.1", CONF_PASSWORD: "new_password"}

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        return_value=None,
    ):
        result = await flow.async_step_reconfigure(user_input)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    flow.async_update_reload_and_abort.assert_called_once_with(
        mock_entry, options={CONF_HOST: "192.168.0.1", CONF_PASSWORD: "new_password"}
    )


@pytest.mark.asyncio
async def test_reconfigure_invalid_auth():
    """Test reconfigure with invalid auth returns error."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}

    mock_entry = MagicMock()
    mock_entry.options = {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "wrong"}
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        side_effect=ZTEAuthError,
    ):
        result = await flow.async_step_reconfigure(
            {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "wrong"}
        )

    assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.asyncio
async def test_reconfigure_cannot_connect():
    """Test reconfigure with connection error returns error."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}

    mock_entry = MagicMock()
    mock_entry.options = {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "pass"}
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        side_effect=ZTEConnectionError,
    ):
        result = await flow.async_step_reconfigure(
            {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "pass"}
        )

    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_reconfigure_unknown_error():
    """Test reconfigure with unexpected exception returns error."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}

    mock_entry = MagicMock()
    mock_entry.options = {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "pass"}
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        side_effect=Exception("unexpected"),
    ):
        result = await flow.async_step_reconfigure(
            {CONF_HOST: "1.1.1.1", CONF_PASSWORD: "pass"}
        )

    assert result["errors"] == {"base": "unknown"}


@pytest.mark.asyncio
async def test_user_step_strips_url_host():
    """Test that a URL entered as host is normalised before being stored."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}
    flow.hass.config_entries.async_entry_for_domain_unique_id.return_value = None

    user_input = {
        CONF_HOST: "https://192.168.0.1/",
        CONF_USERNAME: "admin",
        CONF_PASSWORD: "password",
    }

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        return_value={"imei": "test_imei", "model": "test_model", "sw_version": "1.0"},
    ):
        result = await flow.async_step_user(user_input)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_HOST] == "192.168.0.1"


@pytest.mark.asyncio
async def test_reconfigure_blank_password_keeps_stored():
    """Test that a blank password on reconfigure retains the stored value."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}
    flow.async_update_reload_and_abort = MagicMock(
        return_value={"type": FlowResultType.ABORT, "reason": "reconfigure_successful"}
    )

    mock_entry = MagicMock()
    mock_entry.options = {CONF_HOST: "192.168.0.1", CONF_PASSWORD: "stored_password"}
    flow._get_reconfigure_entry = MagicMock(return_value=mock_entry)

    # User leaves the password field blank and only changes the host format
    user_input = {CONF_HOST: "http://192.168.0.1", CONF_PASSWORD: ""}

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        return_value=None,
    ):
        result = await flow.async_step_reconfigure(user_input)

    assert result["type"] == FlowResultType.ABORT
    flow.async_update_reload_and_abort.assert_called_once_with(
        mock_entry,
        options={CONF_HOST: "192.168.0.1", CONF_PASSWORD: "stored_password"},
    )


@pytest.mark.asyncio
async def test_options_flow_blank_password_keeps_stored():
    """Test that a blank password on the options flow retains the stored value."""
    entry = MagicMock()
    entry.options = {CONF_HOST: "192.168.0.1", CONF_PASSWORD: "stored_password"}
    flow = ZTEOptionsFlow(entry)
    flow.hass = MagicMock()

    user_input = {CONF_HOST: "192.168.0.1", CONF_PASSWORD: ""}

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        return_value=None,
    ):
        result = await flow.async_step_init(user_input)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PASSWORD] == "stored_password"
