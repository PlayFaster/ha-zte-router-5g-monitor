from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN, CONF_STOP_POLLING, COORDINATOR

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the switch platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data[COORDINATOR]
    # Fetch initial state here while hass is available
    initial_state = data.get(CONF_STOP_POLLING, False)
    
    async_add_entities([ZTEStopPollingSwitch(coordinator, entry, initial_state)])

class ZTEStopPollingSwitch(SwitchEntity):
    def __init__(self, coordinator, entry, initial_state):
        self._coordinator = coordinator
        self._entry = entry
        self._attr_name = "Pause Polling"
        self._attr_unique_id = f"{entry.unique_id}_pause_polling"
        self._attr_icon = "mdi:pause-circle"
        self._attr_entity_category = EntityCategory.CONFIG
        self._is_on = initial_state

    @property
    def is_on(self):
        return self._is_on

    async def async_turn_on(self, **kwargs):
        self._is_on = True
        self.hass.data[DOMAIN][self._entry.entry_id][CONF_STOP_POLLING] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._is_on = False
        self.hass.data[DOMAIN][self._entry.entry_id][CONF_STOP_POLLING] = False
        self.async_write_ha_state()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._coordinator.data.get("lan_ipaddr", "zte_router"))},
            "name": "ZTE 5G Router"
        }