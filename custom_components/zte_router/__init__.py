import logging
import asyncio
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ZTERouterAPI
from .const import DOMAIN, COORDINATOR, CONF_SCAN_INTERVAL, CONF_STOP_POLLING

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR, 
    Platform.BUTTON, 
    Platform.BINARY_SENSOR, 
    Platform.NUMBER, 
    Platform.SWITCH
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ZTE Router from a config entry."""
    api = ZTERouterAPI(
        entry.data[CONF_HOST],
        entry.data.get(CONF_USERNAME),
        entry.data[CONF_PASSWORD]
    )

    await hass.async_add_executor_job(api.try_set_protocol)

    # Read persisted values from entry.options
    stop_polling = entry.options.get(CONF_STOP_POLLING, False)
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, 180)

    # State tracking for polling controls and resilience
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        CONF_STOP_POLLING: stop_polling,
        CONF_SCAN_INTERVAL: scan_interval,
        "consecutive_failures": 0 
    }

    async def async_update_data():
        """Fetch data from API with enhanced fail-safe for startup."""
        entry_data = hass.data[DOMAIN][entry.entry_id]
        is_paused = entry_data.get(CONF_STOP_POLLING, False)
        is_first_run = coordinator.data is None

        # 1. If paused and NOT the first run, return cached data immediately
        if is_paused and not is_first_run:
            _LOGGER.debug("ZTE Router: Polling is paused; returning cached data.")
            return coordinator.data

        # 2. Attempt Fetch
        last_error = None
        for attempt in range(2):
            try:
                data = await hass.async_add_executor_job(api.get_all_data)
                sms_cap = await hass.async_add_executor_job(api.get_sms_capacity)
                last_sms = await hass.async_add_executor_job(api.get_last_sms_content)
                
                data.update(sms_cap)
                data["last_sms"] = last_sms
                
                # Success: Record the timestamp and reset failure count
                coordinator.last_update_success_time = dt_util.now()
                entry_data["consecutive_failures"] = 0
                return data
                
            except Exception as err:
                last_error = err
                if attempt == 0:
                    # Shorter wait during boot/retry for better responsiveness
                    _LOGGER.warning("ZTE Router: Fetch failed, retrying in 30 seconds...")
                    await asyncio.sleep(30)
                else:
                    _LOGGER.warning("ZTE Router: Second fetch attempt failed for this cycle")

        # 3. Hybrid Resilience (Grace Period)
        entry_data["consecutive_failures"] += 1
        
        # If we have data from a previous success, use it to prevent "Unavailable"
        if coordinator.data is not None:
            if entry_data["consecutive_failures"] == 1:
                _LOGGER.warning("ZTE Router: Fetch failed. Holding last known values for one cycle.")
            return coordinator.data

        # 4. Critical Logic: Safe Startup
        # If we are PAUSED and the first fetch fails, return an empty dict.
        # This prevents UpdateFailed from "bricking" the entities in the UI.
        if is_paused:
            _LOGGER.warning("ZTE Router: Initial fetch failed while paused. Starting with empty data to maintain UI control.")
            return {}

        # 5. Hard Fail
        # If we are NOT paused and we've failed 2+ cycles, mark as unavailable
        _LOGGER.error("ZTE Router: Connection lost. Marking entities unavailable.")
        raise UpdateFailed(f"Error communicating with API: {last_error}")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="ZTE Router Data",
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )
    
    coordinator.last_update_success_time = None

    # This will now finish successfully even if the router is offline, provided it's paused
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id][COORDINATOR] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)