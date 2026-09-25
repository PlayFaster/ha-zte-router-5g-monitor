"""Select platform for ZTE Router 5G."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
import logging
from typing import Any, Final

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import device_profile
from .api import ZTERouterExpectedUnavailableError
from .const import APN_PROFILE_SLOTS, DOMAIN
from .coordinator import ZTERouterDataUpdateCoordinator
from .entity_defaults import default_enabled
from .helpers import ZTEAboutEntity, ZTEDeviceEntity, expected_outage_error, get_first

_LOGGER = logging.getLogger(__name__)

# Writes are serialised — see the note in `switch.py`. `0` (unlimited) stays
# correct for the read-only platforms; a platform that commands this
# single-session router must not issue concurrent `goform` writes.
PARALLEL_UPDATES = 1


# The MC888 Pro answers `network_net_select`; the bare spelling leads because
# the reference MC7010 answers on it. See `helpers.get_first`.
_ALIAS_NET_SELECT: Final = ("net_select", "network_net_select")


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
    # Set where the entity has no value under conditions the router treats as
    # normal, so `unknown` is the correct reading rather than a fault. Read by
    # `check_sensor_manifest.py --verify-ha`, which otherwise reports it stuck.
    unknown_is_valid: bool = False
    # Where the options come from the router's own web files rather than from
    # `options_fn`: given the learned device profile, the list, or None where
    # none was learned. A value outside the router's own list is never written,
    # because the router's page would never send it (3.4.4 plan §3.3).
    learned_options_fn: Callable[[dict[str, Any]], list[str] | None] | None = None


def _get_apn_profiles(data: Any) -> list[tuple[int, str, str]]:
    """Return a list of (index, profile_name, pdp_type) from coordinator data."""
    profiles: list[tuple[int, str, str]] = []
    if not data:
        return profiles
    for i in range(APN_PROFILE_SLOTS):
        val = data.get(f"APN_config{i}")
        if val:
            parts = val.split("($)")
            if len(parts) > 0 and parts[0]:
                profile_name = parts[0]
                pdp_type = parts[7] if len(parts) > 7 else "IP"
                profiles.append((i, profile_name, pdp_type))
    return profiles


def _get_current_apn_profile(data: Any) -> str | None:
    """Return the profile in use, which is not always the one `apn_index` names.

    While the router is in **auto** mode it uses the network-provided default
    APN, and `apn_index` retains whatever was last chosen manually. Observed
    live (2026-07-31): auto mode reporting `apn_index=5`
    (`open.internet.public`) while traffic ran over `3FWA.ie`. Showing the
    indexed profile there states something untrue.

    So in auto mode the active APN (`wan_apn`, the **Network APN** sensor) is
    matched against the stored profiles, and `None` is returned when it matches
    none — which is the normal case, since the default APN need not exist in
    the manual list. In manual mode `apn_index` is authoritative and is used
    directly, including for the "Default" profile, whose APN field is empty and
    which therefore leaves **Network APN** reading `unknown`.
    """
    if not data:
        return None

    if str(data.get("apn_mode") or "").strip().lower() == "auto":
        active = str(data.get("wan_apn") or "").strip().lower()
        if not active:
            return None
        for idx, name, _pdp in _get_apn_profiles(data):
            raw = str(data.get(f"APN_config{idx}") or "").split("($)")
            apn = raw[1] if len(raw) > 1 else ""
            if apn.strip().lower() == active:
                return name
        return None

    try:
        active_idx = int(float(data.get("apn_index", -1)))
    except (ValueError, TypeError):
        return None

    if active_idx < 0 or active_idx >= APN_PROFILE_SLOTS:
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
            "Which stored APN profile to connect with. The APN is the gateway "
            "your SIM's network expects; the wrong one usually means no data at "
            "all rather than slow data. Choosing one here also switches APN "
            "Selection Mode to manual. While the mode is auto the router uses "
            "the network's default APN, which may not be in this list - the "
            "Network APN sensor is the authoritative answer to what is actually "
            "in use. Note the Default profile stores no APN, so selecting it "
            "leaves Network APN reading unknown - the router's own page shows "
            "an empty field for the same reason. New profiles are added on the "
            "router's own web page, not here."
        ),
        translation_key="signal_apn_profile",
        entity_category=EntityCategory.CONFIG,
        group="signal",
        options_fn=lambda data: [p[1] for p in _get_apn_profiles(data)],
        value_fn=_get_current_apn_profile,
        # In auto mode the network-provided APN need not exist in the stored
        # profile list, and `_get_current_apn_profile` returns None rather
        # than naming a profile that is not in use. Observed live on an
        # MC7010: auto mode, active APN `3FWA.ie`, one stored profile
        # (`Default`, empty APN field) — no match is possible.
        unknown_is_valid=True,
        setter_fn=lambda api, option, data: _set_apn_profile_option(api, option, data),
    ),
    ZTESelectEntityDescription(
        key="apn_mode",
        about=(
            "Whether the router picks the APN itself (auto, using the network's "
            "default) or uses the profile you chose (manual). Auto is right for "
            "almost everyone. To switch to manual, choose an APN Profile "
            "instead - that sets the mode and the profile together, which is "
            "what the router requires."
        ),
        translation_key="signal_apn_mode",
        entity_category=EntityCategory.CONFIG,
        group="signal",
        options_fn=lambda data: ["auto", "manual"],
        value_fn=lambda data: data.get("apn_mode") if data else None,
        setter_fn=lambda api, option, data: api.set_apn_mode(option, data),
    ),
    ZTESelectEntityDescription(
        key="net_select",
        about=(
            "Which mobile technologies the router may use, such as 4G only, 5G "
            "only, or both. Values starting with Only lock the router to one "
            "technology. Where 5G coverage is marginal, locking to 5G can drop the "
            "connection entirely."
        ),
        translation_key="signal_net_select_mode",
        entity_category=EntityCategory.CONFIG,
        group="signal",
        options_fn=lambda data: [],
        learned_options_fn=device_profile.auto_modes,
        value_fn=lambda data: get_first(data, _ALIAS_NET_SELECT) if data else None,
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
    ZTEAboutEntity,
    ZTEDeviceEntity,
    CoordinatorEntity[ZTERouterDataUpdateCoordinator],
    SelectEntity,
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
        self._attr_entity_registry_enabled_default = default_enabled(
            description, coordinator.model
        )
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    def _learned_options(self) -> list[str] | None:
        """The router's own option list, or None where it has not been learned."""
        learned_fn = self.entity_description.learned_options_fn
        if learned_fn is None:
            return None
        profile = getattr(self.coordinator.api, "profile", None)
        return learned_fn(profile if isinstance(profile, dict) else {})

    @property
    def options(self) -> list[str]:
        """Return the list of available options."""
        if not self.coordinator.data:
            return []
        if self.entity_description.learned_options_fn is None:
            return self.entity_description.options_fn(self.coordinator.data)
        # The router's list, with its current value added where the list lacks
        # it, so the state is always one of the options. Nothing learned: the
        # current value alone, which shows the state and allows no change.
        current = self.current_option
        options = list(self._learned_options() or [])
        if current and current not in options:
            options.append(current)
        return options

    @property
    def available(self) -> bool:
        """Unavailable where there is no option at all to show."""
        if not super().available:
            return False
        if self.entity_description.learned_options_fn is None:
            return True
        return bool(self.options)

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option, surfacing a refusal rather than logging it.

        A failure here used to be swallowed into the log, so a rejected APN or
        bearer change looked like a select that silently sprang back. This API
        answers `200 OK` for a refused write, which makes an unreported failure
        especially easy to miss (IQS `action-exceptions`).

        Deliberately *not* confirmed by a targeted read-back, unlike the
        switches. **The omission is precautionary, and the reasoning behind it
        is untested.** The expectation is that these setters re-establish the
        connection and that the router answers with blank values while it
        does — which this integration reads as an expired session — so a
        read-back would risk a needless re-login and would report a
        slow-but-successful change as a failure.

        Neither half has been observed. The two writes issued on the reference
        MC7010 on 2026-09-14 were effectively no-ops — `apn_mode` auto to auto,
        and `net_select` `auto_select` to `4G_AND_5G`, which is Auto to Auto —
        so neither exercised a change that would take the connection down.
        Settling it needs a restricting bearer value (`Only_LTE` or `Only_5G`)
        or a real APN change, and neither has been run.

        Until then the debounced refresh is the instrument, on the grounds that
        it cannot report a false failure whatever the router does. If the
        expectation turns out to be wrong, a read-back becomes available here
        and this paragraph is what says so.
        """
        if self.entity_description.learned_options_fn is not None:
            learned = self._learned_options()
            placeholders = {"entity": self.entity_description.key, "option": option}
            if learned is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="select_options_not_learned",
                    translation_placeholders=placeholders,
                )
            if option not in learned:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="select_option_not_offered",
                    translation_placeholders=placeholders,
                )
        try:
            await self.entity_description.setter_fn(
                self.coordinator.api, option, self.coordinator.data
            )
        except Exception as err:
            if isinstance(err, ZTERouterExpectedUnavailableError):
                raise expected_outage_error(err) from err
            _LOGGER.error(
                "%s: Failed to set %s to %s: %s",
                self._entry.title,
                self.entity_description.key,
                option,
                err,
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="select_set_failed",
                translation_placeholders={
                    "entity": self.entity_description.key,
                    "error": str(err),
                },
            ) from err
        await self.coordinator.async_force_refresh()
