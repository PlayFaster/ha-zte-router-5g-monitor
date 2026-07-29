"""Sensor platform for ZTE Router 5G."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
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
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ENDPOINT_SMS_MESSAGES, ZTERouterDataUpdateCoordinator
from .helpers import (
    ZTEAboutEntity,
    arfcn_to_band,
    build_device_info,
    earfcn_to_band,
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
        return sum(int(data.get(k, 0)) for k in keys)
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


def _get_first(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first key in `keys` that the router actually populated.

    Members of the `goform` family spell the same measurement differently, so
    a sensor names every spelling it knows and takes whichever one arrives.
    A key that is present but empty counts as absent — this API answers with
    `""` for fields the hardware does not support, so `in data` alone is not
    enough to tell "supported" from "reported".

    Every key named here must also be requested in `api.py:get_all_data()`;
    an alias for a key that is never asked for can never fire.
    """
    return next(
        (data[key] for key in keys if key in data and data[key] not in ("", None)),
        None,
    )


# Cross-model key aliases. The first entry is the spelling the MC7010 uses, so
# its execution path is unchanged; later entries only come into play on
# hardware that does not populate the first.
_ALIAS_5G_RSRP: Final = ("Z5g_rsrp", "5g_rsrp", "nr5g_rsrp")
_ALIAS_5G_SINR: Final = ("Z5g_SINR", "Z5g_snr", "5g_sinr", "nr5g_sinr")
_ALIAS_5G_PCI: Final = ("nr5g_pci", "Z5g_CELL_ID")
_ALIAS_MONTHLY_TX: Final = ("monthly_tx_bytes", "flux_monthly_tx_bytes")
_ALIAS_MONTHLY_RX: Final = ("monthly_rx_bytes", "flux_monthly_rx_bytes")


def _monthly_total_bytes(data: dict[str, Any]) -> int | None:
    """Sum the monthly TX and RX counters, honouring the key aliases.

    Shared by the GB and raw-bytes totals so they cannot disagree with the
    individual TX/RX sensors on hardware that uses the `flux_` spelling —
    a divergence that would look like real data rather than a bug.
    """
    tx = _safe_int(_get_first(data, _ALIAS_MONTHLY_TX))
    rx = _safe_int(_get_first(data, _ALIAS_MONTHLY_RX))
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
        value_fn=lambda data: _safe_int(data.get("realtime_time")),
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
        value_fn=lambda data: data.get("hardware_version"),
    ),
    ZTESensorEntityDescription(
        key="battery_value",
        about=(
            "Battery charge, on ZTE models that have one. A mains-powered unit such "
            "as the MC7010 has no battery yet still reports 100%, so the value means "
            "nothing unless your model actually has one. Disabled by default for "
            "that reason."
        ),
        translation_key="system_battery_value",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
        min_limit=0,
        max_limit=100,
        group="system",
        value_fn=lambda data: _safe_int(data.get("battery_value")),
    ),
    # Thermal telemetry. This is the set of thermal keys the sibling project
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
            "Temperature of the power amplifier - the part of the radio that drives "
            "the transmit signal, and normally the hottest thing in the unit. Many "
            "ZTE models do not report it, in which case this stays unknown."
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
        value_fn=lambda data: _safe_float(data.get("pm_sensor_pa1")),
    ),
    ZTESensorEntityDescription(
        key="pm_sensor_ambient",
        about=(
            "Internal air temperature inside the modem, away from the radio itself. "
            "Read alongside the power amplifier temperature it indicates whether the "
            "unit as a whole is running hot or just the transmitter."
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
        value_fn=lambda data: _safe_float(data.get("pm_sensor_ambient")),
    ),
    ZTESensorEntityDescription(
        key="pm_sensor_mdm",
        about=(
            "Temperature of the modem module - the cellular baseband, as distinct "
            "from the power amplifier that drives the transmit signal. Many ZTE "
            "models do not report it, in which case this stays unknown."
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
        value_fn=lambda data: _safe_float(data.get("pm_sensor_mdm")),
    ),
    ZTESensorEntityDescription(
        key="pm_modem_5g",
        about=(
            "Temperature reported by the 5G modem section. The vendor does not "
            "document how this differs from the 5G radio temperature; on hardware "
            "that populates both, compare them before relying on either."
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
        value_fn=lambda data: _safe_float(data.get("pm_modem_5g")),
    ),
    ZTESensorEntityDescription(
        key="pm_sensor_5g",
        about=(
            "Temperature of the 5G radio. The vendor does not document how this "
            "differs from the 5G modem temperature; on hardware that populates "
            "both, compare them before relying on either."
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
            "Access Point Name - the gateway profile the router uses to reach your "
            "ISP's network. A wrong APN is a common cause of a router that has good "
            "signal but no working data."
        ),
        translation_key="signal_wan_apn",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_str(data.get("wan_apn")),
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
        value_fn=lambda data: _safe_str(data.get("network_type")),
    ),
    ZTESensorEntityDescription(
        key="signalbar",
        about=(
            "The router's own signal rating, 0 to 5, the same one shown on its web "
            "page. It is a coarse summary - for anything precise use RSRP or SINR, "
            "which is what the bars are derived from."
        ),
        translation_key="signal_signalbar",
        state_class=SensorStateClass.MEASUREMENT,
        group="signal",
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
        value_fn=lambda data: _safe_str(data.get("network_provider")),
    ),
    ZTESensorEntityDescription(
        key="mdm_mcc",
        about=(
            "Mobile Country Code - a three-digit code identifying the country of the "
            "network the modem is attached to (for example 272 = Ireland)."
        ),
        translation_key="signal_mdm_mcc",
        entity_category=EntityCategory.DIAGNOSTIC,
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
        value_fn=lambda data: data.get("rmnc"),
    ),
    ZTESensorEntityDescription(
        key="lte_rsrp",
        about=(
            "Reference Signal Received Power - the strength of the 4G signal, in dBm. "
            "This is the single most useful number for aiming or siting the router. "
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
        value_fn=lambda data: _safe_float(data.get("lte_rsrp")),
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
            "4G cell sector serving the router. Neighbouring sectors reuse the range, "
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
        value_fn=lambda data: data.get("lte_ca_pcell_band"),
    ),
    ZTESensorEntityDescription(
        key="lte_ca_pcell_bandwidth",
        about=(
            "The channel width of the primary 4G band, in MHz. Wider is faster: 20 "
            "MHz carries roughly four times the data of 5 MHz, all else being equal."
        ),
        translation_key="signal_lte_ca_pcell_bandwidth",
        native_unit_of_measurement="MHz",
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_ca_pcell_bandwidth")),
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
        value_fn=lambda data: data.get("lte_ca_scell_band") or None,
    ),
    ZTESensorEntityDescription(
        key="lte_ca_scell_bandwidth",
        about=(
            "Channel width of the aggregated secondary 4G band, in MHz. It adds to "
            "the primary band's capacity rather than replacing it."
        ),
        translation_key="signal_lte_ca_scell_bandwidth",
        native_unit_of_measurement="MHz",
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: _safe_float(data.get("lte_ca_scell_bandwidth")),
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
            "of interest when comparing against neighbouring cells or diagnosing "
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
        value_fn=lambda data: _safe_float(_get_first(data, _ALIAS_5G_RSRP)),
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
            "Signal-to-Interference-plus-Noise Ratio for 5G, in dB - the clearest "
            "predictor of 5G speed, because it accounts for interference as well as "
            "noise. Typically: above 20 is excellent, 13 to 20 good, 0 to 13 fair, "
            "below 0 poor."
        ),
        translation_key="signal_z5g_sinr",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="dB",
        min_limit=-20,
        max_limit=50,
        group="signal",
        value_fn=lambda data: _safe_float(_get_first(data, _ALIAS_5G_SINR)),
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
        value_fn=lambda data: _safe_str(_get_first(data, _ALIAS_5G_PCI)),
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
            "neighbouring cells."
        ),
        translation_key="signal_nr5g_action_channel",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: _safe_int(data.get("nr5g_action_channel")),
    ),
    ZTESensorEntityDescription(
        key="rssi",
        about=(
            "Overall received signal strength reported by the modem, in dBm. Kept for "
            "completeness - the per-technology LTE and 5G metrics are more "
            "diagnostic."
        ),
        translation_key="signal_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        min_limit=-120,
        max_limit=-20,
        group="signal",
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
            "by the Network Mode control. Restricting it can stabilise a connection "
            "that keeps switching between 4G and 5G."
        ),
        translation_key="signal_net_select",
        entity_category=EntityCategory.DIAGNOSTIC,
        group="signal",
        value_fn=lambda data: data.get("net_select"),
    ),
    ZTESensorEntityDescription(
        key="ppp_status",
        about=(
            "The state of the data session with your ISP. It can show disconnected "
            "while the radio signal is still strong, which points at an APN or "
            "account problem rather than coverage."
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
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
        group="data",
        # Divided by 1_000_000_000 to match decimal GB (UnitOfInformation.GIGABYTES)
        value_fn=lambda data: _get_bytes_to_gb(_get_first(data, _ALIAS_MONTHLY_TX)),
    ),
    ZTESensorEntityDescription(
        key="monthly_rx_bytes",
        about=(
            "Data downloaded this billing month, as counted by the router. Treat it "
            "as a close guide rather than an exact match for your ISP's billing."
        ),
        translation_key="data_monthly_rx_bytes",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
        group="data",
        # Divided by 1_000_000_000 to match decimal GB (UnitOfInformation.GIGABYTES)
        value_fn=lambda data: _get_bytes_to_gb(_get_first(data, _ALIAS_MONTHLY_RX)),
    ),
    ZTESensorEntityDescription(
        key="monthly_total_bytes",
        about=(
            "Combined upload and download for the billing month - the figure to "
            "compare against a data cap."
        ),
        translation_key="data_monthly_total_bytes",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
        group="data",
        value_fn=lambda data: _get_bytes_to_gb(_monthly_total_bytes(data)),
    ),
    # Standard Byte Sensors (Enabled by default, supports UI conversion)
    ZTESensorEntityDescription(
        key="monthly_tx_bytes_raw",
        about=(
            "The same monthly upload total in bytes, unconverted. Provided for "
            "automations that need the exact number; the GB version is the friendlier "
            "one to display."
        ),
        translation_key="data_monthly_tx_bytes_raw",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        group="data",
        value_fn=lambda data: _safe_int(_get_first(data, _ALIAS_MONTHLY_TX)),
    ),
    ZTESensorEntityDescription(
        key="monthly_rx_bytes_raw",
        about=(
            "The same monthly download total in bytes, unconverted. Use the GB "
            "version for display and this one for precise arithmetic."
        ),
        translation_key="data_monthly_rx_bytes_raw",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        group="data",
        value_fn=lambda data: _safe_int(_get_first(data, _ALIAS_MONTHLY_RX)),
    ),
    ZTESensorEntityDescription(
        key="monthly_total_bytes_raw",
        about=(
            "Combined monthly upload and download in bytes. The GB sensor is easier "
            "to read; this one avoids rounding in automations."
        ),
        translation_key="data_monthly_total_bytes_raw",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        group="data",
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
        value_fn=lambda data: _safe_int(data.get("realtime_tx_thrpt")),
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
        value_fn=lambda data: _safe_int(data.get("realtime_rx_thrpt")),
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
        value_fn=lambda data: _safe_int(data.get("realtime_tx_bytes")),
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
        value_fn=lambda data: _safe_int(data.get("realtime_rx_bytes")),
    ),
    # --- SMS Sub-device ---
    ZTESensorEntityDescription(
        key="sms_unread_num",
        translation_key="sms_sms_unread_num",
        state_class=SensorStateClass.MEASUREMENT,
        group="sms",
        value_fn=lambda data: _safe_int(data.get("sms_unread_num")),
    ),
    ZTESensorEntityDescription(
        key="msg_total",
        about=(
            "Total messages held across every storage area - router memory and SIM, "
            "inbox, sent and drafts. The breakdown per area is in this sensor's "
            "attributes. Storage filling up stops new messages arriving, which the "
            "Integration Health sensor flags."
        ),
        translation_key="sms_msg_total",
        state_class=SensorStateClass.MEASUREMENT,
        group="sms",
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
            "Which 4G bands the modem is permitted to use, as a bitmask. Locking to a "
            "band can help a marginal connection, but locking to one that is "
            "unavailable will leave the router with no service."
        ),
        translation_key="signal_lte_band_lock",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="signal",
        value_fn=lambda data: _safe_str(data.get("lte_band_lock")),
    ),
    ZTESensorEntityDescription(
        key="data_volume_alert_percent",
        about=(
            "The percentage of your configured data allowance at which the router "
            "raises its own alert. This is the router's internal warning threshold, "
            "separate from any automation you build in Home Assistant."
        ),
        translation_key="data_volume_alert_percent",
        native_unit_of_measurement="%",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        min_limit=0,
        max_limit=100,
        group="data",
        value_fn=lambda data: _safe_int(data.get("data_volume_alert_percent")),
    ),
    ZTESensorEntityDescription(
        key="sntp_server",
        about=(
            "The time server the router synchronises its clock from. An unreachable "
            "time server can make the timestamps on SMS messages and logs wrong, so "
            "it is worth checking if dates look implausible."
        ),
        translation_key="system_sntp_server",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        group="system",
        value_fn=lambda data: _safe_str(data.get("sntp_server0")),
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
            "sntp_dst_enable",
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
            elif key == "sntp_server":
                detail = {
                    "sntp_server1": data.get("sntp_server1"),
                    "sntp_dst_enable": data.get("sntp_dst_enable") == "1",
                }

        return self._with_about(detail) or {}

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information with sub-device support."""
        return build_device_info(
            self.coordinator, self._entry, self.entity_description.group
        )
