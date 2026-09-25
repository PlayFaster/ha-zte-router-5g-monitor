"""Which names each poll asks the router for (3.4.4-dev2).

Every poll used to ask for every spelling of every value, so each spelling
added for another model cost every model on every poll. The plan below asks,
on most polls, only for:

- names read outside an entity (`ALWAYS_POLLED`): session checks, the uptime
  latch, change history, the write paths;
- names that have answered on this firmware;
- a rotating fifth of the names that have never answered, where the entity
  reading them has not found its value under another spelling.

A **full poll** asks for everything, and runs on the first poll with nothing
learned, every 30th poll, at least daily, on Refresh Now, before a diagnostics
download, and after a reboot, a firmware change or the data connection
returning. A name no entity was seen to read is polled every time: the plan
drops only what it can attribute to a reader.

**Blank is not absence.** This API answers `""` both for a name it does not
know and for a known name with no value now, so a name that answered once is
kept even while blank: a 5G value must be read on the first poll after 5G
returns. Plan: `.notes/issues/plans_status/v344_plan.md` §9.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
import re
from typing import Any, Final

# Names read outside any entity description, by module. Kept literal, not
# computed, so a new reader is a deliberate edit;
# `test_every_internal_read_is_always_polled` scans those modules and fails on
# a name missing here.
ALWAYS_POLLED: Final[frozenset[str]] = frozenset(
    {
        # Contract, session sentinels and the uptime latch (api, coordinator,
        # const).
        "network_type",
        "strBearer",
        "signalbar",
        "system_uptime",
        "realtime_time",
        "flux_realtime_time",
        "flux_system_uptime",
        "wan_connect_status",
        "ppp_status",
        "dial_mode",
        "modem_main_state",
        # Identity and outage checks.
        "imei",
        "wa_inner_version",
        "model_name",
        "opms_wan_mode",
        "opms_wan_auto_mode",
        # Change history (observations).
        "cell_id",
        "network_cell_id",
        "network_provider",
        "strFullName",
        "strShortName",
        "wan_apn",
        "wan_apn_ui",
        "wan_ipaddr",
        # Write paths that read the current form (api): APN and data limit.
        "apn_index",
        "apn_mode",
        "ODU_led_switch",
        "data_volume_alert_percent",
        "data_volume_clear_date",
        "data_volume_clear_day",
        "data_volume_limit_size",
        "data_volume_limit_switch",
        "data_volume_limit_unit",
        "flux_auto_clear_flow_data_switch",
        "flux_clear_date",
        "flux_data_volume_alert_percent",
        "flux_data_volume_limit_size",
        "flux_data_volume_limit_switch",
        "flux_data_volume_limit_unit",
        "traffic_clear_date",
        "wan_auto_clear_flow_data_switch",
        # SMS counters: send classification, storage full, and the message
        # total's attributes.
        "sms_nv_total",
        "sms_nv_rev_total",
        "sms_nv_send_total",
        "sms_nv_draftbox_total",
        "sms_sim_total",
        "sms_sim_rev_total",
        "sms_sim_send_total",
        "sms_sim_draftbox_total",
        # Time-server attributes on the SNTP sensor.
        "sntp_dst_enable",
        "sntp_server1",
        "sntp_server2",
        # Read by binary sensors built as classes, outside a description.
        "alg_sip_enable",
        "reboot_dod",
        "reboot_dow",
        "reboot_hour1",
        "reboot_hour2",
        "reboot_min1",
        "reboot_min2",
        "reboot_schedule_enable",
        "reboot_schedule_mode",
        "upnpEnabled",
        "wan_lte_ca",
        "web_sleep_switch",
        "web_wake_switch",
    }
)

# Always polled by prefix: the APN profile slots the APN writes and selects
# read by index.
ALWAYS_POLLED_PREFIXES: Final[tuple[str, ...]] = ("APN_config",)

FULL_POLL_EVERY: Final = 30
FULL_POLL_MAX_AGE: Final = timedelta(hours=24)
ROTATION: Final = 5

# `network_type` spellings, measured across the downloads held on 2026-09-25:
# `ENDC` (MC7010) and `EN-DC` (MC888 Pro) with a 5G leg, `LTE-NSA` with none.
# `LTE-NSA` carries "NSA" in its name and is LTE; any value not listed counts
# as possibly 5G, so an unseen SA spelling opens the 5G names.
_5G_MODES: Final = frozenset({"ENDC", "EN-DC"})
_LTE_MODES: Final = frozenset({"LTE-NSA", "LTE", ""})
_5G_NAME: Final = re.compile(r"^(?:network_)?(?:5g_|z5g_|Z5g_|nr5g_|nr_|Nr_)")


def is_5g_name(name: str) -> bool:
    """Whether a name belongs to one of the 5G prefix families."""
    return bool(_5G_NAME.match(name))


def is_5g_mode(network_type: Any) -> bool:
    """Whether `network_type` says a 5G leg may be attached."""
    value = str(network_type or "").strip()
    if value in _5G_MODES:
        return True
    return value not in _LTE_MODES


class RecordingDict(dict[str, Any]):
    """A payload that records every key read from it.

    Run against the real payload it returns real values; run against an empty
    one every lookup misses, so `get_first` walks a whole alias tuple and every
    unconditional read is seen.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Start with no reads."""
        super().__init__(*args, **kwargs)
        self.reads: set[str] = set()

    def __getitem__(self, key: str) -> Any:
        """Record, then read."""
        self.reads.add(key)
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        """Record, then read."""
        self.reads.add(key)
        return super().get(key, default)

    def __contains__(self, key: object) -> bool:
        """Record, then test."""
        if isinstance(key, str):
            self.reads.add(key)
        return super().__contains__(key)


def _call(fn: Callable[[Any], Any], payload: RecordingDict) -> Any:
    """Run an entity's reader; a reader that raises reads nothing more.

    Its reads before the fault are still recorded, and an entity that cannot
    read accepts no value.
    """
    try:
        return fn(payload)
    except Exception:  # noqa: BLE001 - any reader fault; the entity handles its own
        return None


def _blank(value: Any) -> bool:
    return value in (None, "")


def _always(name: str) -> bool:
    return name in ALWAYS_POLLED or name.startswith(ALWAYS_POLLED_PREFIXES)


# An entity's readers: (unique_id, callables taking the payload).
Reader = tuple[str, tuple[Callable[[Any], Any], ...]]


class PollPlan:
    """The names to ask for, and what each poll taught."""

    def __init__(self, universe: Iterable[str]) -> None:
        """Hold the full name list and start with nothing learned."""
        self.universe: tuple[str, ...] = tuple(dict.fromkeys(universe))
        self.answered: set[str] = set()
        self.readers: dict[str, set[str]] = {}
        self.consumers: dict[str, set[str]] = {}
        self.disabled: set[str] = set()
        self.polls = 0
        self.full_reasons: set[str] = {"first poll"}
        self.sweep_5g = False
        self.last_full: datetime | None = None
        self.last_kind = ""
        self.last_requested = 0
        self._last_5g: bool | None = None

    # -- what to ask -------------------------------------------------------

    def request_full(self, reason: str) -> None:
        """Owe a full poll, cleared only when one succeeds."""
        self.full_reasons.add(reason)

    def _full_due(self, now: datetime) -> bool:
        if self.full_reasons:
            return True
        if self.last_full is None:
            # The daily clock starts at the first poll; a restart that loaded
            # stored names does not owe a full poll for having restarted.
            self.last_full = now
        if self.polls and self.polls % FULL_POLL_EVERY == 0:
            return True
        return now - self.last_full >= FULL_POLL_MAX_AGE

    def _live_consumers(self, name: str) -> set[str] | None:
        """Enabled readers of a name; None where no entity was seen to read it."""
        consumers = self.consumers.get(name)
        if not consumers:
            return None
        return consumers - self.disabled

    def _resolved(self, entity: str) -> bool:
        return bool(self.readers.get(entity, set()) & self.answered)

    def names(self, now: datetime) -> tuple[frozenset[str] | None, bool]:
        """The names for the next poll, and whether it is a full poll.

        `None` means everything. A full poll still skips names only disabled
        entities read.
        """
        full = self._full_due(now)
        keep: list[str] = []
        unresolved: list[str] = []
        for name in self.universe:
            if _always(name):
                keep.append(name)
                continue
            live = self._live_consumers(name)
            if live is None:
                keep.append(name)
                continue
            if not live:
                continue
            if full or name in self.answered:
                keep.append(name)
                continue
            if all(self._resolved(entity) for entity in live):
                continue
            if self.sweep_5g and is_5g_name(name):
                keep.append(name)
                continue
            unresolved.append(name)
        slot = self.polls % ROTATION
        keep += [n for i, n in enumerate(unresolved) if i % ROTATION == slot]
        return frozenset(keep), full

    # -- what a poll taught ------------------------------------------------

    def learn_readers(self, readers: Iterable[Reader], data: dict[str, Any]) -> None:
        """Record which names each entity reads, empty and against real data."""
        universe = set(self.universe)
        for entity, fns in readers:
            reads = self.readers.setdefault(entity, set())
            for payload in (RecordingDict(), RecordingDict(data)):
                for fn in fns:
                    _call(fn, payload)
                reads |= payload.reads & universe
            for name in reads:
                self.consumers.setdefault(name, set()).add(entity)

    def learn_answers(self, readers: Iterable[Reader], data: dict[str, Any]) -> bool:
        """Mark names that answered with a value their entity accepts.

        A name read by no entity counts on any non-blank value. Returns whether
        anything new was learned, which is when the store is written.
        """
        before = len(self.answered)
        accepted: set[str] = set()
        for _entity, fns in readers:
            payload = RecordingDict(data)
            values = [_call(fn, payload) for fn in fns]
            if any(v is not None and v is not False for v in values):
                accepted |= {n for n in payload.reads if not _blank(data.get(n))}
        for name in self.universe:
            if _blank(data.get(name)):
                continue
            if name in accepted or name not in self.consumers:
                self.answered.add(name)
        return len(self.answered) > before

    def after_poll(
        self, data: dict[str, Any], *, full: bool, fresh: bool, now: datetime
    ) -> None:
        """Advance the counters; a full poll counts only on a fresh answer."""
        self.polls += 1
        self.last_kind = "full" if full else "narrowed"
        if full and fresh:
            self.full_reasons.clear()
            self.last_full = now
        self.sweep_5g = False
        is_5g = is_5g_mode(data.get("network_type"))
        if self._last_5g is False and is_5g:
            self.sweep_5g = True
        self._last_5g = is_5g

    def load(self, stored: dict[str, Any]) -> str:
        """Take the stored answered names at startup; returns their firmware.

        Loaded before the first poll so that poll is already narrowed; the
        firmware is not known until it answers, and the coordinator discards
        the names and owes a full poll if it differs.
        """
        answered = stored.get("answered")
        firmware = stored.get("firmware")
        if isinstance(answered, list) and isinstance(firmware, str) and firmware:
            self.answered = {n for n in answered if isinstance(n, str)}
            self.full_reasons.discard("first poll")
            return firmware
        return ""

    def to_store(self, firmware: str) -> dict[str, Any]:
        """The record written when something new answers."""
        return {"firmware": firmware, "answered": sorted(self.answered)}

    def summary(self) -> dict[str, Any]:
        """What a diagnostics download publishes."""
        unresolved = [
            n
            for n in self.universe
            if not _always(n) and n not in self.answered and self._live_consumers(n)
        ]
        return {
            "last_kind": self.last_kind,
            "last_requested": self.last_requested,
            "universe": len(self.universe),
            "always_polled": sum(1 for n in self.universe if _always(n)),
            "answered": len(self.answered),
            "unresolved": len(unresolved),
            "skipped_disabled": sum(
                1 for n in self.universe if self._live_consumers(n) == set()
            ),
            "full_owed": sorted(self.full_reasons),
        }
