"""Config flow for ZTE Router 5G integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import AbortFlow, FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ZTEAuthError, ZTEConnectionError, ZTERouterAPI
from .const import CONF_NAME, DEFAULT_NAME, DOMAIN
from .helpers import get_router_model

_LOGGER = logging.getLogger(__name__)


def _user_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Return the user/options form schema, pre-filled with defaults."""
    return vol.Schema(
        {
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Optional(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
        }
    )


async def _validate_credentials(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate router credentials and return basic device info."""
    session = async_get_clientsession(hass)
    api = ZTERouterAPI(
        session,
        user_input[CONF_HOST],
        user_input.get(CONF_USERNAME),
        user_input[CONF_PASSWORD],
    )
    # Fully async validation
    await api.try_set_protocol(5)
    await api.login(5)
    data = await api.get_all_data()

    return {
        "model": get_router_model(data),
        "sw_version": data.get("wa_inner_version"),
        "imei": data.get("imei"),
    }


class ZTEConfigFlow(
    config_entries.ConfigFlow,  # type: ignore[misc]
    domain=DOMAIN,  # type: ignore[call-arg]
):
    """Handle a config flow for ZTE Router 5G Monitor."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial setup step."""
        errors = {}

        if user_input is not None:
            try:
                info = await _validate_credentials(self.hass, user_input)

                unique_id = info.get("imei") or user_input[CONF_HOST]
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                # Store credentials and custom name in options
                # Store hardware metadata in data
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, DEFAULT_NAME),
                    data=info,
                    options=user_input,
                )

            except AbortFlow:
                raise
            except ZTEAuthError:
                errors["base"] = "invalid_auth"
            except ZTEConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during config flow user step")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration of the integration."""
        errors = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            try:
                await _validate_credentials(self.hass, user_input)

                return self.async_update_reload_and_abort(
                    entry,
                    options={**entry.options, **user_input},
                )

            except ZTEAuthError:
                errors["base"] = "invalid_auth"
            except ZTEConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception(
                    "Unexpected error during config flow reconfigure step"
                )
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_user_schema(entry.options),
            errors=errors,
            description_placeholders={"host": entry.options.get(CONF_HOST, "")},
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Perform reauthentication when the router password changes."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="reauth_successful")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reauth confirm step to submit new credentials."""
        errors = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        host = entry.options.get(CONF_HOST, "") if entry else ""

        if user_input is not None:
            try:
                await _validate_credentials(self.hass, user_input)

                if entry is None:
                    return self.async_abort(reason="reauth_successful")

                # Merge new credentials into existing entry options
                updated_options = dict(entry.options)
                updated_options.update(user_input)
                self.hass.config_entries.async_update_entry(
                    entry, options=updated_options
                )

                # Reload the entry to pick up new credentials
                await self.hass.config_entries.async_reload(entry.entry_id)

                return self.async_abort(reason="reauth_successful")

            except ZTEAuthError:
                errors["base"] = "invalid_auth"
            except ZTEConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during config flow reauth step")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_user_schema({}),
            errors=errors,
            description_placeholders={"host": host},
        )

    @staticmethod
    @callback  # type: ignore[untyped-decorator]
    def async_get_options_flow(entry: ConfigEntry) -> ZTEOptionsFlow:
        """Return the options flow handler."""
        return ZTEOptionsFlow(entry)


class ZTEOptionsFlow(config_entries.OptionsFlow):  # type: ignore[misc]
    """Handle reconfiguration of an existing ZTE Router entry."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the options flow."""
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options — reconfigure host, username, password."""
        errors = {}

        if user_input is not None:
            try:
                # We call validation but don't need to update 'data' here
                # since it's already populated and will be updated by the coordinator
                await _validate_credentials(self.hass, user_input)

                # Synchronize the integration title if the name changed
                new_name = user_input.get(CONF_NAME, DEFAULT_NAME)
                if new_name != self._entry.title:
                    self.hass.config_entries.async_update_entry(
                        self._entry, title=new_name
                    )

                # Preserve existing runtime options and merge in the updated credentials
                updated_options = dict(self._entry.options)
                updated_options.update(user_input)

                return self.async_create_entry(title="", data=updated_options)

            except ZTEAuthError:
                errors["base"] = "invalid_auth"
            except ZTEConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during config flow options step")
                errors["base"] = "unknown"

        # Pre-fill form with current values
        return self.async_show_form(
            step_id="init",
            data_schema=_user_schema(self._entry.options),
            errors=errors,
        )
