"""Diagnostics support for ZTE Router 5G Monitor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import ZTERouterDataUpdateCoordinator

TO_REDACT = {
    "password",
    "username",
    "wan_ipaddr",
    "lan_ipaddr",
    "imei",
    "sim_imsi",
    "sim_iccid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: ZTERouterDataUpdateCoordinator = entry.runtime_data

    diagnostics_data = {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "coordinator": {
            "consecutive_failures": coordinator.consecutive_failures,
            "last_update_success": coordinator.last_update_success,
            "last_update_success_time": (
                coordinator.last_update_success_time.isoformat()
                if coordinator.last_update_success_time
                else None
            ),
            "data_available": coordinator.data is not None,
        },
        "data": async_redact_data(coordinator.data or {}, TO_REDACT),
    }

    return diagnostics_data
