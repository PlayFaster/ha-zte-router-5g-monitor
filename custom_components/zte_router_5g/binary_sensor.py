"""Binary sensor platform for ZTE Router 5G."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import (
    ENDPOINT_EXTENDED,
    ENDPOINT_SMS_CAPACITY,
    ZTERouterDataUpdateCoordinator,
)
from .entity_defaults import default_enabled
from .helpers import ZTEAboutEntity, ZTEDeviceEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZTEBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes ZTE binary sensor entity."""

    group: str = "signal"
    value_fn: Callable[[Any], bool] | None = None
    # The router keys this entity's value is built from. A boolean value
    # function answers `False` for any input, an empty payload included, so it
    # cannot say whether the router supplied anything — these can. Used by the
    # populated record, which exists so that `reset_entities` does not disable
    # an entity that reported a value yesterday and is merely blank today.
    state_keys: tuple[str, ...] = ()
    extra_attrs_fn: Callable[[Any], dict[str, Any]] | None = None
    # Optional endpoint this entity's value comes from. When set, the entity
    # goes unavailable once that endpoint exhausts its own strike budget
    # rather than serving a stale value forever (dev_standards Section 8).
    source: str | None = None
    # Optional plain-language note surfaced as an unrecorded `about` attribute
    # (dev_standards Section 14). Resolved by the ZTEAboutEntity mixin.
    about: str | None = None


def _nv_store_is_full(data: Any) -> bool:
    """Return whether the router's own message store has run out of room.

    Compares the three NV counters against `sms_nv_total`, the capacity of that
    bank. Mirrored by `coordinator._check_sms_storage`, which feeds the health
    finding from the same arithmetic.

    `sms_nv_total` is the capacity of that bank, not its fill: `Total Msg`
    publishes both, and on the reference MC7010 they read 100 and 20 for the
    two banks.
    """
    if not data:
        return False
    try:
        capacity = int(data.get("sms_nv_total") or 0)
        used = sum(
            int(data.get(key) or 0)
            for key in (
                "sms_nv_rev_total",
                "sms_nv_send_total",
                "sms_nv_draftbox_total",
            )
        )
    except (TypeError, ValueError):
        return False
    return capacity > 0 and used >= capacity


# How a device spells "LTE anchor with a 5G leg" — 5G non-standalone. Measured:
# `ENDC` on the MC7010, `EN-DC` on the MC888 Pro. Neither device has been seen
# to use the other's form.
_ENDC_SPELLINGS: Final = ("ENDC", "EN-DC")


# Define the entity description for static metadata
BEST_CONN_DESCRIPTION = ZTEBinarySensorEntityDescription(
    key="best_connection",
    translation_key="signal_best_connection",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    group="signal",
)

INTEGRATION_HEALTH_DESCRIPTION = ZTEBinarySensorEntityDescription(
    key="integration_health",
    translation_key="system_integration_health",
    device_class=BinarySensorDeviceClass.PROBLEM,
    entity_category=EntityCategory.DIAGNOSTIC,
    group="system",
)

OPERATOR_PROVISIONED_DESCRIPTION = ZTEBinarySensorEntityDescription(
    key="operator_provisioned",
    translation_key="system_operator_provisioned",
    entity_category=EntityCategory.DIAGNOSTIC,
    group="system",
)

BINARY_SENSORS: Final[tuple[ZTEBinarySensorEntityDescription, ...]] = (
    ZTEBinarySensorEntityDescription(
        key="sms_storage_full",
        state_keys=("sms_nv_total", "sms_nv_rev_total"),
        source=ENDPOINT_SMS_CAPACITY,
        about=(
            "On when message storage has no room left. A full store makes the "
            "network stop delivering new messages, and nothing else in the "
            "integration reports that - which is the whole reason this entity "
            "exists."
        ),
        translation_key="sms_storage_full",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Enabled by default, unlike most diagnostics here. Nothing else reports
        # this: a full store makes the network stop delivering, and Integration
        # Health deliberately does not cover it — §19 is about whether the
        # integration's data can be trusted, and this is the device's state,
        # reported correctly. If the entity is off, the condition is invisible.
        entity_registry_enabled_default=True,
        group="sms",
        # `sms_nv_total` is the **capacity** of the router's own store, not
        # how much of it is used — `Total Msg` publishes both side by side, and
        # on the reference MC7010 they read 100 and 20 for the two banks. The
        # fill level is the sum of the three NV counters. SIM storage fills
        # independently and is not this sensor: a full NV store is what stops
        # the network delivering.
        value_fn=lambda data: _nv_store_is_full(data),
    ),
    ZTEBinarySensorEntityDescription(
        key="reboot_schedule",
        state_keys=("reboot_schedule_enable",),
        source=ENDPOINT_EXTENDED,
        about=(
            "Whether the router reboots itself on an internal schedule. Execution "
            "time, repeat mode (weekly/monthly), and both candidate days are in "
            "the attributes."
        ),
        translation_key="system_reboot_schedule",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        entity_registry_enabled_default=False,
        value_fn=lambda data: (
            data.get("reboot_schedule_enable") == "1" if data else False
        ),
        # `reboot_schedule_mode` selects whether the weekly day (`reboot_dow`,
        # 1-indexed from Sunday) or the monthly one (`reboot_dod`) applies:
        # 1 = weekly, 2 = monthly. Confirmed 2026-07-29 from the router's own
        # `js/service.js` — see `docs/zte_how_to_access.md` § Field formats.
        #
        # Still published raw. Resolving them into one "reboots every Monday"
        # string would be friendlier, but this is a disabled-by-default
        # diagnostic whose consumer is someone comparing Home Assistant against
        # the router's own settings page — where these are the values shown.
        extra_attrs_fn=lambda data: {
            "reboot_hour1": data.get("reboot_hour1") if data else None,
            "reboot_min1": data.get("reboot_min1") if data else None,
            "reboot_hour2": data.get("reboot_hour2") if data else None,
            "reboot_min2": data.get("reboot_min2") if data else None,
            "schedule_mode": data.get("reboot_schedule_mode") if data else None,
            "day_of_week": data.get("reboot_dow") if data else None,
            "day_of_month": data.get("reboot_dod") if data else None,
        },
    ),
    ZTEBinarySensorEntityDescription(
        key="web_sleep",
        state_keys=("web_sleep_switch",),
        source=ENDPOINT_EXTENDED,
        about=(
            "Whether the router puts its web management page to sleep after "
            "inactivity. This affects browser logins only, not integration "
            "polling."
        ),
        translation_key="system_web_sleep",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("web_sleep_switch") == "1" if data else False,
    ),
    ZTEBinarySensorEntityDescription(
        key="web_wake",
        state_keys=("web_wake_switch",),
        source=ENDPOINT_EXTENDED,
        about=(
            "Whether the router's web management interface automatically wakes "
            "from sleep when accessed."
        ),
        translation_key="system_web_wake",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("web_wake_switch") == "1" if data else False,
    ),
    ZTEBinarySensorEntityDescription(
        key="upnp_enabled",
        state_keys=("upnpEnabled",),
        source=ENDPOINT_EXTENDED,
        about=(
            "Whether the router lets devices open their own inbound ports. "
            "Convenient for games and consoles, but it means any device on the "
            "network can expose itself without being asked. On a router in bridge "
            "mode this usually has no effect - your main firewall handles it."
        ),
        translation_key="system_upnp_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("upnpEnabled") == "1" if data else False,
    ),
    ZTEBinarySensorEntityDescription(
        key="sip_alg_enabled",
        state_keys=("alg_sip_enable",),
        source=ENDPOINT_EXTENDED,
        about=(
            "SIP ALG rewrites internet-telephony traffic as it passes through. It "
            "is meant to help, and frequently does the opposite: one-way audio and "
            "calls that drop after a set time are the classic symptoms. If VoIP "
            "misbehaves, this is the first thing to turn off."
        ),
        translation_key="system_sip_alg_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("alg_sip_enable") == "1" if data else False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator: ZTERouterDataUpdateCoordinator = entry.runtime_data

    entities: list[BinarySensorEntity] = [
        ZTEBestConnectionSensor(coordinator, entry, BEST_CONN_DESCRIPTION),
        ZTEIntegrationHealthSensor(coordinator, entry, INTEGRATION_HEALTH_DESCRIPTION),
        ZTEOperatorProvisionedSensor(
            coordinator, entry, OPERATOR_PROVISIONED_DESCRIPTION
        ),
    ]
    entities.extend(
        [
            ZTERouterBinarySensor(coordinator, entry, description)
            for description in BINARY_SENSORS
        ]
    )
    async_add_entities(entities)


class ZTEBestConnectionSensor(
    ZTEAboutEntity,
    ZTEDeviceEntity,
    CoordinatorEntity[ZTERouterDataUpdateCoordinator],
    BinarySensorEntity,
):
    """Binary sensor to check for optimal 5G/LTE CA connection."""

    _attr_about = (
        "On when the router has the best connection type it can get - a 5G "
        "carrier aggregated with the 4G anchor. Off does not mean a fault; it "
        "usually means 5G coverage is unavailable where the router is sited."
    )

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: ZTEBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: ZTERouterDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ZTEBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_entity_registry_enabled_default = default_enabled(
            description, coordinator.model
        )
        self._entry = entry

        # Unique ID generated from description key for registry stability
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return true if both 5G and LTE CA are active.

        Returns None (HA `unknown`) before any data has arrived. Reporting
        `off` there would assert "not on the best connection" about a router we
        have not yet read — false certainty, where the honest answer is that we
        do not know yet (dev_standards Section 18).
        """
        data = self.coordinator.data
        if not data:
            return None
        # Both spellings of the same state. The MC7010 reports `ENDC` and the
        # MC888 Pro reports `EN-DC`, consistently across every diagnostics
        # download of each — so testing for one alone left the sensor stuck off
        # on an MC888 whatever the radio was doing (issue #56).
        return bool(
            data.get("network_type") in _ENDC_SPELLINGS
            and data.get("wan_lte_ca") == "ca_activated"
        )


class ZTEOperatorProvisionedSensor(
    ZTEAboutEntity,
    ZTEDeviceEntity,
    CoordinatorEntity[ZTERouterDataUpdateCoordinator],
    BinarySensorEntity,
):
    """Reports whether the router declines to serve its own TR-069 settings.

    TR-069 is the standard an operator uses to configure a router remotely. A
    router supplied by an operator is commonly locked so that those settings
    cannot be read or changed locally, and this device says so plainly: asking
    for one of them answers `{"result": "failure"}` rather than a value, in
    40 to 60 milliseconds. A self-purchased router answers them.

    Reads `coordinator.provisioning_restricted` rather than
    `coordinator.data`, because that dict means "what the router said" and
    feeds the populated counts, the drift check and the sparse-payload check —
    a synthetic key would skew all three.

    Unknown until the probe first succeeds, so a device that has never answered
    reports nothing rather than a confident guess.
    """

    _attr_about = (
        "On when the router refuses to hand over its remote-management "
        "(TR-069) settings, which is usual on a unit supplied by a network "
        "operator and is why some settings cannot be changed locally. Off when "
        "it serves them. Re-checked hourly and whenever Refresh Now is pressed."
    )

    _attr_has_entity_name = True
    entity_description: ZTEBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: ZTERouterDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ZTEBinarySensorEntityDescription,
    ) -> None:
        """Initialize the provisioning sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_entity_registry_enabled_default = default_enabled(
            description, coordinator.model
        )
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return True when the router declines its provisioning settings."""
        return self.coordinator.provisioning_restricted


class ZTEIntegrationHealthSensor(
    ZTEAboutEntity,
    ZTEDeviceEntity,
    CoordinatorEntity[ZTERouterDataUpdateCoordinator],
    BinarySensorEntity,
):
    """Reports the integration's own internal degradation state.

    This is the Section 19 self-diagnosis sensor. Connection failures already
    surface as unavailable entities; what this fills is the failure Home
    Assistant cannot see — the poll *succeeds* while the parsed data is empty or
    wrong, because a firmware update renamed the fields underneath it.

    It reads ``coordinator.health_snapshot`` rather than ``coordinator.data``:
    ``data`` is ``None`` before the first success and frozen at last-good values
    during an outage, so a verdict stored there could never describe the failure
    that stopped it being updated.
    """

    _attr_about = (
        "On when the integration detects a problem with itself, including the "
        "case where a fetch succeeds but returns nothing usable - which nothing "
        "else catches. The attributes carry the detail. It stays available even "
        "when every other entity has gone unavailable, because that is exactly "
        "when it has something to say."
    )

    _attr_has_entity_name = True
    entity_description: ZTEBinarySensorEntityDescription

    # Detail belongs in attributes, but none of it belongs in the recorder:
    # `issues` is prose that changes with the failure, and the rest churns on
    # most polls (Section 14). The entity's on/off state is still recorded.
    _unrecorded_attributes = frozenset(
        {
            "about",
            "issues",
            "severity",
            "degraded_capabilities",
            "drift",
            "repairs",
            "last_good_update",
            "consecutive_failures",
            # The uptime counter's measured drift. Every constant in the
            # boot-time latch was set from one device over one week, and this
            # is what lets a field report carry the device's own rate instead
            # of requiring a recorder database extraction.
            "drift_rate_pct",
            "drift_rate_min_pct",
            "drift_rate_max_pct",
            "drift_intervals",
            "drift_measured_seconds",
            "drift_deficit_seconds",
        }
    )

    def __init__(
        self,
        coordinator: ZTERouterDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ZTEBinarySensorEntityDescription,
    ) -> None:
        """Initialize the health sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_entity_registry_enabled_default = default_enabled(
            description, coordinator.model
        )
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def available(self) -> bool:
        """Always available — including when everything else is not.

        The default ``CoordinatorEntity.available`` returns
        ``last_update_success``, which would take this sensor down at precisely
        the moment it has something to report. A health sensor that disappears
        during an outage is worse than none at all, because its silence is
        indistinguishable from health.
        """
        return True

    @property
    def is_on(self) -> bool:
        """Return True when the integration has detected a problem."""
        return bool(self.coordinator.health_snapshot.get("problem", False))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the detail behind the verdict."""
        snapshot = self.coordinator.health_snapshot
        return (
            self._with_about(
                {
                    "issues": snapshot.get("issues", []),
                    "severity": snapshot.get("severity", "unknown"),
                    "degraded_capabilities": snapshot.get("degraded_capabilities", []),
                    "drift": snapshot.get("drift", []),
                    "repairs": snapshot.get("repairs", []),
                    "last_good_update": snapshot.get("last_good_update"),
                    "consecutive_failures": snapshot.get("consecutive_failures", 0),
                    **self.coordinator.uptime_diagnostics,
                }
            )
            or {}
        )


class ZTERouterBinarySensor(
    ZTEAboutEntity,
    ZTEDeviceEntity,
    CoordinatorEntity[ZTERouterDataUpdateCoordinator],
    BinarySensorEntity,
):
    """Representation of a ZTE Router binary sensor."""

    _attr_has_entity_name = True
    entity_description: ZTEBinarySensorEntityDescription

    # Section 14: every key any description's `extra_attrs_fn` can return. The
    # attributes are built by a lambda on the description, so this set cannot be
    # derived automatically — `test_no_entity_publishes_a_recorded_attribute`
    # is the guard, and it sweeps live entities precisely because a static
    # check cannot see through the lambda.
    _unrecorded_attributes = frozenset(
        {
            "about",
            "reboot_hour1",
            "reboot_min1",
            "reboot_hour2",
            "reboot_min2",
            "schedule_mode",
            "day_of_week",
            "day_of_month",
        }
    )

    def __init__(
        self,
        coordinator: ZTERouterDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ZTEBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_entity_registry_enabled_default = default_enabled(
            description, coordinator.model
        )
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def available(self) -> bool:
        """Return whether this entity has a working data source.

        Entities fed by an optional endpoint go unavailable when that endpoint
        alone has exhausted its strike budget, while the rest of the
        integration keeps serving data (Section 8).
        """
        if not super().available:
            return False
        source = self.entity_description.source
        return source is None or self.coordinator.endpoint_available(source)

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is active.

        Returns None (HA `unknown`) until data is available — see the note on
        ZTEBestConnectionSensor.is_on (dev_standards Section 18).
        """
        if not self.coordinator.data or self.entity_description.value_fn is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if not self.coordinator.data or self.entity_description.extra_attrs_fn is None:
            return self._with_about({}) or {}
        return (
            self._with_about(
                self.entity_description.extra_attrs_fn(self.coordinator.data)
            )
            or {}
        )
