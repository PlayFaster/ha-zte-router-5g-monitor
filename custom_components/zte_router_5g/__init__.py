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
    """Set up ZTE Router 5G Monitor from a config entry with Background Safety."""
    api = ZTERouterAPI(
        entry.data[CONF_HOST],
        entry.data.get(CONF_USERNAME),
        entry.data[CONF_PASSWORD]
    )

    # Initial state from options
    stop_polling = entry.options.get(CONF_STOP_POLLING, False)
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, 180)

    # Initialize data storage immediately
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        CONF_STOP_POLLING: stop_polling,
        CONF_SCAN_INTERVAL: scan_interval,
        "consecutive_failures": 0 
    }

    async def async_update_data():
        """Fetch data from API with resilience and pausing."""
        entry_data = hass.data[DOMAIN][entry.entry_id]
        
        # Check entry.options directly for real-time responsiveness to the switch
        is_paused = entry.options.get(CONF_STOP_POLLING, False)
        is_first_run = coordinator.data is None

        # 1. If paused and NOT the first run, return cached data immediately
        if is_paused and not is_first_run:
            _LOGGER.debug("%s: Polling is paused; returning cached data.", entry.title)
            return coordinator.data

        # 2. Attempt Fetch
        last_error = None
        for attempt in range(2):
            try:
                # Primary data fetch
                data = await hass.async_add_executor_job(api.get_all_data)
                
                # Secondary fetches
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
                    _LOGGER.warning("%s: Fetch failed, retrying in 30 seconds...", entry.title)
                    await asyncio.sleep(30)

        entry_data["consecutive_failures"] += 1
        
        if coordinator.data is not None:
            if entry_data["consecutive_failures"] == 1:
                _LOGGER.warning("%s: Fetch failed. Holding last known values.", entry.title)
            return coordinator.data

        # 4. Safe Startup Bypass
        if is_paused:
            return {}

        _LOGGER.error("%s: Connection lost. Marking entities unavailable.", entry.title)
        raise UpdateFailed(f"Communication error: {last_error}")

    # Create the coordinator
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{entry.title} Data",
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )
    coordinator.last_update_success_time = None
    hass.data[DOMAIN][entry.entry_id][COORDINATOR] = coordinator

    # Forward platforms immediately
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # BACKGROUND INITIALIZATION TASK
    async def _async_background_setup():
        try:
            # 1. Check protocol with aggressive 5s timeout
            await hass.async_add_executor_job(api.try_set_protocol, 5)
            
            # 2. Login with aggressive 5s timeout
            await hass.async_add_executor_job(api.login, 5)
            
            # 3. Trigger first refresh
            # FIX: Use async_refresh() instead of async_config_entry_first_refresh()
            # because the entry is already LOADED.
            await coordinator.async_refresh()
            
            _LOGGER.info("%s: Background initialization complete.", entry.title)
        except Exception as err:
            _LOGGER.warning("%s: Background initialization failed (will retry): %s", entry.title, err)

    hass.async_create_task(_async_background_setup())

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)