from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, COORDINATOR

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    async_add_entities([ZTEBestConnectionSensor(coordinator, entry)])

class ZTEBestConnectionSensor(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_name = "ZTE 5G Best Connection DT540"
        self._attr_unique_id = f"{entry.unique_id}_best_conn"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self):
        data = self.coordinator.data
        return data.get("network_type") == "ENDC" and data.get("wan_lte_ca") == "ca_activated"

    @property
    def icon(self):
        return "mdi:signal" if self.is_on else "mdi:signal-cellular-1"

    @property
    def device_info(self):
        # Anchor to Main Router Device
        return {"identifiers": {(DOMAIN, self.coordinator.data.get("lan_ipaddr", "zte_router"))}, "name": "ZTE 5G Router"}