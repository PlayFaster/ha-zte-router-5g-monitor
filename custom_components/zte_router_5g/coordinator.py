"""DataUpdateCoordinator for ZTE Router 5G."""

import asyncio
import logging
from datetime import timedelta
from typing import Any, cast

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


class ZTERouterDataUpdateCoordinator(DataUpdateCoordinator):  # type: ignore[misc]
    """Class to manage fetching ZTE Router data with resilience and pausing."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: ZTERouterAPI
    ) -> None:
        """Initialize the coordinator."""
        self.api = api
        self.entry = entry
        self.consecutive_failures = 0
        self.last_update_success_time = None
        self._was_available = True

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
            return cast(dict[str, Any], self.data)

        try:
            # Use standard timeout wrapper (HA Best Practice)
            async with asyncio.timeout(30):
                # Fetch all primary data components
                data = await self.api.get_all_data()
                sms_cap = await self.api.get_sms_capacity()
                last_sms = await self.api.get_last_sms_content()

                data.update(sms_cap)
                data["last_sms"] = last_sms

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
                return cast(dict[str, Any], self.data)
            _LOGGER.error("%s: API request timed out", self.entry.title)
            self._was_available = False
            raise UpdateFailed("API request timed out") from err

        except ZTEAuthError as err:
            self.consecutive_failures += 1
            _LOGGER.warning(
                "%s: Authentication failed, triggering reauth: %s",
                self.entry.title,
                err,
            )
            self._was_available = False
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
                return cast(dict[str, Any], self.data)

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
        except ValueError, TypeError:
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
