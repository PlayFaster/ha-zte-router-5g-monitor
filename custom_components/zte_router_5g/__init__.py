"""The ZTE Router 5G integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ZTERouterAPI
from .const import DOMAIN
from .coordinator import ZTERouterDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ZTE Router 5G Monitor from a config entry with Background Safety."""
    session = async_get_clientsession(hass)
    api = ZTERouterAPI(
        session,
        entry.options[CONF_HOST],
        entry.options.get(CONF_USERNAME),
        entry.options[CONF_PASSWORD],
    )

    # Create the specialized coordinator
    coordinator = ZTERouterDataUpdateCoordinator(hass, entry, api)

    # Store for platform access via runtime_data
    entry.runtime_data = coordinator

    # Register the System root device early to prevent via_device warnings in platforms
    device_registry = dr.async_get(hass)
    host = entry.options[CONF_HOST]
    mac = entry.data.get("mac")
    sub_id_prefix = mac if mac else f"host_{host}"

    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{sub_id_prefix}_system")},
        name=f"{entry.title} System",
        manufacturer="ZTE",
        model=entry.data.get("model", "ZTE Router"),
        sw_version=entry.data.get("sw_version"),
        configuration_url=f"http://{host}",
    )

    # Forward platforms immediately so entities appear in HA
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # BACKGROUND INITIALIZATION TASK
    # Offloads the initial connection to keep startup instant.
    async def _async_background_setup():
        try:
            await api.try_set_protocol(5)
            await api.login(5)
            await coordinator.async_refresh()
            _LOGGER.info("%s: Background initialization complete.", entry.title)
        except Exception as err:
            _LOGGER.warning(
                "%s: Background initialization failed (will retry): %s",
                entry.title,
                err,
            )

    # Use the modern background task API for better lifecycle management
    entry.async_create_background_task(
        hass, _async_background_setup(), "zte-router-setup"
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and release resources."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # runtime_data is cleaned up automatically by HA
        # Note: No need to close api.session as it's managed by HA core
        pass
    return unload_ok
