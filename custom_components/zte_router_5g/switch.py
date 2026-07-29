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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_STOP_POLLING, DOMAIN
from .coordinator import ENDPOINT_EXTENDED, ZTERouterDataUpdateCoordinator
from .helpers import ZTEAboutEntity, build_device_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZTESwitchEntityDescription(SwitchEntityDescription):
    """Describes ZTE switch entity."""

    group: str = "system"
    value_fn: Callable[[Any], bool] | None = None
    # Takes the API client, the requested state, and the last polled data.
    # The third argument exists for `DATA_LIMIT_SETTING`, which replaces a
    # whole form and so needs the fields that are not changing.
    setter_fn: Callable[[Any, bool, Any], Coroutine[Any, Any, None]] | None = None
    # Optional plain-language note surfaced as an unrecorded `about` attribute
    # (dev_standards Section 14). Resolved by the ZTEAboutEntity mixin.
    about: str | None = None
    # Optional endpoint this switch's state is read from — see the binary
    # sensor equivalent. Both ZTE switches read from the extended fetch.
    source: str | None = None


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
        source=ENDPOINT_EXTENDED,
        translation_key="system_odu_led_switch",
        entity_category=EntityCategory.CONFIG,
        group="system",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("ODU_led_switch") == "1" if data else False,
        setter_fn=lambda api, state, data: api.set_odu_led_switch(
            "1" if state else "0"
        ),
    ),
    ZTESwitchEntityDescription(
        key="data_limit_switch",
        source=ENDPOINT_EXTENDED,
        about=(
            "Turns on the router's own monthly data cap. When the limit is "
            "reached the router stops passing traffic - it does not merely warn - "
            "so leave this off unless you have set the limit deliberately. The "
            "alert percentage governs when it warns you on the way there."
        ),
        translation_key="data_limit_switch",
        entity_category=EntityCategory.CONFIG,
        group="data",
        entity_registry_enabled_default=False,
        value_fn=lambda data: (
            data.get("data_volume_limit_switch") == "1" if data else False
        ),
        setter_fn=lambda api, state, data: api.set_data_limit_switch(
            "1" if state else "0", data or {}
        ),
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

    entities: list[SwitchEntity] = [
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
    ZTEAboutEntity,
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
    def available(self) -> bool:
        """Return whether the endpoint feeding this switch is still healthy.

        A switch whose state comes from a degraded fetch would otherwise show
        a stale position and invite a write against a stale reading — which
        matters here, because the data-limit write echoes back fields from the
        same payload.
        """
        if not super().available:
            return False
        source = self.entity_description.source
        return source is None or self.coordinator.endpoint_available(source)

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        if not self.coordinator.data or self.entity_description.value_fn is None:
            return False
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_apply(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_apply(False)

    async def _async_apply(self, state: bool) -> None:
        """Send the new state, surfacing a refusal rather than logging it.

        A failure here used to be swallowed into the log, so a write the
        router declined looked to the user like a switch that quietly sprang
        back. This API answers `200 OK` for a refused write, which makes an
        unreported failure especially easy to miss (IQS `action-exceptions`).
        """
        if self.entity_description.setter_fn is None:
            return
        try:
            await self.entity_description.setter_fn(
                self.coordinator.api, state, self.coordinator.data
            )
        except Exception as err:
            _LOGGER.error(
                "%s: Failed to set %s: %s",
                self._entry.title,
                self.entity_description.key,
                err,
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="switch_set_failed",
                translation_placeholders={
                    "entity": self.entity_description.key,
                    "error": str(err),
                },
            ) from err
        await self.coordinator.async_force_refresh()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information with sub-device support."""
        return build_device_info(
            self.coordinator, self._entry, self.entity_description.group
        )


class ZTEPausePollingSwitch(
    ZTEAboutEntity,
    CoordinatorEntity[ZTERouterDataUpdateCoordinator],
    SwitchEntity,
):
    """Switch to pause/resume polling with persistence."""

    _attr_about = (
        "Stops scheduled polling without removing the integration. Useful when "
        "you need the router's own web page, since it allows only one login "
        "session at a time. Entities hold their last known values, and explicit "
        "actions such as Refresh Now still fetch."
    )

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
            await self.coordinator.async_force_refresh()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information with sub-device support."""
        return build_device_info(
            self.coordinator, self._entry, self.entity_description.group
        )
