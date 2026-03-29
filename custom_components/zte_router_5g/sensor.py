from datetime import timedelta
from homeassistant.util import dt as dt_util
from homeassistant.const import CONF_HOST, UnitOfInformation
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import UnitOfInformation
from .const import DOMAIN, COORDINATOR

SENSOR_TYPES = [
    # Main Router Signal
    ("lte_rsrp", "LTE RSRP", "mdi:signal", SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT, "dBm", None, "router"),
    ("lte_rsrq", "LTE RSRQ", "mdi:signal", SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT, "dBm", None, "router"),
    ("lte_rssi", "LTE RSSi", "mdi:signal", SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT, "dBm", None, "router"),
    ("lte_snr", "LTE SNR", "mdi:waveform", SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT, "dB", None, "router"),
    ("Z5g_rsrp", "Z5G RSRP", "mdi:signal", SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT, "dBm", None, "router"),
    ("Z5g_SINR", "Z5G SiNr", "mdi:waveform", SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT, "dB", None, "router"),
    ("signalbar", "SignalBar", "mdi:signal", None, SensorStateClass.MEASUREMENT, None, None, "router"),
    ("network_type", "Network Type", "mdi:transmission-tower", None, None, None, None, "router"),
    
    # Data Usage Device
    ("monthly_rx_bytes", "Download GB", "mdi:download", SensorDeviceClass.DATA_SIZE, SensorStateClass.TOTAL_INCREASING, UnitOfInformation.GIGABYTES, None, "data"),
    ("monthly_tx_bytes", "Upload GB", "mdi:upload", SensorDeviceClass.DATA_SIZE, SensorStateClass.TOTAL_INCREASING, UnitOfInformation.GIGABYTES, None, "data"),
    ("monthly_total_bytes", "Data UpDown GB", "mdi:swap-vertical-bold", SensorDeviceClass.DATA_SIZE, SensorStateClass.TOTAL_INCREASING, UnitOfInformation.GIGABYTES, None, "data"),

    # Diagnostics
    ("last_updated", "Last Updated", "mdi:update", SensorDeviceClass.TIMESTAMP, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("device_uptime", "Device Uptime", "mdi:clock-start", SensorDeviceClass.TIMESTAMP, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("cell_id", "Cell ID", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("lan_ipaddr", "LAN IPAddr", "mdi:map-marker-outline", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("wan_ipaddr", "WAN IPAddr", "mdi:map-marker-outline", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("wan_apn", "WAN APN", "mdi:numeric-3-circle-outline", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("wan_connect_status", "WAN Connect Status", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("lte_ca_pcell_band", "LTE CA PCell Band", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("lte_ca_pcell_bandwidth", "LTE CA PCell Bandwidth", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("lte_pci", "LTE Pci", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("mdm_mcc", "MDM MCC", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("mdm_mnc", "MDM MNC", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("network_provider", "Network Provider", "mdi:numeric-3-circle-outline", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("nr5g_action_band", "NR5G Action Band", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("nr5g_action_channel", "NR5G Action Channel", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("nr5g_pci", "NR5G Pci", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("rmcc", "RMCC", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("rmnc", "RMNC", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("wan_active_band", "WAN Active Band", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("wan_active_channel", "WAN Active Channel", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("wan_lte_ca", "WAN LTE CA", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("wa_inner_version", "Wa Inner Version", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
]

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    entities = [ZTEDataSensor(coordinator, entry, *st) for st in SENSOR_TYPES]
    entities.append(ZTESMSSensor(coordinator, entry))
    entities.append(ZTESMSContentSensor(coordinator, entry))
    async_add_entities(entities)

class ZTEDataSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry, key, name, icon, device_class, state_class, unit, category, group):
        super().__init__(coordinator)
        self._entry = entry
        self._key = key
        self._group = group
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit
        self._attr_entity_category = category
        self._attr_unique_id = f"{entry.unique_id}_{key}"

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data: return None
        if self._key == "last_updated":
            return self.coordinator.last_update_success_time
        if self._key == "device_uptime":
            uptime_seconds = data.get("realtime_time")
            if not uptime_seconds: return None
            try:
                seconds = int(float(uptime_seconds))
                boot_time = dt_util.now() - timedelta(seconds=seconds)
                return boot_time.replace(second=0, microsecond=0)
            except: return None
        if self._key == "monthly_total_bytes":
            try:
                rx = float(data.get("monthly_rx_bytes", 0))
                tx = float(data.get("monthly_tx_bytes", 0))
                return round((rx + tx) / 1073741824, 2)
            except: return None
        val = data.get(self._key)
        if val in [None, ""]: return None
        if "monthly" in self._key and "_bytes" in self._key:
            try: return round(float(val) / 1073741824, 2)
            except: return val
        return val

    @property
    def device_info(self):
        # FIX: Use IP from entry.data instead of coordinator.data to prevent NoneType crash
        host = self._entry.data[CONF_HOST]
        if self._group == "data":
            return {
                "identifiers": {(DOMAIN, f"{host}_monthly")},
                "name": f"{self._entry.title} Monthly",
                "manufacturer": "ZTE",
                "via_device": (DOMAIN, host),
            }
        return {
            "identifiers": {(DOMAIN, host)},
            "name": self._entry.title,
            "manufacturer": "ZTE",
            "configuration_url": f"http://{host}",
            "model": "MC7010"
        }

class ZTESMSSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "Total"
        self._attr_unique_id = f"{entry.unique_id}_total"
        self._attr_icon = "mdi:message-plus-outline"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data: return None
        keys = ['sms_nv_rev_total', 'sms_nv_send_total', 'sms_nv_draftbox_total',
                'sms_sim_rev_total', 'sms_sim_send_total', 'sms_sim_draftbox_total']
        return sum(int(data.get(k, 0)) for k in keys)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        if not data: return {}
        return {
            "sms_nv_total": int(data.get("sms_nv_total", 0)),
            "sms_sim_total": int(data.get("sms_sim_total", 0)),
            "sms_nv_rev_total": int(data.get("sms_nv_rev_total", 0)),
            "sms_nv_send_total": int(data.get("sms_nv_send_total", 0)),
            "sms_nv_draftbox_total": int(data.get("sms_nv_draftbox_total", 0)),
            "sms_sim_rev_total": int(data.get("sms_sim_rev_total", 0)),
            "sms_sim_send_total": int(data.get("sms_sim_send_total", 0)),
            "sms_sim_draftbox_total": int(data.get("sms_sim_draftbox_total", 0)),
        }

    @property
    def device_info(self):
        # FIX: Use IP from entry.data
        host = self._entry.data[CONF_HOST]
        return {
            "identifiers": {(DOMAIN, f"{host}_sms")},
            "name": f"{self._entry.title} SMS",
            "manufacturer": "ZTE",
            "via_device": (DOMAIN, host),
        }

class ZTESMSContentSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "Recent"
        self._attr_unique_id = f"{entry.unique_id}_recent"
        self._attr_icon = "mdi:message-badge-outline"

    @property
    def native_value(self):
        if not self.coordinator.data: return "No messages"
        msg = self.coordinator.data.get("last_sms", {})
        return msg.get("content_decoded", "No messages")

    @property
    def extra_state_attributes(self):
        if not self.coordinator.data: return {}
        msg = self.coordinator.data.get("last_sms", {})
        return {
            "id": msg.get("id"),
            "number": msg.get("number_decoded"),
            "date": msg.get("date_decoded"),
        }

    @property
    def device_info(self):
        # FIX: Use IP from entry.data
        host = self._entry.data[CONF_HOST]
        return {
            "identifiers": {(DOMAIN, f"{host}_sms")},
            "name": f"{self._entry.title} SMS",
            "via_device": (DOMAIN, host),
        }