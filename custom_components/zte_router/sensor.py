from datetime import timedelta
from homeassistant.util import dt as dt_util

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import UnitOfInformation
from .const import DOMAIN, COORDINATOR

# Mapping: (key, name, icon, device_class, state_class, unit, category, device_group)
# groups: router, data, sms
SENSOR_TYPES = [
    # Main Router Signal
    ("lte_rsrp", "ZTE 5G LTE RSRP DT509", "mdi:signal", SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT, "dBm", None, "router"),
    ("lte_rsrq", "ZTE 5G LTE RSRQ DT510", "mdi:signal", SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT, "dBm", None, "router"),
    ("lte_rssi", "ZTE 5G LTE RSSi DT511", "mdi:signal", SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT, "dBm", None, "router"),
    ("lte_snr", "ZTE 5G LTE SNR DT512", "mdi:waveform", SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT, "dB", None, "router"),
    ("Z5g_rsrp", "ZTE 5G Z5G RSRP DT535", "mdi:signal", SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT, "dBm", None, "router"),
    ("Z5g_SINR", "ZTE 5G Z5G SiNr DT536", "mdi:waveform", SensorDeviceClass.SIGNAL_STRENGTH, SensorStateClass.MEASUREMENT, "dB", None, "router"),
    ("signalbar", "ZTE 5G SignalBar DT527", "mdi:signal", None, SensorStateClass.MEASUREMENT, None, None, "router"),
    ("network_type", "ZTE 5G Network Type DT518", "mdi:transmission-tower", None, None, None, None, "router"),
    
    # Data Usage Device
    ("monthly_rx_bytes", "ZTE 5G Monthly Download DT515", "mdi:download", SensorDeviceClass.DATA_SIZE, SensorStateClass.TOTAL_INCREASING, UnitOfInformation.GIGABYTES, None, "data"),
    ("monthly_tx_bytes", "ZTE 5G Monthly Upload DT516", "mdi:upload", SensorDeviceClass.DATA_SIZE, SensorStateClass.TOTAL_INCREASING, UnitOfInformation.GIGABYTES, None, "data"),
    ("monthly_total_bytes", "ZTE 5G Monthly Data UpDown DT517", "mdi:swap-vertical-bold", SensorDeviceClass.DATA_SIZE, SensorStateClass.TOTAL_INCREASING, UnitOfInformation.GIGABYTES, None, "data"),

    # Diagnostics
    ("last_updated", "Last Updated", "mdi:update", SensorDeviceClass.TIMESTAMP, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("device_uptime", "Device Uptime", "mdi:clock-start", SensorDeviceClass.TIMESTAMP, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("cell_id", "ZTE 5G Cell ID DT502", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("lan_ipaddr", "ZTE 5G LAN IPAddr DT503", "mdi:map-marker-outline", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("wan_ipaddr", "ZTE 5G WAN IPAddr DT532", "mdi:map-marker-outline", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("wan_apn", "ZTE 5G WAN APN DT530", "mdi:numeric-3-circle-outline", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("wan_connect_status", "ZTE 5G WAN Connect Status DT531", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("lte_ca_pcell_band", "ZTE 5G LTE CA PCell Band DT504", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("wa_inner_version", "ZTE 5G Wa Inner Version DT534", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("mdm_mcc", "ZTE 5G MDM MCC DT513", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
    ("mdm_mnc", "ZTE 5G MDM MNC DT514", "mdi:transmission-tower", None, None, None, EntityCategory.DIAGNOSTIC, "router"),
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
        
        # New: Last Successful Update Timestamp
        if self._key == "last_updated":
            return self.coordinator.last_update_success_time

        # New: Locked Device Uptime (Boot Time)
        if self._key == "device_uptime":
            uptime_seconds = data.get("realtime_time")
            if uptime_seconds is None or uptime_seconds == "":
                return None
            try:
                # Calculate boot time and round to nearest minute to prevent jitter
                seconds = int(float(uptime_seconds))
                boot_time = dt_util.now() - timedelta(seconds=seconds)
                return boot_time.replace(second=0, microsecond=0)
            except:
                return None

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
        host = self.coordinator.data.get("lan_ipaddr", "zte_router")
        if self._group == "data":
            return {
                "identifiers": {(DOMAIN, f"{host}_data")},
                "name": "ZTE Router Data Usage",
                "manufacturer": "ZTE",
                "via_device": (DOMAIN, host),
            }
        return {
            "identifiers": {(DOMAIN, host)},
            "name": "ZTE 5G Router",
            "manufacturer": "ZTE",
            "model": "MC7010/MC801",
        }

class ZTESMSSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_name = "ZTE 5G SMS Total DT543"
        self._attr_unique_id = f"{entry.unique_id}_sms_total"
        self._attr_icon = "mdi:message-plus-outline"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        data = self.coordinator.data
        keys = ['sms_nv_rev_total', 'sms_nv_send_total', 'sms_nv_draftbox_total',
                'sms_sim_rev_total', 'sms_sim_send_total', 'sms_sim_draftbox_total']
        return sum(int(data.get(k, 0)) for k in keys)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
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
        host = self.coordinator.data.get("lan_ipaddr", "zte_router")
        return {
            "identifiers": {(DOMAIN, f"{host}_sms")},
            "name": "ZTE Router SMS Service",
            "manufacturer": "ZTE",
            "via_device": (DOMAIN, host),
        }

class ZTESMSContentSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_name = "ZTE 5G SMS Recent DT542"
        self._attr_unique_id = f"{entry.unique_id}_sms_recent"
        self._attr_icon = "mdi:message-badge-outline"

    @property
    def native_value(self):
        msg = self.coordinator.data.get("last_sms", {})
        return msg.get("content_decoded", "No messages")

    @property
    def extra_state_attributes(self):
        msg = self.coordinator.data.get("last_sms", {})
        return {
            "id": msg.get("id"),
            "number": msg.get("number_decoded"),
            "date": msg.get("date_decoded"),
        }

    @property
    def device_info(self):
        host = self.coordinator.data.get("lan_ipaddr", "zte_router")
        return {
            "identifiers": {(DOMAIN, f"{host}_sms")},
            "name": "ZTE Router SMS Service",
            "via_device": (DOMAIN, host),
        }