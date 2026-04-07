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
from homeassistant.const import CONF_HOST, UnitOfInformation
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import ZTERouterDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class ZTESensorEntityDescription(SensorEntityDescription):
    """Describes ZTE sensor entity."""

    value_fn: Callable[[Any], Any]
    group: str = "main"


def _get_bytes_to_gb(val: Any) -> float | None:
    """Convert bytes string to rounded GB float."""
    if val in [None, ""]:
        return None
    try:
        return round(float(val) / 1073741824, 2)
    except ValueError, TypeError:
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
    except ValueError, TypeError:
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
    except ValueError, TypeError:
        return None


# Technical Router Sensors
SENSOR_TYPES: Final[tuple[ZTESensorEntityDescription, ...]] = (
    ZTESensorEntityDescription(
        key="lte_rsrp",
        translation_key="lte_rsrp",
        icon="mdi:signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dBm",
        value_fn=lambda data: data.get("lte_rsrp"),
    ),
    ZTESensorEntityDescription(
        key="lte_rsrq",
        translation_key="lte_rsrq",
        icon="mdi:signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dBm",
        value_fn=lambda data: data.get("lte_rsrq"),
    ),
    ZTESensorEntityDescription(
        key="lte_rssi",
        translation_key="lte_rssi",
        icon="mdi:signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dBm",
        value_fn=lambda data: data.get("lte_rssi"),
    ),
    ZTESensorEntityDescription(
        key="lte_snr",
        translation_key="lte_snr",
        icon="mdi:waveform",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        value_fn=lambda data: data.get("lte_snr"),
    ),
    ZTESensorEntityDescription(
        key="z5g_rsrp",
        translation_key="z5g_rsrp",
        icon="mdi:signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dBm",
        value_fn=lambda data: data.get("Z5g_rsrp"),
    ),
    ZTESensorEntityDescription(
        key="z5g_rsrq",
        translation_key="z5g_rsrq",
        icon="mdi:signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        value_fn=lambda data: data.get("Z5g_rsrq"),
    ),
    ZTESensorEntityDescription(
        key="z5g_rssi",
        translation_key="z5g_rssi",
        icon="mdi:signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dBm",
        value_fn=lambda data: data.get("Z5g_rssi"),
    ),
    ZTESensorEntityDescription(
        key="z5g_sinr",
        translation_key="z5g_sinr",
        icon="mdi:waveform",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        value_fn=lambda data: data.get("Z5g_SINR"),
    ),
    ZTESensorEntityDescription(
        key="signalbar",
        translation_key="signalbar",
        icon="mdi:signal",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("signalbar"),
    ),
    ZTESensorEntityDescription(
        key="network_type",
        translation_key="network_type",
        icon="mdi:transmission-tower",
        value_fn=lambda data: data.get("network_type"),
    ),
    ZTESensorEntityDescription(
        key="monthly_rx_bytes",
        translation_key="monthly_rx_bytes",
        icon="mdi:download",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        group="data",
        value_fn=lambda data: _get_bytes_to_gb(data.get("monthly_rx_bytes")),
    ),
    ZTESensorEntityDescription(
        key="monthly_tx_bytes",
        translation_key="monthly_tx_bytes",
        icon="mdi:upload",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        group="data",
        value_fn=lambda data: _get_bytes_to_gb(data.get("monthly_tx_bytes")),
    ),
    ZTESensorEntityDescription(
        key="monthly_total_bytes",
        translation_key="monthly_total_bytes",
        icon="mdi:swap-vertical-bold",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        group="data",
        value_fn=lambda data: (
            round(
                (
                    float(data.get("monthly_rx_bytes", 0))
                    + float(data.get("monthly_tx_bytes", 0))
                )
                / 1073741824,
                2,
            )
            if data.get("monthly_rx_bytes") is not None
            else None
        ),
    ),
    ZTESensorEntityDescription(
        key="last_updated",
        translation_key="last_updated",
        icon="mdi:update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: None,  # Handled in native_value
    ),
    ZTESensorEntityDescription(
        key="device_uptime",
        translation_key="device_uptime",
        icon="mdi:clock-start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_get_uptime,
    ),
    ZTESensorEntityDescription(
        key="cell_id",
        translation_key="cell_id",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("cell_id"),
    ),
    ZTESensorEntityDescription(
        key="lan_ipaddr",
        translation_key="lan_ipaddr",
        icon="mdi:map-marker-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("lan_ipaddr"),
    ),
    ZTESensorEntityDescription(
        key="wan_ipaddr",
        translation_key="wan_ipaddr",
        icon="mdi:map-marker-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("wan_ipaddr"),
    ),
    ZTESensorEntityDescription(
        key="wan_apn",
        translation_key="wan_apn",
        icon="mdi:numeric-3-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("wan_apn"),
    ),
    ZTESensorEntityDescription(
        key="wan_connect_status",
        translation_key="wan_connect_status",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("wan_connect_status"),
    ),
    ZTESensorEntityDescription(
        key="lte_ca_pcell_band",
        translation_key="lte_ca_pcell_band",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("lte_ca_pcell_band"),
    ),
    ZTESensorEntityDescription(
        key="lte_ca_pcell_bandwidth",
        translation_key="lte_ca_pcell_bandwidth",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("lte_ca_pcell_bandwidth"),
    ),
    ZTESensorEntityDescription(
        key="lte_ca_scell_band",
        translation_key="lte_ca_scell_band",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("lte_ca_scell_band"),
    ),
    ZTESensorEntityDescription(
        key="lte_ca_scell_bandwidth",
        translation_key="lte_ca_scell_bandwidth",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("lte_ca_scell_bandwidth"),
    ),
    ZTESensorEntityDescription(
        key="lte_pci",
        translation_key="lte_pci",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("lte_pci"),
    ),
    ZTESensorEntityDescription(
        key="mdm_mcc",
        translation_key="mdm_mcc",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("mdm_mcc"),
    ),
    ZTESensorEntityDescription(
        key="mdm_mnc",
        translation_key="mdm_mnc",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("mdm_mnc"),
    ),
    ZTESensorEntityDescription(
        key="network_provider",
        translation_key="network_provider",
        icon="mdi:numeric-3-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("network_provider"),
    ),
    ZTESensorEntityDescription(
        key="nr5g_action_band",
        translation_key="nr5g_action_band",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("nr5g_action_band"),
    ),
    ZTESensorEntityDescription(
        key="nr5g_action_channel",
        translation_key="nr5g_action_channel",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("nr5g_action_channel"),
    ),
    ZTESensorEntityDescription(
        key="nr5g_pci",
        translation_key="nr5g_pci",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("nr5g_pci"),
    ),
    ZTESensorEntityDescription(
        key="rmcc",
        translation_key="rmcc",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("rmcc"),
    ),
    ZTESensorEntityDescription(
        key="rmnc",
        translation_key="rmnc",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("rmnc"),
    ),
    ZTESensorEntityDescription(
        key="wan_active_band",
        translation_key="wan_active_band",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("wan_active_band"),
    ),
    ZTESensorEntityDescription(
        key="wan_active_channel",
        translation_key="wan_active_channel",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("wan_active_channel"),
    ),
    ZTESensorEntityDescription(
        key="wan_lte_ca",
        translation_key="wan_lte_ca",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("wan_lte_ca"),
    ),
    ZTESensorEntityDescription(
        key="wa_inner_version",
        translation_key="wa_inner_version",
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("wa_inner_version"),
    ),
    # SMS Sensors
    ZTESensorEntityDescription(
        key="msg_total",
        translation_key="msg_total",
        icon="mdi:message-plus-outline",
        state_class=SensorStateClass.MEASUREMENT,
        group="sms",
        value_fn=_get_total_sms,
    ),
    ZTESensorEntityDescription(
        key="msg_recent",
        translation_key="msg_recent",
        icon="mdi:message-badge-outline",
        group="sms",
        value_fn=lambda data: data.get("last_sms", {}).get(
            "content_decoded", "No messages"
        ),
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the sensor platform."""
    coordinator: ZTERouterDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        ZTESensor(coordinator, entry, description) for description in SENSOR_TYPES
    ]
    async_add_entities(entities)


class ZTESensor(CoordinatorEntity[ZTERouterDataUpdateCoordinator], SensorEntity):
    """Implementation of technical router and SMS sensors."""

    _attr_has_entity_name = True
    entity_description: ZTESensorEntityDescription

    def __init__(self, coordinator, entry, description):
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

        # Special case: Last Updated
        if self.entity_description.key == "last_updated":
            return self.coordinator.last_update_success_time

        try:
            return self.entity_description.value_fn(self.coordinator.data)
        except KeyError, AttributeError, ValueError, TypeError:
            return None

    @property
    def extra_state_attributes(self):
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
            except ValueError, TypeError:
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

        # "Flat Identity" identifiers: consistent from boot
        main_identifiers = {(DOMAIN, host)}

        if group == "main":
            return {
                "identifiers": main_identifiers,
                "name": self._entry.title,
                "manufacturer": "ZTE",
                "configuration_url": f"http://{host}",
                "model": self.coordinator.model,
                "sw_version": self.coordinator.sw_version,
            }

        # Sub-device dynamic routing
        group_names = {"sms": "SMS", "data": "Monthly"}
        display_group = group_names.get(group, group.capitalize())
        sub_name = f"{self._entry.title} {display_group}"

        return {
            "identifiers": {(DOMAIN, f"{host}_{group}")},
            "name": sub_name,
            "manufacturer": "ZTE",
            "model": self.coordinator.model,
            "sw_version": self.coordinator.sw_version,
            "via_device": (DOMAIN, host),
        }
