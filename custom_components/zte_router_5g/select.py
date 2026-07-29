"""Select platform for ZTE Router 5G."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ZTERouterDataUpdateCoordinator
from .helpers import ZTEAboutEntity, build_device_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZTESelectEntityDescription(SelectEntityDescription):
    """Describes ZTE select entity."""

    value_fn: Callable[[Any], str | None]
    options_fn: Callable[[Any], list[str]]
    setter_fn: Callable[[Any, str, Any], Coroutine[Any, Any, None]]
    group: str = "system"
    # Optional plain-language note surfaced as an unrecorded `about` attribute
    # (dev_standards Section 14). Resolved by the ZTEAboutEntity mixin.
    about: str | None = None


def _get_apn_profiles(data: Any) -> list[tuple[int, str, str]]:
    """Return a list of (index, profile_name, pdp_type) from coordinator data."""
    profiles: list[tuple[int, str, str]] = []
    if not data:
        return profiles
    for i in range(20):
        val = data.get(f"APN_config{i}")
        if val:
            parts = val.split("($)")
            if len(parts) > 0 and parts[0]:
                profile_name = parts[0]
                pdp_type = parts[7] if len(parts) > 7 else "IP"
                profiles.append((i, profile_name, pdp_type))
    return profiles


def _get_current_apn_profile(data: Any) -> str | None:
    """Get the active APN profile name based on apn_index."""
    if not data:
        return None
    try:
        active_idx = int(float(data.get("apn_index", -1)))
    except (ValueError, TypeError):
        return None

    if active_idx < 0 or active_idx > 19:
        return None

    val = data.get(f"APN_config{active_idx}")
    if val:
        parts = val.split("($)")
        if len(parts) > 0 and parts[0]:
            return str(parts[0])
    return None


async def _set_apn_profile_option(api: Any, option: str, data: Any) -> None:
    """Select the APN profile option and commit to router."""
    profiles = _get_apn_profiles(data)
    target = next((p for p in profiles if p[1] == option), None)
    if target is None:
        raise ValueError(f"APN profile name {option} not found in available list")

    idx, _, pdp_type = target
    _LOGGER.info("Setting default APN to index %s (%s, PDP: %s)", idx, option, pdp_type)
    await api.set_apn(idx, pdp_type)


SELECT_TYPES: tuple[ZTESelectEntityDescription, ...] = (
    ZTESelectEntityDescription(
        key="apn_profile",
        about=(
            "Which stored APN profile the router uses to connect. The APN is the "
            "gateway your SIM's network expects; the wrong one usually means no "
            "data at all rather than slow data. Only takes effect when APN "
            "Selection Mode is set to manual."
        ),
        translation_key="signal_apn_profile",
        entity_category=EntityCategory.CONFIG,
        group="signal",
        options_fn=lambda data: [p[1] for p in _get_apn_profiles(data)],
        value_fn=_get_current_apn_profile,
        setter_fn=lambda api, option, data: _set_apn_profile_option(api, option, data),
    ),
    ZTESelectEntityDescription(
        key="apn_mode",
        about=(
            "Whether the router picks the APN itself from the SIM (auto) or uses "
            "the profile you chose (manual). Auto is right for almost everyone; "
            "manual is for a carrier whose APN the router guesses wrongly."
        ),
        translation_key="signal_apn_mode",
        entity_category=EntityCategory.CONFIG,
        group="signal",
        options_fn=lambda data: ["auto", "manual"],
        value_fn=lambda data: data.get("apn_mode") if data else None,
        setter_fn=lambda api, option, data: api.set_apn_mode(option),
    ),
    ZTESelectEntityDescription(
        key="net_select",
        about=(
            "Which mobile technologies the router may use. The combined options "
            "let it fall back when a signal weakens; the Only options lock it. "
            "Locking to 5G can drop the connection entirely where 5G coverage is "
            "marginal, so prefer a combined setting unless you are testing."
        ),
        translation_key="signal_net_select_mode",
        entity_category=EntityCategory.CONFIG,
        group="signal",
        options_fn=lambda data: ["4G_AND_5G", "LTE_AND_5G", "Only_5G", "Only_LTE"],
        value_fn=lambda data: data.get("net_select") if data else None,
        setter_fn=lambda api, option, data: api.set_bearer_preference(option),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    coordinator: ZTERouterDataUpdateCoordinator = entry.runtime_data
    async_add_entities(
        [
            ZTERouterSelect(coordinator, entry, description)
            for description in SELECT_TYPES
        ]
    )


class ZTERouterSelect(
    ZTEAboutEntity, CoordinatorEntity[ZTERouterDataUpdateCoordinator], SelectEntity
):
    """Representation of a ZTE Router select entity."""

    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"about"})
    entity_description: ZTESelectEntityDescription

    def __init__(
        self,
        coordinator: ZTERouterDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ZTESelectEntityDescription,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def options(self) -> list[str]:
        """Return the list of available options."""
        if not self.coordinator.data:
            return []
        return self.entity_description.options_fn(self.coordinator.data)

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        try:
            await self.entity_description.setter_fn(
                self.coordinator.api, option, self.coordinator.data
            )
            await self.coordinator.async_force_refresh()
        except Exception:
            _LOGGER.exception(
                "%s: Failed to set %s to %s",
                self._entry.title,
                self.entity_description.key,
                option,
            )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information with sub-device support."""
        return build_device_info(
            self.coordinator, self._entry, self.entity_description.group
        )
