"""Sensor platform for ZTE Router 5G."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfDataRate,
    UnitOfFrequency,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    PROJECTION_CONFIDENCE_LOW,
    PROJECTION_CONFIDENCE_MEDIUM,
    PROJECTION_CREDIBILITY_DAYS,
)
from .coordinator import (
    ENDPOINT_EXTENDED,
    ENDPOINT_SMS_MESSAGES,
    ZTERouterDataUpdateCoordinator,
)
from .helpers import (
    ZTEAboutEntity,
    arfcn_to_band,
    build_device_info,
    cycle_bounds,
    earfcn_to_band,
    get_first,
    project_cycle_usage,
)

_LOGGER = logging.getLogger(__name__)

_BYTES_PER_GB = 1000000000

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZTESensorEntityDescription(SensorEntityDescription):
    """Describes ZTE sensor entity."""

    value_fn: Callable[[Any], Any]
    group: str = "system"
    min_limit: float | None = None
    max_limit: float | None = None
    # Optional endpoint this sensor's value comes from. When set, the entity
    # goes unavailable once that endpoint exhausts its own strike budget,
    # instead of serving a stale value forever (dev_standards Section 8).
    source: str | None = None
    # Optional plain-language note surfaced as an unrecorded `about` attribute
    # (dev_standards Section 14). Use it where the entity name alone does not
    # say what the value is or what a good value looks like — chiefly the
    # signal metrics, whose names are acronyms.
    about: str | None = None


def _get_bytes_to_gb(val: Any) -> float | None:
    """Convert bytes string to rounded GB float."""
    if val in [None, ""]:
        return None
    try:
        return round(float(val) / _BYTES_PER_GB, 2)
    except (ValueError, TypeError):
        return None


def _get_uptime(data: Any) -> Any:
    """Get the cached boot timestamp from data."""
    return data.get("boot_time")


def _get_total_sms(data: Any) -> int | None:
    """Calculate total SMS count across all storage banks."""
    keys = [
        "sms_nv_rev_total",
        "sms_nv_send_total",
        "sms_nv_draftbox_total",
        "sms_sim_rev_total",
        "sms_sim_send_total",
        "sms_sim_draftbox_total",
    ]
    try:
        # Present-but-empty is absent, the same rule `get_first` applies. A
        # router that reports one bank as `""` was otherwise blanking the whole
        # sensor and its attribute breakdown, which reads as "no messages" —
        # the opposite of what an unreadable bank means. A genuinely
        # unparsable value still returns None.
        return sum(int(raw) for k in keys if (raw := data.get(k)) not in (None, ""))
    except (ValueError, TypeError):
        return None


# Helper to safely convert router string values to float
def _safe_float(val: Any) -> float | None:
    """Safely convert a value to float, rounded at parse time.

    Rounding **once, here** curtails the dozen-decimal noise controllers emit
    (e.g. 99.930600002408) so stored history and long-term statistics stay
    clean. This is distinct from display: `suggested_display_precision`
    controls how many decimals are *shown*, this controls how many are
    *stored* (dev_standards Section 6).
    """
    if val in [None, ""]:
        return None
    try:
        return round(float(val), 3)
    except (ValueError, TypeError):
        return None


# Helper to safely convert router string values to int
def _safe_int(val: Any) -> int | None:
    """Safely convert value to int or return None."""
    if val in [None, ""]:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


# Helper to safely convert router string values to string and map empty to None
def _safe_str(val: Any) -> str | None:
    """Safely convert value to string or return None if empty."""
    if val in [None, ""]:
        return None
    return str(val)


# Cross-model key aliases. The first entry is the spelling the MC7010 uses, so
# its execution path is unchanged; later entries only come into play on
# hardware that does not populate the first.
_ALIAS_5G_RSRP: Final = ("Z5g_rsrp", "5g_rsrp", "nr5g_rsrp")
_ALIAS_5G_SINR: Final = ("Z5g_SINR", "Z5g_snr", "5g_sinr", "nr5g_sinr")
_ALIAS_5G_PCI: Final = ("nr5g_pci", "Z5g_CELL_ID")
_ALIAS_MONTHLY_TX: Final = ("monthly_tx_bytes", "flux_monthly_tx_bytes")
_ALIAS_MONTHLY_RX: Final = ("monthly_rx_bytes", "flux_monthly_rx_bytes")

# The `flux_` prefix is a parallel vocabulary across this API, not a quirk of
# the monthly counters. The bare spelling leads because the reference MC7010
# answers on it; order is the tie-break, see `get_first`.
_ALIAS_REALTIME_TX_BYTES: Final = ("realtime_tx_bytes", "flux_realtime_tx_bytes")
_ALIAS_REALTIME_RX_BYTES: Final = ("realtime_rx_bytes", "flux_realtime_rx_bytes")
_ALIAS_REALTIME_TX_THRPT: Final = ("realtime_tx_thrpt", "flux_realtime_tx_thrpt")
_ALIAS_REALTIME_RX_THRPT: Final = ("realtime_rx_thrpt", "flux_realtime_rx_thrpt")
_ALIAS_REALTIME_TIME: Final = ("realtime_time", "flux_realtime_time")

# Alternate spellings mined from the router's own web UI on 2026-09-01. Each
# answered the identical value to the key it leads at the moment it was
# sampled. `strBearer` has since been observed empty on that device while
# `network_type` reported `ENDC`, so it is a fallback rather than a proven
# duplicate — which is what a fallback is for: the leader wins whenever it
# carries a value.
_ALIAS_NETWORK_TYPE: Final = ("network_type", "strBearer")
_ALIAS_PROVIDER: Final = ("network_provider", "strFullName", "strShortName")
_ALIAS_WAN_APN: Final = ("wan_apn", "wan_apn_ui")
_ALIAS_HARDWARE: Final = ("hardware_version", "hardwarenumber")
_ALIAS_LIMIT_SIZE: Final = ("data_volume_limit_size", "flux_data_volume_limit_size")
_ALIAS_LIMIT_UNIT: Final = ("data_volume_limit_unit", "flux_data_volume_limit_unit")
_ALIAS_ALERT_PERCENT: Final = (
    "data_volume_alert_percent",
    "flux_data_volume_alert_percent",
)

# Day of the month on which the router zeroes its monthly counters. Three
# spellings are in circulation across the goform family; `traffic_clear_date` is
# the one a live MC7010 probe answered on, so it leads. Order is the tie-break —
# see `get_first`.
_ALIAS_CLEAR_DAY: Final = (
    "traffic_clear_date",
    "data_volume_clear_date",
    "data_volume_clear_day",
    "flux_clear_date",
)


# The `network_` prefix is a third parallel vocabulary, observed on the MC888
# Pro in issue #56 and on no other device. Each of these keys is populated
# there while the bare spelling this integration polls is empty, which is the
# test a fallback has to pass — the alternate answers where the leader does
# not. The bare spellings lead because the reference MC7010 answers on them.
#
# The family is partial. `network_lte_rsrq`, `network_lte_snr` and
# `network_lte_rssi` appear in no mined set from either device, so three of the
# four primary signal metrics have no `network_` equivalent to fall back to.
_ALIAS_LTE_RSRP: Final = ("lte_rsrp", "network_lte_rsrp")
_ALIAS_CA_PCELL_BAND: Final = ("lte_ca_pcell_band", "network_lte_ca_pcell_band")
_ALIAS_CA_PCELL_BW: Final = (
    "lte_ca_pcell_bandwidth",
    "network_lte_ca_pcell_bandwidth",
)
_ALIAS_CA_SCELL_BAND: Final = ("lte_ca_scell_band", "network_lte_ca_scell_band")
_ALIAS_CA_SCELL_BW: Final = (
    "lte_ca_scell_bandwidth",
    "network_lte_ca_scell_bandwidth",
)
_ALIAS_NET_SELECT: Final = ("net_select", "network_net_select")
_ALIAS_NET_SELECT_MODE: Final = ("net_select_mode", "network_net_select_mode")
_ALIAS_AUTO_CLEAR_SWITCH: Final = (
    "wan_auto_clear_flow_data_switch",
    "flux_auto_clear_flow_data_switch",
)
_ALIAS_LIMIT_SWITCH: Final = (
    "data_volume_limit_switch",
    "flux_data_volume_limit_switch",
)


def _scell_field(data: dict[str, Any], index: int) -> float | None:
    """Return one field of the first secondary carrier, or None.

    `lte_multi_ca_scell_sig_info` carries one comma-separated group per
    secondary carrier, semicolon-terminated. A live MC7010 reading with one
    carrier: `-89.1,-11.0,17.2,-58.1,0.0,2.0`.

    Fields one to four are RSRP, RSRQ, SNR and RSSI. That order is measured
    rather than inferred: RSRQ, RSRP and RSSI are related by definition as
    `RSRQ = RSRP - RSSI + 10*log10(N)`, and solving for N across twelve samples
    on 2026-09-02 gave 99.4 resource blocks with a spread of 2.3 - 100 RB, a
    20 MHz carrier. No other assignment yields a physically possible N, and the
    ranges separate RSRQ from RSSI, which the identity alone cannot. Fields
    five and six are not published: one is constant at 0 and the other was seen
    changing from 2 to 4, and neither is understood.

    The first group only. A device aggregating two secondary carriers reports
    two groups, and reading past the first would need entities that do not
    exist - but the parser must not assume there is only ever one, which is why
    the split is on `;` rather than a whole-string parse.
    """
    raw = data.get("lte_multi_ca_scell_sig_info")
    if not isinstance(raw, str) or not raw.strip():
        return None
    first = raw.strip().rstrip(";").split(";")[0]
    fields = first.split(",")
    if len(fields) <= index:
        return None
    return _safe_float(fields[index])


def _clear_day(data: dict[str, Any]) -> int | None:
    """Return the monthly counter reset day, 1-31, or None.

    Warns when more than one spelling is populated with *different* values.
    `get_first` would silently take the leader, and a silent disagreement
    between two firmware spellings of the same setting is precisely the kind of
    thing that surfaces months later as "the projection is a week out".
    """
    values = {
        key: parsed
        for key in _ALIAS_CLEAR_DAY
        if (parsed := _safe_int(data.get(key))) is not None
    }
    if not values:
        return None
    if len(set(values.values())) > 1:
        _LOGGER.warning(
            "Router reports disagreeing monthly reset days: %s. Using %s. "
            "Please open an issue with a diagnostics download",
            values,
            next(iter(values.values())),
        )
    day = next(iter(values.values()))
    return day if 1 <= day <= 31 else None


def _data_allowance_bytes(data: dict[str, Any]) -> int | None:
    """Return the configured monthly data cap in bytes, or None.

    The router encodes the cap as `<value>_<multiplier>`, where the multiplier
    is the number of mebibytes in the chosen unit — `2_1048576` is 2 TiB,
    because 1 TiB is 1048576 MiB. **Inferred from one sample**, cross-checked
    against the router's own Data Management page showing "2TB" and an 80%
    reminder at "1.6TB" for exactly this value.

    Note the router's "TB" is binary, so 2 TiB shows here as ~2199 GB once
    Home Assistant converts to decimal gigabytes. That is the same quantity,
    not a discrepancy.

    Returns None when the cap is expressed in time rather than data — the
    router can limit by hours instead of bytes, and a duration is not an
    allowance this sensor can report.
    """
    if get_first(data, _ALIAS_LIMIT_UNIT) == "time":
        return None

    raw = _safe_str(get_first(data, _ALIAS_LIMIT_SIZE))
    if raw is None or raw.count("_") != 1:
        return None

    value_s, mult_s = raw.split("_")
    value = _safe_float(value_s)
    mult = _safe_int(mult_s)
    if value is None or mult is None or value <= 0 or mult <= 0:
        return None

    return int(value * mult * 1024 * 1024)


@dataclass(frozen=True)
class _Projection:
    """A projected end-of-cycle figure and the context needed to judge it."""

    bytes_used: int
    projected_bytes: int
    cycle_start: datetime
    cycle_length_days: int
    elapsed_days: float
    weight: float
    basis: str
    cycle_source: str

    @property
    def confidence(self) -> str:
        """Return how much of this figure rests on observed data."""
        if self.weight < PROJECTION_CONFIDENCE_LOW:
            return "low"
        if self.weight < PROJECTION_CONFIDENCE_MEDIUM:
            return "medium"
        return "high"


def _projection(data: dict[str, Any]) -> _Projection | None:
    """Project this cycle's data usage to its end, or None if it cannot be.

    Returns None only when the router's automatic monthly reset is switched
    off, because then the counters never roll over and there is genuinely no
    cycle to project against. Everything else — including the first minute of a
    new cycle — produces a figure, because a sensor showing `unknown` reads as
    broken.

    A router that reports no reset day falls back to the **calendar month**
    rather than going silent. That is right for anyone billed calendar-monthly
    and no worse than nothing for anyone else, whereas an unexplained `unknown`
    that never clears is worse than both. The assumption is published as
    `cycle_source` so it is visible rather than hidden in the arithmetic.
    """
    # The router has been seen to report this as "off"; the sibling switches
    # in this API use "0"/"1", and casing is not guaranteed. An exact match on
    # one spelling silently treats every other "disabled" form as enabled and
    # projects against a cycle the router is not keeping.
    if str(get_first(data, _ALIAS_AUTO_CLEAR_SWITCH) or "").strip().lower() in (
        "off",
        "0",
        "false",
    ):
        return None

    clear_day = _clear_day(data)
    cycle_source = "router"
    if clear_day is None:
        clear_day = 1
        cycle_source = "calendar_assumed"

    used = _monthly_total_bytes(data)
    if used is None:
        return None

    now = dt_util.now()
    start, _end, length = cycle_bounds(clear_day, now)
    elapsed = (now - start).total_seconds() / 86400.0

    # No cycle history yet. Phase 4 supplies `prior_rate` from the stored
    # previous-cycle total; until then the denominator floor inside
    # `project_cycle_usage` carries the whole job on its own.
    prior_rate: float | None = None

    projected = project_cycle_usage(
        used=used,
        elapsed_days=elapsed,
        cycle_length_days=length,
        prior_rate=prior_rate,
        credibility_days=PROJECTION_CREDIBILITY_DAYS,
    )

    return _Projection(
        bytes_used=used,
        projected_bytes=int(projected),
        cycle_start=start,
        cycle_length_days=length,
        elapsed_days=elapsed,
        weight=elapsed / (elapsed + PROJECTION_CREDIBILITY_DAYS),
        basis="run_rate_only" if prior_rate is None else "blended",
        cycle_source=cycle_source,
    )


def _projected_bytes(data: dict[str, Any]) -> int | None:
    """Return the projected end-of-cycle byte count, or None."""
    result = _projection(data)
    return None if result is None else result.projected_bytes


def _monthly_total_bytes(data: dict[str, Any]) -> int | None:
    """Sum the monthly TX and RX counters, honouring the key aliases.

    Shared by the GB and raw-bytes totals so they cannot disagree with the
    individual TX/RX sensors on hardware that uses the `flux_` spelling —
    a divergence that would look like real data rather than a bug.
    """
    tx = _safe_int(get_first(data, _ALIAS_MONTHLY_TX))
    rx = _safe_int(get_first(data, _ALIAS_MONTHLY_RX))
    if tx is None or rx is None:
        return None
    return tx + rx


def _band_or_channel_fallback(
    data: dict[str, Any],
    band_key: str,
    channel_key: str,
    resolver: Callable[[int | str | None], str | None],
) -> str | None:
    """Prefer the band name the router reports; derive it only if absent.

    Some models report the channel number but leave the band name empty. The
    reported name always wins — the resolver is a fallback, and for NR it is
    an inherently ambiguous one.
    """
    reported = _safe_str(data.get(band_key))
    if reported is not None:
        return reported
    return resolver(data.get(channel_key))


# Technical Router Sensors
SENSOR_TYPES: Final[tuple[ZTESensorEntityDescription, ...]] = (
    # --- System Sub-device ---
    ZTESensorEntityDescription(
        key="model_name",
        translation_key="system_model_name",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: data.get("model_name"),
    ),
    ZTESensorEntityDescription(
        key="wa_inner_version",
        about=(
            "The router's firmware build string. Worth recording before a firmware "
            "update, so you can tell what changed if the router starts behaving "
            "differently afterwards."
        ),
        translation_key="system_wa_inner_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: data.get("wa_inner_version"),
    ),
    ZTESensorEntityDescription(
        key="wan_ipaddr",
        about=(
            "The address your ISP has given the router on the mobile network - what "
            "the internet sees. Often a shared carrier-grade NAT address, which is "
            "why inbound connections and port forwarding usually do not work on "
            "mobile broadband."
        ),
        translation_key="system_wan_ipaddr",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: _safe_str(data.get("wan_ipaddr")),
    ),
    ZTESensorEntityDescription(
        key="lan_ipaddr",
        translation_key="system_lan_ipaddr",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: data.get("lan_ipaddr"),
    ),
    ZTESensorEntityDescription(
        key="device_uptime",
        about=(
            "The moment the router last booted, held steady between reboots rather "
            "than recalculated each poll. It only moves when the router's own uptime "
            "counter drops, so a genuine restart is easy to trigger automations on."
        ),
        translation_key="system_device_uptime",
        device_class=SensorDeviceClass.TIMESTAMP,
        group="system",
        value_fn=_get_uptime,
    ),
    ZTESensorEntityDescription(
        key="realtime_time",
        about=(
            "How long the router has been running since its last boot. The Device "
            "Uptime sensor expresses the same fact as a timestamp, which is usually "
            "the easier one to automate against."
        ),
        translation_key="system_uptime_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        group="system",
        min_limit=0,
        value_fn=lambda data: _safe_int(get_first(data, _ALIAS_REALTIME_TIME)),
    ),
    ZTESensorEntityDescription(
        key="last_updated",
        translation_key="system_last_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        group="system",
        value_fn=lambda data: None,  # Handled in property
    ),
    ZTESensorEntityDescription(
        key="imei",
        about=(
            "International Mobile Equipment Identity - the modem's unique 15-digit "
            "hardware serial, used by networks to identify the device itself rather "
            "than the SIM. This integration also uses it as the stable identity for "
            "your router, so entity history survives an IP change."
        ),
        translation_key="system_imei",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        value_fn=lambda data: data.get("imei"),
    ),
    ZTESensorEntityDescription(
        key="hardware_version",
        translation_key="system_hardware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: get_first(data, _ALIAS_HARDWARE),
    ),
    ZTESensorEntityDescription(
        key="new_version_state",
        about=(
            "Whether the router has found a firmware update. The value is the "
            "router's own, reported unchanged."
        ),
        translation_key="system_firmware_update_available",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: _safe_str(data.get("new_version_state")),
    ),
    ZTESensorEntityDescription(
        key="current_upgrade_state",
        about=(
            "Whether a firmware update is running. The value is the router's "
            "own, reported unchanged."
        ),
        translation_key="system_firmware_update_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: _safe_str(data.get("current_upgrade_state")),
    ),
    ZTESensorEntityDescription(
        key="battery_value",
        about=(
            "Battery charge level for portable ZTE models. Mains-powered units "
            "lacking a battery report 100%."
        ),
        translation_key="system_battery_value",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        min_limit=0,
        max_limit=100,
        group="system",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_int(data.get("battery_value")),
    ),
    # Thermal sensors. This is the set of thermal keys the sibling project
    # `Kajkac/ZTE-MC-Home-assistant-repo` polls with °C units, verified against
    # its `const.py` and live batch `cmd=` strings — not a hand-picked subset.
    #
    # Probed on an MC7010, which answers `""` for every one of them, so all
    # five are disabled by default: on the primary target hardware they would
    # otherwise add five permanently-unknown entities to the UI. No model is
    # yet confirmed to populate any of them; they are here for the hardware
    # that does.
    ZTESensorEntityDescription(
        key="pm_sensor_pa1",
        about=(
            "Temperature of the RF power amplifier driving the transmit signal, "
            "typically the warmest component in the unit. Not reported by all "
            "models."
        ),
        translation_key="system_pm_sensor_pa1",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        min_limit=-40,
        max_limit=125,
        group="system",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_float(data.get("pm_sensor_pa1")),
    ),
    ZTESensorEntityDescription(
        key="pm_sensor_ambient",
        about=(
            "Internal air temperature inside the modem, away from the radio itself. "
            "Read alongside the power amplifier temperature it indicates whether the "
            "unit as a whole is running hot or just the transmitter. Not reported by "
            "all models."
        ),
        translation_key="system_pm_sensor_ambient",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        min_limit=-40,
        max_limit=125,
        group="system",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_float(data.get("pm_sensor_ambient")),
    ),
    ZTESensorEntityDescription(
        key="pm_sensor_mdm",
        about=(
            "Temperature of the 4G/LTE cellular baseband module. Not reported by "
            "all models."
        ),
        translation_key="system_pm_sensor_mdm",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        min_limit=-40,
        max_limit=125,
        group="system",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_float(data.get("pm_sensor_mdm")),
    ),
    ZTESensorEntityDescription(
        key="pm_modem_5g",
        about=(
            "Temperature reported by the router's 5G modem section. Not reported "
            "by all models."
        ),
        translation_key="system_pm_modem_5g",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        min_limit=-40,
        max_limit=125,
        group="system",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_float(data.get("pm_modem_5g")),
    ),
    ZTESensorEntityDescription(
        key="pm_sensor_5g",
        about=(
            "Temperature reported by the router's 5G radio. Not reported by all models."
        ),
        translation_key="system_pm_sensor_5g",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        min_limit=-40,
        max_limit=125,
        group="system",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_float(data.get("pm_sensor_5g")),
    ),
    ZTESensorEntityDescription(
        key="sim_imsi",
        about=(
            "International Mobile Subscriber Identity - the unique number identifying "
            "your SIM's subscription on the network, as distinct from the IMEI which "
            "identifies the hardware."
        ),
        translation_key="system_sim_imsi",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: data.get("sim_imsi"),
    ),
    ZTESensorEntityDescription(
        key="sim_iccid",
        about=(
            "Integrated Circuit Card ID - the SIM card's own serial number, printed "
            "on the card itself. Useful for identifying which SIM is in the router "
            "without opening it."
        ),
        translation_key="system_sim_iccid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: data.get("sim_iccid"),
    ),
    # --- Signal Sub-device ---
    ZTESensorEntityDescription(
        key="wan_connect_status",
        about=(
            "Whether the router currently has a data connection to the mobile "
            "network. This covers the mobile side only - it can report connected "
            "while the wider internet is unreachable."
        ),
        translation_key="signal_wan_connect_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("wan_connect_status"),
    ),
    ZTESensorEntityDescription(
        key="wan_apn",
        about=(
            "Access Point Name - the gateway the router is actually connected "
            "with. This is the authoritative answer: while APN Selection Mode is "
            "auto the router uses the network's own default, which may not be one "
            "of your stored profiles, so the APN Profile selector can differ from "
            "this or read unknown. A wrong APN is a common cause of a router that "
            "has good signal but no working data."
        ),
        translation_key="signal_wan_apn",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_str(get_first(data, _ALIAS_WAN_APN)),
    ),
    ZTESensorEntityDescription(
        key="network_type",
        about=(
            "The connection technology in use. ENDC and LTE-NSA are both 5G "
            "non-standalone, where a 4G anchor carries the connection alongside a 5G "
            "carrier: ENDC means the 5G carrier is actually in use, LTE-NSA means the "
            "router is attached for 5G but is running on the 4G anchor alone, which "
            "is what weak 5G coverage looks like. Plain LTE means no 5G at all."
        ),
        translation_key="signal_network_type",
        group="signal",
        value_fn=lambda data: _safe_str(get_first(data, _ALIAS_NETWORK_TYPE)),
    ),
    ZTESensorEntityDescription(
        key="signalbar",
        about=(
            "The router's own signal rating, 0 to 5, the same one shown on its web "
            "page. It is a coarse summary - for anything precise use RSRP or SNR, "
            "which is what the bars are derived from."
        ),
        translation_key="signal_signalbar",
        state_class=SensorStateClass.MEASUREMENT,
        group="signal",
        min_limit=0,
        max_limit=5,
        value_fn=lambda data: _safe_int(data.get("signalbar")),
    ),
    ZTESensorEntityDescription(
        key="network_provider",
        about=(
            "The mobile network the router is registered to. This can differ from the "
            "SIM's home network while roaming."
        ),
        translation_key="signal_network_provider",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_str(get_first(data, _ALIAS_PROVIDER)),
    ),
    ZTESensorEntityDescription(
        key="mdm_mcc",
        about=(
            "Mobile Country Code - a three-digit code identifying the country of the "
            "network the modem is attached to (for example 272 = Ireland)."
        ),
        translation_key="signal_mdm_mcc",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: data.get("mdm_mcc"),
    ),
    ZTESensorEntityDescription(
        key="mdm_mnc",
        about=(
            "Mobile Network Code - identifies the individual operator within that "
            "country. Together with the MCC it uniquely names the network you are on."
        ),
        translation_key="signal_mdm_mnc",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: data.get("mdm_mnc"),
    ),
    ZTESensorEntityDescription(
        key="rmcc",
        about=(
            "Mobile Country Code of the network the router is registered to, as "
            "opposed to the modem's own view. It differs from the modem MCC while "
            "roaming."
        ),
        translation_key="signal_rmcc",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: data.get("rmcc"),
    ),
    ZTESensorEntityDescription(
        key="rmnc",
        about=(
            "Mobile Network Code of the registered network. Compare with the modem "
            "MNC to tell whether the router is roaming."
        ),
        translation_key="signal_rmnc",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: data.get("rmnc"),
    ),
    ZTESensorEntityDescription(
        key="lte_rsrp",
        about=(
            "Reference Signal Received Power - the strength of the 4G signal, in dBm. "
            "This is the number to watch when aiming or siting the router; SNR is the "
            "better guide to how fast the connection will actually go. "
            "Typically: better than -80 is excellent, -80 to -90 good, -90 to -100 "
            "fair, below -100 poor. Values are negative, so closer to zero is "
            "stronger."
        ),
        translation_key="signal_lte_rsrp",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        min_limit=-140,
        max_limit=-30,
        group="signal",
        value_fn=lambda data: _safe_float(get_first(data, _ALIAS_LTE_RSRP)),
    ),
    ZTESensorEntityDescription(
        key="lte_rsrq",
        about=(
            "Reference Signal Received Quality - 4G signal quality rather than raw "
            "strength, in dB. It reflects how much interference and load the cell is "
            "carrying. Typically: better than -10 is excellent, -10 to -15 good, -15 "
            "to -20 fair, below -20 poor. Strong RSRP with poor RSRQ usually means a "
            "busy cell."
        ),
        translation_key="signal_lte_rsrq",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        min_limit=-40,
        max_limit=0,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_rsrq")),
    ),
    ZTESensorEntityDescription(
        key="lte_rssi",
        about=(
            "Received Signal Strength Indicator - total received power across the 4G "
            "channel, including noise and interference, in dBm. Less diagnostic than "
            "RSRP, because it cannot separate your cell's signal from everything else "
            "on the frequency."
        ),
        translation_key="signal_lte_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        min_limit=-120,
        max_limit=-20,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_rssi")),
    ),
    ZTESensorEntityDescription(
        key="lte_snr",
        about=(
            "Signal-to-Noise Ratio for 4G, in dB - how far the wanted signal rises "
            "above the background noise. This is the best predictor of achievable "
            "speed. Typically: above 20 is excellent, 13 to 20 good, 0 to 13 fair, "
            "below 0 poor."
        ),
        translation_key="signal_lte_snr",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        min_limit=-20,
        max_limit=50,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_snr")),
    ),
    ZTESensorEntityDescription(
        key="lte_pci",
        about=(
            "Physical Cell Identity - a number from 0 to 503 identifying the specific "
            "4G cell sector serving the router. Neighboring sectors reuse the range, "
            "so a change means you have moved to a different sector or mast."
        ),
        translation_key="signal_lte_pci",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_str(data.get("lte_pci")),
    ),
    ZTESensorEntityDescription(
        key="cell_id",
        about=(
            "The identifier of the 4G cell currently serving the router. A change "
            "means you have been handed to a different cell, which often explains a "
            "sudden change in speed or signal."
        ),
        translation_key="signal_cell_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_str(data.get("cell_id")),
    ),
    ZTESensorEntityDescription(
        key="wan_lte_ca",
        about=(
            "Whether Carrier Aggregation is active - the modem combining two or more "
            "frequency bands at once for extra bandwidth. When active, the secondary "
            "band appears in the SCell sensors."
        ),
        translation_key="signal_wan_lte_ca",
        group="signal",
        value_fn=lambda data: data.get("wan_lte_ca"),
    ),
    ZTESensorEntityDescription(
        key="lte_ca_pcell_band",
        about=(
            "The primary 4G band carrying your connection. Lower-numbered bands "
            "generally travel further and penetrate buildings better; higher bands "
            "usually carry more capacity over shorter distances."
        ),
        translation_key="signal_lte_ca_pcell_band",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: get_first(data, _ALIAS_CA_PCELL_BAND),
    ),
    ZTESensorEntityDescription(
        key="lte_ca_pcell_bandwidth",
        about=(
            "The channel width of the primary 4G band, in MHz. Wider is faster: 20 "
            "MHz carries roughly four times the data of 5 MHz, all else being equal."
        ),
        translation_key="signal_lte_ca_pcell_bandwidth",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_float(get_first(data, _ALIAS_CA_PCELL_BW)),
    ),
    ZTESensorEntityDescription(
        key="lte_ca_scell_band",
        about=(
            "The secondary 4G band added by Carrier Aggregation. Only present while "
            "aggregation is active."
        ),
        translation_key="signal_lte_ca_scell_band",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: get_first(data, _ALIAS_CA_SCELL_BAND) or None,
    ),
    ZTESensorEntityDescription(
        key="lte_ca_scell_bandwidth",
        about=(
            "Channel width of the aggregated secondary 4G band, in MHz. It adds to "
            "the primary band's capacity rather than replacing it."
        ),
        translation_key="signal_lte_ca_scell_bandwidth",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_float(get_first(data, _ALIAS_CA_SCELL_BW)),
    ),
    ZTESensorEntityDescription(
        key="wan_active_band",
        about=(
            "The frequency band currently carrying your connection. Which band you "
            "land on is decided by the network, and it affects both range and speed."
        ),
        translation_key="signal_wan_active_band",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _band_or_channel_fallback(
            data, "wan_active_band", "wan_active_channel", earfcn_to_band
        ),
    ),
    ZTESensorEntityDescription(
        key="wan_active_channel",
        about=(
            "The specific radio channel number in use within the active band. Mainly "
            "of interest when comparing against neighboring cells or diagnosing "
            "interference."
        ),
        translation_key="signal_wan_active_channel",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_int(data.get("wan_active_channel")),
    ),
    ZTESensorEntityDescription(
        key="z5g_rsrp",
        about=(
            "Reference Signal Received Power for the 5G carrier, in dBm - the 5G "
            "equivalent of LTE RSRP, and the number to watch when siting the router "
            "for 5G. Typically: better than -80 is excellent, -80 to -90 good, -90 to "
            "-100 fair, below -100 poor."
        ),
        translation_key="signal_z5g_rsrp",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        min_limit=-140,
        max_limit=-30,
        group="signal",
        value_fn=lambda data: _safe_float(get_first(data, _ALIAS_5G_RSRP)),
    ),
    ZTESensorEntityDescription(
        key="z5g_rsrq",
        about=(
            "Reference Signal Received Quality for 5G, in dB - quality rather than "
            "strength, reflecting interference and cell load. Typically: better than "
            "-10 is excellent, -10 to -15 good, -15 to -20 fair, below -20 poor."
        ),
        translation_key="signal_z5g_rsrq",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        min_limit=-40,
        max_limit=0,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("Z5g_rsrq")),
    ),
    ZTESensorEntityDescription(
        key="z5g_rssi",
        about=(
            "Total received power across the 5G channel, in dBm, including noise and "
            "interference. Use 5G RSRP for a cleaner measure of your own cell's "
            "strength."
        ),
        translation_key="signal_z5g_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        min_limit=-120,
        max_limit=-20,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("Z5g_rssi")),
    ),
    ZTESensorEntityDescription(
        key="z5g_sinr",
        about=(
            "Signal-to-Noise Ratio for the 5G carrier, in dB - how far the wanted "
            "signal rises above everything competing with it. This is the best "
            "predictor of achievable 5G speed. Typically: above 20 is excellent, "
            "13 to 20 good, 0 to 13 fair, below 0 poor."
        ),
        translation_key="signal_z5g_sinr",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        min_limit=-20,
        max_limit=50,
        group="signal",
        value_fn=lambda data: _safe_float(get_first(data, _ALIAS_5G_SINR)),
    ),
    ZTESensorEntityDescription(
        key="nr5g_pci",
        about=(
            "Physical Cell Identity for the 5G cell, from 0 to 1007. A change means "
            "the router has been handed to a different 5G sector or mast."
        ),
        translation_key="signal_nr5g_pci",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_str(get_first(data, _ALIAS_5G_PCI)),
    ),
    ZTESensorEntityDescription(
        key="nr5g_action_band",
        about=(
            "The active 5G NR band. Bands below 1 GHz reach furthest, mid-band "
            "(around 3.5 GHz) is the usual balance of speed and coverage, and high "
            "bands are fastest over the shortest distance."
        ),
        translation_key="signal_nr5g_action_band",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _band_or_channel_fallback(
            data, "nr5g_action_band", "nr5g_action_channel", arfcn_to_band
        ),
    ),
    ZTESensorEntityDescription(
        key="nr5g_action_channel",
        about=(
            "The 5G channel number in use within the active band, expressed as "
            "an NR-ARFCN. Useful when comparing your connection against "
            "neighboring cells."
        ),
        translation_key="signal_nr5g_action_channel",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_int(data.get("nr5g_action_channel")),
    ),
    ZTESensorEntityDescription(
        key="rssi",
        about=(
            "Combined signal strength across all active radio frequencies, in dBm. "
            "Technology-specific LTE and 5G RSRP metrics provide more diagnostic "
            "detail."
        ),
        translation_key="signal_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        min_limit=-120,
        max_limit=-20,
        group="signal",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_float(data.get("rssi")),
    ),
    ZTESensorEntityDescription(
        key="rscp",
        about=(
            "Received Signal Code Power, in dBm - a 3G/UMTS measurement. Only "
            "meaningful if the router has fallen back to 3G, which on a 5G CPE "
            "usually signals a coverage problem."
        ),
        translation_key="signal_rscp",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        min_limit=-120,
        max_limit=-20,
        group="signal",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_float(data.get("rscp")),
    ),
    ZTESensorEntityDescription(
        key="enodeb_id",
        about=(
            "The identifier of the 4G base station (eNodeB) serving you - the mast "
            "itself, rather than the individual sector, which is the Cell ID. A "
            "change here means you have moved to a different mast."
        ),
        translation_key="signal_enodeb_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_str(data.get("enodeb_id")),
    ),
    ZTESensorEntityDescription(
        key="net_select",
        about=(
            "The network technology the router is currently allowed to use, as chosen "
            "by the Network Mode control. Restricting it can stabilize a connection "
            "that keeps switching between 4G and 5G."
        ),
        translation_key="signal_net_select",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: get_first(data, _ALIAS_NET_SELECT),
    ),
    ZTESensorEntityDescription(
        key="net_select_config",
        about=(
            "Whether the router picks its network mode itself or holds the one "
            "you chose - the Automatic or Manual setting on its own network "
            "selection page. Automatic lets it fall back as coverage changes; "
            "Manual keeps the Network Mode you set until you change it."
        ),
        translation_key="signal_net_select_config",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: get_first(data, _ALIAS_NET_SELECT_MODE),
    ),
    ZTESensorEntityDescription(
        key="upgrade_result",
        about=(
            "The outcome of the router's last firmware update attempt. Reads "
            "error where an update was tried and did not complete, which the "
            "update-state entities do not show."
        ),
        translation_key="system_upgrade_result",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="system",
        value_fn=lambda data: data.get("upgrade_result") or None,
    ),
    ZTESensorEntityDescription(
        key="5g_rsrp_antenna_1",
        about=(
            "Reference signal strength at the first 5G receiver, in dBm. The "
            "two receivers see the same cell through different antennas, so a "
            "persistent gap between them points at placement or an obstruction "
            "rather than at the network."
        ),
        translation_key="signal_5g_rsrp_antenna_1",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        min_limit=-140,
        max_limit=-40,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("5g_rx0_rsrp")),
    ),
    ZTESensorEntityDescription(
        key="5g_rsrp_antenna_2",
        about=(
            "Reference signal strength at the second 5G receiver, in dBm. "
            "Compare with the first: a steady difference is an antenna or "
            "placement effect, not a change in coverage."
        ),
        translation_key="signal_5g_rsrp_antenna_2",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        min_limit=-140,
        max_limit=-40,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("5g_rx1_rsrp")),
    ),
    ZTESensorEntityDescription(
        key="ca_scell_rsrp",
        about=(
            "Reference signal strength on the aggregated secondary carrier, in "
            "dBm. Carrier aggregation adds a second band alongside the primary "
            "one; this is how strong that second band is."
        ),
        translation_key="signal_ca_scell_rsrp",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        min_limit=-140,
        max_limit=-40,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: _scell_field(data, 0),
    ),
    ZTESensorEntityDescription(
        key="ca_scell_rsrq",
        about=(
            "Reference signal quality on the aggregated secondary carrier, in "
            "dB. Typically -10 or better is good, below -15 poor."
        ),
        translation_key="signal_ca_scell_rsrq",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        suggested_display_precision=1,
        min_limit=-40,
        max_limit=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: _scell_field(data, 1),
    ),
    ZTESensorEntityDescription(
        key="ca_scell_snr",
        about=(
            "Signal-to-noise ratio on the aggregated secondary carrier, in dB. "
            "Worth comparing against the primary: the secondary band often "
            "carries the cleaner signal, which the headline SNR does not show."
        ),
        translation_key="signal_ca_scell_snr",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        suggested_display_precision=1,
        min_limit=-20,
        max_limit=50,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: _scell_field(data, 2),
    ),
    ZTESensorEntityDescription(
        key="ca_scell_rssi",
        about=(
            "Total received power on the aggregated secondary carrier, in dBm - "
            "wanted signal, interference and noise together."
        ),
        translation_key="signal_ca_scell_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        min_limit=-120,
        max_limit=-20,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: _scell_field(data, 3),
    ),
    ZTESensorEntityDescription(
        key="sim_pin_attempts",
        about=(
            "PIN attempts left before the SIM locks and needs the PUK. A SIM "
            "that has locked presents as no service, which otherwise looks "
            "like a coverage or connection fault."
        ),
        translation_key="system_sim_pin_attempts",
        min_limit=0,
        max_limit=10,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        value_fn=lambda data: _safe_int(data.get("pinnumber")),
    ),
    ZTESensorEntityDescription(
        key="sim_puk_attempts",
        about=(
            "PUK attempts left before the SIM is permanently blocked and has "
            "to be replaced by the operator."
        ),
        translation_key="system_sim_puk_attempts",
        min_limit=0,
        max_limit=10,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        value_fn=lambda data: _safe_int(data.get("puknumber")),
    ),
    ZTESensorEntityDescription(
        key="modem_state",
        about=(
            "What the modem itself reports about its own startup, separately "
            "from whether a connection is up. Useful when the router answers "
            "but nothing is passing traffic."
        ),
        translation_key="system_modem_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        value_fn=lambda data: data.get("modem_main_state") or None,
    ),
    ZTESensorEntityDescription(
        key="connection_failure_count",
        about=(
            "How many times the router has failed to establish the mobile data "
            "connection since it last restarted. A rising count with the "
            "connection apparently up means it is dropping and recovering."
        ),
        translation_key="system_connection_failure_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        min_limit=0,
        max_limit=10000,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        value_fn=lambda data: _safe_int(data.get("ppp_dial_conn_fail_counter")),
    ),
    ZTESensorEntityDescription(
        key="roaming_state",
        about=(
            "Whether the SIM is on its home network or roaming. Roaming can "
            "carry different charges and different speed limits."
        ),
        translation_key="signal_roaming_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: data.get("simcard_roam") or None,
    ),
    ZTESensorEntityDescription(
        key="nr5g_nsa_band_lock",
        about=(
            "The 5G bands the router may use in non-standalone mode, where 5G "
            "runs alongside a 4G anchor. The counterpart to LTE Band Lock."
        ),
        translation_key="signal_nr5g_nsa_band_lock",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: data.get("nr5g_nsa_band_lock") or None,
    ),
    ZTESensorEntityDescription(
        key="nr5g_sa_band_lock",
        about=(
            "The 5G bands the router may use in standalone mode, where 5G runs "
            "without a 4G anchor."
        ),
        translation_key="signal_nr5g_sa_band_lock",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: data.get("nr5g_sa_band_lock") or None,
    ),
    ZTESensorEntityDescription(
        key="ppp_status",
        about=(
            "Whether the router is currently passing the connection straight "
            "through in bridge mode - connected means it is. This is the live "
            "session, not the configuration: WAN Operating Mode reports which mode "
            "the router is set to, bridge or gateway, while this reports whether "
            "that session is actually up. It can show disconnected while the radio "
            "signal is still strong, which points at an APN or account problem "
            "rather than coverage."
        ),
        translation_key="signal_ppp_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("ppp_status"),
    ),
    # --- Data Sub-device ---
    # Legacy GB Sensors (Disabled by default, preserved for history)
    ZTESensorEntityDescription(
        key="monthly_tx_bytes",
        about=(
            "Data uploaded this billing month, as counted by the router. This is the "
            "router's own counter, not your ISP's - it resets when the router says so "
            "and may not match your operator's billing exactly."
        ),
        translation_key="data_monthly_tx_bytes",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
        group="data",
        # Divided by 1_000_000_000 to match decimal GB (UnitOfInformation.GIGABYTES)
        min_limit=0,
        value_fn=lambda data: _get_bytes_to_gb(get_first(data, _ALIAS_MONTHLY_TX)),
    ),
    ZTESensorEntityDescription(
        key="monthly_rx_bytes",
        about=(
            "Data downloaded this billing month, as counted by the router. Treat it "
            "as a close guide rather than an exact match for your ISP's billing."
        ),
        translation_key="data_monthly_rx_bytes",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
        group="data",
        # Divided by 1_000_000_000 to match decimal GB (UnitOfInformation.GIGABYTES)
        min_limit=0,
        value_fn=lambda data: _get_bytes_to_gb(get_first(data, _ALIAS_MONTHLY_RX)),
    ),
    ZTESensorEntityDescription(
        key="monthly_total_bytes",
        about=(
            "Combined upload and download for the billing month - the figure to "
            "compare against a data cap."
        ),
        translation_key="data_monthly_total_bytes",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
        group="data",
        min_limit=0,
        value_fn=lambda data: _get_bytes_to_gb(_monthly_total_bytes(data)),
    ),
    # Standard Byte Sensors (Enabled by default, supports UI conversion)
    ZTESensorEntityDescription(
        key="monthly_tx_bytes_raw",
        about=(
            "Monthly upload total, counted by the router. Home Assistant displays "
            "it in GB while storing the exact byte count, so no separate sensor is "
            "needed for automations that want the precise figure."
        ),
        translation_key="data_monthly_tx_bytes_raw",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        group="data",
        min_limit=0,
        value_fn=lambda data: _safe_int(get_first(data, _ALIAS_MONTHLY_TX)),
    ),
    ZTESensorEntityDescription(
        key="monthly_rx_bytes_raw",
        about=(
            "Monthly download total, counted by the router. Home Assistant "
            "displays it in GB while storing the exact byte count, so it is both "
            "readable on a dashboard and precise in automations."
        ),
        translation_key="data_monthly_rx_bytes_raw",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        group="data",
        min_limit=0,
        value_fn=lambda data: _safe_int(get_first(data, _ALIAS_MONTHLY_RX)),
    ),
    ZTESensorEntityDescription(
        key="monthly_total_bytes_raw",
        # TOTAL_INCREASING, not TOTAL. These counters zero on the router's
        # billing day, and the two classes handle that completely differently:
        # under TOTAL_INCREASING the recorder calls `reset_detected()` and
        # treats a fall below 90% of the previous value as a new cycle, while
        # under TOTAL a reset is only recognized via a `last_reset` attribute
        # this integration does not publish. The monthly rollover therefore
        # recorded as a large negative delta and walked the long-term
        # statistics sum backwards every month. Verified against
        # `homeassistant/components/sensor/recorder.py`.
        about=(
            "Combined monthly upload and download - the figure to compare against "
            "a data cap. Home Assistant displays it in GB while storing the exact "
            "byte count, so nothing is rounded away in automations."
        ),
        translation_key="data_monthly_total_bytes_raw",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        group="data",
        min_limit=0,
        value_fn=_monthly_total_bytes,
    ),
    ZTESensorEntityDescription(
        key="realtime_tx_thrpt",
        about=(
            "Current upload rate. This is a snapshot taken at the moment the router "
            "was last polled, not an average - brief peaks between polls are not "
            "captured."
        ),
        translation_key="data_realtime_tx_thrpt",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        suggested_display_precision=2,
        min_limit=0,
        group="data",
        value_fn=lambda data: _safe_int(get_first(data, _ALIAS_REALTIME_TX_THRPT)),
    ),
    ZTESensorEntityDescription(
        key="realtime_rx_thrpt",
        about=(
            "Current download rate at the instant of the last poll. Because it is "
            "sampled rather than averaged, it will not reflect a short burst that "
            "happened between polls."
        ),
        translation_key="data_realtime_rx_thrpt",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        suggested_display_precision=2,
        min_limit=0,
        group="data",
        value_fn=lambda data: _safe_int(get_first(data, _ALIAS_REALTIME_RX_THRPT)),
    ),
    ZTESensorEntityDescription(
        key="realtime_tx_bytes",
        about=(
            "Data uploaded during the current session - since the router last "
            "restarted, not since the start of the month. It resets to zero on every "
            "reboot."
        ),
        translation_key="data_realtime_tx_bytes",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        min_limit=0,
        group="data",
        value_fn=lambda data: _safe_int(get_first(data, _ALIAS_REALTIME_TX_BYTES)),
    ),
    ZTESensorEntityDescription(
        key="realtime_rx_bytes",
        about=(
            "Data downloaded during the current session, reset on every router "
            "reboot. For billing, use the monthly sensors instead."
        ),
        translation_key="data_realtime_rx_bytes",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        min_limit=0,
        group="data",
        value_fn=lambda data: _safe_int(get_first(data, _ALIAS_REALTIME_RX_BYTES)),
    ),
    # --- SMS Sub-device ---
    ZTESensorEntityDescription(
        key="sms_unread_num",
        translation_key="sms_sms_unread_num",
        state_class=SensorStateClass.MEASUREMENT,
        group="sms",
        min_limit=0,
        max_limit=1000,
        value_fn=lambda data: _safe_int(data.get("sms_unread_num")),
    ),
    ZTESensorEntityDescription(
        key="msg_total",
        about=(
            "Total messages held across every storage area - router memory and SIM, "
            "inbox, sent and drafts. The breakdown per area is in this sensor's "
            "attributes. Storage filling up stops new messages arriving."
        ),
        translation_key="sms_msg_total",
        state_class=SensorStateClass.MEASUREMENT,
        group="sms",
        min_limit=0,
        max_limit=1000,
        value_fn=_get_total_sms,
    ),
    ZTESensorEntityDescription(
        key="msg_recent",
        about=(
            "The most recently received message. Sender, date and storage index are "
            "in the attributes; the index is what the delete action needs to remove "
            "this specific message."
        ),
        translation_key="sms_msg_recent",
        group="sms",
        # The only sensor fed by an optional endpoint — the other SMS sensors
        # read counters returned by the mandatory get_all_data fetch.
        source=ENDPOINT_SMS_MESSAGES,
        value_fn=lambda data: data.get("last_sms", {}).get("content_decoded"),
    ),
    # --- Discovered Technical Settings & Info ---
    ZTESensorEntityDescription(
        key="lte_band_lock",
        about=(
            "Hexadecimal bitmask of the 4G bands the modem is permitted to use. "
            "Bit 0 is band 1, so bit 2 is band 3 and bit 19 is band 20 - "
            "0x60088080045 means bands 1, 3, 7, 20, 28, 32, 42 and 43. Use it to "
            "confirm which bands a band lock has left available; locking to one "
            "the router cannot see leaves it with no service."
        ),
        translation_key="signal_lte_band_lock",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_str(data.get("lte_band_lock")),
    ),
    ZTESensorEntityDescription(
        key="data_allowance",
        about=(
            "The monthly data cap configured on the router itself, matching the "
            "Data Plan figure on its Data Management page. Useful as the "
            "threshold for an automation, so it tracks the router rather than a "
            "number typed into the automation. The router counts in binary "
            "units, so a 2 TB plan shows here as about 2199 GB - the same "
            "amount, counted the way Home Assistant counts. Unavailable if no "
            "limit is set, or if the limit is set in hours rather than data."
        ),
        translation_key="data_allowance",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Enabled by default: it is the number Projected Cycle Usage is judged
        # against, and pairs with Alert Threshold. Reports nothing when no cap
        # is configured, which is the honest answer rather than a reason to
        # hide it.
        min_limit=0,
        # 1 PiB. The encoding is inferred from a single sample, so a guard band
        # keeps a misparse out of the statistics rather than trusting it.
        max_limit=1125899906842624,
        group="data",
        value_fn=_data_allowance_bytes,
    ),
    ZTESensorEntityDescription(
        key="data_volume_alert_percent",
        about=(
            "The percentage of the Allowance at which the router raises its own "
            "alert - 80% of a 2 TB plan means it warns you at 1.6 TB. This is the "
            "router's internal threshold, separate from any automation you build "
            "in Home Assistant."
        ),
        translation_key="data_volume_alert_percent",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Deliberately no `state_class`: a configured threshold changes at most
        # a handful of times in the life of an install, so a trend line of it
        # holds nothing. Enabled by default because it is the number the
        # router's own alert fires on, and it pairs with `Allowance`.
        min_limit=0,
        max_limit=100,
        group="data",
        value_fn=lambda data: _safe_int(get_first(data, _ALIAS_ALERT_PERCENT)),
    ),
    ZTESensorEntityDescription(
        key="sntp_server",
        about=(
            "The time server the router synchronizes its clock from. An unreachable "
            "time server can make the timestamps on SMS messages and logs wrong, so "
            "it is worth checking if dates look implausible."
        ),
        translation_key="system_sntp_server",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_str(data.get("sntp_server0")),
    ),
    ZTESensorEntityDescription(
        key="data_clear_day",
        about=(
            "The day of the month on which the router zeroes its monthly data "
            "counters. This is the router's own billing cycle, which need not "
            "start on the 1st - check it against your provider's bill. If your "
            "month is shorter than this day, the reset happens on the last day "
            "instead."
        ),
        translation_key="data_clear_day",
        entity_category=EntityCategory.DIAGNOSTIC,
        min_limit=1,
        max_limit=31,
        group="data",
        value_fn=_clear_day,
    ),
    ZTESensorEntityDescription(
        key="data_projection",
        about=(
            "Projected total data usage for the current billing cycle, based on "
            "average daily consumption so far. It reads low on the first day of a "
            "cycle and settles within 24 hours."
        ),
        translation_key="data_projection",
        device_class=SensorDeviceClass.DATA_SIZE,
        # Deliberately **no** `state_class`, so this never reaches long-term
        # statistics.
        #
        # This is an estimate of where the current cycle ends up, and it is
        # useful now — not as a history. The measurement it derives from,
        # `Monthly Total`, is already recorded with a proper state class, so
        # keeping the projection's own history would store a derived view of a
        # number that is already stored, and invite charts of what we once
        # guessed rather than what actually happened.
        #
        # `MEASUREMENT` would have been the only defensible class if it were
        # kept — `TOTAL` would make the statistics engine read every fall (a
        # heavy first week diluted by a quiet second) as a counter reset, which
        # only a manual purge undoes.
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        min_limit=0,
        group="data",
        value_fn=_projected_bytes,
    ),
    ZTESensorEntityDescription(
        key="lte_multi_ca_scell_info",
        about=(
            "Raw descriptor of the additional 4G carriers in use, one "
            "semicolon-terminated group per secondary cell. The fields are cell "
            "index, PCI, a value that varies between polls, LTE band, EARFCN and "
            "bandwidth in MHz - so '2,352,1,20,6300,10' is band 20 on EARFCN 6300 "
            "at 10 MHz. The named Carrier Aggregation sensors are friendlier for "
            "display."
        ),
        translation_key="signal_lte_multi_ca_scell_info",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_str(data.get("lte_multi_ca_scell_info")),
    ),
    ZTESensorEntityDescription(
        key="opms_wan_mode",
        about=(
            "Whether the router is passing traffic as a gateway of its own or "
            "bridging it straight through to equipment behind it. Changing this "
            "is deliberately not offered here: it alters the path this "
            "integration reaches the router over, so use the router's own web "
            "page where a mistake can still be undone."
        ),
        translation_key="system_opms_wan_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_str(data.get("opms_wan_mode")),
    ),
    ZTESensorEntityDescription(
        key="opms_wan_auto_mode",
        about=(
            "The WAN operating mode the router falls back to automatically. A "
            "difference between this and the active mode is normal."
        ),
        translation_key="system_opms_wan_auto_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_str(data.get("opms_wan_auto_mode")),
    ),
    ZTESensorEntityDescription(
        key="sntp_timezone",
        about=(
            "The router's configured base timezone and Daylight Saving Time "
            "(DST) offset - for example '0-1' represents base offset UTC+0 with "
            "DST active."
        ),
        translation_key="system_sntp_timezone",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_str(data.get("sntp_timezone")),
    ),
    ZTESensorEntityDescription(
        key="apn_interface_version",
        about=(
            "Which version of the router's own APN configuration format is in "
            "use. Only of interest when an APN change is not taking effect."
        ),
        translation_key="system_apn_interface_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        source=ENDPOINT_EXTENDED,
        value_fn=lambda data: _safe_str(data.get("apn_interface_version")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: ZTERouterDataUpdateCoordinator = entry.runtime_data
    async_add_entities(
        [
            ZTERouterSensor(coordinator, entry, description)
            for description in SENSOR_TYPES
        ]
    )


class ZTERouterSensor(
    ZTEAboutEntity, CoordinatorEntity[ZTERouterDataUpdateCoordinator], SensorEntity
):
    """Representation of a ZTE Router sensor."""

    _attr_has_entity_name = True
    entity_description: ZTESensorEntityDescription

    # Attributes excluded from the recorder (dev_standards Section 14). The
    # entity's state is still recorded — only these named keys are dropped.
    #
    # `number` is the SMS *sender's* phone number: third-party personal data
    # that would otherwise be written to the database on every poll. `id` and
    # `date` change with each new message and have no historical value beside
    # the state itself. The eight SMS counters are a breakdown of a state that
    # is already recorded, so keeping them would store the same movement twice.
    #
    # Section 14: every attribute this entity can publish is listed here. The
    # default is total — attributes carry detail that does not merit its own
    # entity, not history. `sntp_server1` and `sntp_dst_enable` were previously
    # exempted as "static config worth seeing in history"; that justification
    # does not survive the rule, since anyone who needs their history should
    # have them as an entity or a template sensor.
    _unrecorded_attributes = frozenset(
        {
            "about",
            "sntp_server1",
            "sntp_server2",
            "sntp_dst_enable",
            "confidence",
            "basis",
            "cycle_day",
            "cycle_start",
            "cycle_source",
            "id",
            "number",
            "date",
            "sms_nv_total",
            "sms_sim_total",
            "sms_nv_rev_total",
            "sms_nv_send_total",
            "sms_nv_draftbox_total",
            "sms_sim_rev_total",
            "sms_sim_send_total",
            "sms_sim_draftbox_total",
        }
    )

    def __init__(
        self,
        coordinator: ZTERouterDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ZTESensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def available(self) -> bool:
        """Return whether this sensor has a working data source.

        Sensors fed by an optional endpoint go unavailable when that endpoint
        alone has exhausted its strike budget, while the rest of the
        integration keeps serving data (Section 8).
        """
        if not super().available:
            return False
        source = self.entity_description.source
        return source is None or self.coordinator.endpoint_available(source)

    @property
    def native_value(self) -> Any:
        """Return the value of the sensor."""
        if not self.coordinator.data:
            return None

        key = self.entity_description.key

        if key == "last_updated":
            return self.coordinator.last_update_success_time

        try:
            value = self.entity_description.value_fn(self.coordinator.data)
        except (KeyError, AttributeError, ValueError):
            return None

        if value is None:
            return None

        # Guard bands
        if isinstance(value, (int, float)):
            if (
                self.entity_description.min_limit is not None
                and value < self.entity_description.min_limit
            ):
                return None
            if (
                self.entity_description.max_limit is not None
                and value > self.entity_description.max_limit
            ):
                return None

        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the `about` note, plus detailed attributes for some sensors.

        Every return path goes through `_with_about` — a bare `return {}` here
        would drop the note for that sensor only, which is the kind of gap that
        shows up as "some entities have an about and some don't" much later.
        """
        data = self.coordinator.data
        key = self.entity_description.key
        detail: dict[str, Any] = {}

        if data:
            if key == "msg_total":
                try:
                    detail = {
                        "sms_nv_total": int(data.get("sms_nv_total", 0)),
                        "sms_sim_total": int(data.get("sms_sim_total", 0)),
                        "sms_nv_rev_total": int(data.get("sms_nv_rev_total", 0)),
                        "sms_nv_send_total": int(data.get("sms_nv_send_total", 0)),
                        "sms_nv_draftbox_total": int(
                            data.get("sms_nv_draftbox_total", 0)
                        ),
                        "sms_sim_rev_total": int(data.get("sms_sim_rev_total", 0)),
                        "sms_sim_send_total": int(data.get("sms_sim_send_total", 0)),
                        "sms_sim_draftbox_total": int(
                            data.get("sms_sim_draftbox_total", 0)
                        ),
                    }
                except (ValueError, TypeError):
                    detail = {}
            elif key == "msg_recent":
                msg = data.get("last_sms", {})
                detail = {
                    "id": msg.get("id"),
                    "number": msg.get("number_decoded"),
                    "date": msg.get("date_decoded"),
                }
            elif key == "data_projection":
                if (result := _projection(data)) is not None:
                    detail = {
                        "confidence": result.confidence,
                        "basis": result.basis,
                        "cycle_day": (
                            f"{int(result.elapsed_days) + 1} of "
                            f"{result.cycle_length_days}"
                        ),
                        "cycle_start": result.cycle_start.date().isoformat(),
                        "cycle_source": result.cycle_source,
                    }
            elif key == "sntp_server":
                detail = {
                    "sntp_server1": data.get("sntp_server1"),
                    "sntp_server2": data.get("sntp_server2"),
                    "sntp_dst_enable": data.get("sntp_dst_enable") == "1",
                }

        return self._with_about(detail) or {}

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information with sub-device support."""
        return build_device_info(
            self.coordinator, self._entry, self.entity_description.group
        )
