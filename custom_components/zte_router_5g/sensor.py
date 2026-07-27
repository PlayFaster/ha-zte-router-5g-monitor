"""Sensor platform for ZTE Router 5G."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ENDPOINT_SMS_MESSAGES, ZTERouterDataUpdateCoordinator
from .helpers import build_device_info

_LOGGER = logging.getLogger(__name__)

_BYTES_PER_GB = 1000000000

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZTESensorEntityDescription(SensorEntityDescription):
    """Describes ZTE sensor entity."""

    value_fn: Callable[[Any], Any]
    group: str = "system"
    min_limit: float | None = None
    max_limit: float | None = None
    # Optional endpoint this sensor's value comes from. When set, the entity
    # goes unavailable once that endpoint exhausts its own strike budget,
    # instead of serving a stale value forever (dev_standards Section 8).
    source: str | None = None


def _get_bytes_to_gb(val: Any) -> float | None:
    """Convert bytes string to rounded GB float."""
    if val in [None, ""]:
        return None
    try:
        return round(float(val) / _BYTES_PER_GB, 2)
    except (ValueError, TypeError):
        return None


def _get_uptime(data: Any) -> Any:
    """Get the cached boot timestamp from data."""
    return data.get("boot_time")


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
    """Safely convert a value to float, rounded at parse time.

    Rounding **once, here** curtails the dozen-decimal noise controllers emit
    (e.g. 99.930600002408) so stored history and long-term statistics stay
    clean. This is distinct from display: `suggested_display_precision`
    controls how many decimals are *shown*, this controls how many are
    *stored* (dev_standards Section 6).
    """
    if val in [None, ""]:
        return None
    try:
        return round(float(val), 3)
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


# Helper to safely convert router string values to string and map empty to None
def _safe_str(val: Any) -> str | None:
    """Safely convert value to string or return None if empty."""
    if val in [None, ""]:
        return None
    return str(val)


# Technical Router Sensors
SENSOR_TYPES: Final[tuple[ZTESensorEntityDescription, ...]] = (
    # --- System Sub-device ---
    ZTESensorEntityDescription(
        key="model_name",
        translation_key="system_model_name",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: data.get("model_name"),
    ),
    ZTESensorEntityDescription(
        key="wa_inner_version",
        translation_key="system_wa_inner_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: data.get("wa_inner_version"),
    ),
    ZTESensorEntityDescription(
        key="wan_ipaddr",
        translation_key="system_wan_ipaddr",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: _safe_str(data.get("wan_ipaddr")),
    ),
    ZTESensorEntityDescription(
        key="lan_ipaddr",
        translation_key="system_lan_ipaddr",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: data.get("lan_ipaddr"),
    ),
    ZTESensorEntityDescription(
        key="device_uptime",
        translation_key="system_device_uptime",
        device_class=SensorDeviceClass.TIMESTAMP,
        group="system",
        value_fn=_get_uptime,
    ),
    ZTESensorEntityDescription(
        key="realtime_time",
        translation_key="system_uptime_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        group="system",
        value_fn=lambda data: _safe_int(data.get("realtime_time")),
    ),
    ZTESensorEntityDescription(
        key="last_updated",
        translation_key="system_last_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        group="system",
        value_fn=lambda data: None,  # Handled in property
    ),
    ZTESensorEntityDescription(
        key="imei",
        translation_key="system_imei",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        value_fn=lambda data: data.get("imei"),
    ),
    ZTESensorEntityDescription(
        key="hardware_version",
        translation_key="system_hardware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: data.get("hardware_version"),
    ),
    ZTESensorEntityDescription(
        key="battery_value",
        translation_key="system_battery_value",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        min_limit=0,
        max_limit=100,
        group="system",
        value_fn=lambda data: _safe_int(data.get("battery_value")),
    ),
    ZTESensorEntityDescription(
        key="sim_imsi",
        translation_key="system_sim_imsi",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        value_fn=lambda data: data.get("sim_imsi"),
    ),
    ZTESensorEntityDescription(
        key="sim_iccid",
        translation_key="system_sim_iccid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        value_fn=lambda data: data.get("sim_iccid"),
    ),
    # --- Signal Sub-device ---
    ZTESensorEntityDescription(
        key="wan_connect_status",
        translation_key="signal_wan_connect_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("wan_connect_status"),
    ),
    ZTESensorEntityDescription(
        key="wan_apn",
        translation_key="signal_wan_apn",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_str(data.get("wan_apn")),
    ),
    ZTESensorEntityDescription(
        key="network_type",
        translation_key="signal_network_type",
        group="signal",
        value_fn=lambda data: _safe_str(data.get("network_type")),
    ),
    ZTESensorEntityDescription(
        key="signalbar",
        translation_key="signal_signalbar",
        state_class=SensorStateClass.MEASUREMENT,
        group="signal",
        value_fn=lambda data: _safe_int(data.get("signalbar")),
    ),
    ZTESensorEntityDescription(
        key="network_provider",
        translation_key="signal_network_provider",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_str(data.get("network_provider")),
    ),
    ZTESensorEntityDescription(
        key="mdm_mcc",
        translation_key="signal_mdm_mcc",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("mdm_mcc"),
    ),
    ZTESensorEntityDescription(
        key="mdm_mnc",
        translation_key="signal_mdm_mnc",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("mdm_mnc"),
    ),
    ZTESensorEntityDescription(
        key="rmcc",
        translation_key="signal_rmcc",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: data.get("rmcc"),
    ),
    ZTESensorEntityDescription(
        key="rmnc",
        translation_key="signal_rmnc",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: data.get("rmnc"),
    ),
    ZTESensorEntityDescription(
        key="lte_rsrp",
        translation_key="signal_lte_rsrp",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        min_limit=-140,
        max_limit=-30,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_rsrp")),
    ),
    ZTESensorEntityDescription(
        key="lte_rsrq",
        translation_key="signal_lte_rsrq",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        min_limit=-40,
        max_limit=0,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_rsrq")),
    ),
    ZTESensorEntityDescription(
        key="lte_rssi",
        translation_key="signal_lte_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        min_limit=-120,
        max_limit=-20,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_rssi")),
    ),
    ZTESensorEntityDescription(
        key="lte_snr",
        translation_key="signal_lte_snr",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        min_limit=-20,
        max_limit=50,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_snr")),
    ),
    ZTESensorEntityDescription(
        key="lte_pci",
        translation_key="signal_lte_pci",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_str(data.get("lte_pci")),
    ),
    ZTESensorEntityDescription(
        key="cell_id",
        translation_key="signal_cell_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_str(data.get("cell_id")),
    ),
    ZTESensorEntityDescription(
        key="wan_lte_ca",
        translation_key="signal_wan_lte_ca",
        group="signal",
        value_fn=lambda data: data.get("wan_lte_ca"),
    ),
    ZTESensorEntityDescription(
        key="lte_ca_pcell_band",
        translation_key="signal_lte_ca_pcell_band",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("lte_ca_pcell_band"),
    ),
    ZTESensorEntityDescription(
        key="lte_ca_pcell_bandwidth",
        translation_key="signal_lte_ca_pcell_bandwidth",
        native_unit_of_measurement="MHz",
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_ca_pcell_bandwidth")),
    ),
    ZTESensorEntityDescription(
        key="lte_ca_scell_band",
        translation_key="signal_lte_ca_scell_band",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: data.get("lte_ca_scell_band") or None,
    ),
    ZTESensorEntityDescription(
        key="lte_ca_scell_bandwidth",
        translation_key="signal_lte_ca_scell_bandwidth",
        native_unit_of_measurement="MHz",
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_ca_scell_bandwidth")),
    ),
    ZTESensorEntityDescription(
        key="wan_active_band",
        translation_key="signal_wan_active_band",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_str(data.get("wan_active_band")),
    ),
    ZTESensorEntityDescription(
        key="wan_active_channel",
        translation_key="signal_wan_active_channel",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_int(data.get("wan_active_channel")),
    ),
    ZTESensorEntityDescription(
        key="z5g_rsrp",
        translation_key="signal_z5g_rsrp",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        min_limit=-140,
        max_limit=-30,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("Z5g_rsrp")),
    ),
    ZTESensorEntityDescription(
        key="z5g_rsrq",
        translation_key="signal_z5g_rsrq",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        min_limit=-40,
        max_limit=0,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("Z5g_rsrq")),
    ),
    ZTESensorEntityDescription(
        key="z5g_rssi",
        translation_key="signal_z5g_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        min_limit=-120,
        max_limit=-20,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("Z5g_rssi")),
    ),
    ZTESensorEntityDescription(
        key="z5g_sinr",
        translation_key="signal_z5g_sinr",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        min_limit=-20,
        max_limit=50,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("Z5g_SINR")),
    ),
    ZTESensorEntityDescription(
        key="nr5g_pci",
        translation_key="signal_nr5g_pci",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_str(data.get("nr5g_pci")),
    ),
    ZTESensorEntityDescription(
        key="nr5g_action_band",
        translation_key="signal_nr5g_action_band",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_str(data.get("nr5g_action_band")),
    ),
    ZTESensorEntityDescription(
        key="nr5g_action_channel",
        translation_key="signal_nr5g_action_channel",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_int(data.get("nr5g_action_channel")),
    ),
    ZTESensorEntityDescription(
        key="rssi",
        translation_key="signal_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        min_limit=-120,
        max_limit=-20,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("rssi")),
    ),
    ZTESensorEntityDescription(
        key="rscp",
        translation_key="signal_rscp",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        min_limit=-120,
        max_limit=-20,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("rscp")),
    ),
    ZTESensorEntityDescription(
        key="enodeb_id",
        translation_key="signal_enodeb_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_str(data.get("enodeb_id")),
    ),
    ZTESensorEntityDescription(
        key="net_select",
        translation_key="signal_net_select",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("net_select"),
    ),
    ZTESensorEntityDescription(
        key="ppp_status",
        translation_key="signal_ppp_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("ppp_status"),
    ),
    # --- Data Sub-device ---
    # Legacy GB Sensors (Disabled by default, preserved for history)
    ZTESensorEntityDescription(
        key="monthly_tx_bytes",
        translation_key="data_monthly_tx_bytes",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
        group="data",
        # Divided by 1_000_000_000 to match decimal GB (UnitOfInformation.GIGABYTES)
        value_fn=lambda data: _get_bytes_to_gb(data.get("monthly_tx_bytes")),
    ),
    ZTESensorEntityDescription(
        key="monthly_rx_bytes",
        translation_key="data_monthly_rx_bytes",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
        group="data",
        # Divided by 1_000_000_000 to match decimal GB (UnitOfInformation.GIGABYTES)
        value_fn=lambda data: _get_bytes_to_gb(data.get("monthly_rx_bytes")),
    ),
    ZTESensorEntityDescription(
        key="monthly_total_bytes",
        translation_key="data_monthly_total_bytes",
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
        translation_key="data_monthly_tx_bytes_raw",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        group="data",
        value_fn=lambda data: _safe_int(data.get("monthly_tx_bytes")),
    ),
    ZTESensorEntityDescription(
        key="monthly_rx_bytes_raw",
        translation_key="data_monthly_rx_bytes_raw",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        group="data",
        value_fn=lambda data: _safe_int(data.get("monthly_rx_bytes")),
    ),
    ZTESensorEntityDescription(
        key="monthly_total_bytes_raw",
        translation_key="data_monthly_total_bytes_raw",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
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
        translation_key="data_realtime_tx_thrpt",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        suggested_display_precision=2,
        min_limit=0,
        group="data",
        value_fn=lambda data: _safe_int(data.get("realtime_tx_thrpt")),
    ),
    ZTESensorEntityDescription(
        key="realtime_rx_thrpt",
        translation_key="data_realtime_rx_thrpt",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        suggested_display_precision=2,
        min_limit=0,
        group="data",
        value_fn=lambda data: _safe_int(data.get("realtime_rx_thrpt")),
    ),
    ZTESensorEntityDescription(
        key="realtime_tx_bytes",
        translation_key="data_realtime_tx_bytes",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        min_limit=0,
        group="data",
        value_fn=lambda data: _safe_int(data.get("realtime_tx_bytes")),
    ),
    ZTESensorEntityDescription(
        key="realtime_rx_bytes",
        translation_key="data_realtime_rx_bytes",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        min_limit=0,
        group="data",
        value_fn=lambda data: _safe_int(data.get("realtime_rx_bytes")),
    ),
    # --- SMS Sub-device ---
    ZTESensorEntityDescription(
        key="sms_unread_num",
        translation_key="sms_sms_unread_num",
        state_class=SensorStateClass.MEASUREMENT,
        group="sms",
        value_fn=lambda data: _safe_int(data.get("sms_unread_num")),
    ),
    ZTESensorEntityDescription(
        key="msg_total",
        translation_key="sms_msg_total",
        state_class=SensorStateClass.MEASUREMENT,
        group="sms",
        value_fn=_get_total_sms,
    ),
    ZTESensorEntityDescription(
        key="msg_recent",
        translation_key="sms_msg_recent",
        group="sms",
        # The only sensor fed by an optional endpoint — the other SMS sensors
        # read counters returned by the mandatory get_all_data fetch.
        source=ENDPOINT_SMS_MESSAGES,
        value_fn=lambda data: data.get("last_sms", {}).get("content_decoded"),
    ),
    # --- Discovered Technical Settings & Info ---
    ZTESensorEntityDescription(
        key="lte_band_lock",
        translation_key="signal_lte_band_lock",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: _safe_str(data.get("lte_band_lock")),
    ),
    ZTESensorEntityDescription(
        key="data_volume_alert_percent",
        translation_key="data_volume_alert_percent",
        native_unit_of_measurement="%",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        min_limit=0,
        max_limit=100,
        group="data",
        value_fn=lambda data: _safe_int(data.get("data_volume_alert_percent")),
    ),
    ZTESensorEntityDescription(
        key="sntp_server",
        translation_key="system_sntp_server",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        value_fn=lambda data: _safe_str(data.get("sntp_server0")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
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

    # Attributes excluded from the recorder (dev_standards Section 14). The
    # entity's state is still recorded — only these named keys are dropped.
    #
    # `number` is the SMS *sender's* phone number: third-party personal data
    # that would otherwise be written to the database on every poll. `id` and
    # `date` change with each new message and have no historical value beside
    # the state itself. The eight SMS counters are a breakdown of a state that
    # is already recorded, so keeping them would store the same movement twice.
    #
    # Deliberately still recorded: `sntp_server1` and `sntp_dst_enable`. They
    # are static configuration, cost effectively nothing, and a change to them
    # is genuinely worth being able to see in history.
    _unrecorded_attributes = frozenset(
        {
            "id",
            "number",
            "date",
            "sms_nv_total",
            "sms_sim_total",
            "sms_nv_rev_total",
            "sms_nv_send_total",
            "sms_nv_draftbox_total",
            "sms_sim_rev_total",
            "sms_sim_send_total",
            "sms_sim_draftbox_total",
        }
    )

    def __init__(
        self,
        coordinator: ZTERouterDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ZTESensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def available(self) -> bool:
        """Return whether this sensor has a working data source.

        Sensors fed by an optional endpoint go unavailable when that endpoint
        alone has exhausted its strike budget, while the rest of the
        integration keeps serving data (Section 8).
        """
        if not super().available:
            return False
        source = self.entity_description.source
        return source is None or self.coordinator.endpoint_available(source)

    @property
    def native_value(self) -> Any:
        """Return the value of the sensor."""
        if not self.coordinator.data:
            return None

        key = self.entity_description.key

        if key == "last_updated":
            return self.coordinator.last_update_success_time

        try:
            value = self.entity_description.value_fn(self.coordinator.data)
        except (KeyError, AttributeError, ValueError):
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
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed attributes for specific sensors."""
        data = self.coordinator.data
        if not data:
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

        if key == "sntp_server":
            return {
                "sntp_server1": data.get("sntp_server1"),
                "sntp_dst_enable": data.get("sntp_dst_enable") == "1",
            }

        return {}

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information with sub-device support."""
        return build_device_info(
            self.coordinator, self._entry, self.entity_description.group
        )
