"""Switch platform for ZTE Router 5G."""

from __future__ import annotations

import asyncio
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
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_STOP_POLLING,
    DOMAIN,
    WRITE_VERIFY_RETRY_DELAY,
    WRITE_VERIFY_TIMEOUT,
)
from .coordinator import ZTERouterDataUpdateCoordinator
from .helpers import ZTEAboutEntity, build_device_info

_LOGGER = logging.getLogger(__name__)

# Writes are serialised. `0` (unlimited) is right for the read-only platforms,
# where the coordinator does the fetching and there is nothing to serialise, but
# on a platform that commands the device it means an unbounded number of
# concurrent `goform` POSTs — and this router permits a single session, so
# overlapping writes are exactly how a session gets torn down. Rapid toggling
# now queues instead of racing.
PARALLEL_UPDATES = 1


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
    # sensor equivalent. Both writable switches now read from the core fetch,
    # so neither sets this; it remains for a future switch that does not.
    source: str | None = None
    # The response key this switch's position is read from. Used for two
    # things: telling "the router reported off" apart from "the router did not
    # report this at all", and naming the key to read back after a write. Note
    # it is not always the entity key — `data_limit_switch` reads from
    # `data_volume_limit_switch`.
    state_key: str | None = None
    # Whether to confirm a write by reading `state_key` straight back.
    #
    # Opt-in, and deliberately NOT set on anything that disturbs the radio. The
    # APN and bearer selects re-establish the connection, during which the
    # router answers with blank values — which this integration reads as an
    # expired session. A read-back there would risk a spurious re-login and
    # would report a slow-but-successful change as a failure.
    verify_after_write: bool = False


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
        state_key="ODU_led_switch",
        verify_after_write=True,
        about=(
            "Turns the status light on the outdoor unit on or off. Cosmetic "
            "only - the connection is unaffected, so switching it off is safe "
            "if the unit is visible from a window or a bedroom. The router "
            "reports the light's real state, so this reflects the unit rather "
            "than the last command sent."
        ),
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
        state_key="data_volume_limit_switch",
        verify_after_write=True,
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
        # Last position the router actually reported. Held so a poll that omits
        # the key does not read as a confident "off" — see `_remember_position`.
        self._last_known = False
        self._remember_position()

    def _remember_position(self) -> None:
        """Latch the position, but only from a payload that reported it.

        A missing key used to evaluate to `False`, so any response without it —
        a dead session answering blanks, a degraded fetch — displayed a
        confident "off" the router had never reported, and the switch appeared
        to move on its own. Holding the last real reading is the honest answer:
        it is what we last knew, and it avoids inventing a position. A key that
        is genuinely gone is an availability problem, and `available` already
        covers that.
        """
        data = self.coordinator.data
        value_fn = self.entity_description.value_fn
        if data is None or value_fn is None:
            return
        state_key = self.entity_description.state_key
        if state_key is not None and state_key not in data:
            return
        self._last_known = value_fn(data)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Latch the new position before publishing it."""
        self._remember_position()
        super()._handle_coordinator_update()

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
        """Return the last position the router reported."""
        return self._last_known

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

        if self.entity_description.verify_after_write:
            await self._async_confirm(state)
        await self.coordinator.async_force_refresh()

    async def _async_confirm(self, state: bool) -> None:
        """Read the setting straight back, so the UI need not wait for a poll.

        The coordinator's refresh is debounced with a ten-second cooldown, so a
        write landing inside that window did not reach the state machine for up
        to ten seconds — long enough for the frontend's optimistic toggle to
        revert first, which is what made this switch look erratic. Confirming
        directly costs ~16 ms and reports the router's own value rather than
        assuming the command took.

        A read that *fails* leaves the write unverified, not failed: the
        command may well have landed, and the next poll will settle it. Only a
        successful read reporting the wrong value proves a refusal.
        """
        state_key = self.entity_description.state_key
        value_fn = self.entity_description.value_fn
        if state_key is None or value_fn is None:
            return

        for attempt in range(2):
            if attempt:
                # Only ever reached when the first read disagreed. The MC7010
                # applies before it answers the write, so the fast path never
                # pays this.
                await asyncio.sleep(WRITE_VERIFY_RETRY_DELAY)
            try:
                data = await self.coordinator.api.get_params(
                    [state_key], timeout_sec=WRITE_VERIFY_TIMEOUT
                )
            except Exception as err:  # noqa: BLE001 - unverified, not failed
                _LOGGER.debug(
                    "%s: Could not confirm %s, leaving it to the next poll: %s",
                    self._entry.title,
                    self.entity_description.key,
                    err,
                )
                return
            if state_key not in data:
                return
            if value_fn(data) is state:
                self._last_known = state
                self.async_write_ha_state()
                return

        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="switch_write_not_applied",
            translation_placeholders={"entity": self.entity_description.key},
        )

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
        # No `_attr_is_on`: `is_on` is a property reading `entry.options`, which
        # shadows the attribute entirely. Assigning it looked like it seeded the
        # initial state and never did. `initial_state` is read by the caller
        # from the same options, so the position is correct from construction.
        del initial_state

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
