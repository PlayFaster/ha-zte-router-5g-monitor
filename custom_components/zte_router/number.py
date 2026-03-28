import asyncio
from datetime import timedelta
from homeassistant.components.number import NumberEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.const import UnitOfTime
from .const import DOMAIN, COORDINATOR, CONF_SCAN_INTERVAL

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the number platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data[COORDINATOR]
    
    # Read from persisted storage (hass.data was initialized from options in __init__)
    initial_value = data.get(CONF_SCAN_INTERVAL, 180)
    
    async_add_entities([ZTEPollingInterval(coordinator, entry, initial_value)])

class ZTEPollingInterval(NumberEntity):
    """Number entity to control the polling interval with persistence."""
    
    def __init__(self, coordinator, entry, initial_value):
        self._coordinator = coordinator
        self._entry = entry
        self._attr_name = "Polling Interval"
        self._attr_unique_id = f"{entry.unique_id}_poll_interval"
        self._attr_native_min_value = 30
        self._attr_native_max_value = 3600
        self._attr_native_step = 30
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_native_value = initial_value
        self._refresh_task = None

    async def async_set_native_value(self, value: float) -> None:
        """Handle the UI slider change."""
        # 1. Update the UI state immediately so the slider stays where the user put it
        self._attr_native_value = value
        self.async_write_ha_state()

        # 2. Debounce logic: Cancel any existing pending refresh task
        if self._refresh_task:
            self._refresh_task.cancel()

        # 3. Create a new task to apply the change after a short delay
        self._refresh_task = asyncio.create_task(self._async_debounced_apply(value))

    async def _async_debounced_apply(self, value: float) -> None:
        """Apply change and persist to ConfigEntry Options."""
        try:
            await asyncio.sleep(2)
            val_int = int(value)
            
            # 1. Update session memory
            self.hass.data[DOMAIN][self._entry.entry_id][CONF_SCAN_INTERVAL] = val_int
            self._coordinator.update_interval = timedelta(seconds=val_int)
            
            # 2. Persist to ConfigEntry Options (saves to .storage)
            new_options = dict(self._entry.options)
            new_options[CONF_SCAN_INTERVAL] = val_int
            self.hass.config_entries.async_update_entry(self._entry, options=new_options)
            
            # 3. Trigger immediate refresh
            await self._coordinator.async_request_refresh()
            
        except asyncio.CancelledError:
            pass

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._coordinator.data.get("lan_ipaddr", "zte_router"))},
            "name": "ZTE 5G Router"
        }