import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from .api import ZTERouterAPI
from .const import DOMAIN, NAME

class ZTEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ZTE 5G Router Monitor."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                # Validate the connection
                api = ZTERouterAPI(
                    user_input[CONF_HOST],
                    user_input.get(CONF_USERNAME),
                    user_input[CONF_PASSWORD]
                )
                
                # Check connectivity and credentials
                await self.hass.async_add_executor_job(api.try_set_protocol)
                await self.hass.async_add_executor_job(api.login)
                
                # Use IP as unique ID
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"{NAME} ({user_input[CONF_HOST]})",
                    data=user_input
                )
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors,
        )