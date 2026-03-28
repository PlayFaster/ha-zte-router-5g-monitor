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

    # State tracking for polling controls and resilience
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        CONF_STOP_POLLING: False,
        CONF_SCAN_INTERVAL: 180,
        "consecutive_failures": 0  # Track failures across polling cycles
    }

    async def async_update_data():
        """Fetch data from API with retry and stale-data logic."""
        entry_data = hass.data[DOMAIN][entry.entry_id]
        
        if entry_data.get(CONF_STOP_POLLING):
            _LOGGER.debug("ZTE Router: Polling is currently paused")
            return coordinator.data

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
                    _LOGGER.warning("ZTE Router: Fetch failed, retrying in 30 seconds...")
                    await asyncio.sleep(30)
                else:
                    _LOGGER.warning("ZTE Router: Second fetch attempt failed for this cycle")

        # 3. Hybrid Resilience (Grace Period)
        entry_data["consecutive_failures"] += 1
        
        # If this is the FIRST cycle to fail (after both retries), return stale data
        if entry_data["consecutive_failures"] == 1 and coordinator.data:
            _LOGGER.warning(
                "ZTE Router: Polling cycle failed. Holding last known values for one cycle grace period. Error: %s", 
                last_error
            )
            return coordinator.data

        # 4. Hard Fail
        # If we reach here, we've failed 2+ cycles in a row (or have no previous data)
        _LOGGER.error("ZTE Router: Connection lost for multiple cycles. Marking entities unavailable.")
        raise UpdateFailed(f"Error communicating with API after retries: {last_error}")

    # Create the coordinator
    # Note: update_interval can be changed dynamically by number.py
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="ZTE Router Data",
        update_method=async_update_data,
        update_interval=timedelta(seconds=180),
    )
    
    # Initialize the custom attribute
    coordinator.last_update_success_time = None

    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id][COORDINATOR] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)