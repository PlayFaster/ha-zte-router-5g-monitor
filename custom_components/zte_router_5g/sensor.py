"""Sensor platform for ZTE Router 5G."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_HOST,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfDataRate,
    UnitOfInformation,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import ZTERouterDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZTESensorEntityDescription(SensorEntityDescription):
    """Describes ZTE sensor entity."""

    value_fn: Callable[[Any], Any]
    group: str = "system"
    min_limit: float | None = None
    max_limit: float | None = None


def _get_bytes_to_gb(val: Any) -> float | None:
    """Convert bytes string to rounded GB float."""
    if val in [None, ""]:
        return None
    try:
        return round(float(val) / 1073741824, 2)
    except (ValueError, TypeError):
        return None


def _get_uptime(data: Any) -> Any:
    """Calculate boot timestamp from uptime seconds."""
    uptime_seconds = data.get("realtime_time")
    if not uptime_seconds:
        return None
    try:
        seconds = int(float(uptime_seconds))
        boot_time = dt_util.now() - timedelta(seconds=seconds)
        return boot_time.replace(second=0, microsecond=0)
    except (ValueError, TypeError):
        return None


def _get_total_sms(data: Any) -> int | None:
    """Calculate total SMS count across all storage banks."""
    keys = [
        "sms_nv_rev_total",
        "sms_nv_send_total",
        "sms_nv_draftbox_total",
        "sms_sim_rev_total",
        "sms_sim_send_total",
        "sms_sim_draftbox_total",
    ]
    try:
        return sum(int(data.get(k, 0)) for k in keys)
    except (ValueError, TypeError):
        return None


# Helper to safely convert router string values to float
def _safe_float(val: Any) -> float | None:
    """Safely convert value to float or return None."""
    if val in [None, ""]:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# Helper to safely convert router string values to int
def _safe_int(val: Any) -> int | None:
    """Safely convert value to int or return None."""
    if val in [None, ""]:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


# Technical Router Sensors
SENSOR_TYPES: Final[tuple[ZTESensorEntityDescription, ...]] = (
    # --- System Sub-device ---
    ZTESensorEntityDescription(
        key="model_name",
        name="Model Name",
        icon="mdi:router-wireless",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: data.get("model_name"),
    ),
    ZTESensorEntityDescription(
        key="wa_inner_version",
        name="Firmware Version",
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: data.get("wa_inner_version"),
    ),
    ZTESensorEntityDescription(
        key="wan_ipaddr",
        name="WAN IP Address",
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: data.get("wan_ipaddr"),
    ),
    ZTESensorEntityDescription(
        key="lan_ipaddr",
        name="LAN IP Address",
        icon="mdi:ip",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: data.get("lan_ipaddr"),
    ),
    ZTESensorEntityDescription(
        key="device_uptime",
        name="Uptime",
        icon="mdi:clock-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=_get_uptime,
    ),
    ZTESensorEntityDescription(
        key="last_updated",
        name="Last Updated",
        icon="mdi:update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: None,  # Handled in property
    ),
    ZTESensorEntityDescription(
        key="imei",
        name="IMEI",
        icon="mdi:cellphone-information",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        value_fn=lambda data: data.get("imei"),
    ),
    ZTESensorEntityDescription(
        key="hardware_version",
        name="Hardware Version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: data.get("hardware_version"),
    ),
    ZTESensorEntityDescription(
        key="battery_value",
        name="Battery",
        icon="mdi:battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        min_limit=0,
        max_limit=100,
        group="system",
        value_fn=lambda data: _safe_int(data.get("battery_value")),
    ),
    ZTESensorEntityDescription(
        key="sim_imsi",
        name="SIM IMSI",
        icon="mdi:sim",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        value_fn=lambda data: data.get("sim_imsi"),
    ),
    ZTESensorEntityDescription(
        key="sim_iccid",
        name="SIM ICCID",
        icon="mdi:sim",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        value_fn=lambda data: data.get("sim_iccid"),
    ),
    # --- Signal Sub-device ---
    ZTESensorEntityDescription(
        key="wan_connect_status",
        name="Connection Status",
        icon="mdi:connection",
        group="signal",
        value_fn=lambda data: data.get("wan_connect_status"),
    ),
    ZTESensorEntityDescription(
        key="wan_apn",
        name="Network APN",
        icon="mdi:access-point-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("wan_apn"),
    ),
    ZTESensorEntityDescription(
        key="network_type",
        name="Network Type",
        icon="mdi:network",
        group="signal",
        value_fn=lambda data: data.get("network_type"),
    ),
    ZTESensorEntityDescription(
        key="signalbar",
        name="Signal Bars",
        icon="mdi:signal-cellular-3",
        state_class=SensorStateClass.MEASUREMENT,
        group="signal",
        value_fn=lambda data: _safe_int(data.get("signalbar")),
    ),
    ZTESensorEntityDescription(
        key="network_provider",
        name="Network Provider",
        icon="mdi:sim-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("network_provider"),
    ),
    ZTESensorEntityDescription(
        key="mdm_mcc",
        name="MDM MCC",
        icon="mdi:map-marker",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("mdm_mcc"),
    ),
    ZTESensorEntityDescription(
        key="mdm_mnc",
        name="MDM MNC",
        icon="mdi:map-marker",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("mdm_mnc"),
    ),
    ZTESensorEntityDescription(
        key="rmcc",
        name="Roaming MCC",
        icon="mdi:map-marker-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: data.get("rmcc"),
    ),
    ZTESensorEntityDescription(
        key="rmnc",
        name="Roaming MNC",
        icon="mdi:map-marker-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: data.get("rmnc"),
    ),
    ZTESensorEntityDescription(
        key="lte_rsrp",
        name="LTE RSRP",
        icon="mdi:signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        min_limit=-140,
        max_limit=-30,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_rsrp")),
    ),
    ZTESensorEntityDescription(
        key="lte_rsrq",
        name="LTE RSRQ",
        icon="mdi:signal",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        min_limit=-40,
        max_limit=0,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_rsrq")),
    ),
    ZTESensorEntityDescription(
        key="lte_rssi",
        name="LTE RSSI",
        icon="mdi:signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        min_limit=-120,
        max_limit=-20,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_rssi")),
    ),
    ZTESensorEntityDescription(
        key="lte_snr",
        name="LTE SNR",
        icon="mdi:waveform",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        min_limit=-20,
        max_limit=50,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_snr")),
    ),
    ZTESensorEntityDescription(
        key="lte_pci",
        name="LTE PCI",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("lte_pci"),
    ),
    ZTESensorEntityDescription(
        key="cell_id",
        name="Cell ID",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("cell_id"),
    ),
    ZTESensorEntityDescription(
        key="wan_lte_ca",
        name="Carrier Aggregation",
        icon="mdi:plus-network",
        group="signal",
        value_fn=lambda data: data.get("wan_lte_ca"),
    ),
    ZTESensorEntityDescription(
        key="lte_ca_pcell_band",
        name="LTE Primary Band",
        icon="mdi:antenna",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("lte_ca_pcell_band"),
    ),
    ZTESensorEntityDescription(
        key="lte_ca_pcell_bandwidth",
        name="LTE Primary Bandwidth",
        icon="mdi:swap-horizontal",
        native_unit_of_measurement="MHz",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_ca_pcell_bandwidth")),
    ),
    ZTESensorEntityDescription(
        key="lte_ca_scell_band",
        name="LTE Secondary Band",
        icon="mdi:antenna",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: data.get("lte_ca_scell_band") or None,
    ),
    ZTESensorEntityDescription(
        key="lte_ca_scell_bandwidth",
        name="LTE Secondary Bandwidth",
        icon="mdi:swap-horizontal",
        native_unit_of_measurement="MHz",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_ca_scell_bandwidth")),
    ),
    ZTESensorEntityDescription(
        key="wan_active_band",
        name="LTE Active Band",
        icon="mdi:antenna",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("wan_active_band"),
    ),
    ZTESensorEntityDescription(
        key="wan_active_channel",
        name="LTE Active Channel",
        icon="mdi:numeric",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_int(data.get("wan_active_channel")),
    ),
    ZTESensorEntityDescription(
        key="z5g_rsrp",
        name="5G RSRP",
        icon="mdi:signal-5g",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        min_limit=-140,
        max_limit=-30,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("Z5g_rsrp")),
    ),
    ZTESensorEntityDescription(
        key="z5g_rsrq",
        name="5G RSRQ",
        icon="mdi:signal-5g",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        min_limit=-40,
        max_limit=0,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("Z5g_rsrq")),
    ),
    ZTESensorEntityDescription(
        key="z5g_rssi",
        name="5G RSSI",
        icon="mdi:signal-5g",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        min_limit=-120,
        max_limit=-20,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("Z5g_rssi")),
    ),
    ZTESensorEntityDescription(
        key="z5g_sinr",
        name="5G SNR",
        icon="mdi:waveform",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        min_limit=-20,
        max_limit=50,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("Z5g_SINR")),
    ),
    ZTESensorEntityDescription(
        key="nr5g_pci",
        name="5G PCI",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("nr5g_pci"),
    ),
    ZTESensorEntityDescription(
        key="nr5g_action_band",
        name="5G Active Band",
        icon="mdi:antenna",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("nr5g_action_band"),
    ),
    ZTESensorEntityDescription(
        key="nr5g_action_channel",
        name="5G Active Channel",
        icon="mdi:numeric",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_int(data.get("nr5g_action_channel")),
    ),
    ZTESensorEntityDescription(
        key="rssi",
        name="Legacy RSSI",
        icon="mdi:signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_registry_enabled_default=False,
        min_limit=-120,
        max_limit=-20,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("rssi")),
    ),
    ZTESensorEntityDescription(
        key="rscp",
        name="Legacy RSCP",
        icon="mdi:signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_registry_enabled_default=False,
        min_limit=-120,
        max_limit=-20,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("rscp")),
    ),
    ZTESensorEntityDescription(
        key="enodeb_id",
        name="eNodeB ID",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("enodeb_id"),
    ),
    ZTESensorEntityDescription(
        key="net_select",
        name="Network Mode",
        icon="mdi:network",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("net_select"),
    ),
    ZTESensorEntityDescription(
        key="ppp_status",
        name="PPP Status",
        icon="mdi:connection",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("ppp_status"),
    ),
    # --- Data Sub-device ---
    # Legacy GB Sensors (Disabled by default, preserved for history)
    ZTESensorEntityDescription(
        key="monthly_tx_bytes",
        name="Monthly Sent GB",
        icon="mdi:upload-network",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
        group="data",
        # Divided by 2^30 (1073741824) to match historical GB logic
        value_fn=lambda data: _get_bytes_to_gb(data.get("monthly_tx_bytes")),
    ),
    ZTESensorEntityDescription(
        key="monthly_rx_bytes",
        name="Monthly Received GB",
        icon="mdi:download-network",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
        group="data",
        # Divided by 2^30 (1073741824) to match historical GB logic
        value_fn=lambda data: _get_bytes_to_gb(data.get("monthly_rx_bytes")),
    ),
    ZTESensorEntityDescription(
        key="monthly_total_bytes",
        name="Monthly Total GB",
        icon="mdi:network-outline",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
        group="data",
        value_fn=lambda data: _get_bytes_to_gb(
            (
                int(data.get("monthly_tx_bytes", 0))
                + int(data.get("monthly_rx_bytes", 0))
            )
            if data.get("monthly_tx_bytes") and data.get("monthly_rx_bytes")
            else None
        ),
    ),
    # Standard Byte Sensors (Enabled by default, supports UI conversion)
    ZTESensorEntityDescription(
        key="monthly_tx_bytes_raw",
        name="Monthly Sent",
        icon="mdi:upload-network",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        group="data",
        value_fn=lambda data: _safe_int(data.get("monthly_tx_bytes")),
    ),
    ZTESensorEntityDescription(
        key="monthly_rx_bytes_raw",
        name="Monthly Received",
        icon="mdi:download-network",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        group="data",
        value_fn=lambda data: _safe_int(data.get("monthly_rx_bytes")),
    ),
    ZTESensorEntityDescription(
        key="monthly_total_bytes_raw",
        name="Monthly Total",
        icon="mdi:network-outline",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        group="data",
        value_fn=lambda data: (
            (
                int(data.get("monthly_tx_bytes", 0))
                + int(data.get("monthly_rx_bytes", 0))
            )
            if data.get("monthly_tx_bytes") and data.get("monthly_rx_bytes")
            else None
        ),
    ),
    ZTESensorEntityDescription(
        key="realtime_tx_thrpt",
        name="Upload Speed",
        icon="mdi:upload-network",
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        min_limit=0,
        group="data",
        value_fn=lambda data: _safe_int(data.get("realtime_tx_thrpt")),
    ),
    ZTESensorEntityDescription(
        key="realtime_rx_thrpt",
        name="Download Speed",
        icon="mdi:download-network",
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        min_limit=0,
        group="data",
        value_fn=lambda data: _safe_int(data.get("realtime_rx_thrpt")),
    ),
    ZTESensorEntityDescription(
        key="realtime_tx_bytes",
        name="Session Sent",
        icon="mdi:upload-network",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        min_limit=0,
        group="data",
        value_fn=lambda data: _safe_int(data.get("realtime_tx_bytes")),
    ),
    ZTESensorEntityDescription(
        key="realtime_rx_bytes",
        name="Session Received",
        icon="mdi:download-network",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        min_limit=0,
        group="data",
        value_fn=lambda data: _safe_int(data.get("realtime_rx_bytes")),
    ),
    # --- SMS Sub-device ---
    ZTESensorEntityDescription(
        key="sms_unread_num",
        name="Unread Msg",
        icon="mdi:email-mark-as-unread",
        state_class=SensorStateClass.MEASUREMENT,
        group="sms",
        value_fn=lambda data: _safe_int(data.get("sms_unread_num")),
    ),
    ZTESensorEntityDescription(
        key="msg_total",
        name="Total Msg",
        icon="mdi:email-multiple",
        state_class=SensorStateClass.MEASUREMENT,
        group="sms",
        value_fn=_get_total_sms,
    ),
    ZTESensorEntityDescription(
        key="msg_recent",
        name="Recent Msg",
        icon="mdi:email-outline",
        group="sms",
        value_fn=lambda data: data.get("last_sms", {}).get("content_decoded"),
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the sensor platform."""
    coordinator: ZTERouterDataUpdateCoordinator = entry.runtime_data
    async_add_entities(
        [
            ZTERouterSensor(coordinator, entry, description)
            for description in SENSOR_TYPES
        ]
    )


class ZTERouterSensor(CoordinatorEntity[ZTERouterDataUpdateCoordinator], SensorEntity):
    """Representation of a ZTE Router sensor."""

    _attr_has_entity_name = True
    entity_description: ZTESensorEntityDescription

    def __init__(
        self,
        coordinator: ZTERouterDataUpdateCoordinator,
        entry,
        description: ZTESensorEntityDescription,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def native_value(self):
        """Return the value of the sensor."""
        if not self.coordinator.data:
            return None

        key = self.entity_description.key

        if key == "last_updated":
            return self.coordinator.last_update_success_time

        try:
            value = self.entity_description.value_fn(self.coordinator.data)
        except (KeyError, AttributeError):
            return None

        if value is None:
            return None

        # Guard bands
        if isinstance(value, (int, float)):
            if (
                self.entity_description.min_limit is not None
                and value < self.entity_description.min_limit
            ):
                return None
            if (
                self.entity_description.max_limit is not None
                and value > self.entity_description.max_limit
            ):
                return None

        return value

    @property
    def extra_state_attributes(self):
        """Return detailed attributes for specific sensors."""
        data = self.coordinator.data
        if data is None:
            return {}

        key = self.entity_description.key

        if key == "msg_total":
            try:
                return {
                    "sms_nv_total": int(data.get("sms_nv_total", 0)),
                    "sms_sim_total": int(data.get("sms_sim_total", 0)),
                    "sms_nv_rev_total": int(data.get("sms_nv_rev_total", 0)),
                    "sms_nv_send_total": int(data.get("sms_nv_send_total", 0)),
                    "sms_nv_draftbox_total": int(data.get("sms_nv_draftbox_total", 0)),
                    "sms_sim_rev_total": int(data.get("sms_sim_rev_total", 0)),
                    "sms_sim_send_total": int(data.get("sms_sim_send_total", 0)),
                    "sms_sim_draftbox_total": int(
                        data.get("sms_sim_draftbox_total", 0)
                    ),
                }
            except (ValueError, TypeError):
                return {}

        if key == "msg_recent":
            msg = data.get("last_sms", {})
            return {
                "id": msg.get("id"),
                "number": msg.get("number_decoded"),
                "date": msg.get("date_decoded"),
            }

        return {}

    @property
    def device_info(self):
        """Return device information with sub-device support."""
        host = self._entry.options[CONF_HOST]
        group = self.entity_description.group

        group_names = {
            "system": "System",
            "signal": "Signal",
            "data": "Data",
            "sms": "SMS",
        }
        display_group = group_names.get(group, group.capitalize())
        sub_name = f"{self._entry.title} {display_group}"

        sub_id_prefix = (
            self.coordinator.imei if self.coordinator.imei else f"host_{host}"
        )

        info = {
            "identifiers": {(DOMAIN, f"{sub_id_prefix}_{group}")},
            "name": sub_name,
            "manufacturer": "ZTE",
            "model": self.coordinator.model,
            "sw_version": self.coordinator.sw_version,
            "configuration_url": f"http://{host}",
        }

        if group != "system":
            info["via_device"] = (DOMAIN, f"{sub_id_prefix}_system")

        return info
