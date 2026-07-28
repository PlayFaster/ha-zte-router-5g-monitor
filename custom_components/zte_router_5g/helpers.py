"""Shared helpers for the ZTE Router 5G Monitor integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo

from ._compat import via_device_link
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


class ZTEAboutEntity:
    """Mixin exposing a static, human-facing ``about`` note as an attribute.

    Ported from ``unifi_network_monitor`` / ``wifi_ssid_monitor``; keep the three
    implementations interchangeable. Set the text via ``_attr_about`` (class-level,
    for single-instance entities) or an ``about`` field on the entity description
    (for description-driven ones). The note shows in Developer Tools and the More
    Info dialog but is listed in ``_unrecorded_attributes``, so the recorder never
    writes it to history — zero storage cost however often the state changes
    (dev_standards Section 14).

    List this mixin FIRST in an entity's bases so its ``extra_state_attributes``
    wins over the platform default. An entity that defines its own
    ``extra_state_attributes`` must route the result through ``_with_about``, or
    the note silently disappears for that entity only.

    The text is hardcoded rather than translated — it is a pragmatic use of the
    attribute channel, and there is no HA-native "entity description" field.
    """

    _unrecorded_attributes = frozenset({"about"})
    _attr_about: str | None = None

    @property
    def _about_text(self) -> str | None:
        """Resolve the note from ``_attr_about`` or the entity description."""
        if self._attr_about is not None:
            return self._attr_about
        description = getattr(self, "entity_description", None)
        return getattr(description, "about", None) if description is not None else None

    def _with_about(self, attrs: dict[str, Any] | None) -> dict[str, Any] | None:
        """Merge the ``about`` note into an entity's own attribute dict."""
        about = self._about_text
        if about is None:
            return attrs
        return {"about": about, **(attrs or {})}

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Default: expose only the ``about`` note when one is set."""
        return self._with_about(None)


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
        # via_device (tuple) is deprecated in HA 2026.8 and removed in 2027.8;
        # via_device_link feature-detects and emits via_device_id where available.
        # The registry and entry id are resolved from the coordinator so no new
        # argument has to be threaded through every entity call site.
        cast(dict[str, Any], info).update(
            via_device_link(
                coordinator.hass, DOMAIN, f"{sub_id_prefix}_system", entry.entry_id
            )
        )

    return info
