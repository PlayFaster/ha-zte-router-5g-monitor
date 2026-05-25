"""Number platform for ZTE Router 5G."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SCAN_INTERVAL
from .coordinator import ZTERouterDataUpdateCoordinator
from .helpers import build_device_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZTENumberEntityDescription(NumberEntityDescription):
    """Describes ZTE number entity."""

    group: str = "system"


# Define the entity description for static metadata
POLLING_INTERVAL_DESCRIPTION = ZTENumberEntityDescription(
    key="polling_interval",
    translation_key="system_polling_interval",
    native_min_value=30,
    native_max_value=3600,
    native_step=30,
    native_unit_of_measurement=UnitOfTime.SECONDS,
    entity_category=EntityCategory.CONFIG,
    group="system",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number platform."""
    coordinator: ZTERouterDataUpdateCoordinator = entry.runtime_data

    # Read initial value from entry options (survives restarts)
    initial_value = entry.options.get(CONF_SCAN_INTERVAL, 180)

    async_add_entities(
        [
            ZTEPollingInterval(
                coordinator, entry, POLLING_INTERVAL_DESCRIPTION, initial_value
            )
        ]
    )


class ZTEPollingInterval(
    CoordinatorEntity[ZTERouterDataUpdateCoordinator],
    NumberEntity,
):
    """Number entity to control the polling interval with persistence."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: ZTENumberEntityDescription

    def __init__(
        self,
        coordinator: ZTERouterDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ZTENumberEntityDescription,
        initial_value: float,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._entry = entry
        self.entity_description = description

        # Registry identification
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

        # Local state
        self._attr_native_value = initial_value
        self._refresh_task: asyncio.Task[Any] | None = None

    async def async_will_remove_from_hass(self) -> None:
        """Cancel any pending debounce task on removal."""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()

    async def async_set_native_value(self, value: float) -> None:
        """Handle the UI slider change."""
        # Update local UI state immediately for responsiveness
        self._attr_native_value = value
        self.async_write_ha_state()

        # Cancel any pending update task to reset the debounce timer
        if self._refresh_task:
            self._refresh_task.cancel()

        # Start a new debounced task
        self._refresh_task = self.hass.async_create_task(
            self._async_debounced_apply(value)
        )

    async def _async_debounced_apply(self, value: float) -> None:
        """Apply change and persist to ConfigEntry Options after a delay."""
        try:
            # Wait for 2 seconds of inactivity before committing
            await asyncio.sleep(2)
            val_int = int(value)

            _LOGGER.debug("Applying new polling interval: %s seconds", val_int)

            # 1. Update the coordinator's actual update interval
            self.coordinator.update_interval = timedelta(seconds=val_int)

            # 2. Persist to ConfigEntry Options (saves to .storage/core.config_entries)
            # This ensures the setting survives a Home Assistant restart.
            new_options = dict(self._entry.options)
            new_options[CONF_SCAN_INTERVAL] = val_int
            self.hass.config_entries.async_update_entry(
                self._entry, options=new_options
            )

            # 3. Trigger an immediate refresh using the new interval
            await self.coordinator.async_request_refresh()

        except asyncio.CancelledError:
            # Task was cancelled because the user moved the slider again
            pass
        except Exception as err:
            _LOGGER.error("Failed to apply polling interval change: %s", err)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information with sub-device support."""
        return build_device_info(
            self.coordinator, self._entry, self.entity_description.group
        )
