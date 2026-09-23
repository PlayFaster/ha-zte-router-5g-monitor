"""Switch platform for ZTE Router 5G."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
import logging
from typing import Any, Final, cast

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ZTERouterExpectedUnavailableError
from .const import (
    CONF_STOP_POLLING,
    DATA_CONNECT_FOLLOWUP_SECONDS,
    DOMAIN,
    OUTAGE_CAP_DATA_DISCONNECT,
    OUTAGE_REASON_DATA_DISCONNECT,
    WRITE_VERIFY_RETRY_DELAY,
    WRITE_VERIFY_TIMEOUT,
)
from .coordinator import ZTERouterDataUpdateCoordinator
from .entity_defaults import default_enabled
from .helpers import ZTEAboutEntity, ZTEDeviceEntity, expected_outage_error, get_first

_LOGGER = logging.getLogger(__name__)

# Writes are serialised. `0` (unlimited) is right for the read-only platforms,
# where the coordinator does the fetching and there is nothing to serialise, but
# on a platform that commands the device it means an unbounded number of
# concurrent `goform` POSTs — and this router permits a single session, so
# overlapping writes are exactly how a session gets torn down. Rapid toggling
# now queues instead of racing.
PARALLEL_UPDATES = 1


# The MC888 Pro answers `flux_data_volume_limit_switch` and leaves the bare
# spelling empty. The bare spelling leads because the reference MC7010 answers
# on it; order is the tie-break, see `helpers.get_first`.
_ALIAS_LIMIT_SWITCH: Final = (
    "data_volume_limit_switch",
    "flux_data_volume_limit_switch",
)


# The `ppp_status` values the router's own web page treats as connected, from
# `checkConnectedStatus` in the MC7010's `js/util.js`. Only `ppp_connected` has
# been observed; the IPv6 forms are the GUI's, taken as given.
_DATA_CONNECTED: Final = frozenset(
    {"ppp_connected", "ipv6_connected", "ipv4_ipv6_connected"}
)
# The switch shows the direction the router is heading, not only a finished
# connection. `ppp_connecting` reads as on, as `ppp_disconnecting` already
# reads as off. Counting only the connected values made the refresh that runs
# straight after turning on read `ppp_connecting` as off, and the switch
# sprang back until the next poll; found on the MC7010 on 2026-09-23. Data
# Connection Status still shows the exact state, so a router stuck
# connecting is visible there.
_DATA_ON: Final = _DATA_CONNECTED | {"ppp_connecting"}


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
    # Alternate spellings of `state_key` on other firmware, in the same
    # leader-first order the sensor aliases use. The MC888 Pro answers
    # `flux_data_volume_limit_switch` and leaves the bare spelling empty, so a
    # switch reading only `state_key` there has no position to report and its
    # write cannot be verified.
    state_aliases: tuple[str, ...] = ()

    @property
    def state_keys(self) -> tuple[str, ...]:
        """Every spelling this switch's position may arrive under."""
        return ((self.state_key,) if self.state_key else ()) + self.state_aliases

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
        state_aliases=("flux_data_volume_limit_switch",),
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
            str(get_first(data, _ALIAS_LIMIT_SWITCH) or "").strip().lower()
            in ("1", "on", "true")
            if data
            else False
        ),
        setter_fn=lambda api, state, data: api.set_data_limit_switch(
            "1" if state else "0", data or {}
        ),
    ),
    ZTESwitchEntityDescription(
        key="data_connection",
        state_key="ppp_status",
        # Not verified by the generic read-back: an immediate read shows
        # `ppp_disconnecting`, which that check would report as a refusal.
        # `ZTEDataConnectionSwitch` confirms from the transitional states.
        verify_after_write=False,
        about=(
            "Turns the router's mobile data connection on or off, like the "
            "switch in the router's own web page. Home Assistant keeps reaching "
            "the router over your network while data is off. Turning it off can "
            "take up to a minute, and other controls are refused until it "
            "completes."
        ),
        translation_key="signal_data_connection",
        entity_category=EntityCategory.CONFIG,
        group="signal",
        value_fn=lambda data: data.get("ppp_status") in _DATA_ON if data else False,
        setter_fn=lambda api, state, data: api.set_data_connection(state),
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
            _ENTITY_CLASS.get(description.key, ZTERouterSwitch)(
                coordinator, entry, description
            )
            for description in SWITCH_TYPES
        ]
    )

    async_add_entities(entities)


class ZTERouterSwitch(
    ZTEAboutEntity,
    ZTEDeviceEntity,
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
        self._attr_entity_registry_enabled_default = default_enabled(
            description, coordinator.model
        )
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
        state_keys = self.entity_description.state_keys
        if state_keys and not any(key in data for key in state_keys):
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
        if source is not None and not self.coordinator.endpoint_available(source):
            return False

        # A missing key is not an Off position. Every `value_fn` here resolves
        # an absent value to False, so a router that does not have the setting
        # — the MC888 Pro is an indoor unit and answers nothing for
        # `ODU_led_switch` — gets a control showing a position it was never
        # told. Sensors already treat present-but-empty as absent and return
        # None; switches were the one platform rendering it as a state, which
        # invites a write composed from a reading that does not exist.
        keys = self.entity_description.state_keys
        if not keys:
            return True
        data = self.coordinator.data or {}
        return any(data.get(name) not in (None, "") for name in keys)

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
        setter = self.entity_description.setter_fn
        if setter is None:
            return
        await self._async_write(setter, state)
        await self._async_after_write(state)

    async def _async_write(
        self,
        setter: Callable[[Any, bool, Any], Coroutine[Any, Any, None]],
        state: bool,
    ) -> None:
        """Send the new state, mapping a failure to an error the user sees."""
        try:
            await setter(self.coordinator.api, state, self.coordinator.data)
        except Exception as err:
            if isinstance(err, ZTERouterExpectedUnavailableError):
                raise expected_outage_error(err) from err
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

    async def _async_after_write(self, state: bool) -> None:
        """Confirm the write where configured, then refresh."""
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
        state_keys = self.entity_description.state_keys
        value_fn = self.entity_description.value_fn
        if not state_keys or value_fn is None:
            return

        for attempt in range(2):
            if attempt:
                # Only ever reached when the first read disagreed. The MC7010
                # applies before it answers the write, so the fast path never
                # pays this.
                await asyncio.sleep(WRITE_VERIFY_RETRY_DELAY)
            try:
                data = await self.coordinator.api.get_params(
                    list(state_keys), timeout_sec=WRITE_VERIFY_TIMEOUT
                )
            except Exception as err:  # noqa: BLE001 - unverified, not failed
                _LOGGER.debug(
                    "%s: Could not confirm %s, leaving it to the next poll: %s",
                    self._entry.title,
                    self.entity_description.key,
                    err,
                )
                return
            if not any(key in data for key in state_keys):
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


class ZTEDataConnectionSwitch(ZTERouterSwitch):
    """The router's data connection, confirmed from its transitional state.

    The router answers the command before the change completes, and a
    disconnect then takes it offline. Measured on the MC7010 on 2026-09-23,
    twice: `ppp_disconnecting` was readable for about a second after the
    reply, then the router stopped answering for between 17 and 36 s.
    Reconnecting reached `ppp_connected` within a second, with no silence.
    """

    async def _async_after_write(self, state: bool) -> None:
        """Read the state once, at once, then open the outage window on turn-off.

        The read is taken before the window opens, so the gate does not refuse
        it. A read that fails, or reports neither the requested state nor its
        transitional form, leaves the write unconfirmed rather than failed: the
        router accepted the command, and the next poll settles the position.
        """
        status = await self._read_status()
        confirming = _DATA_ON if state else {"ppp_disconnecting", "ppp_disconnected"}
        if status in confirming:
            self._last_known = state
            self.async_write_ha_state()
        else:
            _LOGGER.debug(
                "%s: Data connection change not yet confirmed (ppp_status=%s)",
                self._entry.title,
                status,
            )
        if not state:
            self.coordinator.async_open_expected_outage(
                OUTAGE_REASON_DATA_DISCONNECT, OUTAGE_CAP_DATA_DISCONNECT
            )
            return
        await self.coordinator.async_force_refresh()
        refreshed = (self.coordinator.data or {}).get("ppp_status")
        if status in _DATA_CONNECTED or refreshed in _DATA_CONNECTED:
            return
        # Neither read saw a finished connection. One more refresh settles it
        # rather than leaving the switch to the next scheduled poll.
        self.async_on_remove(
            async_call_later(
                self.hass, DATA_CONNECT_FOLLOWUP_SECONDS, self._async_followup
            )
        )

    async def _async_followup(self, _now: Any) -> None:
        """The one refresh after turning on, when the first did not settle it."""
        await self.coordinator.async_force_refresh()

    async def _read_status(self) -> str | None:
        """Read `ppp_status`, or `None` if the router did not answer it."""
        try:
            data = await self.coordinator.api.get_params(
                ["ppp_status"], timeout_sec=WRITE_VERIFY_TIMEOUT
            )
        except Exception as err:  # noqa: BLE001 - unconfirmed, not failed
            _LOGGER.debug(
                "%s: Could not read the data connection state: %s",
                self._entry.title,
                err,
            )
            return None
        value = data.get("ppp_status")
        return value if isinstance(value, str) else None


# Switches whose behavior after a write differs from the generic entity.
_ENTITY_CLASS: Final[dict[str, type[ZTERouterSwitch]]] = {
    "data_connection": ZTEDataConnectionSwitch,
}


class ZTEPausePollingSwitch(
    ZTEAboutEntity,
    ZTEDeviceEntity,
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
