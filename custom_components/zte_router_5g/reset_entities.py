"""The `reset_entities` administrative action.

A user exploring an integration enables everything to see what is there, and
then has to click through dozens of entities to get back to a useful set —
or delete and re-add the config entry, which destroys custom names, dashboard
bindings and long-term statistics. This is the bulk operation that avoids
both.

Five things it can do, in this order when several are asked for:

1. A baseline — either `reset_to_default`, the per-model default that platform
   setup itself resolves, or `restore_snapshot`, a set the user saved earlier.
2. `enable_populated`, turning on whatever this router actually reports.
3. `disable_unavailable` and `disable_unknown`, turning off what it does not.

`exclude_entities` and `preserve_user_customized` then filter the result, so a
specific instruction always beats the baseline.

**`reset_to_default` resolves through `entity_defaults.default_enabled`**, the
same function each platform calls when it builds an entity. Two readers of
different sources would disagree, and a reset would undo the model overlay
every time it ran. It is also the only way an overlay reaches an installation
that already exists, because Home Assistant reads
`entity_registry_enabled_default` once, at first registration, and never
again.

**Nothing is written unless `dry_run` is false**, and `dry_run` defaults to
true. The response says what would change either way, which makes the dry run
the way to build an `exclude_entities` list: run it, read `changes.to_disable`,
and carry the handful worth keeping into the real call.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .entity_defaults import default_enabled
from .observations import entity_keys_with_values

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import ZTERouterDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# States that mean "this entity has nothing to say right now".
_UNAVAILABLE: Final = "unavailable"
_UNKNOWN: Final = "unknown"

# The operations that change something, for the rule that a snapshot may not
# be captured in the same call.
_MUTATIONS: Final = (
    "reset_to_default",
    "enable_populated",
    "disable_unavailable",
    "disable_unknown",
    "restore_snapshot",
)


def _guard_combinations(data: dict[str, Any]) -> None:
    """Refuse combinations that have no single sensible meaning.

    Refused rather than resolved by precedence: silently preferring one of two
    baselines would make the same call mean different things on different
    installations, which is worse than an error a user reads once.
    """
    if data["reset_to_default"] and data["restore_snapshot"]:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="reset_two_baselines",
        )
    if data["save_snapshot"] and any(data[name] for name in _MUTATIONS):
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="reset_snapshot_with_changes",
        )


def _entity_key(entry: er.RegistryEntry, prefix: str) -> str:
    """Return the entity description key behind a registry entry.

    Entity unique ids are built as `f"{entry.unique_id}_{description.key}"`,
    where the config entry's unique id is the router IMEI or its host address.
    Both can contain underscores, so the prefix is removed by length rather
    than by splitting on the first separator.
    """
    unique = entry.unique_id or ""
    head = f"{prefix}_"
    return unique[len(head) :] if unique.startswith(head) else ""


class _Planner:
    """Works out what should change, without changing anything."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ZTERouterDataUpdateCoordinator,
        entries: list[er.RegistryEntry],
        data: dict[str, Any],
    ) -> None:
        """Hold the inputs a plan is built from."""
        self._hass = hass
        self._coordinator = coordinator
        self._entries = entries
        self._data = data
        self._prefix = coordinator.entry.unique_id or ""
        self._snapshot = coordinator.observations.snapshot()
        self._reporting = entity_keys_with_values(coordinator.data or {})

    def _wanted(self, entry: er.RegistryEntry, key: str) -> bool | None:
        """Return the state this entry should end in, or None to leave it."""
        wanted: bool | None = None

        if self._data["restore_snapshot"]:
            # A snapshot names only the entities that existed when it was
            # taken. Anything added since falls through to the resolved
            # default, so an upgrade still delivers new entities.
            if key in self._snapshot:
                wanted = self._snapshot[key]
        elif self._data["reset_to_default"]:
            wanted = default_enabled(_DESCRIPTIONS[key], self._coordinator.model)

        # Reporting a value *now*, not ever: this operation means "show me
        # what my router actually serves". It uses the same rule the populated
        # record is built with, so the two cannot drift apart.
        if self._data["enable_populated"] and key in self._reporting:
            wanted = True

        state = self._hass.states.get(entry.entity_id)
        if state is not None:
            if self._data["disable_unavailable"] and state.state == _UNAVAILABLE:
                wanted = self._maybe_disable(key, wanted)
            if self._data["disable_unknown"] and state.state == _UNKNOWN:
                wanted = self._maybe_disable(key, wanted)

        return wanted

    def _maybe_disable(self, key: str, wanted: bool | None) -> bool | None:
        """Disable a blank entity unless it has reported a value before.

        The default protects a value that is only temporarily missing — 5G
        sensors while the router is on LTE, secondary-carrier sensors while
        aggregation is inactive. `include_ever_populated` turns that guard off.
        """
        if self._data["include_ever_populated"]:
            return False
        if key in self._coordinator.observations.ever_populated():
            return wanted
        return False

    def plan(self) -> tuple[list[dict[str, str]], list[dict[str, str]], int]:
        """Return the entities to enable, the ones to disable, and the rest."""
        to_enable: list[dict[str, str]] = []
        to_disable: list[dict[str, str]] = []
        excluded = set(self._data["exclude_entities"])

        for entry in self._entries:
            if entry.entity_id in excluded:
                continue
            # An entity the user turned off stays off. There is no matching
            # signal for one they turned on: the registry has no `enabled_by`,
            # and Home Assistant enables every entity at once in one gesture,
            # so "chosen" and "explored" are indistinguishable there.
            if (
                self._data["preserve_user_customized"]
                and entry.disabled_by is er.RegistryEntryDisabler.USER
            ):
                continue

            key = _entity_key(entry, self._prefix)
            if _DESCRIPTIONS.get(key) is None:
                continue
            wanted = self._wanted(entry, key)
            if wanted is None or wanted == (entry.disabled_by is None):
                continue

            row = {
                "entity_id": entry.entity_id,
                "name": entry.name or entry.original_name or "",
            }
            (to_enable if wanted else to_disable).append(row)

        unchanged = len(self._entries) - len(to_enable) - len(to_disable)
        return to_enable, to_disable, unchanged


# Every entity description this integration ships, by key. Built lazily
# because the platform modules import the coordinator.
_DESCRIPTIONS: dict[str, Any] = {}


def _load_descriptions() -> None:
    """Fill the description lookup on first use."""
    if _DESCRIPTIONS:
        return
    from .binary_sensor import BINARY_SENSORS
    from .number import POLLING_INTERVAL_DESCRIPTION
    from .select import SELECT_TYPES
    from .sensor import SENSOR_TYPES
    from .switch import SWITCH_TYPES

    for descriptions in (
        SENSOR_TYPES,
        BINARY_SENSORS,
        SWITCH_TYPES,
        SELECT_TYPES,
        (POLLING_INTERVAL_DESCRIPTION,),
    ):
        for description in descriptions:
            _DESCRIPTIONS[description.key] = description


async def async_reset_entities(
    hass: HomeAssistant,
    coordinator: ZTERouterDataUpdateCoordinator,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Plan and optionally apply a bulk change to entity enabled states."""
    _load_descriptions()
    _guard_combinations(data)

    # Refuse to act on a coordinator that is not talking to the router. Every
    # state-driven operation reads what entities are reporting right now, and
    # during an outage that is nothing at all — a run then disables almost
    # everything, and the dry run that preceded it looked the same.
    if not coordinator.last_update_success:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="reset_coordinator_unavailable",
        )

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, coordinator.entry.entry_id)

    if data["save_snapshot"]:
        return await _save(coordinator, entries, dry_run=data["dry_run"])

    if data["restore_snapshot"] and not coordinator.observations.snapshot():
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="reset_no_snapshot",
        )

    to_enable, to_disable, unchanged = _Planner(hass, coordinator, entries, data).plan()

    if not data["dry_run"] and (to_enable or to_disable):
        for row in to_enable:
            registry.async_update_entity(row["entity_id"], disabled_by=None)
        for row in to_disable:
            registry.async_update_entity(
                row["entity_id"], disabled_by=er.RegistryEntryDisabler.USER
            )
        await hass.config_entries.async_reload(coordinator.entry.entry_id)

    return {
        "dry_run": data["dry_run"],
        "summary": {
            "total_evaluated": len(entries),
            "to_enable": len(to_enable),
            "to_disable": len(to_disable),
            "unchanged": unchanged,
        },
        "changes": {"to_enable": to_enable, "to_disable": to_disable},
        "populated_history": coordinator.observations.populated_history(),
    }


async def _save(
    coordinator: ZTERouterDataUpdateCoordinator,
    entries: list[er.RegistryEntry],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Record the current enabled state of every entity as a baseline."""
    captured = {
        key: not entry.disabled_by
        for entry in entries
        if (key := _entity_key(entry, coordinator.entry.unique_id or ""))
        in _DESCRIPTIONS
    }
    if not dry_run:
        await coordinator.observations.async_save_snapshot(captured)

    enabled = sum(1 for on in captured.values() if on)
    return {
        "dry_run": dry_run,
        "summary": {
            "total_evaluated": len(entries),
            "to_enable": 0,
            "to_disable": 0,
            "unchanged": len(entries),
        },
        "changes": {"to_enable": [], "to_disable": []},
        "populated_history": coordinator.observations.populated_history(),
        # Reported so a snapshot taken mid-exploration is visible as one. A
        # baseline holding nearly every entity restores nearly every entity,
        # which is rarely what its author meant.
        "snapshot": {"entities": len(captured), "enabled": enabled},
    }
