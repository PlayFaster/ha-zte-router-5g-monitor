"""DataUpdateCoordinator for ZTE Router 5G."""

import asyncio
import contextlib
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ._compat import device_by_identifier
from .api import ZTEAuthError, ZTECredentialsError, ZTERouterAPI
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_STOP_POLLING,
    DISCOVERY_SETTLE_SECONDS,
    DOMAIN,
    FETCH_STRIKE_LIMIT,
    HEALTH_DRIFT_STRIKE_LIMIT,
    REPAIR_AUTH_FAILED,
    REPAIR_CONN_ERROR,
    SPARSE_PAYLOAD_FRACTION,
    SPARSE_PAYLOAD_MIN_HISTORY,
    UNREACHABLE_STRIKE_LIMIT,
)
from .helpers import get_router_model

_LOGGER = logging.getLogger(__name__)

# Minimum drop in the router's uptime counter (seconds) that is treated as a
# genuine reboot. A real reboot resets uptime to ~0, so this margin only serves
# to reject small downward blips from coarse resolution or stale readings.
UPTIME_REBOOT_MARGIN = 30

# How far the boot instant derived from a live counter may sit from the stored
# one and still be judged the same boot. Applied once per Home Assistant start
# and never during a running session, so it cannot reintroduce polling jitter.
# It absorbs drift between the Home Assistant clock and the router's counter
# accumulated across an offline period: a crystal at 100 ppm drifts roughly
# three minutes over three weeks. Estimated, not measured — confirm from the
# reconciliation logs and adjust.
BOOT_MATCH_TOLERANCE = 600

# A stored boot instant further ahead of now() than this is rejected as
# invalid. It can only arise from a latch taken against a clock that was wrong
# and has since been corrected.
BOOT_FUTURE_TOLERANCE = 300

# Below this year the system clock is treated as unset rather than wrong. A
# host without a battery-backed real-time clock, including most Raspberry Pi
# units, starts at 1970-01-01 and stays there until NTP completes; re-latching
# in that window writes a boot instant decades adrift. **Do not delete this as
# an arbitrary constant** — it exists for that specific startup window.
CLOCK_FLOOR_YEAR = 2024

# An uptime beyond this is rejected as a bad reading rather than believed.
# Ten years, comfortably past any plausible consumer router.
MAX_PLAUSIBLE_UPTIME = 10 * 365 * 24 * 3600

# Storage for the running uptime counter. The counter is persisted on a fixed
# interval as well as on every latch, so the counter-regression check has a
# reasonably current baseline after a restart. `boot_time` stays in
# `entry.data`: a boot instant does not go stale, so it needs no maintenance.
UPTIME_STORAGE_VERSION = 1
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
    "uptime": ("realtime_time", "flux_realtime_time"),
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
        # Serializes a diagnostics discovery probe against the poll; both use
        # the same API client and the same session.
        self._async_update_lock = asyncio.Lock()
        self.last_update_success_time: datetime | None = None
        self._was_available = True
        self._boot_time: datetime | None = None
        self._last_uptime: int | None = None

        # Startup reconciliation state. `_startup_reconciled` stays false until
        # a poll yields a usable counter and the reconciliation completes, so a
        # failed or guard-rejected poll defers it rather than skipping it.
        # `_pending_startup_strike` carries the one-poll wait: the runtime
        # comparison cannot revisit it, because the first poll sets
        # `_last_uptime` from the live reading and finds no regression against
        # it on the second.
        self._startup_reconciled = False
        self._pending_startup_strike = False
        self._store: Store[dict[str, Any]] | None = None
        self._stored_last_uptime: int | None = None
        self._last_counter_write: datetime | None = None
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
        # The boot instant is physically constant between reboots, so a value
        # written weeks ago is still correct and is restored as-is. A naive or
        # unparsable value is treated as absent, which routes to an
        # unconditional latch on the first poll rather than raising when it is
        # subtracted from an aware datetime.
        boot_time_str = entry.data.get("boot_time")
        if boot_time_str:
            with contextlib.suppress(Exception):
                parsed = dt_util.parse_datetime(boot_time_str)
                if parsed is not None and parsed.tzinfo is not None:
                    self._boot_time = parsed

        # `entry.data["last_uptime"]` is deliberately NOT read. It is written
        # only on a latch, so it is frozen at whatever small value the previous
        # reboot recorded, and comparing a live counter against it is the
        # defect this design replaces. The counter comes from the store
        # instead; the legacy key is dropped on the next latch.

        # Load hardware identity from persistent ConfigEntry data.
        # This ensures device info is stable from boot (The "Flat Identity" pattern).
        self.model = entry.data.get("model", "ZTE Router")
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
        data = await self.api.get_all_data()
        # Merged under the core payload rather than over it, so a stale cached
        # extended value can never mask a fresh core one if the two ever come
        # to share a key.
        extended = await self._fetch_optional(
            ENDPOINT_EXTENDED, self.api.get_extended_data, {}
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

        The lock is the point. `async_run_discovery` has taken it since the
        probe was added, with a comment saying the two "take turns" — but this
        method never acquired it, so nothing was serialized and the guard did
        nothing at all.

        What that allowed: a scheduled poll running during a diagnostics
        download shares this coordinator's `ZTERouterAPI`, and a poll that
        judges the session expired re-logs in. The router permits one session,
        so the new login invalidates the cookie the discovery pass is
        replaying. Discovery probes run with `authenticated=False` precisely so
        that a probe never silently re-authenticates and samples an
        authenticated response, which means they cannot recover: they simply go
        blank, and their names are recorded as unanswered.

        Measured directly. With a competing client logging in every 180
        seconds, 2 of 12 passes came back having read 413 and 445 names without
        a session against 16 in a healthy pass; with the competitor paused, 0
        of 12. This closes the same window for the poll inside our own process.

        A discovery pass can hold this for the length of its budget, so a poll
        may wait. That is the correct trade: a delayed poll holds last known
        values for one cycle, while an overlapping one corrupts a download the
        user is waiting on and publishes absences that were never measured.
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
        if is_paused and not is_first_run and not forced:
            _LOGGER.debug(
                "%s: Polling is paused; returning cached data.", self.entry.title
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
                seconds: int | None = None
                with contextlib.suppress(ValueError, TypeError):
                    # Aliased: a device that spells this `flux_realtime_time`
                    # would otherwise never latch a boot time, and the uptime
                    # sensor would sit at `unknown` forever. Mirrors
                    # `sensor._ALIAS_REALTIME_TIME`, which `sensor.py` cannot
                    # be imported from here — `test_uptime_alias_matches_the
                    # _sensor_tuple` fails if the two diverge.
                    raw_uptime = data.get("realtime_time") or data.get(
                        "flux_realtime_time"
                    )
                    if raw_uptime is not None:
                        seconds = int(float(raw_uptime))

                if seconds is None or seconds < 0:
                    # Bad-reading guard: keep the latched value untouched and do
                    # not advance the reboot anchor on a missing/garbage reading.
                    data["boot_time"] = self._boot_time
                else:
                    self._apply_uptime(seconds)
                    data["boot_time"] = self._boot_time

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
                        self.imei
                        or f"host_{self.entry.options.get(CONF_HOST, 'unknown')}"
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
                self._check_new_sms(messages)
                await self._read_provisioning(forced=forced)
                return data

        except TimeoutError as err:
            self.consecutive_failures += 1
            self._record_health_failure(err)
            if (
                self.data is not None
                and self.consecutive_failures <= FETCH_STRIKE_LIMIT
            ):
                if self.consecutive_failures == 1:
                    _LOGGER.warning(
                        "%s: Error fetching ZTE data, holding last known values: %s",
                        self.entry.title,
                        err,
                    )
                else:
                    _LOGGER.debug(
                        "%s: Error fetching ZTE data (failure %d/%d): %s",
                        self.entry.title,
                        self.consecutive_failures,
                        FETCH_STRIKE_LIMIT,
                        err,
                    )
                return self.data
            _LOGGER.error("%s: API request timed out", self.entry.title)
            self._was_available = False
            raise UpdateFailed("API request timed out") from err

        except ZTEAuthError as err:
            self.consecutive_failures += 1
            self._record_health_failure(err)
            if (
                self.data is not None
                and self.consecutive_failures <= FETCH_STRIKE_LIMIT
            ):
                if self.consecutive_failures == 1:
                    _LOGGER.warning(
                        "%s: Authentication failed, holding last known values: %s",
                        self.entry.title,
                        err,
                    )
                else:
                    _LOGGER.debug(
                        "%s: Authentication failed (failure %d/%d): %s",
                        self.entry.title,
                        self.consecutive_failures,
                        FETCH_STRIKE_LIMIT,
                        err,
                    )
                return self.data

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
            self.consecutive_failures += 1
            self._record_health_failure(err)
            # Failure resilience — hold last known values for three cycles
            if (
                self.data is not None
                and self.consecutive_failures <= FETCH_STRIKE_LIMIT
            ):
                if self.consecutive_failures == 1:
                    _LOGGER.warning(
                        "%s: Error fetching ZTE data, holding last known values: %s",
                        self.entry.title,
                        err,
                    )
                else:
                    _LOGGER.debug(
                        "%s: Error fetching ZTE data (failure %d/%d): %s",
                        self.entry.title,
                        self.consecutive_failures,
                        FETCH_STRIKE_LIMIT,
                        err,
                    )
                return self.data

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

    # ------------------------------------------------------------------
    # Boot-time latch
    #
    # Two checks decide whether the router rebooted while Home Assistant was
    # not watching, and they do not carry equal weight. A counter that has
    # moved backward is conclusive: no clock is involved, and while the counter
    # is monotonic the check cannot produce a false positive. A boot instant
    # that has moved is suggestive but derived from now(), so on its own it
    # waits one poll before acting.
    #
    # Full specification, including both worked failure modes:
    # `.shared/info/uptime_timestamp/uptime_timestamp_router_vs_ha_202608.md`.
    # ------------------------------------------------------------------

    async def async_load_stored_uptime(self) -> None:
        """Load the persisted uptime counter. Never raises.

        Awaited in ``async_setup_entry`` so the counter is in memory before the
        background initialization task runs the first poll. An absent, corrupt
        or unreadable record resolves to "no stored counter", which skips the
        counter-regression check and leaves the boot-instant check fully
        functional on its own — the store is a cross-check, never the anchor.
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
            # can fail entry setup: the store is a cross-check, and the
            # boot-instant check works without it. Narrowing this to the
            # exceptions seen so far would let an unanticipated one abort a
            # setup that has no need of the store at all.
            _LOGGER.debug(
                "%s: uptime store unreadable, continuing without it: %s",
                self.entry.title,
                err,
            )
            return
        if isinstance(stored, dict):
            with contextlib.suppress(ValueError, TypeError):
                raw = stored.get("last_uptime")
                if raw is not None:
                    self._stored_last_uptime = int(raw)

    def _apply_uptime(self, seconds: int) -> None:
        """Route one usable counter reading to startup or runtime handling."""
        now = dt_util.now()

        if now.year < CLOCK_FLOOR_YEAR:
            # Clock floor guard: the host has no battery-backed clock and NTP
            # has not completed. Defer rather than latch a boot instant that
            # would be decades adrift.
            _LOGGER.debug(
                "%s: system clock reads %s; deferring uptime reconciliation",
                self.entry.title,
                now.isoformat(),
            )
            return
        if seconds > MAX_PLAUSIBLE_UPTIME:
            _LOGGER.warning(
                "%s: implausible uptime %s s; keeping the stored boot time",
                self.entry.title,
                seconds,
            )
            return

        if self._startup_reconciled:
            self._apply_runtime_uptime(seconds, now)
        else:
            self._reconcile_startup_uptime(seconds, now)

        self._last_uptime = seconds
        self._maybe_persist_counter(seconds, now)

    def _apply_runtime_uptime(self, seconds: int, now: datetime) -> None:
        """Compare the counter against itself during an unbroken session.

        Exact, and the reason the latch is stable: the router's hardware
        counter is compared with its own previous value, so no clock enters the
        comparison and no jitter can reach the timestamp.
        """
        if (
            self._last_uptime is not None
            and seconds < self._last_uptime - UPTIME_REBOOT_MARGIN
        ):
            self._latch_boot_time(now - timedelta(seconds=seconds), seconds)

    def _reconcile_startup_uptime(self, seconds: int, now: datetime) -> None:
        """Decide, on the first usable poll, whether the router rebooted."""
        raw_boot = (now - timedelta(seconds=seconds)).replace(microsecond=0)
        stored_boot = self._boot_time

        if stored_boot is not None and dt_util.as_utc(stored_boot) > dt_util.as_utc(
            now
        ) + timedelta(seconds=BOOT_FUTURE_TOLERANCE):
            # Only reachable from a latch taken against a clock that was wrong
            # and has since been corrected.
            _LOGGER.warning(
                "%s: stored boot time %s is in the future; re-latching",
                self.entry.title,
                stored_boot.isoformat(),
            )
            stored_boot = None

        if stored_boot is None:
            self._latch_boot_time(raw_boot, seconds)
            self._finish_startup()
            return

        boot_diverged = (
            abs(
                (dt_util.as_utc(raw_boot) - dt_util.as_utc(stored_boot)).total_seconds()
            )
            > BOOT_MATCH_TOLERANCE
        )
        counter_regressed = (
            self._stored_last_uptime is not None
            and seconds < self._stored_last_uptime - UPTIME_REBOOT_MARGIN
        )

        if self._pending_startup_strike:
            self._resolve_startup_strike(raw_boot, seconds, boot_diverged, stored_boot)
            return

        if counter_regressed:
            # Conclusive on its own, whatever the boot-instant check reports.
            self._log_reconciliation(
                "counter regression", seconds, stored_boot, raw_boot
            )
            self._latch_boot_time(raw_boot, seconds)
            self._finish_startup()
            return

        if boot_diverged:
            # The only combination that waits. It is also the expected shape of
            # a genuine long-gap reboot whose stored counter has aged, so the
            # wait guards against a single bad reading or an unsynchronized
            # clock rather than expressing doubt about the reboot.
            _LOGGER.warning(
                "%s: boot instant moved but the counter did not regress "
                "(live %s s, stored counter %s, stored boot %s, derived %s); "
                "deferring the decision one poll",
                self.entry.title,
                seconds,
                self._stored_last_uptime,
                stored_boot.isoformat(),
                raw_boot.isoformat(),
            )
            self._pending_startup_strike = True
            return

        self._log_reconciliation("no reboot", seconds, stored_boot, raw_boot)
        self._finish_startup()

    def _resolve_startup_strike(
        self,
        raw_boot: datetime,
        seconds: int,
        boot_diverged: bool,
        stored_boot: datetime,
    ) -> None:
        """Take the deferred decision on the next usable poll."""
        if boot_diverged:
            self._log_reconciliation(
                "boot instant, confirmed on the second poll",
                seconds,
                stored_boot,
                raw_boot,
            )
            self._latch_boot_time(raw_boot, seconds)
        else:
            # A warning was recorded against the first poll. Answer it, so the
            # log does not leave an unresolved alarm behind.
            _LOGGER.info(
                "%s: the deferred boot-time divergence was a false alarm "
                "(live %s s, stored boot %s, derived %s); keeping the stored "
                "boot time",
                self.entry.title,
                seconds,
                stored_boot.isoformat(),
                raw_boot.isoformat(),
            )
        self._finish_startup()

    def _finish_startup(self) -> None:
        """Mark startup reconciliation complete and clear the pending wait."""
        self._startup_reconciled = True
        self._pending_startup_strike = False

    def _log_reconciliation(
        self,
        outcome: str,
        seconds: int,
        stored_boot: datetime | None,
        raw_boot: datetime,
    ) -> None:
        """Record every input to a startup decision, and the decision."""
        _LOGGER.info(
            "%s: uptime reconciliation — %s (live %s s, stored counter %s, "
            "stored boot %s, derived boot %s)",
            self.entry.title,
            outcome,
            seconds,
            self._stored_last_uptime,
            stored_boot.isoformat() if stored_boot is not None else None,
            raw_boot.isoformat(),
        )

    def _latch_boot_time(self, boot_time: datetime, seconds: int) -> None:
        """Re-anchor the boot instant and persist it immediately."""
        self._boot_time = boot_time.replace(microsecond=0)
        _LOGGER.info(
            "%s: boot time latched: %s", self.entry.title, self._boot_time.isoformat()
        )
        # The legacy `last_uptime` key is dropped here. It is never read, and
        # leaving it invites a future reader to wire it back in.
        new_data = {
            key: value for key, value in self.entry.data.items() if key != "last_uptime"
        }
        new_data["boot_time"] = self._boot_time.isoformat()
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)
        self._write_counter(seconds, dt_util.now())

    def _maybe_persist_counter(self, seconds: int, now: datetime) -> None:
        """Flush the running counter on a fixed interval.

        Bounds how far behind the stored counter can fall, for every stop
        condition rather than only an orderly one. A clean shutdown is covered
        as well without a hook: ``async_delay_save`` registers a final-write
        listener that flushes any pending save when Home Assistant stops.
        """
        if (
            self._last_counter_write is not None
            and now - self._last_counter_write < UPTIME_WRITE_INTERVAL
        ):
            return
        self._write_counter(seconds, now)

    def _write_counter(self, seconds: int, now: datetime) -> None:
        """Schedule a debounced write of the running counter."""
        if self._store is None:  # pragma: no cover - store is loaded at setup
            return
        self._stored_last_uptime = seconds
        self._last_counter_write = now
        self._store.async_delay_save(
            lambda: {"last_uptime": seconds}, UPTIME_SAVE_DELAY
        )

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

    async def async_run_discovery(self) -> dict[str, Any]:
        """Run the discovery pass under the coordinator's update lock.

        The probe shares this coordinator's API client, and a chunk that times
        out clears the session. Running it beside a live poll could score that
        poll expired, and repeating it across chunks could reach
        `FETCH_STRIKE_LIMIT` — marking entities unavailable because the user
        pressed Download Diagnostics. The lock makes the two take turns.
        """
        async with self._async_update_lock:
            result = await self.api.run_discovery()
            # A pass issues several hundred requests in under a minute, and a
            # write attempted immediately afterwards was once refused with an
            # empty transport error on the reference MC7010 — once in two
            # runs, not reproducible on the next. The pause is held inside the
            # lock so the next poll waits for it too, and the user is already
            # waiting for a download.
            await asyncio.sleep(DISCOVERY_SETTLE_SECONDS)
            return result

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
        """Check for new SMS messages and fire events."""
        if not messages:
            return

        # Sort by date decoded ascending (oldest first) to ensure events fire in order.
        # Filter out messages that lack a valid date_decoded.
        sms_list = [m for m in messages if m.get("date_decoded")]
        sms_list.sort(key=lambda x: x["date_decoded"])

        if not sms_list:
            return

        # On first run, just set the baseline timestamp and hashes
        if self.last_sms_timestamp is None:
            self.last_sms_timestamp = sms_list[-1]["date_decoded"]
            self.fired_sms_hashes = {
                f"{msg['id']}_{msg['date_decoded']}"
                for msg in sms_list
                if msg["date_decoded"] == self.last_sms_timestamp
            }
            _LOGGER.debug(
                "%s: SMS tracking baseline established at %s",
                self.entry.title,
                self.last_sms_timestamp,
            )
            return

        new_messages = []
        for msg in sms_list:
            msg_hash = f"{msg['id']}_{msg['date_decoded']}"
            if msg["date_decoded"] > self.last_sms_timestamp or (
                msg["date_decoded"] == self.last_sms_timestamp
                and msg_hash not in self.fired_sms_hashes
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
            if msg["date_decoded"] > self.last_sms_timestamp:
                self.last_sms_timestamp = msg["date_decoded"]
                self.fired_sms_hashes = {msg_hash}
            else:
                self.fired_sms_hashes.add(msg_hash)
