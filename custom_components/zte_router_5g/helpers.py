"""Shared helpers for the ZTE Router 5G Monitor integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import ZTERouterDataUpdateCoordinator

# Known model strings to detect from the wa_inner_version firmware string.
# e.g. 'IRL_H3G_MC7010DV1.0.0B01' → 'MC7010'
_KNOWN_MODELS = ["MC7010", "MC801", "MC888", "MC889"]


def get_router_model(coordinator_data: dict[str, Any] | None) -> str:
    """Extract the router model from coordinator data.

    Checks 'model_name' first (e.g. 'MC7010'), then falls back to parsing
    'wa_inner_version' (e.g. 'IRL_H3G_MC7010DV1.0.0B01').
    Returns 'ZTE Router' if no model is recognised.
    """
    if not coordinator_data:
        return "ZTE Router"

    # 1. Direct model name check
    model_name = coordinator_data.get("model_name")
    if model_name:
        return cast(str, model_name)

    # 2. Firmware version parsing fallback
    version = coordinator_data.get("wa_inner_version", "")
    for model in _KNOWN_MODELS:
        if model in version:
            return model
    return "ZTE Router"


GROUP_NAMES = {
    "system": "System",
    "signal": "Signal",
    "data": "Data",
    "sms": "SMS",
}


def build_device_info(
    coordinator: ZTERouterDataUpdateCoordinator,
    entry: ConfigEntry,
    group: str,
) -> DeviceInfo:
    """Build device info dict for a sub-device group.

    Returns a dict suitable for Entity.device_info, with identifiers,
    name, manufacturer, model, sw_version, configuration_url, and
    via_device for non-system groups.
    """
    host = entry.options[CONF_HOST]
    display_group = GROUP_NAMES.get(group, group.capitalize())
    sub_name = f"{entry.title} {display_group}"

    sub_id_prefix = coordinator.imei or f"host_{host}"

    protocol = coordinator.api.protocol
    info: DeviceInfo = {
        "identifiers": {(DOMAIN, f"{sub_id_prefix}_{group}")},
        "name": sub_name,
        "manufacturer": "ZTE",
        "model": coordinator.model,
        "sw_version": coordinator.sw_version,
        "configuration_url": f"{protocol}://{host}",
    }

    if group != "system":
        info["via_device"] = (DOMAIN, f"{sub_id_prefix}_system")

    return info
