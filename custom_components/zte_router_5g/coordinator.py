"""DataUpdateCoordinator for ZTE Router 5G."""

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ZTEAuthError, ZTERouterAPI
from .const import CONF_SCAN_INTERVAL, CONF_STOP_POLLING, DOMAIN
from .helpers import get_router_model

_LOGGER = logging.getLogger(__name__)

# Minimum drop in the router's uptime counter (seconds) that is treated as a
# genuine reboot. A real reboot resets uptime to ~0, so this margin only serves
# to reject small downward blips from coarse resolution or stale readings.
UPTIME_REBOOT_MARGIN = 30


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
            name=f"{entry.title} Data",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API with resilience and pausing."""
        is_paused = self.entry.options.get(CONF_STOP_POLLING, False)
        is_first_run = self.data is None

        # 1. If paused and NOT the first run, return cached data immediately
        if is_paused and not is_first_run:
            _LOGGER.debug(
                "%s: Polling is paused; returning cached data.", self.entry.title
            )
            return self.data

        try:
            # Use standard timeout wrapper (HA Best Practice)
            async with asyncio.timeout(30):
                try:
                    # Fetch all primary data components
                    data = await self.api.get_all_data()
                    sms_cap = await self.api.get_sms_capacity()
                    # Fetch recent messages to detect events and populate last_sms
                    messages = await self.api.get_sms_messages(mem_store="1", tags="10")
                except ZTEAuthError as auth_err:
                    _LOGGER.info(
                        "%s: Session expired during poll; "
                        "renewing session and retrying: %s",
                        self.entry.title,
                        auth_err,
                    )
                    await self.api.login()
                    data = await self.api.get_all_data()
                    sms_cap = await self.api.get_sms_capacity()
                    messages = await self.api.get_sms_messages(mem_store="1", tags="10")

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
                        if self.imei
                        else f"host_{self.entry.options.get(CONF_HOST, 'unknown')}"
                    )
                    dev_reg = dr.async_get(self.hass)
                    device = dev_reg.async_get_device(
                        identifiers={(DOMAIN, f"{sub_id_prefix}_system")}
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
                self._check_sms_storage(data)
                self._check_new_sms(messages)
                return data

        except TimeoutError as err:
            self.consecutive_failures += 1
            if self.data is not None and self.consecutive_failures <= 3:
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
            if self.data is not None and self.consecutive_failures <= 3:
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

            _LOGGER.warning(
                "%s: Authentication failed: %s",
                self.entry.title,
                err,
            )
            self._was_available = False
            if self.consecutive_failures >= 3:
                _LOGGER.error(
                    "%s: Authentication failed 3 or more times consecutively. "
                    "Triggering reauth.",
                    self.entry.title,
                )
                self.entry.async_start_reauth(self.hass)
            raise UpdateFailed(f"Authentication failed: {err}") from err

        except Exception as err:
            self.consecutive_failures += 1
            # Failure resilience — hold last known values for three cycles
            if self.data is not None and self.consecutive_failures <= 3:
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

    def _check_sms_storage(self, data: dict[str, Any]) -> None:
        """Create or clear the SMS storage full repair issue."""
        try:
            nv_able = int(data.get("nv_sms_able") or 0)
            nv_total = int(data.get("sms_nv_total") or 0)
        except (ValueError, TypeError):
            return
        if nv_able > 0 and nv_total >= nv_able:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "sms_storage_full",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="sms_storage_full",
                translation_placeholders={
                    "nv_total": str(nv_total),
                    "nv_able": str(nv_able),
                },
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, "sms_storage_full")

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
