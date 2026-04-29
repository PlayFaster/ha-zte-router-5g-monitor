"""DataUpdateCoordinator for ZTE Router 5G."""

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_SCAN_INTERVAL, CONF_STOP_POLLING
from .helpers import get_router_model

_LOGGER = logging.getLogger(__name__)


class ZTERouterDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching ZTE Router data with resilience and pausing."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api):
        """Initialize the coordinator."""
        self.api = api
        self.entry = entry
        self.consecutive_failures = 0
        self.last_update_success_time = None

        # Load hardware identity from persistent ConfigEntry data.
        # This ensures device info is stable from boot (The "Flat Identity" pattern).
        self.model = entry.data.get("model", "ZTE Router")
        self.sw_version = entry.data.get("sw_version")
        self.mac = entry.data.get("mac")

        # Determine the initial update interval from entry options
        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, 180)

        super().__init__(
            hass,
            _LOGGER,
            name=f"{entry.title} Data",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self):
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

                    new_data = dict(self.entry.data)
                    new_data.update({"model": new_model, "sw_version": new_version})
                    self.hass.config_entries.async_update_entry(
                        self.entry, data=new_data
                    )

                # Success path
                self.last_update_success_time = dt_util.now()
                self.consecutive_failures = 0
                return data

        except TimeoutError as err:
            self.consecutive_failures += 1
            if self.data is not None and self.consecutive_failures <= 3:
                _LOGGER.warning(
                    "%s: Error fetching ZTE data (failure %d/3), "
                    "holding last known values: %s",
                    self.entry.title,
                    self.consecutive_failures,
                    err,
                )
                return self.data
            _LOGGER.error("%s: API request timed out", self.entry.title)
            raise UpdateFailed("API request timed out") from err

        except Exception as err:
            self.consecutive_failures += 1
            # Failure resilience — hold last known values for three cycles
            if self.data is not None and self.consecutive_failures <= 3:
                _LOGGER.warning(
                    "%s: Error fetching ZTE data (failure %d/3), "
                    "holding last known values: %s",
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
            raise UpdateFailed(f"Communication error: {err}") from err
