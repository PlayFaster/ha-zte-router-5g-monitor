import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import AbortFlow
from .api import ZTERouterAPI, ZTEAuthError, ZTEConnectionError
from .const import DOMAIN, DEFAULT_NAME

_LOGGER = logging.getLogger(__name__)


def _user_schema(defaults: dict) -> vol.Schema:
    """Return the user/options form schema, pre-filled with defaults."""
    return vol.Schema({
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")) : str,
        vol.Optional(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")) : str,
        vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")) : str,
    })


async def _validate_credentials(hass, user_input: dict) -> None:
    """Validate router credentials. Raises ZTEConnectionError or ZTEAuthError on failure."""
    api = ZTERouterAPI(
        user_input[CONF_HOST],
        user_input.get(CONF_USERNAME),
        user_input[CONF_PASSWORD]
    )
    try:
        await hass.async_add_executor_job(api.try_set_protocol, 5)
        await hass.async_add_executor_job(api.login, 5)
    finally:
        # Always close the validation session regardless of outcome
        await hass.async_add_executor_job(api.close)


class ZTEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ZTE Router 5G Monitor."""

    VERSION = 2

    async def async_step_user(self, user_input=None):
        """Handle the initial setup step."""
        errors = {}

        if user_input is not None:
            try:
                await _validate_credentials(self.hass, user_input)

                # Use the host IP as the unique ID so two routers are separate devices
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()

                # Store credentials in options (not data) so the options flow
                # can update them without needing a migration.
                return self.async_create_entry(
                    title=DEFAULT_NAME,
                    data={},
                    options=user_input,
                )

            except AbortFlow:
                # Re-raise AbortFlow so HA can show the "Already Configured" message
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

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(entry):
        """Return the options flow handler."""
        return ZTEOptionsFlow(entry)


class ZTEOptionsFlow(config_entries.OptionsFlow):
    """Handle reconfiguration of an existing ZTE Router entry."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input=None):
        """Manage the options — reconfigure host, username, password."""
        errors = {}

        if user_input is not None:
            try:
                await _validate_credentials(self.hass, user_input)

                # Preserve existing runtime options (scan interval, stop polling)
                # and merge in the updated credentials
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