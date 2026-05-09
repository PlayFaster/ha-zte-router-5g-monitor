"""Binary sensor platform for ZTE Router 5G."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
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


# Define the entity description for static metadata
BEST_CONN_DESCRIPTION = ZTEBinarySensorEntityDescription(
    key="best_connection",
    translation_key="signal_best_connection",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    group="signal",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator: ZTERouterDataUpdateCoordinator = entry.runtime_data
    # Pass the description object into the sensor
    async_add_entities(
        [ZTEBestConnectionSensor(coordinator, entry, BEST_CONN_DESCRIPTION)]
    )


class ZTEBestConnectionSensor(
    CoordinatorEntity[ZTERouterDataUpdateCoordinator], BinarySensorEntity
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
        return (
            data.get("network_type") == "ENDC"
            and data.get("wan_lte_ca") == "ca_activated"
        )

    @property
    def icon(self) -> str:
        """Return icon based on connection status."""
        return "mdi:signal" if self.is_on else "mdi:signal-cellular-1"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information with sub-device support."""
        return build_device_info(
            self.coordinator, self._entry, self.entity_description.group
        )
