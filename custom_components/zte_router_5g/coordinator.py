"""DataUpdateCoordinator for ZTE Router 5G."""

import asyncio
from collections import deque
from collections.abc import Callable, Coroutine
import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import device_profile
from ._compat import device_by_identifier
from .api import (
    POLL_UNIVERSE,
    SMS_STORE_ALL,
    SMS_STORE_SIM,
    ExpectedOutage,
    ZTEAuthError,
    ZTECredentialsError,
    ZTERouterAPI,
)
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_STOP_POLLING,
    CONNECTION_UPTIME_KEYS,
    DATA_CONNECT_FOLLOWUP_SECONDS,
    DATA_CONNECTED_STATES,
    DEVICE_UPTIME_KEYS,
    DISCOVERY_SETTLE_SECONDS,
    DOMAIN,
    FETCH_STRIKE_LIMIT,
    HEALTH_DRIFT_STRIKE_LIMIT,
    OUTAGE_CHECK_INTERVAL,
    OUTAGE_HISTORY_CAP,
    OUTAGE_HOLD,
    OUTAGE_PROBE_FAST,
    OUTAGE_REASON_DATA_CONNECT,
    OUTAGE_REASON_REBOOT,
    OUTAGE_REASONS_DATA,
    REPAIR_AUTH_FAILED,
    REPAIR_CONN_ERROR,
    SPARSE_PAYLOAD_FRACTION,
    SPARSE_PAYLOAD_MIN_HISTORY,
    UNREACHABLE_STRIKE_LIMIT,
)
from .helpers import get_first, get_router_model, sms_instant
from .observations import ObservationRecorder
from .poll_plan import PollPlan, Reader

_LOGGER = logging.getLogger(__name__)

# Minimum drop in the router's uptime counter (seconds) that is treated as a
# genuine reboot. A real reboot resets uptime to ~0, so this margin only serves
# to reject small downward blips from coarse resolution or stale readings.
UPTIME_REBOOT_MARGIN = 30

# The outer limit on how far a counter may run from wall-clock time and still be
# believable. **This is not the device's drift rate** — that is measured per
# installation (see `_drift_rate`). This bound is used in exactly two places:
# clamping the measured rate, and the cold-start check in
# `_cold_start_implausible` where nothing has been measured yet.
#
# Set wide deliberately. A healthy anchor yields a counter/elapsed ratio between
# 0.8 and 1.0 for any believable counter; the MC7010 measured here sits at
# 0.957. A stale anchor yields a ratio near zero, because a reboot resets the
# counter while elapsed-since-anchor does not. The two populations are an order
# of magnitude apart, so headroom costs nothing and precision buys nothing.
MAX_DRIFT = 0.20

# Below this year the system clock is treated as unset rather than wrong. A
# host without a battery-backed real-time clock, including most Raspberry Pi
# units, starts at 1970-01-01 and stays there until NTP completes; re-latching
# in that window writes a boot instant decades adrift. **Do not delete this as
# an arbitrary constant** — it exists for that specific startup window.
CLOCK_FLOOR_YEAR = 2024

# An uptime beyond this is rejected as a bad reading rather than believed.
# Ten years, comfortably past any plausible consumer router.
MAX_PLAUSIBLE_UPTIME = 10 * 365 * 24 * 3600

# --- Drift rate estimation -------------------------------------------------
#
# The router's uptime counter does not advance at wall-clock rate. The MC7010
# measured for this work runs ~4.34% slow, so a boot instant derived as
# `now() - counter` walks forward while the router runs: eleven minutes after
# twelve hours of uptime, four and a half hours after four days. The rate is a
# property of the hardware and differs between devices, so it is measured here
# rather than assumed.
#
# Measurement is from consecutive polls and makes no reference to the boot
# anchor, which is what keeps it honest: the anchor is what the rate is used to
# judge, so deriving one from the other would be circular.

# Intervals shorter than this are discarded: the counter arrives as whole
# seconds, so one second of quantization in thirty is 3% of noise.
DRIFT_MIN_INTERVAL = 60

# The rate is not used until this much wall time has accumulated. Below it the
# cold-start path applies. **This is also what prevents a division by zero** on
# a fresh install, where `_drift_sum_wall` is 0 — the check must run before the
# division, not on its result.
DRIFT_MIN_ACCUMULATED = 3600

# The accumulators are capped, then scaled down proportionally when exceeded.
# That preserves the ratio while letting newer evidence move it, so a firmware
# update that fixes the router's timer is followed rather than outvoted by
# history. A judgement, not a measurement.
DRIFT_ACCUMULATOR_CAP = 30 * 24 * 3600

# --- Startup shortfall test ------------------------------------------------
#
# `expected = stored_counter + elapsed * (1 - rate)`, and a live counter below
# that by more than the margin means the router rebooted during the gap.
#
# The margin scales because the error it absorbs scales: the dominant term is
# rate-estimate error multiplied by the gap, which is 43 s over two hours and
# 3000 s over a week. The proportional term is roughly four times the spread
# observed across measured intervals (4.24%-4.73%). The floor covers
# quantization and poll latency on short gaps.
SHORTFALL_MARGIN_FLOOR = 300
SHORTFALL_MARGIN_RATE = 0.02

# How far the observed counter/elapsed ratio may sit from the ratio the
# measured rate predicts before the anchor is judged implausible. Runs on every
# poll and is the backstop against retaining an anchor that has become wrong.
PLAUSIBILITY_TOLERANCE = 0.05

# Storage for the running counter, the write time and the drift accumulators.
# `boot_time` stays in `entry.data`: a boot instant does not go stale, so it
# needs no maintenance, and leaving it there means no migration. The store is
# advisory — where it is absent or unreadable the cold-start path still works.
UPTIME_STORAGE_VERSION = 1
PROFILE_STORAGE_VERSION = 1
UPTIME_WRITE_INTERVAL = timedelta(minutes=20)
UPTIME_SAVE_DELAY = 60


# Optional endpoints that hold their own last-good payload and strike count, so
# one flaky endpoint degrades only its own entities (Section 8, per-endpoint
# resilience). The mandatory `get_all_data` fetch is deliberately absent — its
# failure is a whole-integration failure and belongs on the global path.
ENDPOINT_SMS_CAPACITY = "sms_capacity"
ENDPOINT_SMS_MESSAGES = "sms_messages"
# The second half of the batch poll. Split off because the router bounds a GET
# at ~2048 characters; optional because it carries only diagnostics and
# disabled-by-default entities, so a failure must not blank Signal and Data.
ENDPOINT_EXTENDED = "extended_data"
ENDPOINT_PROVISIONING = "provisioning"

# How often the operator-provisioning probe runs. A refusal replaces the whole
# response, so this read can never share a request with anything else and costs
# one round trip whenever it fires. Gated on elapsed time rather than a poll
# count, following `UPTIME_WRITE_INTERVAL`: a count behaves differently for
# every user, since twenty polls is ten minutes at a 30-second interval and
# over five hours at 960.
PROVISIONING_READ_INTERVAL = timedelta(hours=1)

# The key the probe reads. Declined by an operator-supplied MC7010 and answered
# plainly by a self-purchased MC888 Pro, which is the asymmetry the sensor
# reports. Any of the eleven declined names would serve; this one is a plain
# configuration string rather than a credential.
PROVISIONING_PROBE_KEY = "tr069_ServerURL"

# Every repair this integration can raise. The names double as `translation_key`
# values, which stay bare; only the registry **id** carries the entry (see
# `_repair_ids`). Adding one means adding it here, or unload will not clear it.
REPAIR_NAMES = (REPAIR_AUTH_FAILED, REPAIR_CONN_ERROR)

# Repairs this integration used to raise and no longer does. They are kept here
# for one reason: `ir.async_delete_issue` looks up by id, so a card raised under
# a retired name has no code left that can clear it and no UI path out — all
# three were `is_fixable=False`. `clear_legacy_repairs` deletes them at every
# setup, which is what makes retiring them safe.
#
# `router_unreachable` was renamed to `conn_error`; `firmware_contract_drift`
# moved to the Integration Health sensor's `drift` attribute, and
# `sms_storage_full` to a binary sensor. Neither condition is one the user can
# act on in the Repairs panel, which is the test the family policy applies.
# Deleting an entry from this tuple strands any card still live under it.
RETIRED_REPAIR_NAMES = (
    "router_unreachable",
    "firmware_contract_drift",
    "sms_storage_full",
)

# Keys the router is expected to return on every successful poll. Used only for
# the Section 19 contract-drift check: a non-empty response in which none of
# these resolve means the upstream schema changed underneath a "successful"
# fetch — the silent failure HA itself cannot detect.
#
# Every key here must require a session. `wa_inner_version` was removed on
# 2026-07-31: the router answers it without one, so it was populated in every
# response the router could produce, `present` was never empty, the strike
# counter reset on every cycle, and the check could not fire under any
# circumstances — including the firmware change it exists to catch. Adding an
# unauthenticated key here disables this check silently; `_UNAUTHENTICATED_KEYS`
# in `api.py` names the ones known to qualify, and a test enforces the split.
# Flattened from `api._CONTRACT_CONCEPTS`, which is the authority. Mirrored
# rather than imported so the dependency keeps running one way; the two are
# built from the same mapping and `test_contract_keys_agree` fails if they
# diverge. Drift is judged per *concept* — a device spelling one differently
# has not lost it.
CORE_CONCEPTS: dict[str, tuple[str, ...]] = {
    "network_type": ("network_type", "strBearer"),
    "signal_bars": ("signalbar",),
    "uptime": ("system_uptime", "realtime_time", "flux_realtime_time"),
    "connection_state": ("wan_connect_status", "ppp_status"),
}

CORE_KEYS = tuple(key for spellings in CORE_CONCEPTS.values() for key in spellings)

# The single drift finding this integration can report. Section 19 requires the
# `drift` attribute to be a list of findings, so the message lives here rather
# than inline: the health sensor publishes it and the `issues` list repeats it,
# and the two must not be able to drift apart from each other.
DRIFT_CONTRACT = (
    "Router returned data but none of the expected fields were present — "
    "they were reported before and have stopped"
)


# The keys a window record keeps from the poll before it opened and from its
# closing poll: the connection state, the network, and the two modes that
# change how the router connects.
_OUTAGE_SNAPSHOT_KEYS = ("ppp_status", "network_type", "dial_mode", "opms_wan_mode")


def _outage_snapshot(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """The window record's view of one poll, or `None` without one."""
    if not data:
        return None
    return {key: data.get(key) for key in _OUTAGE_SNAPSHOT_KEYS}


def _session_reading(raw: Any) -> bool:
    """Whether a session counter reading is a live session.

    Measured on the MC7010 on 2026-09-23: `realtime_time` reads blank or 0
    while data is off. Read as a counter, 0 latches the connection start at
    the moment data went off, and the climb from 0 after the reconnect is no
    drop, so the anchor stays at the off time.
    """
    seconds = _counter_seconds(raw)
    return seconds is not None and seconds > 0


def _counter_seconds(raw: Any) -> int | None:
    """A counter reading as whole seconds, or `None` if blank or unusable."""
    with contextlib.suppress(ValueError, TypeError):
        if raw not in (None, ""):
            value = int(float(raw))
            return value if value >= 0 else None
    return None


def _data_settled(reason: str, status: object) -> bool:
    """Whether `ppp_status` is the state a data window's command leads to."""
    if reason == OUTAGE_REASON_DATA_CONNECT:
        return status in DATA_CONNECTED_STATES
    return status == "ppp_disconnected"


def _outage_reply(reply: Any) -> dict[str, Any] | None:
    """The router's reply to the command, reduced to its `result` field.

    Every goform write answers `{"result": ...}`. Keeping only that field keeps
    the record free of anything else a firmware might add.
    """
    if isinstance(reply, dict):
        return {"result": reply.get("result")}
    return None


# The counter key `entry.data` held before the counters moved to the store.
# Dropped at the next latch; never read.
LEGACY_COUNTER_KEYS = frozenset({"last_uptime"})


@dataclass
class _UptimeLatch:
    """One counter, its anchor, and everything learned about its rate.

    Ported from the Huawei project in 3.4.2-dev7, where three run. Two run
    here and **nothing is shared between them**: `system_uptime` resets on a
    reboot and `realtime_time` on every data reconnect, so a rate, a stored
    counter or a reconciliation flag borrowed from one would be evidence
    about a different question.

    `pauses` is the property that decides which mechanism applies:

    - `uptime` and `CurrentConnectTime` advance whenever they exist at all.
      A dropped link ends the session and resets `CurrentConnectTime` rather
      than freezing it, so within one session it tracks wall time exactly —
      measured across a real reconnect, 9 s to 216 s over 207 s of wall. Both
      can therefore be asked "did you continue across that gap at wall rate?"
      and both carry the full mechanism.
    - `TotalConnectTime` accumulates across reboots and **stops whenever the
      session is down**. A real reconnect cost it exactly the 2.3 s the link
      was out, and it has lost 3.8 hours to downtime since April
      (`tests/fixtures/huawei_reconnect_trace.json`). Legitimate downtime
      makes it under-run wall time with nothing wrong, so no rate-based
      expectation can be asked of it. It carries the floor rule alone: it
      moves backwards only on a statistics clear.
    """

    label: str
    boot_key: str
    counter_key: str
    pauses: bool = False

    boot_time: datetime | None = None
    last_counter: int | None = None
    last_poll_at: datetime | None = None
    startup_reconciled: bool = False

    stored_counter: int | None = None
    stored_written_at: datetime | None = None
    last_counter_write: datetime | None = None

    drift_sum_wall: float = 0.0
    drift_sum_counter: float = 0.0
    drift_interval_count: int = 0
    drift_rate_min: float | None = None
    drift_rate_max: float | None = None


def _state_keys_reader(keys: tuple[str, ...]) -> Callable[[Any], Any]:
    """A reader over a switch's or binary sensor's `state_keys`."""

    def read(data: Any) -> Any:
        return [data.get(k) for k in keys]

    return read


class ZTERouterDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching ZTE Router data with resilience and pausing."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: ZTERouterAPI
    ) -> None:
        """Initialize the coordinator."""
        self.api = api
        self.entry = entry
        self.consecutive_failures = 0
        # The most keys this entry has ever seen populated, for the sparse
        # payload check. Not persisted: a restart re-learns it on the first
        # poll, which is the conservative direction.
        self._payload_high_water = 0
        # 3.4.4-dev2: which names each poll asks for. A narrowed poll asks for
        # fewer names than a full one, so the sparse check keeps one high-water
        # mark per poll kind and swaps them in `_sparse_payload_finding`.
        self.poll_plan = PollPlan(POLL_UNIVERSE)
        self._poll_kind = "full"
        self._high_water_kind = "full"
        self._high_water_by_kind: dict[str, int] = {}
        self._poll_store: Store[dict[str, Any]] | None = None
        self._poll_firmware = ""
        self._poll_previous: dict[str, Any] = {}
        # Serializes a diagnostics discovery probe against the poll; both use
        # the same API client and the same session.
        self._async_update_lock = asyncio.Lock()
        self.last_update_success_time: datetime | None = None
        # The expected-outage window's timer, and whether the poll now running
        # is the one that decides whether the window closes. See
        # `async_open_expected_outage`.
        self._outage_unsub: CALLBACK_TYPE | None = None
        self._outage_closing = False
        # Whether the open window is still waiting for the router to stop
        # answering, and when it opened on the monotonic clock, for the hold.
        self._outage_awaiting_drop = False
        self._outage_opened_mono = 0.0
        # The follow-up refresh after a data window closes on `ppp_connecting`.
        self._outage_followup_unsub: CALLBACK_TYPE | None = None
        # The most recent windows, oldest first, kept after they close so a
        # diagnostics download can explain a gap in polling and show what the
        # router did around each command.
        self.expected_outages: deque[dict[str, Any]] = deque(maxlen=OUTAGE_HISTORY_CAP)
        self._was_available = True
        self._profile_store: Store[dict[str, Any]] | None = None

        # Reboot-detection latches - frozen timestamps for uptime-derived
        # sensors. Each is recomputed exactly once per genuine counter reset
        # and then held. The structure is the Huawei project's.
        #
        # **Nothing is shared between the two.** Their counters reset on
        # different events, so a rate, a stored counter or a reconciliation
        # flag borrowed from one is evidence about a different question.
        self._system_latch = _UptimeLatch(
            label="System boot time",
            boot_key="boot_time",
            counter_key="last_system_uptime",
        )
        self._conn_latch = _UptimeLatch(
            label="Connection start time",
            boot_key="connection_start",
            counter_key="last_conn_uptime",
        )
        self._latches = (self._system_latch, self._conn_latch)

        # Populated by `async_load_stored_uptime` during setup.
        self._store: Store[dict[str, Any]] | None = None
        # The key the system latch reads, chosen on the first poll that
        # answers one of `DEVICE_UPTIME_KEYS`. See `_device_uptime_raw`.
        self._uptime_source: str | None = None

        # The anchors are restored from `entry.data`, where they have always
        # lived. The counters come from the store, which is written on an
        # interval rather than only at a latch.
        for latch in self._latches:
            with contextlib.suppress(Exception):
                if v := entry.data.get(latch.boot_key):
                    parsed = dt_util.parse_datetime(v)
                    # Naive values raise on subtraction from an aware `now()`.
                    # Treated as absent, which routes to an unconditional
                    # latch.
                    if parsed is not None and parsed.tzinfo is not None:
                        latch.boot_time = parsed
        self._last_provisioning_read: datetime | None = None
        # None until the first successful read, so the sensor reports unknown
        # rather than a confident guess on a device that has never answered.
        self.provisioning_restricted: bool | None = None
        self.last_sms_timestamp: str | None = None
        self.fired_sms_hashes: set[str] = set()

        # One-shot flag set by async_force_refresh so an explicit user action
        # fetches even while polling is paused (Section 13).
        self._force_refresh_once = False

        # Repair ids are scoped to the entry. The issue registry keys on
        # `(domain, issue_id)`, so a bare id gives every config entry the same
        # row — with two routers and one failing, the healthy one's next
        # successful poll deletes the failing one's repair.
        self._repair_ids = {name: f"{entry.entry_id}_{name}" for name in REPAIR_NAMES}

        # Per-endpoint resilience state (Section 8).
        self._endpoint_failures: dict[str, int] = {}
        self._endpoint_cache: dict[str, Any] = {}

        # Section 19 health state. Deliberately NOT stored in `self.data`, which
        # is None before the first success and frozen at last-good values during
        # an outage — a verdict held there could never describe the failure that
        # stopped it being updated.
        self.health_snapshot: dict[str, Any] = {
            "problem": False,
            "issues": [],
            "severity": "ok",
            "degraded_capabilities": [],
            "drift": [],
            "repairs": [],
            "last_good_update": None,
            "consecutive_failures": 0,
        }
        self._drift_baseline: set[str] = set()
        self._drift_strikes = 0
        self._unreachable_repair_raised = False
        self._auth_repair_raised = False

        # Snapshot of the non-live options this entry was set up with; the
        # update listener diffs against it to decide reload vs live-apply.
        self.reload_signature: dict[str, Any] = {}
        # The record of the last delete attempt is restored onto the API
        # object, because it lives in memory there and a reporter's download is
        # routinely taken after a restart. Issue #56 turned on exactly that: the
        # section read `null` and the router's answer to the delete was lost.
        stored_delete = entry.data.get("last_delete")
        if isinstance(stored_delete, dict):
            api.last_delete = dict(stored_delete)

        # `entry.data["last_uptime"]` is deliberately NOT read. It is written
        # only on a latch, so it is frozen at whatever small value the previous
        # reboot recorded, and comparing a live counter against it is the
        # defect this design replaces. The counter comes from the store
        # instead; the legacy key is dropped on the next latch.

        # Load hardware identity from persistent ConfigEntry data.
        # This ensures device info is stable from boot (The "Flat Identity" pattern).
        self.model = entry.data.get("model", "ZTE Router")
        self.observations = ObservationRecorder(hass, entry)
        self.sw_version = entry.data.get("sw_version")
        self.imei = entry.data.get("imei")

        # Determine the initial update interval from entry options
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, 180)

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{entry.title} Data",
            update_interval=timedelta(seconds=scan_interval),
        )

    def clear_legacy_repairs(self) -> None:
        """Delete repairs raised under ids this integration no longer uses.

        `ir.async_delete_issue` looks up by id, so a card still live under an
        id nothing raises any more has no code left that can clear it and no UI
        path either — every retired repair was `is_fixable=False`. Called once
        at setup, so no rename can strand one. Safe to keep indefinitely:
        deleting an issue that does not exist is a no-op.

        Three generations are swept, and each is here because a card could
        survive the change that retired it:

        1. The bare, unscoped names, from before ids carried the entry id.
        2. The retired names under their bare form.
        3. The retired names under the entry-scoped form they were last raised
           with — the generation created by the repair-set alignment, where
           `router_unreachable` became `conn_error` and two others moved off
           the Repairs panel entirely.
        """
        for name in (*REPAIR_NAMES, *RETIRED_REPAIR_NAMES):
            ir.async_delete_issue(self.hass, DOMAIN, name)
        for name in RETIRED_REPAIR_NAMES:
            ir.async_delete_issue(self.hass, DOMAIN, f"{self.entry.entry_id}_{name}")

    def clear_repairs(self) -> None:
        """Clear every repair this entry raised.

        Called on unload **and** on removal. Without it a user who deletes the
        integration while a repair is showing keeps it in the Repairs panel
        permanently: `is_fixable=False`, and the integration that would clear
        it is gone.
        """
        for issue_id in self._repair_ids.values():
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._unreachable_repair_raised = False
        self._auth_repair_raised = False

    def apply_live_options(self) -> None:
        """Apply the options that change without a reload.

        Only the two keys in LIVE_OPTION_KEYS reach here. `stop_polling` needs
        no action — the coordinator re-reads it at the top of every cycle — so
        this exists for the scan interval, which has to be pushed onto the
        scheduler.
        """
        scan_interval = self.entry.options.get(CONF_SCAN_INTERVAL, 180)
        new_interval = timedelta(seconds=int(scan_interval))
        if new_interval != self.update_interval:
            _LOGGER.debug(
                "%s: Applying polling interval %ss without reload.",
                self.entry.title,
                scan_interval,
            )
            self.update_interval = new_interval

    # -- expected-outage window ------------------------------------------

    @property
    def outage_active(self) -> bool:
        """Whether an expected-outage window is open and within its cap."""
        outage = self.api.expected_outage
        return isinstance(outage, ExpectedOutage) and not outage.expired

    @property
    def last_expected_outage(self) -> dict[str, Any] | None:
        """The most recent window's record, or `None` if none has opened."""
        return self.expected_outages[-1] if self.expected_outages else None

    @property
    def outage_reason(self) -> str | None:
        """The reason of the open window, or `None` when none is open."""
        outage = self.api.expected_outage
        if isinstance(outage, ExpectedOutage) and not outage.expired:
            return outage.reason
        return None

    @property
    def outage_closing(self) -> bool:
        """Whether the poll now running is a window's closing poll."""
        return self._outage_closing

    def async_open_expected_outage(
        self,
        reason: str,
        cap_seconds: float,
        *,
        command: str | None = None,
        reply: Any = None,
        ppp_status_after_reply: str | None = None,
    ) -> None:
        """Open the window after the router accepted a command that takes it offline.

        One mechanism for every such command. While open, polls are skipped
        and every other router request is refused at once with a message naming
        the reason. The window closes only when a full poll succeeds, and the
        cap closes it regardless, so a router that never returns is still
        reported.

        The check runs in two phases. A window opened on a command first waits
        for the router to stop answering, probing every `OUTAGE_PROBE_FAST`
        seconds. Measured on the MC7010, the router kept answering for up to
        12 s after `CONNECT_NETWORK`, so a window that closed on the first
        answer closed before the outage began. A router that has not dropped
        within `OUTAGE_HOLD` seconds is taken to have had no outage. Once it
        has dropped, a probe every `OUTAGE_CHECK_INTERVAL` seconds waits for
        its return. The reboot window opens only after `ZTERouterAPI.reboot`
        has seen the router drop, so it starts in the second phase.
        """
        outage = self.api.open_expected_outage(reason, cap_seconds)
        self._cancel_outage_followup()
        self._outage_awaiting_drop = reason != OUTAGE_REASON_REBOOT
        self._outage_opened_mono = monotonic()
        opened = outage.opened_at.isoformat()
        self.expected_outages.append(
            {
                "reason": reason,
                "command": command,
                "reply": _outage_reply(reply),
                "ppp_status_after_reply": ppp_status_after_reply,
                "opened": opened,
                "cap_seconds": cap_seconds,
                "checks": 0,
                "down_at": None if self._outage_awaiting_drop else opened,
                "back_at": None,
                "outage_seconds": None,
                "before": _outage_snapshot(self.data),
                "after": None,
                "closed": None,
                "closed_by": None,
            }
        )
        self._schedule_outage_check()

    def _schedule_outage_check(self) -> None:
        """Arm the next check, replacing any already armed."""
        self._cancel_outage_check()
        interval = (
            OUTAGE_PROBE_FAST if self._outage_awaiting_drop else OUTAGE_CHECK_INTERVAL
        )
        self._outage_unsub = async_call_later(
            self.hass, interval, self._async_outage_check
        )

    def _cancel_outage_check(self) -> None:
        """Disarm the check timer, if armed."""
        if self._outage_unsub is not None:
            self._outage_unsub()
            self._outage_unsub = None

    def _cancel_outage_followup(self) -> None:
        """Disarm the follow-up refresh, if armed."""
        if self._outage_followup_unsub is not None:
            self._outage_followup_unsub()
            self._outage_followup_unsub = None

    async def _async_outage_check(self, _now: datetime | None = None) -> None:
        """Check whether the router has dropped or is back, and close when done."""
        self._outage_unsub = None
        outage = self.api.expected_outage
        if not isinstance(outage, ExpectedOutage):
            return
        if outage.expired:
            self._close_expected_outage("cap")
            await self.async_request_refresh()
            return
        record = self.last_expected_outage
        if record is not None:
            record["checks"] += 1
        answered = await self.api.outage_probe()
        stamp = dt_util.utcnow().isoformat()

        if self._outage_awaiting_drop:
            if not answered:
                self._outage_awaiting_drop = False
                if record is not None:
                    record["down_at"] = stamp
            elif monotonic() - self._outage_opened_mono >= OUTAGE_HOLD:
                if await self._async_closing_poll():
                    self._close_expected_outage("no_outage")
                    return
            self._schedule_outage_check()
            return

        if answered:
            if record is not None and record["back_at"] is None:
                record["back_at"] = stamp
            if await self._async_closing_poll():
                self._close_expected_outage("answer")
                return
        self._schedule_outage_check()

    async def _async_closing_poll(self) -> bool:
        """Run the window's closing poll, and return whether it succeeded."""
        before = self.last_update_success_time
        self._outage_closing = True
        try:
            with self.api.outage_bypass():
                await self.async_refresh()
        finally:
            self._outage_closing = False
        return self.last_update_success_time != before

    def _close_expected_outage(self, closed_by: str) -> None:
        """Close the window, record how it ended, and settle a data window."""
        self._cancel_outage_check()
        outage = self.api.expected_outage
        reason = outage.reason if isinstance(outage, ExpectedOutage) else None
        self.api.close_expected_outage()
        self._outage_awaiting_drop = False
        record = self.last_expected_outage
        if record is None:
            return
        record["closed"] = dt_util.utcnow().isoformat()
        record["closed_by"] = closed_by
        if closed_by != "cap":
            record["after"] = _outage_snapshot(self.data)
        if record["down_at"] and record["back_at"]:
            record["outage_seconds"] = round(
                (
                    datetime.fromisoformat(record["back_at"])
                    - datetime.fromisoformat(record["down_at"])
                ).total_seconds(),
                1,
            )
        # A closing poll can read a state the command does not lead to:
        # `ppp_connecting` after turning on, since connected came up to 15 s
        # after the router answered again, and once `ppp_connected` after
        # turning off. One more refresh settles it; under paused polling
        # nothing else would. Deliberately a refresh and not a condition on
        # closing: a failed turn-on, a redial under `auto_dial` or a change
        # made in the router's own page would then hold every control refused
        # until the cap.
        if (
            closed_by != "cap"
            and reason in OUTAGE_REASONS_DATA
            and not _data_settled(reason, (self.data or {}).get("ppp_status"))
        ):
            self._outage_followup_unsub = async_call_later(
                self.hass, DATA_CONNECT_FOLLOWUP_SECONDS, self._async_outage_followup
            )

    async def _async_outage_followup(self, _now: datetime | None = None) -> None:
        """The one refresh after a data window closed unsettled."""
        self._outage_followup_unsub = None
        await self.async_force_refresh()

    async def async_shutdown(self) -> None:
        """Disarm the outage timers before the coordinator is torn down."""
        self._cancel_outage_check()
        self._cancel_outage_followup()
        await super().async_shutdown()

    async def async_force_refresh(self) -> None:
        """Force an immediate fetch, even while polling is paused.

        Every explicit user action — Refresh Now, a control change, an SMS
        service — must route through here rather than calling
        ``async_request_refresh`` directly, or it is silently swallowed by the
        pause short-circuit exactly when the user most wants a fetch
        (dev_standards Section 13). Scheduled polls still respect the pause.
        """
        self._force_refresh_once = True
        try:
            await self.async_request_refresh()
        except Exception:
            # The flag is consumed at the top of `_async_update_data`, so an
            # update that never runs leaves it set — and the next *scheduled*
            # poll would then fetch despite the pause. Self-correcting after one
            # cycle, but §13's flag lifecycle asks that every path out clears it.
            self._force_refresh_once = False
            raise

    @property
    def endpoint_failures(self) -> dict[str, int]:
        """Return the per-endpoint strike counts, as a copy.

        Read by `diagnostics.py`, which must never be able to mutate coordinator
        state — it is a read path (Section 20).
        """
        return dict(self._endpoint_failures)

    def endpoint_available(self, source: str) -> bool:
        """Return whether an optional endpoint is still serving usable data.

        Entities fed by an optional endpoint consult this in their ``available``
        property, so an endpoint that has exhausted its own strike budget marks
        only its own entities unavailable (Section 8).
        """
        return self._endpoint_failures.get(source, 0) <= FETCH_STRIKE_LIMIT

    async def _fetch_optional(
        self,
        source: str,
        factory: Callable[[], Coroutine[Any, Any, Any]],
        default: Any,
    ) -> Any:
        """Fetch one optional endpoint under its own strike budget.

        Returns the endpoint's last-good payload while it has strikes left, and
        ``default`` once exhausted. ``ZTEAuthError`` is deliberately not caught:
        a rejected session is an integration-wide condition that must reach the
        global handler to drive reauth, not be absorbed by one endpoint.
        """
        try:
            result = await factory()
        except ZTEAuthError:
            raise
        except Exception as err:  # noqa: BLE001 - containment is the point here
            # Deliberately broad: Section 8 requires a *changed or unexpected*
            # response to degrade this one endpoint rather than trip the global
            # failure path. Narrowing this would let an unforeseen parse error
            # blank every entity in the integration.
            failures = self._endpoint_failures.get(source, 0) + 1
            self._endpoint_failures[source] = failures
            if failures == 1:
                _LOGGER.warning(
                    "%s: Endpoint '%s' failed, holding last known values: %s",
                    self.entry.title,
                    source,
                    err,
                )
            elif failures == FETCH_STRIKE_LIMIT + 1:
                _LOGGER.error(
                    "%s: Endpoint '%s' failed %d times; marking its entities "
                    "unavailable: %s",
                    self.entry.title,
                    source,
                    failures,
                    err,
                )
            else:
                _LOGGER.debug(
                    "%s: Endpoint '%s' failed (%d/%d): %s",
                    self.entry.title,
                    source,
                    failures,
                    FETCH_STRIKE_LIMIT,
                    err,
                )
            if failures <= FETCH_STRIKE_LIMIT and source in self._endpoint_cache:
                return self._endpoint_cache[source]
            return default

        if self._endpoint_failures.get(source):
            _LOGGER.info("%s: Endpoint '%s' recovered.", self.entry.title, source)
        self._endpoint_failures[source] = 0
        self._endpoint_cache[source] = result
        return result

    async def _fetch_all(self) -> tuple[dict[str, Any], dict[str, Any], list[Any]]:
        """Fetch the mandatory payload plus all three optional endpoints.

        ``get_all_data`` is mandatory: its failure is a whole-integration
        failure and falls through to the global strike handler. The other three
        are optional and each carries its own last-good payload and strike
        count, so one flaky endpoint degrades only its own entities rather than
        blanking Signal and Data too (Section 8).

        ``get_extended_data`` is the second half of the batch poll, split off
        because the router bounds a GET at ~2048 characters. It is optional
        because everything in it is a diagnostic or a disabled-by-default
        entity: three cycles of held values, then those entities alone go
        unavailable.

        A ``ZTEAuthError`` from any of the four propagates, so the caller can
        renew the session and retry the whole set once.
        """
        names, full = self.poll_plan.names(dt_util.utcnow())
        self._poll_kind = "full" if full else "narrowed"
        self.poll_plan.last_requested = (
            len(names) if names is not None else len(POLL_UNIVERSE)
        )
        _LOGGER.debug(
            "%s: %s poll, %d names%s",
            self.entry.title,
            self._poll_kind,
            self.poll_plan.last_requested,
            f" ({', '.join(sorted(self.poll_plan.full_reasons))})"
            if self.poll_plan.full_reasons
            else "",
        )
        data = await self.api.get_all_data(names)
        # Merged under the core payload rather than over it, so a stale cached
        # extended value can never mask a fresh core one if the two ever come
        # to share a key.
        extended = await self._fetch_optional(
            ENDPOINT_EXTENDED, lambda: self.api.get_extended_data(names), {}
        )
        data = {**extended, **data}
        sms_cap = await self._fetch_optional(
            ENDPOINT_SMS_CAPACITY, self.api.get_sms_capacity, {}
        )
        messages = await self._fetch_optional(
            ENDPOINT_SMS_MESSAGES,
            lambda: self.api.get_sms_messages(mem_store="1", tags="10"),
            [],
        )
        return data, sms_cap, messages

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the API, serialized against a discovery pass.

        The lock is the point. `async_run_discovery` has taken it since the probe
        was added, with a comment saying the two "take turns" — but this method
        never acquired it, so nothing was serialized.

        What that allowed: a scheduled poll during a diagnostics download shares
        this coordinator's `ZTERouterAPI`, and a poll judging the session expired
        re-logs in. The router permits one session, so the new login invalidates
        the cookie the discovery pass is replaying. Probes run with
        `authenticated=False` precisely so one never silently re-authenticates
        and samples an authenticated response — so they cannot recover. They go
        blank, and their names are recorded as unanswered.

        Measured: with a competing client logging in every 180 seconds, 2 of 12
        passes read 413 and 445 names without a session against 16 in a healthy
        pass; with the competitor paused, 0 of 12.

        A discovery pass can hold this for its whole budget, so a poll may wait.
        That is the right trade: a delayed poll holds last known values for one
        cycle, while an overlapping one corrupts a download the user is waiting
        on and publishes absences that were never measured.
        """
        async with self._async_update_lock:
            return await self._async_update_data_locked()

    async def _async_update_data_locked(self) -> dict[str, Any]:
        """Fetch data from API with resilience and pausing."""
        # Consume the one-shot force flag before anything can short-circuit.
        forced = self._force_refresh_once
        self._force_refresh_once = False

        is_paused = self.entry.options.get(CONF_STOP_POLLING, False)
        is_first_run = self.data is None

        # 1. If paused and NOT the first run, return cached data immediately —
        #    unless this cycle was explicitly forced by a user action.
        # The closing poll of an expected-outage window runs even while paused:
        # the window closes only on a real fetch, and a paused entry would
        # otherwise hold it open until the cap.
        if is_paused and not is_first_run and not forced and not self._outage_closing:
            _LOGGER.debug(
                "%s: Polling is paused; returning cached data.", self.entry.title
            )
            return self.data

        # 2. The router accepted a command that takes it offline. Returning
        #    here skips everything a fetch drives: post-processing, health,
        #    change history, the Last Updated timestamp and the failure count.
        if self.outage_active and not self._outage_closing and not is_first_run:
            _LOGGER.debug(
                "%s: Router expected to be offline; skipping this poll.",
                self.entry.title,
            )
            return self.data

        if forced and is_paused:
            _LOGGER.debug(
                "%s: Forced refresh overriding paused polling.", self.entry.title
            )

        try:
            # Use standard timeout wrapper (HA Best Practice)
            async with asyncio.timeout(30):
                try:
                    data, sms_cap, messages = await self._fetch_all()
                except ZTEAuthError as auth_err:
                    _LOGGER.info(
                        "%s: Session expired during poll; "
                        "renewing session and retrying: %s",
                        self.entry.title,
                        auth_err,
                    )
                    await self.api.login()
                    data, sms_cap, messages = await self._fetch_all()

                self._postprocess_payload(data, sms_cap, messages)

                # Success path
                self.last_update_success_time = dt_util.now()
                self.consecutive_failures = 0
                if not self._was_available:
                    self._was_available = True
                    _LOGGER.info(
                        "%s: Reconnected successfully.",
                        self.entry.title,
                    )
                self._record_health_success(data)
                # Never fails a poll: a fault here leaves the plan as it was,
                # and the owed full poll stays owed.
                try:
                    await self._update_poll_plan(data)
                except Exception as err:  # noqa: BLE001 - see above
                    _LOGGER.debug(
                        "%s: poll plan not updated: %s", self.entry.title, err
                    )
                self._check_new_sms(messages)
                await self._read_provisioning(forced=forced)
                await self._observe(data)
                return data

        except TimeoutError as err:
            held = self._hold_last_values(err, "Error fetching ZTE data")
            if held is not None:
                return held
            _LOGGER.error("%s: API request timed out", self.entry.title)
            self._was_available = False
            raise UpdateFailed("API request timed out") from err

        except ZTEAuthError as err:
            held = self._hold_last_values(err, "Authentication failed")
            if held is not None:
                return held

            # Only a rejected password is the user's to fix. A session that
            # merely lapsed is ours, and re-login above has already tried; if
            # it is still failing, telling the user their credentials are wrong
            # sends them to re-enter a password that was never the problem.
            if isinstance(err, ZTECredentialsError):
                _LOGGER.error(
                    "%s: Router rejected the credentials: %s",
                    self.entry.title,
                    err,
                )
                self._set_auth_repair(True)
                raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err

            _LOGGER.error(
                "%s: Session could not be established: %s",
                self.entry.title,
                err,
            )
            raise UpdateFailed(f"Session could not be established: {err}") from err

        except Exception as err:
            held = self._hold_last_values(err, "Error fetching ZTE data")
            if held is not None:
                return held

            # Safe startup bypass — if paused on first run, start with empty data
            if is_paused:
                _LOGGER.warning(
                    "%s: Initial fetch failed while paused. Starting with empty data.",
                    self.entry.title,
                )
                return {}

            _LOGGER.error(
                "%s: Connection lost. Marking entities unavailable.", self.entry.title
            )
            self._was_available = False
            raise UpdateFailed(f"Communication error: {err}") from err

    def _hold_last_values(self, err: Exception, label: str) -> dict[str, Any] | None:
        """Record a failed cycle and return the values to hold, if any.

        Failure resilience: a transient fault holds the last known values for
        `FETCH_STRIKE_LIMIT` cycles rather than emptying every entity. `None`
        means there is nothing to hold or the strike budget is spent, and the
        caller decides how the cycle fails.

        The closing poll of an expected-outage window is exempt. A router still
        starting up answers blank and fails the poll; that is the window not
        yet over, not a fault, so the window stays open and nothing is counted.
        """
        if self._outage_closing:
            return self.data
        self.consecutive_failures += 1
        self._record_health_failure(err)
        if self.data is None or self.consecutive_failures > FETCH_STRIKE_LIMIT:
            return None
        if self.consecutive_failures == 1:
            _LOGGER.warning(
                "%s: %s, holding last known values: %s",
                self.entry.title,
                label,
                err,
            )
        else:
            _LOGGER.debug(
                "%s: %s (failure %d/%d): %s",
                self.entry.title,
                label,
                self.consecutive_failures,
                FETCH_STRIKE_LIMIT,
                err,
            )
        return self.data

    def _postprocess_payload(
        self,
        data: dict[str, Any],
        sms_cap: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> None:
        """Fold the fetched parts into one payload and latch what persists.

        Pure payload work: the SMS capacity merge, the latest-message pick,
        the boot-time latch, and the device-registry refresh when the
        router's reported hardware changes. Nothing here decides whether
        the cycle succeeded.
        """
        data.update(sms_cap)
        # Sort by ID descending to find the latest message
        if messages:
            sorted_msgs = sorted(
                messages, key=lambda x: int(x.get("id", 0)), reverse=True
            )
            data["last_sms"] = sorted_msgs[0]
        else:
            data["last_sms"] = {}

        # Stable boot time: latch once and only re-derive it when the
        # router's uptime counter drops (a genuine reboot). The boot
        # instant is physically constant between reboots, so freezing it
        # eliminates the drift caused by recomputing now() - uptime
        # against two independently ticking clocks.
        # Two counters, two reset events, two independent latches, routed as
        # the Huawei project routes its three.
        system_raw = self._device_uptime_raw(data)
        conn_raw = get_first(data, CONNECTION_UPTIME_KEYS)
        if not _session_reading(conn_raw):
            conn_raw = None
        self._apply_uptime_readings(
            ((self._system_latch, system_raw), (self._conn_latch, conn_raw))
        )
        data["boot_time"] = self._system_latch.boot_time
        data["uptime_seconds"] = _counter_seconds(system_raw)
        # Empty while data is off: the counter is blank then, and the last
        # session's start would read as a live one.
        data["connection_start"] = (
            self._conn_latch.boot_time if conn_raw is not None else None
        )
        # Connection Duration's value: `None` while data is off, when the
        # counter reads blank or 0 (3.4.2-dev8).
        data["connection_seconds"] = _counter_seconds(conn_raw)

        # Identify if hardware metadata has changed
        new_model = get_router_model(data)
        new_version = data.get("wa_inner_version")

        if new_version != self.sw_version or new_model != self.model:
            _LOGGER.info(
                "%s: Hardware metadata updated: %s (%s)",
                self.entry.title,
                new_model,
                new_version,
            )
            self.sw_version = new_version
            self.model = new_model

            # Update device registry instead of writing entry.data on every poll
            sub_id_prefix = (
                self.imei or f"host_{self.entry.options.get(CONF_HOST, 'unknown')}"
            )
            dev_reg = dr.async_get(self.hass)
            # async_get_device(identifiers=…) is deprecated in HA 2026.8
            # and removed in 2027.8; the shim feature-detects the scoped
            # replacement.
            device = device_by_identifier(
                dev_reg,
                DOMAIN,
                f"{sub_id_prefix}_system",
                self.entry.entry_id,
            )
            if device:
                dev_reg.async_update_device(
                    device.id, model=new_model, sw_version=new_version
                )

    # ------------------------------------------------------------------
    # State views
    #
    # The two attribute names below predate the latch objects and are read
    # by the test suite. They stay as views rather than as a second copy: the
    # latch holds the state, and these say where to find it.
    # ------------------------------------------------------------------

    @property
    def _boot_time(self) -> datetime | None:
        """The anchor for the router's uptime counter."""
        return self._system_latch.boot_time

    @_boot_time.setter
    def _boot_time(self, value: datetime | None) -> None:
        self._system_latch.boot_time = value

    @property
    def _last_uptime(self) -> int | None:
        """The last system counter reading this coordinator saw."""
        return self._system_latch.last_counter

    @_last_uptime.setter
    def _last_uptime(self, value: int | None) -> None:
        self._system_latch.last_counter = value

    # ------------------------------------------------------------------
    # Boot-time latches
    #
    # A counter is a good reset detector and a poor clock. Comparing a
    # counter with its own previous value needs no clock at all and cannot
    # drift; deriving a timestamp as `now - counter` inherits the divergence
    # between the router's oscillator and the host's. The anchor is therefore
    # latched once and held, and re-derived only when something says it must
    # be.
    #
    # Four paths, in the order they are evaluated:
    #
    #   1. Guards         - a reading or a clock that cannot be trusted.
    #   2. Counter drop   - conclusive, vetoed by nothing.
    #   3. Startup        - did the counter continue across a gap Home
    #                       Assistant did not observe?
    #   4. Plausibility   - is the anchor still credible? Every poll.
    #
    # The design, the drift measurement behind the constants and the nine
    # decisions are in
    # `.shared/info/uptime_timestamp/uptime_drift_analyzed.md`.
    # ------------------------------------------------------------------

    def _apply_uptime_readings(self, readings: Any) -> None:
        """Route each `(latch, raw)` reading, then write the anchors once.

        The Huawei project's per-poll latch loop, verbatim apart from being a
        method.
        """
        entry_data_updates: dict[str, Any] = {}
        for latch, raw in readings:
            self._apply_uptime(latch, raw, entry_data_updates)
        if entry_data_updates:
            # The legacy counter keys are dropped here. They are no longer
            # read - the counters come from the store, which is written on an
            # interval rather than only at a latch - and leaving them invites
            # a future reader to wire the frozen copy back in.
            kept = {
                key: value
                for key, value in self.entry.data.items()
                if key not in LEGACY_COUNTER_KEYS
            }
            self.hass.config_entries.async_update_entry(
                self.entry, data={**kept, **entry_data_updates}
            )

    def _drift_rate(self, latch: _UptimeLatch) -> float | None:
        """Return the fraction of wall time this counter loses, once trustworthy.

        `None` until enough has accumulated. The minimum is checked **before**
        the division, which is also what stops a fresh install dividing by a
        zero denominator.
        """
        if latch.pauses or latch.drift_sum_wall < DRIFT_MIN_ACCUMULATED:
            return None
        rate = 1.0 - (latch.drift_sum_counter / latch.drift_sum_wall)
        # Clamped at both ends for opposite reasons. An unbounded high rate
        # lowers the expected counter until a real shortfall stops
        # registering, suppressing detection; an unbounded low one raises it
        # and produces false alarms.
        return max(-MAX_DRIFT, min(MAX_DRIFT, rate))

    def _record_drift_sample(
        self, latch: _UptimeLatch, seconds: int, now: datetime
    ) -> None:
        """Fold one poll-to-poll interval into this latch's accumulators.

        Duration-weighted, so an interval spanning a long pause carries
        proportionally more evidence than one spanning three minutes. The
        measurement makes no reference to the anchor - the anchor is what the
        rate is used to judge, and deriving one from the other would be
        circular.
        """
        if latch.pauses or latch.last_counter is None or latch.last_poll_at is None:
            return
        wall = (now - latch.last_poll_at).total_seconds()
        advance = seconds - latch.last_counter
        if wall < DRIFT_MIN_INTERVAL or advance <= 0:
            # Too short for the counter's whole-second resolution, or a
            # reset. Neither says anything about the rate.
            return

        latch.drift_sum_wall += wall
        latch.drift_sum_counter += advance
        sample = 1.0 - (advance / wall)
        latch.drift_rate_min = (
            sample
            if latch.drift_rate_min is None
            else min(latch.drift_rate_min, sample)
        )
        latch.drift_rate_max = (
            sample
            if latch.drift_rate_max is None
            else max(latch.drift_rate_max, sample)
        )
        latch.drift_interval_count += 1

        if latch.drift_sum_wall > DRIFT_ACCUMULATOR_CAP:
            # Scale both down together: the ratio survives, but newer
            # evidence can move it, so a firmware fix to the timer is
            # followed rather than averaged away against history.
            scale = DRIFT_ACCUMULATOR_CAP / latch.drift_sum_wall
            latch.drift_sum_wall *= scale
            latch.drift_sum_counter *= scale

    def _derived_boot(
        self, latch: _UptimeLatch, seconds: int, now: datetime
    ) -> datetime:
        """Return the instant this counter started, corrected for its drift.

        `now - counter` is late by exactly the drift the counter has
        accumulated. Dividing by `(1 - rate)` recovers the wall time the
        counter represents. It matters twice: a latch taken long after the
        event is accurate, and the plausibility check can use a tight
        tolerance - without the correction a fresh anchor sits a full `rate`
        from the ratio that check predicts, so any device drifting past the
        tolerance would re-latch on every poll.

        Falls back to the uncorrected instant before a rate is known, where
        the error is bounded by the short accumulation that implies.
        """
        rate = self._drift_rate(latch)
        elapsed = seconds if rate is None else seconds / (1.0 - rate)
        return now - timedelta(seconds=elapsed)

    def _apply_uptime(
        self,
        latch: _UptimeLatch,
        raw: Any,
        entry_data_updates: dict[str, Any],
    ) -> None:
        """Route one counter reading through its latch."""
        seconds: int | None = None
        with contextlib.suppress(ValueError, TypeError):
            if raw is not None:
                seconds = int(float(raw))

        if seconds is None or seconds < 0:
            # Bad-reading guard: missing, unparsable or negative changes
            # nothing at all. Advancing the last-seen counter to a rejected
            # reading would move the reset comparison to a value the router
            # never reported.
            return

        now = dt_util.now()
        if now.year < CLOCK_FLOOR_YEAR:
            # The host has no battery-backed clock and NTP has not completed.
            # Defer rather than latch an instant decades adrift.
            _LOGGER.debug(
                "%s: system clock reads %s; deferring %s reconciliation",
                self.entry.title,
                now.isoformat(),
                latch.label,
            )
            return
        if seconds > MAX_PLAUSIBLE_UPTIME:
            _LOGGER.warning(
                "%s: implausible %s counter %s s; keeping the stored anchor",
                self.entry.title,
                latch.label,
                seconds,
            )
            return

        self._record_drift_sample(latch, seconds, now)

        if latch.startup_reconciled:
            self._apply_runtime_uptime(latch, seconds, now, entry_data_updates)
        else:
            self._reconcile_startup_uptime(latch, seconds, now, entry_data_updates)

        self._check_anchor_plausible(latch, seconds, now, entry_data_updates)

        latch.last_counter = seconds
        latch.last_poll_at = now
        self._maybe_persist_counter(latch, seconds, now)

    def _apply_runtime_uptime(
        self,
        latch: _UptimeLatch,
        seconds: int,
        now: datetime,
        entry_data_updates: dict[str, Any],
    ) -> None:
        """Compare the counter against itself during an unbroken session.

        Exact, and the reason the anchor is stable: no clock enters the
        comparison, so no drift can reach the timestamp. A drop beyond the
        margin is a reset, and nothing vetoes it.
        """
        if latch.last_counter is None:
            return
        if seconds < latch.last_counter - UPTIME_REBOOT_MARGIN:
            self._latch_boot_time(
                latch,
                self._derived_boot(latch, seconds, now),
                seconds,
                now,
                entry_data_updates,
            )
        elif seconds < latch.last_counter:
            # Inside the margin, so not a reset. Logged rather than absorbed
            # in silence: nothing has established that these counters never
            # step backwards, and the margin would otherwise hide the
            # evidence that they do.
            _LOGGER.info(
                "%s: %s counter stepped back %s s (%s to %s), within the %s s "
                "margin and not treated as a reset",
                self.entry.title,
                latch.label,
                latch.last_counter - seconds,
                latch.last_counter,
                seconds,
                UPTIME_REBOOT_MARGIN,
            )

    def _reconcile_startup_uptime(
        self,
        latch: _UptimeLatch,
        seconds: int,
        now: datetime,
        entry_data_updates: dict[str, Any],
    ) -> None:
        """Decide, on the first usable poll, whether a gap contained a reset.

        This is the boundary the running comparison cannot see. The stored
        counter is what makes it answerable, and the defect this mechanism
        replaces was that the stored counter was written **only at a latch**:
        one instance held 61 s against a live 213,412 s, frozen for nineteen
        days, so the comparison could never fire again.
        """
        if latch.stored_counter is not None:
            if latch.pauses or latch.stored_written_at is None:
                self._floor_test(latch, seconds, now, entry_data_updates)
            else:
                self._shortfall_test(
                    latch,
                    seconds,
                    now,
                    latch.stored_counter,
                    latch.stored_written_at,
                    entry_data_updates,
                )
            self._finish_startup(latch)
            return

        # Nothing stored: a fresh install, or the first start after this
        # upgrade. The only evidence is the anchor against the counter,
        # judged with the wide universal bound.
        if latch.boot_time is None or self._cold_start_implausible(latch, seconds, now):
            self._log_reconciliation(latch, "cold start, re-latching", seconds, now)
            self._latch_boot_time(
                latch,
                self._derived_boot(latch, seconds, now),
                seconds,
                now,
                entry_data_updates,
            )
        else:
            self._log_reconciliation(latch, "cold start, anchor retained", seconds, now)
        self._finish_startup(latch)

    def _floor_test(
        self,
        latch: _UptimeLatch,
        seconds: int,
        now: datetime,
        entry_data_updates: dict[str, Any],
    ) -> None:
        """Ask whether a counter that may legitimately pause moved backwards.

        The only question available for `TotalConnectTime`. It stops whenever
        the session is down, so under-running wall time across a gap says
        nothing - a week offline and a week disconnected look identical. It
        moves backwards for exactly one reason, a statistics clear, and that
        is what this detects.
        """
        stored = latch.stored_counter
        if stored is not None and seconds < stored:
            self._log_reconciliation(
                latch,
                f"counter reset during the gap (stored {stored} s)",
                seconds,
                now,
            )
            self._latch_boot_time(
                latch,
                self._derived_boot(latch, seconds, now),
                seconds,
                now,
                entry_data_updates,
            )
        else:
            self._log_reconciliation(
                latch,
                f"counter continued (stored {stored} s)",
                seconds,
                now,
            )

    def _shortfall_test(
        self,
        latch: _UptimeLatch,
        seconds: int,
        now: datetime,
        stored_counter: int,
        written_at: datetime,
        entry_data_updates: dict[str, Any],
    ) -> None:
        """Ask whether the counter continued across the gap as this device does.

        The stored pair is passed in rather than read from the latch: the
        caller has already established both are present, and passing them
        says so.
        """
        elapsed = (dt_util.as_utc(now) - written_at).total_seconds()
        if elapsed < 0:
            # The stored write is dated after now. Nothing useful can be said
            # about the gap, so fall back to the anchor comparison.
            _LOGGER.warning(
                "%s: stored %s write is dated ahead of now; using the "
                "cold-start comparison instead",
                self.entry.title,
                latch.label,
            )
            if latch.boot_time is None or self._cold_start_implausible(
                latch, seconds, now
            ):
                self._latch_boot_time(
                    latch,
                    self._derived_boot(latch, seconds, now),
                    seconds,
                    now,
                    entry_data_updates,
                )
            return

        rate = self._drift_rate(latch) or 0.0
        expected = stored_counter + elapsed * (1.0 - rate)
        # The margin scales because the error it absorbs scales: the dominant
        # term is rate-estimate error multiplied by the gap. The floor covers
        # quantization and poll latency on short gaps.
        margin = max(SHORTFALL_MARGIN_FLOOR, elapsed * SHORTFALL_MARGIN_RATE)

        if seconds < expected - margin:
            self._log_reconciliation(
                latch,
                f"reset during the gap (expected {expected:.0f} s, "
                f"margin {margin:.0f} s)",
                seconds,
                now,
            )
            self._latch_boot_time(
                latch,
                self._derived_boot(latch, seconds, now),
                seconds,
                now,
                entry_data_updates,
            )
        else:
            self._log_reconciliation(
                latch,
                f"counter continued (expected {expected:.0f} s, margin {margin:.0f} s)",
                seconds,
                now,
            )

    def _cold_start_implausible(
        self, latch: _UptimeLatch, seconds: int, now: datetime
    ) -> bool:
        """Judge the anchor with the universal bound, nothing having been learned.

        Two-sided for a counter that tracks wall time. The low side catches
        an anchor that is too early, which is the observed failure; the high
        side catches one that is too late, and exists because no counter has
        been measured running fast.

        **One-sided for a counter that pauses.** Downtime makes the ratio
        arbitrarily small with nothing wrong, so only the high side means
        anything: a counter cannot have run for longer than the anchor says
        has elapsed.
        """
        if latch.boot_time is None:
            return True
        elapsed = (
            dt_util.as_utc(now) - dt_util.as_utc(latch.boot_time)
        ).total_seconds()
        if elapsed <= 0:
            return True
        ratio = seconds / elapsed
        if latch.pauses:
            return ratio > (1.0 + MAX_DRIFT)
        return ratio < (1.0 - MAX_DRIFT) or ratio > (1.0 + MAX_DRIFT)

    def _check_anchor_plausible(
        self,
        latch: _UptimeLatch,
        seconds: int,
        now: datetime,
        entry_data_updates: dict[str, Any],
    ) -> None:
        """Backstop: is the anchor still credible against the counter?

        The startup tests run once and the runtime comparison only sees drops
        as they happen. Neither watches for an anchor that has *become*
        wrong, and retaining a stale anchor indefinitely is the failure this
        design exists to prevent.

        Compared against the counter's own measured rate rather than a
        universal constant, so no guess decides whether an unseen device
        works. A pausing counter has no rate and is not checked here at all:
        its ratio falls legitimately with every outage.
        """
        rate = self._drift_rate(latch)
        if rate is None or latch.boot_time is None:
            return
        elapsed = (
            dt_util.as_utc(now) - dt_util.as_utc(latch.boot_time)
        ).total_seconds()
        if elapsed <= 0:
            return
        if abs(seconds / elapsed - (1.0 - rate)) <= PLAUSIBILITY_TOLERANCE:
            return

        candidate = self._derived_boot(latch, seconds, now)
        if candidate <= latch.boot_time:
            # A reset moves the start instant forward: the anchor can only be
            # ahead of the true start by drift accumulated within the epoch
            # that produced it, and a few percent of an interval cannot
            # exceed the interval. A backward move is therefore not a reset.
            _LOGGER.warning(
                "%s: %s anchor implausible against the counter but the "
                "candidate instant is earlier (%s vs %s); not treating as a reset",
                self.entry.title,
                latch.label,
                candidate.isoformat(),
                latch.boot_time.isoformat(),
            )
            return

        self._log_reconciliation(
            latch, "anchor implausible against the counter", seconds, now
        )
        self._latch_boot_time(latch, candidate, seconds, now, entry_data_updates)

    def _finish_startup(self, latch: _UptimeLatch) -> None:
        """Mark this latch's startup reconciliation complete."""
        latch.startup_reconciled = True

    def _log_reconciliation(
        self, latch: _UptimeLatch, outcome: str, seconds: int, now: datetime
    ) -> None:
        """Record every input to a latch decision, and the decision.

        The absence of this is a substantial part of why the equivalent fault
        took five days of forensics on the sibling project rather than
        showing on the first restart.
        """
        rate = self._drift_rate(latch)
        _LOGGER.info(
            "%s: %s reconciliation - %s (live %s s, stored counter %s, "
            "written at %s, rate %s, stored anchor %s, derived anchor %s)",
            self.entry.title,
            latch.label,
            outcome,
            seconds,
            latch.stored_counter,
            latch.stored_written_at.isoformat() if latch.stored_written_at else None,
            f"{rate * 100:.2f}%" if rate is not None else "not yet measured",
            latch.boot_time.isoformat() if latch.boot_time is not None else None,
            self._derived_boot(latch, seconds, now).replace(microsecond=0).isoformat(),
        )

    def _latch_boot_time(
        self,
        latch: _UptimeLatch,
        boot_time: datetime,
        seconds: int,
        now: datetime,
        entry_data_updates: dict[str, Any],
    ) -> None:
        """Re-anchor this latch and persist it immediately."""
        previous = latch.boot_time
        latch.boot_time = boot_time.replace(microsecond=0)
        _LOGGER.info(
            "%s: %s latched: %s",
            self.entry.title,
            latch.label,
            latch.boot_time.isoformat(),
        )
        if previous is not None and latch.last_counter is not None:
            dropped = seconds < latch.last_counter - UPTIME_REBOOT_MARGIN
            if not dropped:
                # The signature of this entire bug class. A timestamp that
                # moves without the counter having dropped is either a
                # genuine gap reset or a defect, and the two are worth
                # telling apart from the log alone.
                _LOGGER.warning(
                    "%s: %s moved from %s to %s without a counter drop "
                    "(live %s s, previous %s s)",
                    self.entry.title,
                    latch.label,
                    previous.isoformat(),
                    latch.boot_time.isoformat(),
                    seconds,
                    latch.last_counter,
                )
        entry_data_updates[latch.boot_key] = latch.boot_time.isoformat()
        self._write_counter(latch, seconds, now)

    def _maybe_persist_counter(
        self, latch: _UptimeLatch, seconds: int, now: datetime
    ) -> None:
        """Flush the counter and accumulators on a fixed interval.

        **This is the half of the fix that addresses the observed defect.**
        The counter used to reach disk only when a latch happened, so the
        stored value froze at whatever the counter read one poll after a
        boot - 61 s on the instance this was written against - and the
        restart comparison could never fire again. Writing on an interval
        bounds how stale the stored value can be, for every stop condition
        rather than only an orderly one.

        A clean shutdown needs no hook: `async_delay_save` registers a
        final-write listener that flushes a pending save when Home Assistant
        stops.
        """
        if (
            latch.last_counter_write is not None
            and now - latch.last_counter_write < UPTIME_WRITE_INTERVAL
        ):
            return
        self._write_counter(latch, seconds, now)

    def _write_counter(self, latch: _UptimeLatch, seconds: int, now: datetime) -> None:
        """Schedule a debounced write of every latch's counter and accumulators."""
        latch.stored_counter = seconds
        latch.stored_written_at = dt_util.as_utc(now)
        latch.last_counter_write = now
        if self._store is None:
            return
        record = self._store_record()
        self._store.async_delay_save(lambda: record, UPTIME_SAVE_DELAY)

    def _store_record(self) -> dict[str, Any]:
        """Return the persisted form of both latches.

        One record rather than three files: the three are written on the same
        poll and read on the same setup, and a single debounced save is the
        cadence the write interval already assumes. The fields inside each
        block match the sibling projects, so one reader serves all of them.
        """
        record: dict[str, Any] = {}
        for latch in self._latches:
            block: dict[str, Any] = {
                "last_uptime": latch.stored_counter,
                "written_at": (
                    latch.stored_written_at.isoformat()
                    if latch.stored_written_at is not None
                    else None
                ),
                "sum_wall": round(latch.drift_sum_wall, 3),
                "sum_counter": round(latch.drift_sum_counter, 3),
                "interval_count": latch.drift_interval_count,
            }
            if latch.drift_rate_min is not None:
                block["rate_min"] = round(latch.drift_rate_min, 6)
            if latch.drift_rate_max is not None:
                block["rate_max"] = round(latch.drift_rate_max, 6)
            record[latch.counter_key] = block
        return record

    async def async_load_stored_uptime(self) -> None:
        """Load the persisted counters and accumulators. Never raises.

        Awaited in `async_setup_entry` so the record is in memory before the
        background initialization task runs the first poll. An absent,
        corrupt or unreadable record resolves to "nothing learned", which
        routes to the cold-start path - the store is a cross-check, never the
        anchor.
        """
        self._store = Store(
            self.hass,
            UPTIME_STORAGE_VERSION,
            f"{DOMAIN}_{self.entry.entry_id}_uptime",
        )
        stored: dict[str, Any] | None = None
        try:
            stored = await self._store.async_load()
        except Exception as err:  # noqa: BLE001 - see below
            # Deliberately broad. The contract is that **no** storage fault
            # can fail entry setup: the store is a cross-check and the
            # cold-start path works without it. Narrowing this to the
            # exceptions seen so far would let an unanticipated one abort a
            # setup with no need of the store at all.
            _LOGGER.debug(
                "%s: uptime store unreadable, continuing without it: %s",
                self.entry.title,
                err,
            )
            return
        if not isinstance(stored, dict):
            return
        if "last_uptime" in stored:
            # The flat record written before 3.4.2-dev7, when the single latch
            # read `realtime_time`. That is now the connection latch's counter;
            # the system latch starts with nothing learned.
            self._restore_latch(self._conn_latch, stored)
            self._drop_anchorless_counters()
            return
        for latch in self._latches:
            block = stored.get(latch.counter_key)
            if isinstance(block, dict):
                self._restore_latch(latch, block)
        self._drop_anchorless_counters()

    def _drop_anchorless_counters(self) -> None:
        """Cold-start any latch that has a stored counter but no anchor.

        ZTE only. The pre-3.4.2-dev7 flat record gives the connection latch a
        stored counter while `entry.data` has no `connection_start`. The
        startup test then finds the counter continued and keeps an anchor that
        does not exist, so Connection Uptime stays unknown until a reconnect.
        Dropping the stored counter routes that latch to the cold start, which
        latches `now - counter`; the drift it learned is kept.
        """
        for latch in self._latches:
            if latch.boot_time is None and latch.stored_counter is not None:
                latch.stored_counter = None
                latch.stored_written_at = None

    def _restore_latch(self, latch: _UptimeLatch, block: dict[str, Any]) -> None:
        """Read one latch's block back, treating anything unusable as absent."""
        with contextlib.suppress(ValueError, TypeError):
            raw = block.get("last_uptime")
            if raw is not None:
                latch.stored_counter = int(raw)
        with contextlib.suppress(ValueError, TypeError):
            latch.drift_sum_wall = float(block.get("sum_wall", 0.0))
            latch.drift_sum_counter = float(block.get("sum_counter", 0.0))
            latch.drift_interval_count = int(block.get("interval_count", 0))
        for key, attr in (
            ("rate_min", "drift_rate_min"),
            ("rate_max", "drift_rate_max"),
        ):
            with contextlib.suppress(ValueError, TypeError):
                raw = block.get(key)
                if raw is not None:
                    setattr(latch, attr, float(raw))

        # `written_at` carries the same naive-versus-aware hazard as the
        # anchor: both are read back as strings and both are subtracted from
        # `now()`. A value that will not parse, or parses naive, is treated
        # as absent - which means the record cannot date the gap, and the
        # floor comparison applies instead.
        raw_written = block.get("written_at")
        if raw_written:
            with contextlib.suppress(Exception):
                parsed = dt_util.parse_datetime(raw_written)
                if parsed is not None and parsed.tzinfo is not None:
                    latch.stored_written_at = dt_util.as_utc(parsed)

    @property
    def uptime_diagnostics(self) -> dict[str, Any]:
        """Return the drift picture, for the health sensor and diagnostics.

        Published because every constant in the latch was set from one device
        over one week on a sibling project. Without this a field report
        carries no rate, and the only route to one is a recorder extraction.

        Reports the system counter alone. The connection counter keeps its
        own accumulators, and neither is a property of the host clock, so
        listing both here would invite exactly the comparison that is not
        meaningful.
        """
        latch = self._system_latch
        rate = self._drift_rate(latch)
        return {
            "drift_rate_pct": round(rate * 100, 3) if rate is not None else None,
            "drift_rate_min_pct": (
                round(latch.drift_rate_min * 100, 3)
                if latch.drift_rate_min is not None
                else None
            ),
            "drift_rate_max_pct": (
                round(latch.drift_rate_max * 100, 3)
                if latch.drift_rate_max is not None
                else None
            ),
            "drift_intervals": latch.drift_interval_count,
            "drift_measured_seconds": round(latch.drift_sum_wall),
            "drift_deficit_seconds": round(
                latch.drift_sum_wall - latch.drift_sum_counter
            ),
        }

    @property
    def uptime_state(self) -> dict[str, Any]:
        """Return every latch's full state, for the diagnostics download.

        Wider than `uptime_diagnostics`, which is the rate summary the health
        sensor publishes. Carries no device data and nothing to redact:
        counters, rates and timestamps.
        """
        return {
            **self.uptime_diagnostics,
            # The key the system latch reads. ZTE only: the Huawei device has
            # one uptime key.
            "source": self._uptime_source,
            "latches": {
                latch.counter_key: {
                    "anchor": (
                        latch.boot_time.isoformat()
                        if latch.boot_time is not None
                        else None
                    ),
                    "live_counter": latch.last_counter,
                    "stored_counter": latch.stored_counter,
                    "stored_written_at": (
                        latch.stored_written_at.isoformat()
                        if latch.stored_written_at is not None
                        else None
                    ),
                    "startup_reconciled": latch.startup_reconciled,
                    "pauses": latch.pauses,
                    "drift_rate_pct": self._latch_rate_pct(latch),
                }
                for latch in self._latches
            },
        }

    def _latch_rate_pct(self, latch: _UptimeLatch) -> float | None:
        """Return one latch's measured rate as a percentage, or `None`."""
        rate = self._drift_rate(latch)
        return round(rate * 100, 3) if rate is not None else None

    async def _observe(self, data: dict[str, Any]) -> None:
        """Fold a successful poll into the transition and populated records.

        Runs only on the success path, so a degraded or failed poll neither
        records a transition nor forgets a populated entity. The write is
        skipped when nothing changed, which is almost every poll.

        The device key is the same identity `build_device_info` uses, so the
        record belongs to the same device the entities do. It is fixed at
        setup rather than re-read: `entry.data["imei"]` is written once by the
        config flow and never updated, and the entry's unique id, the device
        registry and every entity id are built on it. Re-keying the store on a
        live reading would detach the history from the entities it describes.
        """
        device_id = self.imei or f"host_{self.entry.options.get(CONF_HOST, 'unknown')}"
        if self.observations.observe(data, device_id, list(self.expected_outages)):
            await self.observations.async_save()
        await self._persist_session_lifetimes()

    async def _persist_session_lifetimes(self) -> None:
        """Carry newly observed session lifetimes into the store.

        Written on the poll path rather than at the moment a session ends,
        because the api object has no store of its own and a login must not
        wait on disk. Only a change is written; the list is short and bounded
        by `SESSION_AGE_LEARN_WINDOW`.
        """
        observed = list(getattr(self.api, "session_lifetimes", []))
        if observed and observed != self.observations.session_lifetimes():
            await self.observations.async_save_session_lifetimes(observed)

    def request_full_poll(self, reason: str) -> None:
        """Owe a full poll: every name, cleared only when one succeeds."""
        self.poll_plan.request_full(reason)

    def _poll_readers(self) -> list[Reader]:
        """Each entity description's unique id and the callables reading data.

        Imported here, not at module level, because the platforms import this
        module. Entities built as classes outside a description read names in
        `poll_plan.ALWAYS_POLLED`.
        """
        from .binary_sensor import BINARY_SENSORS
        from .select import SELECT_TYPES
        from .sensor import SENSOR_TYPES
        from .switch import SWITCH_TYPES

        prefix = getattr(self.entry, "unique_id", None) or self.entry.entry_id
        readers: list[Reader] = []
        for description in (
            *SENSOR_TYPES,
            *SWITCH_TYPES,
            *SELECT_TYPES,
            *BINARY_SENSORS,
        ):
            fns: list[Callable[[Any], Any]] = []
            for attr in ("value_fn", "extra_attrs_fn"):
                fn = getattr(description, attr, None)
                if callable(fn):
                    fns.append(fn)
            keys: tuple[str, ...] = tuple(getattr(description, "state_keys", ()) or ())
            if keys:
                fns.append(_state_keys_reader(keys))
            if getattr(description, "counts_changes_of", None) is not None:
                continue
            readers.append((f"{prefix}_{description.key}", tuple(fns)))
        return readers

    def _disabled_unique_ids(self) -> set[str]:
        """Unique ids of this entry's entities disabled in the registry."""
        try:
            from homeassistant.helpers import entity_registry as er

            registry = er.async_get(self.hass)
            return {
                entry.unique_id
                for entry in er.async_entries_for_config_entry(
                    registry, self.entry.entry_id
                )
                if entry.disabled_by is not None
            }
        except Exception:  # noqa: BLE001 - no registry means nothing skipped
            return set()

    async def _update_poll_plan(self, data: dict[str, Any]) -> None:
        """Learn from a successful poll and schedule the next full one.

        A full poll whose extended half came from the cache does not count, and
        nothing is learned from a cached payload; once the endpoint's strikes
        are spent its failure is its own and the poll counts (plan §9.3).
        """
        plan = self.poll_plan
        now = dt_util.utcnow()
        failures = self._endpoint_failures.get(ENDPOINT_EXTENDED, 0)
        fresh = failures == 0 or failures > FETCH_STRIKE_LIMIT
        full = self._poll_kind == "full"
        firmware = str(data.get("wa_inner_version") or "")
        if firmware and firmware != self._poll_firmware:
            if self._poll_firmware:
                # Names learned on another firmware describe one that is gone.
                plan.answered.clear()
                plan.request_full("firmware changed")
            self._poll_firmware = firmware
        previous = self._poll_previous
        uptime = data.get("uptime_seconds")
        if (
            isinstance(uptime, int)
            and isinstance(previous.get("uptime"), int)
            and uptime < previous["uptime"]
        ):
            plan.request_full("reboot")
        link = str(data.get("ppp_status") or "")
        was = str(previous.get("link") or "")
        if previous and link.endswith("_connected") and not was.endswith("_connected"):
            plan.request_full("data connection returned")
        self._poll_previous = {"uptime": uptime, "link": link}
        if fresh:
            readers = self._poll_readers()
            plan.disabled = self._disabled_unique_ids()
            # Readers are learned on a full poll, and on the first poll after
            # a restart that started narrowed from stored names: until they
            # are, every name counts as unowned and is polled.
            if full or not plan.consumers:
                plan.learn_readers(readers, data)
            if plan.learn_answers(readers, data) and self._poll_store is not None:
                self._poll_store.async_delay_save(
                    lambda: plan.to_store(self._poll_firmware), 10
                )
        plan.after_poll(data, full=full, fresh=fresh, now=now)

    async def async_load_profile(self) -> None:
        """Read the cached device profile. Never raises, never fetches.

        Principle 5: Home Assistant startup reads a profile from local storage
        and parses nothing. A missing, corrupt or stale record resolves to "no
        profile", which routes every profile-backed decision to the behaviour
        that shipped before there was one.

        The firmware the profile was read under is **not** checked here,
        because nothing has polled yet and the version is not known. It is
        checked once by `async_learn_profile`, which is the only thing that
        can act on the answer.
        """
        self._poll_store = Store(
            self.hass, PROFILE_STORAGE_VERSION, f"{DOMAIN}_{self.entry.entry_id}_poll"
        )
        try:
            stored_plan = await self._poll_store.async_load()
        except Exception:  # noqa: BLE001 - no storage fault fails setup
            stored_plan = None
        self._poll_firmware = self.poll_plan.load(
            stored_plan if isinstance(stored_plan, dict) else {}
        )
        # Readers are learned from the descriptions alone, against an empty
        # payload, so the first poll after a restart is narrowed; reads that
        # depend on a value are added on the next full poll.
        with contextlib.suppress(Exception):
            self.poll_plan.learn_readers(self._poll_readers(), {})
        self._profile_store = Store(
            self.hass,
            PROFILE_STORAGE_VERSION,
            f"{DOMAIN}_{self.entry.entry_id}_profile",
        )
        try:
            stored = await self._profile_store.async_load()
        except Exception as err:  # noqa: BLE001 - no storage fault fails setup
            _LOGGER.debug(
                "%s: profile store unreadable, continuing without it: %s",
                self.entry.title,
                err,
            )
            return
        if not isinstance(stored, dict):
            return
        if stored.get("profile_version") != device_profile.PROFILE_VERSION:
            # A record written by a build whose profile had a different shape.
            # Discarded rather than migrated: the device that produced it is
            # still there and can simply be asked again.
            return
        self.api.profile = stored

    async def async_learn_profile(self) -> None:
        """Learn the profile once, in the background, if it is not current.

        Runs after the first poll, so the firmware version it is keyed to is
        the one the device is actually running. Re-learned only when that
        version changes, for the reason `cr_version` is cached the same way: an
        upgrade can change every answer in here, and a profile that outlives
        its firmware is worse than none.

        **Never fails a setup and never blocks a write.** Anything that goes
        wrong leaves the profile as it was — absent, or the previous firmware's
        — and every consumer falls back.
        """
        try:
            # Inside the guard, not ahead of it. Reading the version is a
            # request like any other, and a device that cannot answer it must
            # leave the profile as it was rather than fail the task it is in.
            version = await self.api.get_version() or ""
            if version and self.api.profile.get("firmware") == version:
                return
            profile = await self.api.learn_profile()
        except Exception as err:  # noqa: BLE001 - learning is never load-bearing
            _LOGGER.debug(
                "%s: could not learn the device profile: %s", self.entry.title, err
            )
            return
        _LOGGER.info(
            "%s: device profile learned from %d of its own files; %s",
            self.entry.title,
            len(profile.get("sources_read", [])),
            "everything it was asked for"
            if not profile.get("unlearned")
            else "not learned: " + ", ".join(profile["unlearned"]),
        )
        # Entities that read the profile, such as Network Mode Selection's
        # options, are otherwise re-rendered only by the next poll: up to one
        # polling interval late, and not at all while polling is paused.
        if self.data is not None:
            self.async_update_listeners()
        if self._profile_store is None:  # pragma: no cover - set up before this
            return
        try:
            await self._profile_store.async_save(profile)
        except Exception as err:  # noqa: BLE001 - see above
            _LOGGER.debug(
                "%s: could not store the device profile: %s", self.entry.title, err
            )

    def _device_uptime_raw(self, data: dict[str, Any]) -> Any:
        """The system counter's raw reading, from one key chosen per run.

        `DEVICE_UPTIME_KEYS` is a preference order, not a per-poll fallback.
        A booting router can answer `system_uptime` blank while `realtime_time`
        answers, and switching keys between polls would read as a counter drop
        and latch a reboot that did not happen. The first key that answers is
        kept for the run; a blank reading of it is no reading. A session key
        reading 0 is data off, not an answer.

        The key is saved in `entry.data["uptime_source"]`. A run that chooses
        a different key, or the first run with nothing saved, starts the
        system latch afresh: an anchor or stored counter learned from another
        counter is evidence about a different question. Kept, a session anchor
        within `MAX_DRIFT` of the router's uptime passes the cold start, and
        the plausibility check never moves an anchor earlier, so it would stay
        until the next reboot. Found by the 3.4.2-dev8 review.
        """
        if self._uptime_source is None:
            chosen = next(
                (
                    k
                    for k in DEVICE_UPTIME_KEYS
                    if data.get(k) not in (None, "")
                    and (k not in CONNECTION_UPTIME_KEYS or _session_reading(data[k]))
                ),
                None,
            )
            if chosen is None:
                return None
            self._uptime_source = chosen
            if self.entry.data.get("uptime_source") != chosen:
                self._reset_system_latch(chosen)
        raw = data.get(self._uptime_source)
        if raw in (None, ""):
            return None
        if self._uptime_source in CONNECTION_UPTIME_KEYS and not _session_reading(raw):
            return None
        return raw

    def _reset_system_latch(self, chosen: str) -> None:
        """Drop what the system latch holds and record the key it now reads."""
        _LOGGER.info(
            "%s: device uptime read from %s (previously %s); the system latch "
            "starts afresh",
            self.entry.title,
            chosen,
            self.entry.data.get("uptime_source"),
        )
        self._system_latch = _UptimeLatch(
            label=self._system_latch.label,
            boot_key=self._system_latch.boot_key,
            counter_key=self._system_latch.counter_key,
        )
        self._latches = (self._system_latch, self._conn_latch)
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, "uptime_source": chosen}
        )

    @property
    def uptime_source(self) -> str | None:
        """The key the system latch reads, or `None` before one answered."""
        return self._uptime_source

    def persist_last_delete(self) -> None:
        """Write the API's delete record into the entry, so a restart keeps it.

        Called after a delete route finishes, successfully or not: the failing
        case is the one worth keeping. The record is small, bounded to the most
        recent attempt, and carries ids and a result code only — no message
        content and no sender number — so it is no more sensitive than the
        `boot_time` written the same way.
        """
        record = self.api.last_delete
        if record is None:
            return
        new_data = dict(self.entry.data)
        new_data["last_delete"] = record
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)

    async def _read_provisioning(self, *, forced: bool) -> None:
        """Read whether the router declines its provisioning configuration.

        One request, and it cannot ride an existing one: a refusal replaces the
        entire response, so a declined name shares a request with nothing. It
        runs hourly, and on any forced refresh — Refresh Now is what a user
        presses after changing something, so it is the right moment to re-ask.

        The result is held on the coordinator rather than merged into
        `coordinator.data`. That dict means "what the router said" and feeds the
        populated counts, the drift check and the sparse-payload check; a
        synthetic key would skew all three.
        """
        now = dt_util.now()
        if (
            not forced
            and self._last_provisioning_read is not None
            and now - self._last_provisioning_read < PROVISIONING_READ_INTERVAL
        ):
            return

        async def _probe() -> bool:
            answer = await self.api.get_params([PROVISIONING_PROBE_KEY])
            # A declined request carries none of the requested keys. A present
            # name — populated or empty — means the router served it.
            return PROVISIONING_PROBE_KEY not in answer

        restricted = await self._fetch_optional(
            ENDPOINT_PROVISIONING, _probe, self.provisioning_restricted
        )
        if restricted is not None:
            self.provisioning_restricted = bool(restricted)
            self._last_provisioning_read = now

    def _degraded_endpoints(self) -> list[str]:
        """Return the friendly names of endpoints that have exhausted strikes.

        Only genuine failures count. An endpoint the user turned off, or one the
        hardware does not support, is intentionally-off rather than degraded —
        the distinction Section 19 names as the top false-alarm source. This
        integration has no feature toggles, so every optional endpoint here is
        expected to work and a failure is always real.
        """
        friendly = {
            ENDPOINT_SMS_CAPACITY: "SMS storage capacity",
            ENDPOINT_SMS_MESSAGES: "SMS messages",
            ENDPOINT_EXTENDED: "Extended diagnostics",
        }
        # `ENDPOINT_PROVISIONING` is deliberately absent from the map and
        # excluded below. It feeds one diagnostic sensor that is disabled by
        # default, and reporting the integration degraded because an hourly
        # curiosity failed would train users to ignore the health sensor.
        return [
            friendly.get(source, source)
            for source, failures in self._endpoint_failures.items()
            if failures > FETCH_STRIKE_LIMIT and source != ENDPOINT_PROVISIONING
        ]

    def _active_repairs(self, drift: bool) -> list[str]:
        """Return the repair issues currently raised for this entry."""
        active = []
        if self._unreachable_repair_raised:
            active.append(REPAIR_CONN_ERROR)
        if self._auth_repair_raised:
            active.append(REPAIR_AUTH_FAILED)
        return active

    def _set_unreachable_repair(self, unreachable: bool) -> None:
        """Raise or clear the router-unreachable repair issue.

        Raised only after UNREACHABLE_STRIKE_LIMIT consecutive failures, so a
        reboot or a passing network blip never reaches it. Deliberately does not
        diagnose a cause: ten failed fetches means the router is not answering,
        which could be power, cabling, a changed IP, changed credentials or the
        device itself. The repair text lists what to check rather than asserting
        which one it is. Cleared by the next successful poll.
        """
        if unreachable == self._unreachable_repair_raised:
            return
        if unreachable:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._repair_ids[REPAIR_CONN_ERROR],
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=REPAIR_CONN_ERROR,
                translation_placeholders={
                    "name": self.entry.title,
                    "host": str(self.entry.options.get(CONF_HOST, "unknown")),
                    "count": str(self.consecutive_failures),
                },
            )
        else:
            ir.async_delete_issue(
                self.hass, DOMAIN, self._repair_ids[REPAIR_CONN_ERROR]
            )
        self._unreachable_repair_raised = unreachable

    def _set_auth_repair(self, failed: bool) -> None:
        """Raise or clear the credentials-rejected repair issue.

        Raised only for `ZTECredentialsError` — a password the router actually
        refused. A session that merely lapsed is the integration's problem, and
        a repair telling the user to re-enter working credentials would send
        them to fix something that was never wrong.

        This is the only `is_fixable=True` repair here, and `repairs.py` gives
        it a flow that starts the reauth the text promises. Without that module
        Home Assistant falls back to `ConfirmRepairFlow`, whose Fix button
        shows an empty confirm box and deletes the card — dismissing the
        problem rather than fixing it. `is_persistent` keeps it across a
        restart, since a rejected password is still rejected afterwards.
        """
        if failed == self._auth_repair_raised:
            return
        if failed:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._repair_ids[REPAIR_AUTH_FAILED],
                is_fixable=True,
                is_persistent=True,
                severity=ir.IssueSeverity.ERROR,
                translation_key=REPAIR_AUTH_FAILED,
                translation_placeholders={"name": self.entry.title},
                data={"entry_id": self.entry.entry_id},
            )
        else:
            ir.async_delete_issue(
                self.hass, DOMAIN, self._repair_ids[REPAIR_AUTH_FAILED]
            )
        self._auth_repair_raised = failed

    def _check_contract_drift(self, data: dict[str, Any]) -> bool:
        """Detect a response that succeeded but parsed to nothing meaningful.

        This is the highest-value Section 19 check and the direct catch for a
        firmware change: the poll succeeds, the payload is non-empty, and every
        field the integration reads has vanished or been renamed. Requires a
        baseline from an earlier good poll (startup grace) and must persist for
        the full strike budget before it counts, so a single odd response does
        not raise an alarm.
        """
        # Per concept, not per name: a device that answers `ppp_status` where
        # another answers `wan_connect_status` still reports its connection
        # state, and scoring that as drift would fire on every poll.
        present = {
            concept
            for concept, spellings in CORE_CONCEPTS.items()
            if any(data.get(key) not in (None, "") for key in spellings)
        }

        if not self._drift_baseline:
            # Startup grace — no verdict until a good poll establishes what
            # this router actually returns.
            self._drift_baseline = present
            return False

        if present:
            self._drift_strikes = 0
            # Widen the baseline as the router reports more over time.
            self._drift_baseline |= present
            return False

        self._drift_strikes += 1
        return self._drift_strikes >= HEALTH_DRIFT_STRIKE_LIMIT

    async def async_run_discovery(
        self, sources: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Run the discovery pass under the coordinator's update lock.

        `sources` is the crawl a diagnostics download has already made. Passed
        through rather than re-fetched: mining reads the files the router
        serves, the download reads the same files for its own section, and
        crawling twice costs forty-five requests on the reference device to
        read bodies already in hand.

        The probe shares this coordinator's API client, and a chunk that times
        out clears the session. Running it beside a live poll could score that
        poll expired, and repeating it across chunks could reach
        `FETCH_STRIKE_LIMIT` — marking entities unavailable because the user
        pressed Download Diagnostics. The lock makes the two take turns.
        """
        async with self._async_update_lock:
            result = await self.api.run_discovery(sources=sources)
            # A pass issues several hundred requests in under a minute, and a
            # write attempted immediately afterwards was once refused with an
            # empty transport error on the reference MC7010 — once in two
            # runs, not reproducible on the next. The pause is held inside the
            # lock so the next poll waits for it too, and the user is already
            # waiting for a download.
            await asyncio.sleep(DISCOVERY_SETTLE_SECONDS)
            return result

    async def async_fetch_sms_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """Read the router's message banks under the coordinator's update lock.

        For the diagnostics download, which is the only caller. A poll keeps
        only the newest message — `data["last_sms"]` — so the list itself
        exists nowhere by the time a download is generated, and the number of
        messages the router will actually hand over is what `delete_all`
        operates on. Issue #56 could not be diagnosed without it: an MC888 Pro
        reports a delete as successful and keeps the messages, and a download
        showing the bank empty and a download showing two messages point at
        opposite faults.

        The lock is required for the same reason `async_run_discovery` takes
        it: this shares the coordinator's API client, and the router permits
        one session, so an unsynchronized read can re-login underneath a poll.

        Both banks are read: `SMS_STORE_ALL` for the set `delete_all` operates
        on, and the SIM alone so its count can be reported separately. That
        second read is the only way anyone finds out whether the router's own
        "all" selector really is the union — the reference device has an empty
        SIM, so it cannot answer the question here.

        Holds no state. Failures are the caller's to record.
        """
        async with self._async_update_lock:
            combined = await self.api.get_sms_messages(
                mem_store=SMS_STORE_ALL, tags="10"
            )
            sim = await self.api.get_sms_messages(mem_store=SMS_STORE_SIM, tags="10")
            return {"all": combined, "sim": sim}

    def _sparse_payload_finding(self, data: dict[str, Any]) -> str | None:
        """Report a poll that succeeded while answering almost nothing.

        The MC888 Pro in issue #56 polled successfully with six of eighty-two
        keys populated, because the drift check asks only whether *any*
        contract key is present. A handful of values is neither drift nor an
        expiry, but it is not a healthy poll either, and the only place it was
        visible was a diagnostics download.

        The threshold is relative to what this device has answered before, not
        an absolute count: the reference MC7010 legitimately leaves 46 of 127
        names empty, so a fixed floor would either miss the MC888 case or
        report the MC7010 as faulty every cycle. `_payload_high_water` is the
        most this entry has seen, so the finding fires only on a collapse
        against the device's own history.
        """
        if self._poll_kind != self._high_water_kind:
            self._high_water_by_kind[self._high_water_kind] = self._payload_high_water
            self._payload_high_water = self._high_water_by_kind.get(self._poll_kind, 0)
            self._high_water_kind = self._poll_kind
        populated = sum(1 for value in data.values() if value not in ("", None))
        if populated > self._payload_high_water:
            self._payload_high_water = populated
            return None

        if self._payload_high_water < SPARSE_PAYLOAD_MIN_HISTORY:
            return None

        if populated <= self._payload_high_water * SPARSE_PAYLOAD_FRACTION:
            return (
                f"Sparse payload: {populated} keys populated against "
                f"{self._payload_high_water} previously seen"
            )
        return None

    def _record_health_success(self, data: dict[str, Any]) -> None:
        """Refresh the health snapshot after a successful cycle.

        A success clears the outage verdict in the same cycle — never leaving
        the sensor `on` until some later poll. Wrapped so a malformed payload
        can never crash the very update this diagnoses.
        """
        try:
            issues: list[str] = []
            degraded = self._degraded_endpoints()
            if degraded:
                issues.append(f"Degraded: {', '.join(degraded)}")

            # A success means the router answered, so the unreachable repair is
            # cleared in the same cycle regardless of how long it was raised.
            self._set_unreachable_repair(False)
            self._set_auth_repair(False)

            drift = self._check_contract_drift(data)
            drift_findings = [DRIFT_CONTRACT] if drift else []
            issues.extend(drift_findings)

            sparse = self._sparse_payload_finding(data)
            if sparse:
                issues.append(sparse)

            self.health_snapshot = {
                "problem": bool(issues),
                "issues": issues,
                "severity": "warning"
                if (drift or sparse)
                else ("degraded" if degraded else "ok"),
                "degraded_capabilities": degraded,
                "drift": drift_findings,
                "repairs": self._active_repairs(drift),
                "last_good_update": (
                    self.last_update_success_time.isoformat()
                    if self.last_update_success_time
                    else None
                ),
                "consecutive_failures": 0,
            }
        except Exception:  # pragma: no cover - defensive
            # Section 19: the health computation must never crash the update it
            # exists to diagnose. Any failure degrades to healthy/unknown and is
            # logged at debug — a narrower catch would defeat the requirement.
            _LOGGER.debug(
                "%s: Health computation failed; reporting healthy.",
                self.entry.title,
                exc_info=True,
            )
            self.health_snapshot = {
                "problem": False,
                "issues": [],
                "severity": "unknown",
                "degraded_capabilities": [],
                "drift": [],
                "repairs": [],
                "last_good_update": None,
                "consecutive_failures": 0,
            }

    def _record_health_failure(self, err: Exception) -> None:
        """Refresh the health snapshot after a failed cycle.

        Two regimes, per Section 19. **Cold start** — nothing has ever been
        fetched, so there are no held values and waiting out the strike budget
        would leave the user with a wholly-unavailable integration and no
        explanation; flag on the first failure. **Runtime** — last-known values
        are being served, so a single blip should raise no alarm; flag on the
        Nth consecutive failure, matching the Section 8 strike rule.
        """
        try:
            cold_start = self.data is None
            problem = cold_start or self.consecutive_failures >= FETCH_STRIKE_LIMIT

            issues: list[str] = []
            if problem:
                if cold_start:
                    issues.append(
                        f"Cannot reach the router — no data has been fetched "
                        f"since startup ({err})"
                    )
                else:
                    issues.append(
                        f"Cannot reach the router — "
                        f"{self.consecutive_failures} consecutive failures ({err})"
                    )

            degraded = self._degraded_endpoints()
            if degraded:
                issues.append(f"Degraded: {', '.join(degraded)}")

            self._set_unreachable_repair(
                self.consecutive_failures >= UNREACHABLE_STRIKE_LIMIT
            )

            self.health_snapshot = {
                "problem": problem or bool(degraded),
                "issues": issues,
                "severity": "error" if problem else ("degraded" if degraded else "ok"),
                "degraded_capabilities": degraded,
                # No payload arrived, so no drift verdict is possible. Reported
                # empty rather than held from the last cycle, matching the
                # `_active_repairs(False)` call above.
                "drift": [],
                "repairs": self._active_repairs(False),
                "last_good_update": (
                    self.last_update_success_time.isoformat()
                    if self.last_update_success_time
                    else None
                ),
                "consecutive_failures": self.consecutive_failures,
            }
        except Exception:  # pragma: no cover - defensive
            # Section 19: the health computation must never crash the update it
            # exists to diagnose. Any failure degrades to healthy/unknown and is
            # logged at debug — a narrower catch would defeat the requirement.
            _LOGGER.debug(
                "%s: Health computation failed; reporting healthy.",
                self.entry.title,
                exc_info=True,
            )
            # Write a snapshot rather than leaving the last one standing. The
            # success path already does this; without it the failure path holds
            # a verdict describing a cycle that is over, which is the one thing
            # Section 19 says a health verdict must never do.
            self.health_snapshot = {
                "problem": False,
                "issues": [],
                "severity": "unknown",
                "degraded_capabilities": [],
                "drift": [],
                "repairs": [],
                "last_good_update": None,
                "consecutive_failures": self.consecutive_failures,
            }

    def _check_new_sms(self, messages: list[dict[str, Any]]) -> None:
        """Fire an event for each message this device has not reported before.

        Ordered on parsed instants rather than on the ISO strings. While every
        timestamp carried `+00:00` the two were equivalent, but a message now
        carries its router's own offset, and two messages either side of a
        daylight-saving change carry different ones — where text order and time
        order part company.
        """
        if not messages:
            return

        dated = [
            (instant, msg)
            for msg in messages
            if (instant := sms_instant(msg.get("date_decoded"))) is not None
        ]
        dated.sort(key=lambda pair: pair[0])

        if not dated:
            return

        latest_instant, latest_msg = dated[-1]

        # On first run, just set the baseline timestamp and hashes
        baseline = sms_instant(self.last_sms_timestamp)
        if baseline is None:
            self.last_sms_timestamp = latest_msg["date_decoded"]
            self.fired_sms_hashes = {
                f"{msg['id']}_{msg['date_decoded']}"
                for instant, msg in dated
                if instant == latest_instant
            }
            _LOGGER.debug(
                "%s: SMS tracking baseline established at %s",
                self.entry.title,
                self.last_sms_timestamp,
            )
            return

        new_messages = []
        for instant, msg in dated:
            msg_hash = f"{msg['id']}_{msg['date_decoded']}"
            if instant > baseline or (
                instant == baseline and msg_hash not in self.fired_sms_hashes
            ):
                new_messages.append(msg)

        for msg in new_messages:
            # The sender's number is deliberately not logged (Section 20). It
            # reaches automations on the bus event below, which is scoped to
            # this entry; the log is not, and is copied into every diagnostics
            # download and issue report. The message id is enough to correlate
            # a log line with an event.
            _LOGGER.info(
                "%s: New SMS received (id %s)", self.entry.title, msg.get("id")
            )
            self.hass.bus.async_fire(
                "zte_router_5g_sms_received",
                {
                    "entry_id": self.entry.entry_id,
                    "phone": msg.get("number_decoded"),
                    "content": msg.get("content_decoded"),
                    "date": msg.get("date_decoded"),
                    "index": int(msg.get("id", 0)),
                },
            )

            # Update tracking state
            msg_hash = f"{msg['id']}_{msg['date_decoded']}"
            instant = sms_instant(msg["date_decoded"])
            if instant is not None and instant > baseline:
                baseline = instant
                self.last_sms_timestamp = msg["date_decoded"]
                self.fired_sms_hashes = {msg_hash}
            else:
                self.fired_sms_hashes.add(msg_hash)
