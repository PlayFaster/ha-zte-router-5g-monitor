"""What the integration learns from watching successive polls.

Two records, one seam. Both are built after a successful poll, both persist a
small amount of state per device, and both treat an unreadable store as
"nothing learned" rather than as a fault.

**Transition history.** A text entity cannot carry a `state_class`, so it
produces no long-term statistics: when an operator pushes a firmware update or
reassigns a WAN address, the recorder holds what it changed from and when for
ten days and then forgets. Six values are watched for changes and the last
twenty transitions of each are kept.

**The populated set.** Which entities have ever reported a value on this
device. The `reset_entities` action uses it so that disabling everything
currently unavailable does not turn off entities that were populated
yesterday — 5G sensors while attached to LTE, secondary-carrier sensors while
aggregation is inactive. It is only ever added to, so a degraded poll fails to
record rather than wrongly forgetting.

Both stores are keyed by device. One config entry fronts one router here, so
the top level holds a single key, but the shape is shared across projects and
UniFi genuinely monitors several devices behind one entry.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .helpers import get_first

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

HISTORY_STORAGE_VERSION: Final = 1
OBSERVED_STORAGE_VERSION: Final = 1

# Transitions kept per tracked key, oldest discarded first.
#
# The cap is an event count rather than an age, so a slow-moving value keeps
# years of history and a fast-moving one keeps a short rolling window. Both
# are intended: `cell_id` answers "have I been handed between cells recently",
# not "what did this do last year".
HISTORY_CAP: Final = 20

# The values worth remembering the changes of, as router keys.
#
# Each is rare and consequential, and each can change without the user doing
# anything — which is the test. Values that change with the radio (bands, PCI,
# network type) would fill the cap in hours, and values that never change say
# nothing by changing.
#
# `network_provider` and `opms_wan_mode` are additions to the set the
# cross-project item names: an operator reassignment and a bridge/gateway
# reprovisioning both alter how the whole network behaves and leave no other
# trace once the recorder has purged.
TRACKED: Final[dict[str, tuple[str, ...]]] = {
    "wa_inner_version": ("wa_inner_version",),
    "wan_ipaddr": ("wan_ipaddr",),
    "wan_apn": ("wan_apn", "wan_apn_ui"),
    "cell_id": ("cell_id", "network_cell_id"),
    "network_provider": ("network_provider", "strFullName", "strShortName"),
    "opms_wan_mode": ("opms_wan_mode",),
}

# Uptime, for placing a transition against a restart. Read through the alias
# so the MC888 populates it.
_UPTIME_KEYS: Final = ("realtime_time", "flux_realtime_time")


def _uptime(data: dict[str, Any]) -> int | None:
    """Return the router's own uptime counter, or None.

    The counter drifts — 4.34% slow on the reference MC7010 — which makes it a
    poor clock and a reliable reset indicator, and only the second is being
    asked of it here. `None` rather than 0 when the poll carried no uptime: a
    zero would read as "just rebooted", the one wrong answer this can give.
    """
    raw = get_first(data, _UPTIME_KEYS)
    if raw in (None, ""):
        return None
    with contextlib.suppress(ValueError, TypeError):
        return int(float(raw))
    return None


def entity_keys_with_values(data: dict[str, Any]) -> set[str]:
    """Return the keys of every entity that reports a value from this payload.

    Evaluated through each description's own `value_fn` rather than by
    inspecting router keys, so aliases, the composite secondary-carrier fields
    and derived values such as the projection and the eNodeB fallback are all
    covered by the same rule.

    Imported inside the function because the platform modules import the
    coordinator, which imports this one.
    """
    from .binary_sensor import BINARY_SENSORS
    from .select import SELECT_TYPES
    from .sensor import SENSOR_TYPES
    from .switch import SWITCH_TYPES

    found: set[str] = set()
    for descriptions in (SENSOR_TYPES, BINARY_SENSORS, SWITCH_TYPES, SELECT_TYPES):
        for description in descriptions:
            value_fn = getattr(description, "value_fn", None)
            if value_fn is None:
                continue
            # A boolean entity answers `False` for any input, an empty payload
            # included, so calling its value function proves nothing about the
            # router. Nine entities entered this set on the first poll of a
            # device that had said nothing at all. Judge them the way the
            # entity does: by whether a key they read is present, which is the
            # same rule `ZTERouterSwitch.available` applies.
            keys = getattr(description, "state_keys", ())
            if keys and not any(data.get(name) not in (None, "") for name in keys):
                continue
            try:
                value = value_fn(data)
            except Exception:  # noqa: BLE001, S112 - see below
                # Broad and silent. This runs on every successful poll purely
                # to note which entities reported something; a description
                # that raises on an odd payload is the entity's own problem
                # and is surfaced there, and logging it here would repeat the
                # same message every three minutes for as long as it lasts.
                continue
            if value not in (None, ""):
                found.add(description.key)
    return found


class ObservationRecorder:
    """Holds both per-device records and writes them after a poll."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Create the two stores. Neither is read until `async_load`."""
        self._entry = entry
        self._history_store: Store[dict[str, Any]] = Store(
            hass, HISTORY_STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}_history"
        )
        self._observed_store: Store[dict[str, Any]] = Store(
            hass, OBSERVED_STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}_observed"
        )
        self._history: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._observed: dict[str, dict[str, Any]] = {}
        self.device_id: str = f"entry_{entry.entry_id}"

    async def _load_one(
        self, store: Store[dict[str, Any]], label: str
    ) -> dict[str, Any]:
        """Read one store, resolving any fault to an empty record.

        Deliberately broad, matching the uptime store: no storage fault may
        fail entry setup, because everything here is advisory.
        """
        try:
            stored = await store.async_load()
        except Exception as err:  # noqa: BLE001 - see docstring
            _LOGGER.debug(
                "%s: %s store unreadable, continuing without it: %s",
                self._entry.title,
                label,
                err,
            )
            return {}
        return stored if isinstance(stored, dict) else {}

    async def async_load(self) -> None:
        """Read both records into memory. Never raises."""
        self._history = await self._load_one(self._history_store, "history")
        self._observed = await self._load_one(self._observed_store, "observed")

    async def async_remove(self) -> None:
        """Delete both files. Called when the config entry is removed."""
        for store in (self._history_store, self._observed_store):
            with contextlib.suppress(Exception):
                await store.async_remove()

    # -- reading ---------------------------------------------------------

    def history(self, key: str) -> list[dict[str, Any]]:
        """Return the recorded transitions for one tracked key, newest last."""
        return list(self._history.get(self.device_id, {}).get(key, []))

    def change_count(self, key: str) -> int:
        """Return how many transitions have been recorded for one key.

        Counted rather than derived from the list, which is capped: the count
        is what feeds the long-term-statistics counter, and it has to keep
        rising after the twentieth entry pushes the first one out.
        """
        record = self._observed.get(self.device_id, {})
        counts = record.get("change_counts", {})
        return int(counts.get(key, 0))

    def ever_populated(self) -> frozenset[str]:
        """Return the entity keys this device has ever reported a value for."""
        record = self._observed.get(self.device_id, {})
        return frozenset(record.get("populated", []))

    def populated_history(self) -> dict[str, Any]:
        """Describe how much the populated record knows, for the reset action.

        An empty record silently disables the protection that action's default
        relies on, so the caller has to be able to say so rather than present
        a filtered list that filtered nothing.
        """
        record = self._observed.get(self.device_id, {})
        return {
            "entities_known_populated": len(record.get("populated", [])),
            "recording_since": record.get("since"),
        }

    def snapshot(self) -> dict[str, bool]:
        """Return the user's saved baseline for this device, or an empty map.

        Empty means no snapshot has been taken, which `reset_entities` reports
        as an error rather than as a run that changed nothing.
        """
        record = self._observed.get(self.device_id, {})
        saved = record.get("snapshot")
        return dict(saved) if isinstance(saved, dict) else {}

    async def async_save_snapshot(self, enabled: dict[str, bool]) -> None:
        """Record the enabled state of every entity as this device's baseline."""
        self._observed.setdefault(self.device_id, {})["snapshot"] = dict(enabled)
        await self.async_save()

    # -- writing ---------------------------------------------------------

    def observe(self, data: dict[str, Any], device_id: str) -> bool:
        """Fold one successful poll into both records.

        Returns whether anything changed, so a caller can skip the write on
        the overwhelming majority of polls where nothing did.
        """
        self.device_id = device_id
        now = datetime.now(UTC).isoformat()
        dirty = self._observe_transitions(data, now)
        return self._observe_populated(data, now) or dirty

    def _observe_transitions(self, data: dict[str, Any], now: str) -> bool:
        """Append a transition for any tracked value that has changed."""
        record = self._history.setdefault(self.device_id, {})
        counts = self._observed.setdefault(self.device_id, {}).setdefault(
            "change_counts", {}
        )
        dirty = False

        for key, aliases in TRACKED.items():
            value = get_first(data, aliases)
            if value in (None, ""):
                continue
            current = str(value)
            entries = record.setdefault(key, [])
            previous = entries[-1]["to"] if entries else None

            # The first reading is not a change. Recorded with `from: None` so
            # the series has a start, but it does not count as a transition —
            # otherwise every fresh install reports one change of everything.
            if entries and previous == current:
                continue

            entries.append(
                {
                    "timestamp": now,
                    "from": previous,
                    "to": current,
                    "uptime_at_change": _uptime(data),
                }
            )
            del entries[:-HISTORY_CAP]
            if previous is not None:
                counts[key] = int(counts.get(key, 0)) + 1
            dirty = True

        return dirty

    def _observe_populated(self, data: dict[str, Any], now: str) -> bool:
        """Add any entity reporting a value to the populated set.

        Monotonic. A degraded endpoint makes its entities return None, and
        removing them here would erase the very knowledge the reset action
        needs to protect them.
        """
        record = self._observed.setdefault(self.device_id, {})
        known = set(record.get("populated", []))
        found = entity_keys_with_values(data)
        if found <= known:
            return False

        record["populated"] = sorted(known | found)
        record.setdefault("since", now)
        return True

    async def async_save(self) -> None:
        """Persist both records. Never raises."""
        for store, payload, label in (
            (self._history_store, self._history, "history"),
            (self._observed_store, self._observed, "observed"),
        ):
            try:
                await store.async_save(payload)
            except Exception as err:  # noqa: BLE001 - advisory, never fatal
                _LOGGER.debug(
                    "%s: %s store unwritable: %s", self._entry.title, label, err
                )
