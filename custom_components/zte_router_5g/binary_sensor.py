from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import CONF_HOST
from .const import DOMAIN, COORDINATOR

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the binary sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    async_add_entities([ZTEBestConnectionSensor(coordinator, entry)])

class ZTEBestConnectionSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor to check for optimal 5G/LTE CA connection."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry # Store entry
        self._attr_name = "Best Connection"
        self._attr_unique_id = f"{entry.unique_id}_best_conn"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self):
        """Return true if both 5G and LTE CA are active."""
        data = self.coordinator.data
        if not data: return False
        return data.get("network_type") == "ENDC" and data.get("wan_lte_ca") == "ca_activated"

    @property
    def icon(self):
        return "mdi:signal" if self.is_on else "mdi:signal-cellular-1"

    @property
    def device_info(self):
        # FIX: Use IP from entry.data to prevent NoneType crash during background setup
        host = self._entry.data[CONF_HOST]
        return {
            "identifiers": {(DOMAIN, host)}, 
            "name": self._entry.title,
            "manufacturer": "ZTE",
            "configuration_url": f"http://{host}",
            "model": "MC7010"
        }