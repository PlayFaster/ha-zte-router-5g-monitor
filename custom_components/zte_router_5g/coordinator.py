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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ._compat import device_by_identifier
from .api import ZTEAuthError, ZTECredentialsError, ZTERouterAPI
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_STOP_POLLING,
    DOMAIN,
    FETCH_STRIKE_LIMIT,
    UNREACHABLE_STRIKE_LIMIT,
)
from .helpers import get_router_model

_LOGGER = logging.getLogger(__name__)

# Minimum drop in the router's uptime counter (seconds) that is treated as a
# genuine reboot. A real reboot resets uptime to ~0, so this margin only serves
# to reject small downward blips from coarse resolution or stale readings.
UPTIME_REBOOT_MARGIN = 30


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

# Every repair this integration can raise. The names double as `translation_key`
# values, which stay bare; only the registry **id** carries the entry (see
# `_repair_ids`). Adding one means adding it here, or unload will not clear it.
REPAIR_NAMES = ("router_unreachable", "firmware_contract_drift", "sms_storage_full")

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
CORE_KEYS = (
    "network_type",
    "signalbar",
    "realtime_time",
    "wan_connect_status",
)

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
        self.last_update_success_time: datetime | None = None
        self._was_available = True
        self._boot_time: datetime | None = None
        self._last_uptime: int | None = None
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
        self._drift_repair_raised = False
        self._unreachable_repair_raised = False
        self._sms_storage_full = False

        # Snapshot of the non-live options this entry was set up with; the
        # update listener diffs against it to decide reload vs live-apply.
        self.reload_signature: dict[str, Any] = {}
        boot_time_str = entry.data.get("boot_time")
        if boot_time_str:
            with contextlib.suppress(Exception):
                self._boot_time = dt_util.parse_datetime(boot_time_str)
        last_uptime_raw = entry.data.get("last_uptime")
        if last_uptime_raw is not None:
            with contextlib.suppress(ValueError, TypeError):
                self._last_uptime = int(last_uptime_raw)

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
        """Delete repairs raised under the old unscoped ids.

        Before the ids carried the entry, all three were raised under their
        bare names. `ir.async_delete_issue` looks up by id, so a repair still
        live under an old name has no code left that can clear it and no UI
        path either — they are all `is_fixable=False`. Called once at setup, so
        the rename cannot strand one. Safe to keep indefinitely: deleting an
        issue that does not exist is a no-op.
        """
        for name in REPAIR_NAMES:
            ir.async_delete_issue(self.hass, DOMAIN, name)

    def clear_repairs(self) -> None:
        """Clear every repair this entry raised.

        Called on unload **and** on removal. Without it a user who deletes the
        integration while a repair is showing keeps it in the Repairs panel
        permanently: `is_fixable=False`, and the integration that would clear
        it is gone.
        """
        for issue_id in self._repair_ids.values():
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._drift_repair_raised = False
        self._unreachable_repair_raised = False
        self._sms_storage_full = False

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
                    raw_uptime = data.get("realtime_time")
                    if raw_uptime is not None:
                        seconds = int(float(raw_uptime))

                if seconds is None or seconds < 0:
                    # Bad-reading guard: keep the latched value untouched and do
                    # not advance the reboot anchor on a missing/garbage reading.
                    data["boot_time"] = self._boot_time
                else:
                    is_reboot = self._boot_time is None or (
                        self._last_uptime is not None
                        and seconds < self._last_uptime - UPTIME_REBOOT_MARGIN
                    )
                    if is_reboot:
                        calc_time = dt_util.now() - timedelta(seconds=seconds)
                        self._boot_time = calc_time.replace(microsecond=0)
                        new_data = {
                            **self.entry.data,
                            "boot_time": self._boot_time.isoformat(),
                            "last_uptime": seconds,
                        }
                        self.hass.config_entries.async_update_entry(
                            self.entry, data=new_data
                        )
                    self._last_uptime = seconds
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
                # Storage check first, so its repair state is current when the
                # health snapshot reflects it rather than a cycle stale.
                self._check_sms_storage(data)
                self._record_health_success(data)
                self._check_new_sms(messages)
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
                        "%s: Error fetching ZTE data (failure %d/3): %s",
                        self.entry.title,
                        self.consecutive_failures,
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
                        "%s: Authentication failed (failure %d/3): %s",
                        self.entry.title,
                        self.consecutive_failures,
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
                        "%s: Error fetching ZTE data (failure %d/3): %s",
                        self.entry.title,
                        self.consecutive_failures,
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
        return [
            friendly.get(source, source)
            for source, failures in self._endpoint_failures.items()
            if failures > FETCH_STRIKE_LIMIT
        ]

    def _active_repairs(self, drift: bool) -> list[str]:
        """Return the repair issues currently raised for this entry."""
        active = []
        if self._sms_storage_full:
            active.append("sms_storage_full")
        if drift:
            active.append("firmware_contract_drift")
        if self._unreachable_repair_raised:
            active.append("router_unreachable")
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
                self._repair_ids["router_unreachable"],
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="router_unreachable",
                translation_placeholders={
                    "name": self.entry.title,
                    "host": str(self.entry.options.get(CONF_HOST, "unknown")),
                    "count": str(self.consecutive_failures),
                },
            )
        else:
            ir.async_delete_issue(
                self.hass, DOMAIN, self._repair_ids["router_unreachable"]
            )
        self._unreachable_repair_raised = unreachable

    def _set_drift_repair(self, drift: bool) -> None:
        """Raise or clear the contract-drift repair issue.

        Section 19's second tier: a serious, named, actionable condition earns a
        Repair alongside the sensor. Drift qualifies because the user can act —
        report it so the integration can be updated — and it auto-clears on the
        next clean cycle. Kept to this one condition so the Repairs panel does
        not fill with noise; ordinary unreachability is already visible as
        unavailable entities and needs no repair.
        """
        if drift == self._drift_repair_raised:
            return
        if drift:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._repair_ids["firmware_contract_drift"],
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="firmware_contract_drift",
                translation_placeholders={"name": self.entry.title},
            )
        else:
            ir.async_delete_issue(
                self.hass, DOMAIN, self._repair_ids["firmware_contract_drift"]
            )
        self._drift_repair_raised = drift

    def _check_contract_drift(self, data: dict[str, Any]) -> bool:
        """Detect a response that succeeded but parsed to nothing meaningful.

        This is the highest-value Section 19 check and the direct catch for a
        firmware change: the poll succeeds, the payload is non-empty, and every
        field the integration reads has vanished or been renamed. Requires a
        baseline from an earlier good poll (startup grace) and must persist for
        the full strike budget before it counts, so a single odd response does
        not raise an alarm.
        """
        present = {key for key in CORE_KEYS if data.get(key) not in (None, "")}

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
        return self._drift_strikes >= FETCH_STRIKE_LIMIT

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

            drift = self._check_contract_drift(data)
            drift_findings = [DRIFT_CONTRACT] if drift else []
            issues.extend(drift_findings)
            self._set_drift_repair(drift)

            # Reflect an existing repair rather than double-raising it — the
            # SMS-storage issue is owned by _check_sms_storage.
            if self._sms_storage_full:
                issues.append("SMS storage is full")

            self.health_snapshot = {
                "problem": bool(issues),
                "issues": issues,
                "severity": "warning" if drift else ("degraded" if degraded else "ok"),
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

    def _check_sms_storage(self, data: dict[str, Any]) -> None:
        """Create or clear the SMS storage full repair issue."""
        try:
            nv_able = int(data.get("nv_sms_able") or 0)
            nv_total = int(data.get("sms_nv_total") or 0)
        except (ValueError, TypeError):
            return
        self._sms_storage_full = nv_able > 0 and nv_total >= nv_able
        if self._sms_storage_full:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._repair_ids["sms_storage_full"],
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="sms_storage_full",
                translation_placeholders={
                    "nv_total": str(nv_total),
                    "nv_able": str(nv_able),
                },
            )
        else:
            ir.async_delete_issue(
                self.hass, DOMAIN, self._repair_ids["sms_storage_full"]
            )

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
            _LOGGER.info(
                "%s: New SMS from %s", self.entry.title, msg.get("number_decoded")
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
