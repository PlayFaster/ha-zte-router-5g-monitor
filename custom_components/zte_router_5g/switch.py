"""Switch platform for ZTE Router 5G."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, cast

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_STOP_POLLING
from .coordinator import ZTERouterDataUpdateCoordinator
from .helpers import build_device_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZTESwitchEntityDescription(SwitchEntityDescription):  # type: ignore[misc]
    """Describes ZTE switch entity."""

    group: str = "system"


# Define the entity description for static metadata
PAUSE_POLLING_DESCRIPTION = ZTESwitchEntityDescription(
    key="pause_polling",
    translation_key="system_pause_polling",
    entity_category=EntityCategory.CONFIG,
    group="system",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    coordinator: ZTERouterDataUpdateCoordinator = entry.runtime_data

    # Read initial state from entry options (survives restarts)
    initial_state = entry.options.get(CONF_STOP_POLLING, False)

    async_add_entities(
        [
            ZTEPausePollingSwitch(
                coordinator, entry, PAUSE_POLLING_DESCRIPTION, initial_state
            )
        ]
    )


class ZTEPausePollingSwitch(
    CoordinatorEntity[ZTERouterDataUpdateCoordinator],  # type: ignore[misc]
    SwitchEntity,  # type: ignore[misc]
):
    """Switch to pause/resume polling with persistence."""

    _attr_has_entity_name = True
    _attr_should_poll = False  # State is managed by user interaction and memory
    entity_description: ZTESwitchEntityDescription

    def __init__(
        self,
        coordinator: ZTERouterDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ZTESwitchEntityDescription,
        initial_state: bool,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._entry = entry
        self.entity_description = description

        # Registry identification
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_is_on = initial_state

    @property
    def is_on(self) -> bool:
        """Return true if polling is paused."""
        return cast(bool, self._entry.options.get(CONF_STOP_POLLING, False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Pause polling."""
        _LOGGER.debug("Pausing ZTE Router polling")
        await self._async_set_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Resume polling."""
        _LOGGER.debug("Resuming ZTE Router polling")
        await self._async_set_state(False)

    async def _async_set_state(self, state: bool) -> None:
        """Update memory, state, and persist to options."""
        # 1. Persist to ConfigEntry Options (saves to .storage)
        # This ensures the pause state survives a Home Assistant restart.
        new_options = dict(self._entry.options)
        new_options[CONF_STOP_POLLING] = state
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)

        # Signal to HA that the state has changed
        self.async_write_ha_state()

        # 2. If we just resumed, trigger an immediate coordinator refresh
        if not state:
            await self.coordinator.async_request_refresh()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information with sub-device support."""
        return build_device_info(
            self.coordinator, self._entry, self.entity_description.group
        )
