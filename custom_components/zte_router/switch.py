from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN, COORDINATOR, CONF_STOP_POLLING

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the switch platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data[COORDINATOR]
    
    # Read initial state from session memory (initialized from options in __init__)
    initial_state = data.get(CONF_STOP_POLLING, False)
    
    async_add_entities([ZTEPausePollingSwitch(coordinator, entry, initial_state)])

class ZTEPausePollingSwitch(SwitchEntity):
    """Switch to pause/resume polling with persistence."""

    def __init__(self, coordinator, entry, initial_state):
        self._coordinator = coordinator
        self._entry = entry
        self._attr_name = "Pause Polling"
        self._attr_unique_id = f"{entry.unique_id}_pause_polling"
        self._attr_icon = "mdi:pause-circle-outline"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_is_on = initial_state

    @property
    def is_on(self) -> bool:
        """Return true if polling is paused."""
        return self.hass.data[DOMAIN][self._entry.entry_id].get(CONF_STOP_POLLING, False)

    async def async_turn_on(self, **kwargs):
        """Pause polling and persist."""
        await self._async_set_state(True)

    async def async_turn_off(self, **kwargs):
        """Resume polling and persist."""
        await self._async_set_state(False)

    async def _async_set_state(self, state: bool):
        """Update memory, state, and persist to options."""
        # 1. Update session memory
        self.hass.data[DOMAIN][self._entry.entry_id][CONF_STOP_POLLING] = state
        
        # 2. Persist to ConfigEntry Options
        new_options = dict(self._entry.options)
        new_options[CONF_STOP_POLLING] = state
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        
        self.async_write_ha_state()
        
        # If we just resumed, trigger a refresh
        if not state:
            await self._coordinator.async_request_refresh()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._coordinator.data.get("lan_ipaddr", "zte_router"))},
            "name": "ZTE 5G Router"
        }