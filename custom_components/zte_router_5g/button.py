import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.const import CONF_HOST
from .const import DOMAIN, COORDINATOR

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        ZTERebootButton(data["api"], data[COORDINATOR], entry),
        ZTEDeleteAllSMSButton(data["api"], data[COORDINATOR], entry)
    ], True)

class ZTERebootButton(ButtonEntity):
    def __init__(self, api, coordinator, entry):
        self._api = api
        self._coordinator = coordinator
        self._entry = entry
        self._attr_name = "Reboot"
        self._attr_unique_id = f"{entry.unique_id}_reboot"
        self._attr_icon = "mdi:restart"
        self._attr_device_class = "restart"

    @property
    def device_info(self):
        # Anchor to Main Router Device using IP from Config Entry
        host = self._entry.data[CONF_HOST]
        return {
            "identifiers": {(DOMAIN, host)}, 
            "name": self._entry.title,
            "manufacturer": "ZTE",
            "configuration_url": f"http://{host}",
            "model": "MC7010"
        }

    async def async_press(self) -> None:
        try:
            await self.hass.async_add_executor_job(self._api.reboot)
        except Exception as err:
            # FIX: Use dynamic title for logging
            _LOGGER.error("%s: Reboot failed: %s", self._entry.title, err)

class ZTEDeleteAllSMSButton(ButtonEntity):
    def __init__(self, api, coordinator, entry):
        self._api = api
        self._coordinator = coordinator
        self._entry = entry
        self._attr_name = "Delete All SMS"
        self._attr_unique_id = f"{entry.unique_id}_delete_all_sms"
        self._attr_icon = "mdi:email-remove"

    @property
    def device_info(self):
        # Anchor to SMS Child Device using IP from Config Entry
        host = self._entry.data[CONF_HOST]
        return {
            "identifiers": {(DOMAIN, f"{host}_sms")},
            "name": f"{self._entry.title} SMS",
            "manufacturer": "ZTE",
            "via_device": (DOMAIN, host),
        }

    async def async_press(self) -> None:
        try:
            await self.hass.async_add_executor_job(self._api.delete_all_sms)
            await self._coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("%s: Delete SMS failed: %s", self._entry.title, err)