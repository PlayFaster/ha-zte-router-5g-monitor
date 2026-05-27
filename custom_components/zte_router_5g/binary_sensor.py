"""Binary sensor platform for ZTE Router 5G."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ZTERouterDataUpdateCoordinator
from .helpers import build_device_info

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZTEBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes ZTE binary sensor entity."""

    group: str = "signal"
    value_fn: Callable[[Any], bool] | None = None
    extra_attrs_fn: Callable[[Any], dict[str, Any]] | None = None


# Define the entity description for static metadata
BEST_CONN_DESCRIPTION = ZTEBinarySensorEntityDescription(
    key="best_connection",
    translation_key="signal_best_connection",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    group="signal",
)

BINARY_SENSORS: Final[tuple[ZTEBinarySensorEntityDescription, ...]] = (
    ZTEBinarySensorEntityDescription(
        key="reboot_schedule",
        translation_key="system_reboot_schedule",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("reboot_schedule_enable") == "1" if data else False,
        extra_attrs_fn=lambda data: {
            "reboot_hour1": data.get("reboot_hour1") if data else None,
            "reboot_min1": data.get("reboot_min1") if data else None,
            "reboot_hour2": data.get("reboot_hour2") if data else None,
            "reboot_min2": data.get("reboot_min2") if data else None,
        },
    ),
    ZTEBinarySensorEntityDescription(
        key="upnp_enabled",
        translation_key="system_upnp_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("upnpEnabled") == "1" if data else False,
    ),
    ZTEBinarySensorEntityDescription(
        key="sip_alg_enabled",
        translation_key="system_sip_alg_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("alg_sip_enable") == "1" if data else False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator: ZTERouterDataUpdateCoordinator = entry.runtime_data
    
    entities = [
        ZTEBestConnectionSensor(coordinator, entry, BEST_CONN_DESCRIPTION)
    ]
    entities.extend(
        [
            ZTERouterBinarySensor(coordinator, entry, description)
            for description in BINARY_SENSORS
        ]
    )
    async_add_entities(entities)


class ZTEBestConnectionSensor(
    CoordinatorEntity[ZTERouterDataUpdateCoordinator],
    BinarySensorEntity,
):
    """Binary sensor to check for optimal 5G/LTE CA connection."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: ZTEBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: ZTERouterDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ZTEBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry

        # Unique ID generated from description key for registry stability
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def is_on(self) -> bool:
        """Return true if both 5G and LTE CA are active."""
        data = self.coordinator.data
        if not data:
            return False
        # Optimal connection logic based on raw data keys
        return bool(
            data.get("network_type") == "ENDC"
            and data.get("wan_lte_ca") == "ca_activated"
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information with sub-device support."""
        return build_device_info(
            self.coordinator, self._entry, self.entity_description.group
        )


class ZTERouterBinarySensor(
    CoordinatorEntity[ZTERouterDataUpdateCoordinator],
    BinarySensorEntity,
):
    """Representation of a ZTE Router binary sensor."""

    _attr_has_entity_name = True
    entity_description: ZTEBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: ZTERouterDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ZTEBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is active."""
        if not self.coordinator.data or self.entity_description.value_fn is None:
            return False
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if (
            not self.coordinator.data
            or self.entity_description.extra_attrs_fn is None
        ):
            return {}
        return self.entity_description.extra_attrs_fn(self.coordinator.data)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information with sub-device support."""
        return build_device_info(
            self.coordinator, self._entry, self.entity_description.group
        )
