from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType

from custom_components.zte_router_5g.api import ZTEAuthError
from custom_components.zte_router_5g.config_flow import ZTEConfigFlow, ZTEOptionsFlow
from custom_components.zte_router_5g.const import DEFAULT_NAME


@pytest.mark.asyncio
async def test_config_flow_user_step_success():
    """Test successful config flow user step."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    # Fix 'mappingproxy' error by giving the flow a real dict context
    flow.context = {}

    # FIX: Tell the Mock that no entry exists for this unique ID yet.
    # Without this, the Mock returns another Mock (truthy), triggering AbortFlow.
    flow.hass.config_entries.async_entry_for_domain_unique_id.return_value = None

    user_input = {
        CONF_HOST: "192.168.0.1",
        CONF_USERNAME: "admin",
        CONF_PASSWORD: "password",
    }

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        return_value=None,
    ):
        result = await flow.async_step_user(user_input)

    # Home Assistant uses Enums for result types
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == DEFAULT_NAME
    assert result["options"] == user_input


@pytest.mark.asyncio
async def test_config_flow_user_step_invalid_auth():
    """Test config flow user step with invalid auth."""
    flow = ZTEConfigFlow()
    flow.hass = MagicMock()
    flow.context = {}

    user_input = {CONF_HOST: "192.168.0.1", CONF_PASSWORD: "wrong_password"}

    with patch(
        "custom_components.zte_router_5g.config_flow._validate_credentials",
        side_effect=ZTEAuthError,
    ):
        result = await flow.async_step_user(user_input)

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


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
