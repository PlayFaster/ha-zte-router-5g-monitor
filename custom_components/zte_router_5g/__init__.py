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

    # Credentials and settings are stored in entry.options (written by both
    # the initial config flow and the options flow on reconfigure).
    api = ZTERouterAPI(
        entry.options[CONF_HOST],
        entry.options.get(CONF_USERNAME),
        entry.options[CONF_PASSWORD]
    )

    # Runtime state — persisted values from slider/switch changes
    stop_polling = entry.options.get(CONF_STOP_POLLING, False)
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, 180)

    # Initialize data storage immediately so platforms can access it
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

        # Check entry.options directly for real-time responsiveness to the UI switch
        is_paused = entry.options.get(CONF_STOP_POLLING, False)
        is_first_run = coordinator.data is None

        # 1. If paused and NOT the first run, return cached data immediately
        if is_paused and not is_first_run:
            _LOGGER.debug("%s: Polling is paused; returning cached data.", entry.title)
            return coordinator.data

        # 2. Attempt fetch with 1 retry
        last_error = None
        for attempt in range(2):
            try:
                data = await hass.async_add_executor_job(api.get_all_data)
                sms_cap = await hass.async_add_executor_job(api.get_sms_capacity)
                last_sms = await hass.async_add_executor_job(api.get_last_sms_content)

                data.update(sms_cap)
                data["last_sms"] = last_sms

                # Success path
                coordinator.last_update_success_time = dt_util.now()
                entry_data["consecutive_failures"] = 0
                return data

            except Exception as err:
                last_error = err
                if attempt == 0:
                    _LOGGER.warning("%s: Fetch failed: %s. Retrying in 30 seconds...", entry.title, err)
                    await asyncio.sleep(30)
                else:
                    _LOGGER.warning("%s: Second fetch attempt failed for this cycle: %s", entry.title, err)

        # 3. Failure resilience — hold last known values for one cycle
        entry_data["consecutive_failures"] += 1

        if coordinator.data is not None:
            if entry_data["consecutive_failures"] == 1:
                _LOGGER.warning("%s: Fetch failed. Holding last known values.", entry.title)
            return coordinator.data

        # 4. Safe startup bypass — if paused on first run, start with empty data
        if is_paused:
            _LOGGER.warning("%s: Initial fetch failed while paused. Starting with empty data.", entry.title)
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

    # Forward platforms immediately so entities appear in HA (initially as 'Unknown')
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # BACKGROUND INITIALIZATION TASK
    # Offloads the initial connection to prevent blocking HA startup
    async def _async_background_setup():
        try:
            await hass.async_add_executor_job(api.try_set_protocol, 5)
            await hass.async_add_executor_job(api.login, 5)
            await coordinator.async_refresh()
            _LOGGER.info("%s: Background initialization complete.", entry.title)
        except Exception as err:
            _LOGGER.warning("%s: Background initialization failed (will retry): %s", entry.title, err)

    hass.async_create_task(_async_background_setup())

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and release resources."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Close the requests session to free file descriptors and connections
        api = hass.data[DOMAIN][entry.entry_id].get("api")
        if api:
            await hass.async_add_executor_job(api.close)
        hass.data[DOMAIN].pop(entry.entry_id)
        # Clean up the domain key itself if no entries remain
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unload_ok