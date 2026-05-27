"""Switch platform for ZTE Router 5G."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, cast

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_STOP_POLLING
from .coordinator import ZTERouterDataUpdateCoordinator
from .helpers import build_device_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZTESwitchEntityDescription(SwitchEntityDescription):
    """Describes ZTE switch entity."""

    group: str = "system"
    value_fn: Callable[[Any], bool] | None = None
    setter_fn: Callable[[Any, bool], Coroutine[Any, Any, None]] | None = None


# Define the entity description for static metadata
PAUSE_POLLING_DESCRIPTION = ZTESwitchEntityDescription(
    key="pause_polling",
    translation_key="system_pause_polling",
    entity_category=EntityCategory.CONFIG,
    group="system",
)

SWITCH_TYPES: tuple[ZTESwitchEntityDescription, ...] = (
    ZTESwitchEntityDescription(
        key="odu_led_switch",
        translation_key="system_odu_led_switch",
        entity_category=EntityCategory.CONFIG,
        group="system",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("ODU_led_switch") == "1" if data else False,
        setter_fn=lambda api, state: api.set_odu_led_switch("1" if state else "0"),
    ),
    ZTESwitchEntityDescription(
        key="data_limit_switch",
        translation_key="data_limit_switch",
        entity_category=EntityCategory.CONFIG,
        group="data",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("data_volume_limit_switch") == "1" if data else False,
        setter_fn=lambda api, state: api.set_data_limit_switch("1" if state else "0"),
    ),
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

    entities = [
        ZTEPausePollingSwitch(
            coordinator, entry, PAUSE_POLLING_DESCRIPTION, initial_state
        )
    ]
    
    entities.extend(
        [
            ZTERouterSwitch(coordinator, entry, description)
            for description in SWITCH_TYPES
        ]
    )

    async_add_entities(entities)


class ZTERouterSwitch(
    CoordinatorEntity[ZTERouterDataUpdateCoordinator],
    SwitchEntity,
):
    """Switch to control ZTE Router settings."""

    _attr_has_entity_name = True
    entity_description: ZTESwitchEntityDescription

    def __init__(
        self,
        coordinator: ZTERouterDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ZTESwitchEntityDescription,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._entry = entry
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        if not self.coordinator.data or self.entity_description.value_fn is None:
            return False
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if self.entity_description.setter_fn is None:
            return
        try:
            await self.entity_description.setter_fn(self.coordinator.api, True)
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error(
                "%s: Failed to turn on %s: %s",
                self._entry.title,
                self.entity_description.key,
                err,
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        if self.entity_description.setter_fn is None:
            return
        try:
            await self.entity_description.setter_fn(self.coordinator.api, False)
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error(
                "%s: Failed to turn off %s: %s",
                self._entry.title,
                self.entity_description.key,
                err,
            )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information with sub-device support."""
        return build_device_info(
            self.coordinator, self._entry, self.entity_description.group
        )


class ZTEPausePollingSwitch(
    CoordinatorEntity[ZTERouterDataUpdateCoordinator],
    SwitchEntity,
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
