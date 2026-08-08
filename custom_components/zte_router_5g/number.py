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
from .helpers import ZTEAboutEntity, build_device_info

_LOGGER = logging.getLogger(__name__)

# Writes are serialised — see the note in `switch.py`. `0` (unlimited) stays
# correct for the read-only platforms; a platform that commands this
# single-session router must not issue concurrent `goform` writes.
PARALLEL_UPDATES = 1


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
    ZTEAboutEntity,
    CoordinatorEntity[ZTERouterDataUpdateCoordinator],
    NumberEntity,
):
    """Number entity to control the polling interval with persistence."""

    _attr_about = (
        "How often the integration fetches from the router, from 30 seconds to "
        "1 hour. The router permits only one login session at a time, so "
        "polling less often leaves its web page free for longer."
    )

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
        # The value the debounce is waiting to commit, so removal can flush it.
        self._pending_value: float | None = None

    async def async_will_remove_from_hass(self) -> None:
        """Commit a pending slider value on removal, rather than discarding it.

        The slider is optimistic: it shows the new value at once and writes it
        after a 2 s debounce. An options change reloads the entry, which
        removes this entity — and a removal inside that window used to cancel
        the task without writing, so the value snapped back with no
        explanation. Cancel the timer, then apply what it was waiting to do.
        """
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
            if self._pending_value is not None:
                self._persist_interval(self._pending_value)

    def _persist_interval(self, value: float) -> None:
        """Apply the interval to the coordinator and write it to the entry.

        Shared by the debounced apply and the removal flush, so a value
        committed at teardown lands exactly where a committed one would. Kept
        synchronous deliberately — `async_will_remove_from_hass` runs during
        teardown, where awaiting a refresh is neither wanted nor safe.
        """
        val_int = int(value)
        self.coordinator.update_interval = timedelta(seconds=val_int)
        new_options = dict(self._entry.options)
        new_options[CONF_SCAN_INTERVAL] = val_int
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)

    async def async_set_native_value(self, value: float) -> None:
        """Handle the UI slider change."""
        # Update local UI state immediately for responsiveness
        self._attr_native_value = value
        self.async_write_ha_state()

        # Held so a removal inside the debounce window can still commit it.
        self._pending_value = value

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

            _LOGGER.debug("Applying new polling interval: %s seconds", int(value))

            # Coordinator interval + persistence to ConfigEntry Options, so the
            # setting survives a Home Assistant restart.
            self._persist_interval(value)
            self._pending_value = None

            # Trigger an immediate refresh using the new interval
            await self.coordinator.async_force_refresh()

        except asyncio.CancelledError:
            # Task was cancelled because the user moved the slider again
            pass
        except Exception:
            _LOGGER.exception("Failed to apply polling interval change")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information with sub-device support."""
        return build_device_info(
            self.coordinator, self._entry, self.entity_description.group
        )
