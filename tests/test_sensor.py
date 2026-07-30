"""Tests for the ZTE Router sensor."""

import pathlib
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTime,
)
from homeassistant.util import dt as dt_util

from custom_components.zte_router_5g.const import DOMAIN
from custom_components.zte_router_5g.coordinator import ENDPOINT_EXTENDED
from custom_components.zte_router_5g.sensor import (
    _ALIAS_5G_PCI,
    _ALIAS_5G_RSRP,
    _ALIAS_5G_SINR,
    _ALIAS_CLEAR_DAY,
    _ALIAS_MONTHLY_RX,
    _ALIAS_MONTHLY_TX,
    SENSOR_TYPES,
    ZTERouterSensor,
    ZTESensorEntityDescription,
    _clear_day,
    _data_allowance_bytes,
    _get_first,
    _projected_bytes,
    _projection,
    async_setup_entry,
)

from .conftest import assert_is_root, assert_links_to_parent

# --- TESTS FOR ZTERouterSensor ---


def test_sensor_rsrp_simple(mock_coordinator, mock_config_entry):
    """Test standard technical sensor extraction."""
    mock_coordinator.data = {"lte_rsrp": "-95"}
    description = next(d for d in SENSOR_TYPES if d.key == "lte_rsrp")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)

    assert sensor.native_value == -95.0


def test_sensor_z5g_case_sensitivity(mock_coordinator, mock_config_entry):
    """Test the specific case-sensitive mapping for 5G keys."""
    # The router provides 'Z5g_rsrp'
    mock_coordinator.data = {"Z5g_rsrp": "-102"}
    description = next(d for d in SENSOR_TYPES if d.key == "z5g_rsrp")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    assert sensor.native_value == -102.0

    # Test sinr
    mock_coordinator.data = {"Z5g_SINR": "15"}
    description = next(d for d in SENSOR_TYPES if d.key == "z5g_sinr")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    assert sensor.native_value == 15.0


def test_sensor_byte_to_gb_conversion(mock_coordinator, mock_config_entry):
    """Test that monthly_rx_bytes is converted from bytes to GB."""
    # 2GB in bytes (decimal: 2 * 1_000_000_000)
    mock_coordinator.data = {"monthly_rx_bytes": "2000000000"}
    description = next(d for d in SENSOR_TYPES if d.key == "monthly_rx_bytes")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)

    # 2000000000 / 1000000000 = 2.0
    assert sensor.native_value == 2.0


def test_sensor_monthly_total_sum(mock_coordinator, mock_config_entry):
    """Test the manual summing and conversion of monthly_total_bytes."""
    mock_coordinator.data = {
        "monthly_rx_bytes": "1000000000",  # 1GB (decimal)
        "monthly_tx_bytes": "500000000",  # 0.5GB (decimal)
    }
    description = next(d for d in SENSOR_TYPES if d.key == "monthly_total_bytes")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)

    assert sensor.native_value == 1.5

    # Test error path
    mock_coordinator.data = {"monthly_rx_bytes": "invalid"}
    assert sensor.native_value is None


def test_sensor_uptime_calculation(mock_coordinator, mock_config_entry):
    """Test the complex uptime to timestamp conversion."""
    # Mock 'now' to a fixed point
    now = dt_util.now().replace(second=0, microsecond=0)
    # boot_time is set by the coordinator; simulate it here
    expected_time = now - timedelta(seconds=3600)
    mock_coordinator.data = {"boot_time": expected_time}

    description = next(d for d in SENSOR_TYPES if d.key == "device_uptime")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)

    with patch("homeassistant.util.dt.now", return_value=now):
        # Result should be exactly 1 hour ago
        assert sensor.native_value == expected_time

    # Test empty case
    mock_coordinator.data = {"realtime_time": ""}
    assert sensor.native_value is None

    # Test exception case
    mock_coordinator.data = {"realtime_time": "invalid"}
    assert sensor.native_value is None


def test_sensor_last_updated(mock_coordinator, mock_config_entry):
    """Test the last_updated sensor."""
    now = dt_util.now()
    mock_coordinator.last_update_success_time = now
    # Ensure data is truthy so the property proceeds
    mock_coordinator.data = {"some": "data"}

    description = next(d for d in SENSOR_TYPES if d.key == "last_updated")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)

    assert sensor.native_value == now


def test_sensor_error_handling(mock_coordinator, mock_config_entry):
    """Test error handling in native_value."""
    mock_coordinator.data = {"monthly_rx_bytes": "invalid"}
    description = next(d for d in SENSOR_TYPES if d.key == "monthly_rx_bytes")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)

    # Should return None if callback fails (e.g. ValueError)
    assert sensor.native_value is None


def test_sensor_device_info(mock_coordinator, mock_config_entry):
    """Test device_info for main (system), signal, data, and sms groups."""
    mac = "864155042229309"

    # System (Root) group sensor
    description = next(d for d in SENSOR_TYPES if d.key == "device_uptime")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    info = sensor.device_info
    assert info["identifiers"] == {(DOMAIN, f"{mac}_system")}
    assert info["name"] == "My ZTE Router System"
    assert_is_root(info)

    # Signal group sensor
    description = next(d for d in SENSOR_TYPES if d.key == "lte_rsrp")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    info = sensor.device_info
    assert info["identifiers"] == {(DOMAIN, f"{mac}_signal")}
    assert info["name"] == "My ZTE Router Signal"
    assert_links_to_parent(info, DOMAIN, f"{mac}_system")

    # Data group sensor
    description = next(d for d in SENSOR_TYPES if d.key == "monthly_rx_bytes")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    info = sensor.device_info
    assert info["identifiers"] == {(DOMAIN, f"{mac}_data")}
    assert info["name"] == "My ZTE Router Data"
    assert_links_to_parent(info, DOMAIN, f"{mac}_system")

    # SMS group sensor
    description = next(d for d in SENSOR_TYPES if d.key == "msg_total")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    info = sensor.device_info
    assert info["identifiers"] == {(DOMAIN, f"{mac}_sms")}
    assert info["name"] == "My ZTE Router SMS"
    assert_links_to_parent(info, DOMAIN, f"{mac}_system")


# --- SMS SPECIFIC TESTS ---


def test_sensor_sms_summing(mock_coordinator, mock_config_entry):
    """Test that all 6 SMS storage keys are summed correctly."""
    mock_coordinator.data = {
        "sms_nv_rev_total": "10",
        "sms_nv_send_total": "5",
        "sms_nv_draftbox_total": "1",
        "sms_sim_rev_total": "2",
        "sms_sim_send_total": "0",
        "sms_sim_draftbox_total": "1",
    }
    description = next(d for d in SENSOR_TYPES if d.key == "msg_total")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)

    # Sum: 10 + 5 + 1 + 2 + 0 + 1 = 19
    assert sensor.native_value == 19


def test_sensor_sms_attributes(mock_coordinator, mock_config_entry):
    """Test that extra state attributes provide the raw breakdown."""
    mock_coordinator.data = {"sms_nv_total": "15", "sms_sim_total": "5"}
    description = next(d for d in SENSOR_TYPES if d.key == "msg_total")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)

    attrs = sensor.extra_state_attributes
    assert attrs["sms_nv_total"] == 15
    assert attrs["sms_sim_total"] == 5


def test_sensor_sms_content_extraction(mock_coordinator, mock_config_entry):
    """Test extraction of the last SMS content."""
    mock_coordinator.data = {
        "last_sms": {
            "id": "1",
            "content_decoded": "Hello from ZTE!",
            "number_decoded": "123456",
            "date_decoded": "2023-10-10 10:00:00",
        }
    }
    description = next(d for d in SENSOR_TYPES if d.key == "msg_recent")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)

    assert sensor.native_value == "Hello from ZTE!"
    assert sensor.extra_state_attributes["number"] == "123456"
    assert sensor.extra_state_attributes["id"] == "1"


@pytest.mark.asyncio
async def test_sensor_setup_entry():
    """Test platform setup."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test"
    entry.runtime_data = MagicMock()

    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)
    async_add_entities.assert_called_once()


def test_sensor_value_fn_exception(mock_coordinator, mock_config_entry):
    """Test that native_value catches unhandled exceptions in value_fn.

    Covers sensor.py lines 713-714 (outer except in native_value).
    """
    mock_coordinator.data = {"some": "data"}
    desc = ZTESensorEntityDescription(
        key="test_crash",
        translation_key="test_crash",
        value_fn=lambda x: x["nonexistent"],
    )
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, desc)
    assert sensor.native_value is None


def test_sensor_guard_band_min(mock_coordinator, mock_config_entry):
    """Test that native_value returns None when value is below min_limit.

    Covers sensor.py line 725.
    """
    mock_coordinator.data = {"some": "data"}
    desc = ZTESensorEntityDescription(
        key="test_min", translation_key="test_min", value_fn=lambda x: 10, min_limit=20
    )
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, desc)
    assert sensor.native_value is None


def test_sensor_guard_band_max(mock_coordinator, mock_config_entry):
    """Test that native_value returns None when value is above max_limit.

    Covers sensor.py line 730.
    """
    mock_coordinator.data = {"some": "data"}
    desc = ZTESensorEntityDescription(
        key="test_max", translation_key="test_max", value_fn=lambda x: 100, max_limit=50
    )
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, desc)
    assert sensor.native_value is None


def test_sensor_extra_attributes_other_key(mock_coordinator, mock_config_entry):
    """A sensor with no detail attributes still publishes its `about` note.

    `lte_rsrp` carries no per-sensor detail, so before the `about` suite it
    returned `{}`. It now returns the note alone — which is the point of the
    mixin: every entity that has something to explain explains it.
    """
    mock_coordinator.data = {"some": "data"}
    description = next(d for d in SENSOR_TYPES if d.key == "lte_rsrp")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    assert set(sensor.extra_state_attributes) == {"about"}
    assert "Reference Signal Received Power" in sensor.extra_state_attributes["about"]


def test_sensor_without_an_about_publishes_nothing(mock_coordinator, mock_config_entry):
    """Not every sensor gets a note, and those must stay attribute-free.

    Guards the other half of the mixin: `_with_about` must return the entity's
    own attributes untouched when no note is set, rather than inventing an
    empty `about` key.
    """
    mock_coordinator.data = {"some": "data"}
    description = next(d for d in SENSOR_TYPES if d.about is None)
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    assert sensor.extra_state_attributes == {}


# ── Strategy 1: Boundary Value Analysis ────────────────────────────────────


def test_sensor_guard_exactly_at_min_limit_passes(mock_coordinator, mock_config_entry):
    """1E: value == min_limit passes through: strict `<`, not `<=`."""
    mock_coordinator.data = {"some": "data"}
    desc = ZTESensorEntityDescription(
        key="test_min", translation_key="test_min", value_fn=lambda x: 20, min_limit=20
    )
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, desc)
    assert sensor.native_value == 20


def test_sensor_guard_exactly_at_max_limit_passes(mock_coordinator, mock_config_entry):
    """1E: value == max_limit passes through: strict `>`, not `>=`."""
    mock_coordinator.data = {"some": "data"}
    desc = ZTESensorEntityDescription(
        key="test_max", translation_key="test_max", value_fn=lambda x: 50, max_limit=50
    )
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, desc)
    assert sensor.native_value == 50


# ── Strategy 3: Error State & Negative Path Engineering ─────────────────────


def test_sensor_value_fn_attribute_error_caught(mock_coordinator, mock_config_entry):
    """3B: AttributeError in value_fn must be caught and return None."""
    desc = ZTESensorEntityDescription(
        key="test_attr",
        translation_key="test_attr",
        value_fn=lambda x: None.something,
    )
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, desc)
    try:
        result = sensor.native_value
    except AttributeError as exc:
        pytest.fail(
            f"native_value propagated AttributeError (sensor.py:667 bug): {exc}"
        )
    assert result is None


def test_sensor_value_fn_value_error_caught(mock_coordinator, mock_config_entry):
    """3B: ValueError in value_fn must be caught and return None."""
    desc = ZTESensorEntityDescription(
        key="test_val",
        translation_key="test_val",
        value_fn=lambda x: int("not-a-number"),
    )
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, desc)
    try:
        result = sensor.native_value
    except ValueError as exc:
        pytest.fail(f"native_value propagated ValueError (sensor.py:667 bug): {exc}")
    assert result is None


def test_sensor_extra_attributes_type_error_caught(mock_coordinator, mock_config_entry):
    """3C: TypeError in extra_state_attributes must be caught and return {}."""
    mock_coordinator.data = {"sms_nv_total": ["not", "an", "int"]}
    description = next(d for d in SENSOR_TYPES if d.key == "msg_total")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    try:
        attrs = sensor.extra_state_attributes
    except TypeError as exc:
        pytest.fail(
            f"extra_state_attributes raised TypeError (sensor.py:711 bug): {exc}"
        )
    # The detail dict degrades to empty on bad input; the `about` note is
    # static and must survive that — it does not depend on coordinator data.
    assert set(attrs) == {"about"}


# --- SUGGESTED DISPLAY UNIT / PRECISION ---


@pytest.mark.parametrize(
    ("key", "suggested_unit", "precision"),
    [
        # Data size (Bytes -> GB): monthly precision 1, session precision 2
        ("monthly_tx_bytes_raw", UnitOfInformation.GIGABYTES, 1),
        ("monthly_rx_bytes_raw", UnitOfInformation.GIGABYTES, 1),
        ("monthly_total_bytes_raw", UnitOfInformation.GIGABYTES, 1),
        ("realtime_tx_bytes", UnitOfInformation.GIGABYTES, 2),
        ("realtime_rx_bytes", UnitOfInformation.GIGABYTES, 2),
        # Data rate (B/s -> Mbit/s), precision 2
        ("realtime_tx_thrpt", UnitOfDataRate.MEGABITS_PER_SECOND, 2),
        ("realtime_rx_thrpt", UnitOfDataRate.MEGABITS_PER_SECOND, 2),
        # Duration (s -> h), precision 1
        ("realtime_time", UnitOfTime.HOURS, 1),
    ],
)
def test_sensor_suggested_unit_and_precision(key, suggested_unit, precision):
    """Sensors with a unit conversion carry the expected suggested unit/precision."""
    desc = next(d for d in SENSOR_TYPES if d.key == key)
    assert desc.suggested_unit_of_measurement == suggested_unit
    assert desc.suggested_display_precision == precision


def test_sensor_uptime_duration_native_is_seconds():
    """The uptime duration sensor keeps seconds as its native (canonical) unit."""
    desc = next(d for d in SENSOR_TYPES if d.key == "realtime_time")
    assert desc.native_unit_of_measurement == UnitOfTime.SECONDS


@pytest.mark.parametrize(
    "key",
    [
        # Bandwidth in MHz -> 0 decimals (no unit change)
        "lte_ca_pcell_bandwidth",
        "lte_ca_scell_bandwidth",
        # Signal strength in dBm -> 0 decimals (no unit change)
        "lte_rsrp",
        "lte_rssi",
        "z5g_rsrp",
        "z5g_rssi",
        "rssi",
        "rscp",
    ],
)
def test_sensor_zero_precision_no_unit_change(key):
    """MHz bandwidth and dBm signal sensors round to 0 dp, unit unchanged."""
    desc = next(d for d in SENSOR_TYPES if d.key == key)
    assert desc.suggested_display_precision == 0
    assert desc.suggested_unit_of_measurement is None


# ── Coverage gap: _safe_str normal path ──────────────────────────────────


def test_sensor_safe_str_empty(mock_coordinator, mock_config_entry):
    """Test that _safe_str returns None for None/empty values.

    Covers sensor.py:107 (return None for empty values).
    """
    mock_coordinator.data = {"some": "data"}
    description = next(d for d in SENSOR_TYPES if d.key == "wan_ipaddr")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    assert sensor.native_value is None


def test_sensor_safe_str_normal_path(mock_coordinator, mock_config_entry):
    """Test that _safe_str returns str(val) for non-empty values.

    Covers sensor.py:108 (return str(val)).
    """
    mock_coordinator.data = {"wan_ipaddr": "192.168.1.1"}
    description = next(d for d in SENSOR_TYPES if d.key == "wan_ipaddr")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    assert sensor.native_value == "192.168.1.1"


# ── Coverage gap: sntp_server extra_state_attributes ─────────────────────


def test_sensor_sntp_server_attributes(mock_coordinator, mock_config_entry):
    """Test extra_state_attributes for sntp_server sensor.

    Covers sensor.py:775-779.
    """
    mock_coordinator.data = {
        "sntp_server0": "pool.ntp.org",
        "sntp_server1": "time.google.com",
        "sntp_dst_enable": "1",
    }
    description = next(d for d in SENSOR_TYPES if d.key == "sntp_server")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    assert sensor.native_value == "pool.ntp.org"
    attrs = sensor.extra_state_attributes
    assert attrs["sntp_server1"] == "time.google.com"
    assert attrs["sntp_dst_enable"] is True


def test_sensor_sntp_server_attributes_dst_disabled(
    mock_coordinator, mock_config_entry
):
    """Test sntp_server attributes with DST disabled."""
    mock_coordinator.data = {
        "sntp_server0": "pool.ntp.org",
        "sntp_server1": "time.google.com",
        "sntp_dst_enable": "0",
    }
    description = next(d for d in SENSOR_TYPES if d.key == "sntp_server")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    attrs = sensor.extra_state_attributes
    assert attrs["sntp_dst_enable"] is False


# --- Phase 3: cross-model key aliasing -------------------------------------


def _value_for(key, data):
    """Run one sensor description's value_fn against a payload."""
    description = next(d for d in SENSOR_TYPES if d.key == key)
    return description.value_fn(data)


def test_get_first_prefers_the_earliest_populated_key():
    """The MC7010 spelling is first, so its path is unchanged."""
    assert _get_first({"a": "1", "b": "2"}, ("a", "b")) == "1"


def test_get_first_skips_keys_that_are_present_but_empty():
    """A present-but-empty value means unsupported, not zero."""
    assert _get_first({"a": "", "b": "2"}, ("a", "b")) == "2"
    assert _get_first({"a": None, "b": "2"}, ("a", "b")) == "2"


def test_get_first_returns_none_when_nothing_is_populated():
    """No spelling present means unknown, not zero."""
    assert _get_first({"a": ""}, ("a", "b")) is None
    assert _get_first({}, ("a", "b")) is None


def test_get_first_keeps_a_genuine_zero():
    """Zero is a real reading; only '' and None mean absent."""
    assert _get_first({"a": 0}, ("a", "b")) == 0


@pytest.mark.parametrize(
    ("key", "primary", "alternates"),
    [
        ("z5g_rsrp", "Z5g_rsrp", ["5g_rsrp", "nr5g_rsrp"]),
        ("z5g_sinr", "Z5g_SINR", ["Z5g_snr", "5g_sinr", "nr5g_sinr"]),
    ],
)
def test_signal_sensors_read_every_alias(key, primary, alternates):
    """Each alternate spelling must produce the same reading as the primary."""
    assert _value_for(key, {primary: "-95.5"}) == -95.5
    for alternate in alternates:
        assert _value_for(key, {alternate: "-95.5"}) == -95.5, alternate


def test_5g_pci_reads_the_alternate_spelling():
    """nr5g_pci is the MC7010 key; Z5g_CELL_ID is the fallback."""
    assert _value_for("nr5g_pci", {"nr5g_pci": "301"}) == "301"
    assert _value_for("nr5g_pci", {"Z5g_CELL_ID": "301"}) == "301"


def test_the_primary_spelling_wins_when_both_are_present():
    """Behaviour on the MC7010 must not change because an alias exists."""
    assert _value_for("z5g_rsrp", {"Z5g_rsrp": "-90", "nr5g_rsrp": "-70"}) == -90.0


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("monthly_tx_bytes", 2.0),
        ("monthly_rx_bytes", 3.0),
        ("monthly_tx_bytes_raw", 2000000000),
        ("monthly_rx_bytes_raw", 3000000000),
        ("monthly_total_bytes", 5.0),
        ("monthly_total_bytes_raw", 5000000000),
    ],
)
def test_all_six_monthly_call_sites_honour_the_flux_aliases(key, expected):
    """Aliasing only some call sites would leave the totals silently zeroed."""
    flux_only = {
        "flux_monthly_tx_bytes": "2000000000",
        "flux_monthly_rx_bytes": "3000000000",
    }
    assert _value_for(key, flux_only) == expected


def test_monthly_totals_agree_with_their_components_on_either_spelling():
    """The divergence this guards against would look like real data."""
    for tx_key, rx_key in (
        ("monthly_tx_bytes", "monthly_rx_bytes"),
        ("flux_monthly_tx_bytes", "flux_monthly_rx_bytes"),
    ):
        data = {tx_key: "1000000000", rx_key: "4000000000"}
        components = _value_for("monthly_tx_bytes_raw", data) + _value_for(
            "monthly_rx_bytes_raw", data
        )
        assert _value_for("monthly_total_bytes_raw", data) == components


def test_monthly_total_is_unknown_when_either_side_is_missing():
    """A half-known total is worse than no total."""
    assert _value_for("monthly_total_bytes_raw", {"monthly_tx_bytes": "5"}) is None
    assert _value_for("monthly_total_bytes_raw", {"monthly_tx_bytes": ""}) is None
    assert _value_for("monthly_total_bytes", {}) is None


def test_monthly_total_handles_a_genuine_zero_counter():
    """A freshly reset counter reads 0, not unknown."""
    data = {"monthly_tx_bytes": "0", "monthly_rx_bytes": "0"}
    assert _value_for("monthly_total_bytes_raw", data) == 0


# --- Phase 3: band name fallback -------------------------------------------


def test_band_sensors_prefer_the_name_the_router_reports():
    """The resolver is a fallback; a reported name always wins."""
    data = {"wan_active_band": "B3", "wan_active_channel": "9360"}
    assert _value_for("wan_active_band", data) == "B3"

    data = {"nr5g_action_band": "n1", "nr5g_action_channel": "630000"}
    assert _value_for("nr5g_action_band", data) == "n1"


def test_band_sensors_derive_the_name_from_the_channel_when_absent():
    """Some models report the channel but leave the band name empty."""
    assert _value_for("wan_active_band", {"wan_active_channel": "9360"}) == "B28"
    assert (
        _value_for(
            "wan_active_band", {"wan_active_band": "", "wan_active_channel": "9360"}
        )
        == "B28"
    )
    assert _value_for("nr5g_action_band", {"nr5g_action_channel": "630000"}) == "n78"


def test_band_sensors_report_unknown_rather_than_guessing():
    """Neither a name nor a resolvable channel means unknown."""
    assert _value_for("wan_active_band", {}) is None
    assert _value_for("wan_active_band", {"wan_active_channel": "999999"}) is None
    assert _value_for("nr5g_action_band", {"nr5g_action_channel": ""}) is None


# --- Phase 3: thermal diagnostics ------------------------------------------

# The full set of thermal keys the sibling project Kajkac polls with °C units,
# verified against its const.py and live batch cmd strings. Kept as one tuple so
# a sensor added without a test, or a test without a sensor, shows up as a
# mismatch in test_thermal_sensor_set_matches_the_descriptions.
_THERMAL_KEYS = (
    "pm_sensor_pa1",
    "pm_sensor_ambient",
    "pm_sensor_mdm",
    "pm_modem_5g",
    "pm_sensor_5g",
)


def test_thermal_sensor_set_matches_the_descriptions():
    """Guards against the set drifting back to an arbitrary subset."""
    declared = {
        d.key for d in SENSOR_TYPES if d.key.startswith(("pm_sensor", "pm_modem"))
    }
    assert declared == set(_THERMAL_KEYS)


@pytest.mark.parametrize("key", _THERMAL_KEYS)
def test_thermal_sensors_read_their_key(key):
    """Straight read with float coercion."""
    assert _value_for(key, {key: "42.5"}) == 42.5


@pytest.mark.parametrize("key", _THERMAL_KEYS)
def test_thermal_sensors_map_the_mc7010_empty_string_to_unknown(key):
    """The MC7010 answers '' for both; that must not reach a numeric sensor."""
    assert _value_for(key, {key: ""}) is None
    assert _value_for(key, {}) is None


@pytest.mark.parametrize("key", _THERMAL_KEYS)
def test_thermal_sensors_are_disabled_by_default_with_guard_bands(key):
    """Off by default on hardware that never populates them, and bounded."""
    description = next(d for d in SENSOR_TYPES if d.key == key)
    assert description.entity_registry_enabled_default is False
    assert description.entity_category is EntityCategory.DIAGNOSTIC
    assert description.device_class is SensorDeviceClass.TEMPERATURE
    assert description.group == "system"
    assert (description.min_limit, description.max_limit) == (-40, 125)
    assert description.about


def test_every_aliased_key_is_requested_by_the_batch_poll():
    """An alias naming a key api.py never asks for can never fire."""
    source = (
        pathlib.Path(__file__).parent.parent
        / "custom_components"
        / "zte_router_5g"
        / "api.py"
    ).read_text(encoding="utf-8")
    for alias in (
        _ALIAS_5G_RSRP
        + _ALIAS_5G_SINR
        + _ALIAS_5G_PCI
        + _ALIAS_MONTHLY_TX
        + _ALIAS_MONTHLY_RX
        + _ALIAS_CLEAR_DAY
    ):
        assert f'"{alias}"' in source, f"{alias} is aliased but never requested"


# --- Monthly reset day (`_clear_day`) ---


@pytest.mark.parametrize(
    "key", ["traffic_clear_date", "data_volume_clear_date", "data_volume_clear_day"]
)
def test_clear_day_reads_every_spelling(key):
    """Any one of the three spellings alone resolves."""
    assert _clear_day({key: "15"}) == 15


def test_clear_day_prefers_the_live_probed_spelling():
    """`traffic_clear_date` leads the tuple, so it wins a disagreement."""
    assert _clear_day({"traffic_clear_date": "1", "data_volume_clear_date": "20"}) == 1


def test_clear_day_warns_when_spellings_disagree(caplog):
    """A silent disagreement would show up months later as a skewed cycle."""
    _clear_day({"traffic_clear_date": "1", "data_volume_clear_date": "20"})
    assert "disagreeing monthly reset days" in caplog.text


def test_clear_day_is_quiet_when_spellings_agree(caplog):
    """Two spellings carrying the same value is not a fault."""
    _clear_day({"traffic_clear_date": "9", "data_volume_clear_day": "9"})
    assert "disagreeing" not in caplog.text


@pytest.mark.parametrize("raw", ["", None, "not-a-day"])
def test_clear_day_returns_none_when_absent_or_unparsable(raw):
    """Present-but-empty is absent — the router's answer for an unknown key."""
    assert _clear_day({"traffic_clear_date": raw}) is None


@pytest.mark.parametrize("raw", ["0", "32", "-1"])
def test_clear_day_rejects_days_outside_the_month(raw):
    """A day outside 1-31 is not a calendar date, whatever the router says."""
    assert _clear_day({"traffic_clear_date": raw}) is None


def test_clear_day_sensor_is_bounded_and_enabled():
    """Guard bands match the value range; the sensor is worth showing by default."""
    description = next(d for d in SENSOR_TYPES if d.key == "data_clear_day")
    assert (description.min_limit, description.max_limit) == (1, 31)
    assert description.entity_registry_enabled_default is True
    assert description.entity_category is EntityCategory.DIAGNOSTIC
    assert description.group == "data"
    assert description.about


@pytest.mark.parametrize(
    "key",
    [
        "lte_multi_ca_scell_info",
        "opms_wan_mode",
        "opms_wan_auto_mode",
        "sntp_timezone",
        "apn_interface_version",
    ],
)
def test_discovered_diagnostic_sensors_are_disabled_by_default(key):
    """Newly discovered read-only detail should not clutter a default install."""
    description = next(d for d in SENSOR_TYPES if d.key == key)
    assert description.entity_registry_enabled_default is False
    assert description.entity_category is EntityCategory.DIAGNOSTIC
    assert description.about


# --- Data-usage projection ---

_CYCLE_DATA = {
    "traffic_clear_date": "1",
    "monthly_tx_bytes": "10000000000",
    "monthly_rx_bytes": "40000000000",
}


def _at(day, hour=12):
    """Return a patch target fixing `dt_util.now()` to a July 2026 instant."""
    return patch(
        "custom_components.zte_router_5g.sensor.dt_util.now",
        return_value=datetime(2026, 7, day, hour, tzinfo=dt_util.DEFAULT_TIME_ZONE),
    )


def test_projection_is_produced_from_the_monthly_total():
    """50 GB by midday on the 16th of a 31-day cycle projects to 100 GB.

    15.5 days elapsed at 50 GB is 3.23 GB/day, and 15.5 days remain.
    """
    with _at(16):
        projected = _projected_bytes(dict(_CYCLE_DATA))
    assert projected == pytest.approx(100e9, rel=0.01)


def test_projection_is_shown_on_the_first_day_rather_than_unknown():
    """An `unknown` on day one reads as a broken sensor, so a figure is given."""
    with _at(1, hour=6):
        projected = _projected_bytes({**_CYCLE_DATA, "monthly_rx_bytes": "2000000000"})
    assert projected is not None
    assert projected > 0


def test_projection_on_day_one_is_bounded_by_the_denominator_floor():
    """2 GB six hours into a cycle reads as 64 GB, not 248 GB.

    The naive form divides by 0.25 days, giving a rate of 8 GB/day and a
    projection of 248 GB off a single morning's download. Flooring the
    denominator at one day caps the rate at 2 GB/day, so the figure is
    2 + 30.75 x 2. It is still an overestimate — six hours is six hours — but
    it is no longer an artefact of dividing by something close to zero.
    """
    data = {**_CYCLE_DATA, "monthly_tx_bytes": "0", "monthly_rx_bytes": "2000000000"}
    with _at(1, hour=6):
        projected = _projected_bytes(data)
    assert projected == pytest.approx(63.5e9, rel=0.01)


def test_projection_falls_back_to_the_calendar_month():
    """A router with no reset day must not leave a permanently blank sensor.

    Assuming the 1st is right for anyone billed calendar-monthly and no worse
    than nothing for anyone else, whereas an unexplained `unknown` that never
    clears is worse than both. The assumption is published, not hidden.
    """
    data = {k: v for k, v in _CYCLE_DATA.items() if k != "traffic_clear_date"}
    with _at(16):
        result = _projection(data)

    assert result is not None
    assert result.cycle_source == "calendar_assumed"
    assert result.cycle_start.day == 1
    assert result.cycle_length_days == 31


def test_projection_reports_the_router_as_the_cycle_source_when_it_has_one():
    """The fallback must not mask a reset day the router did report."""
    with _at(16):
        result = _projection(dict(_CYCLE_DATA))
    assert result.cycle_source == "router"


def test_projection_is_none_when_the_automatic_reset_is_switched_off():
    """With auto-clear off the counters never roll over, so nothing to project."""
    data = {**_CYCLE_DATA, "wan_auto_clear_flow_data_switch": "off"}
    with _at(16):
        assert _projected_bytes(data) is None


def test_projection_is_produced_when_the_automatic_reset_is_on():
    """The guard must key on 'off' alone, not on the key being present."""
    data = {**_CYCLE_DATA, "wan_auto_clear_flow_data_switch": "on"}
    with _at(16):
        assert _projected_bytes(data) is not None


def test_projection_is_none_without_monthly_counters():
    """Both halves of the total are required; one alone would understate it."""
    with _at(16):
        assert _projected_bytes({"traffic_clear_date": "1"}) is None


@pytest.mark.parametrize(("day", "expected"), [(1, "low"), (4, "medium"), (16, "high")])
def test_projection_confidence_reflects_how_much_is_observed(day, expected):
    """The caveat lives in an attribute so the state can always show a number."""
    with _at(day):
        result = _projection(dict(_CYCLE_DATA))
    assert result.confidence == expected


def test_projection_reports_run_rate_only_until_history_exists():
    """No stored prior cycle yet, and the attribute must say so plainly."""
    with _at(16):
        result = _projection(dict(_CYCLE_DATA))
    assert result.basis == "run_rate_only"


def test_projection_attributes_describe_the_cycle():
    """Cycle day and start let a user judge the figure without reading docs."""
    description = next(d for d in SENSOR_TYPES if d.key == "data_projection")
    coordinator = MagicMock()
    coordinator.data = dict(_CYCLE_DATA)
    entity = ZTERouterSensor(coordinator, MagicMock(), description)

    with _at(16):
        attrs = entity.extra_state_attributes

    assert attrs["cycle_day"] == "16 of 31"
    assert attrs["cycle_start"] == "2026-07-01"
    assert attrs["basis"] == "run_rate_only"
    assert attrs["confidence"] == "high"


def test_projection_attributes_are_absent_when_there_is_no_cycle():
    """The `about` note must survive even when the projection cannot be made."""
    description = next(d for d in SENSOR_TYPES if d.key == "data_projection")
    coordinator = MagicMock()
    coordinator.data = {"wan_auto_clear_flow_data_switch": "off"}
    entity = ZTERouterSensor(coordinator, MagicMock(), description)

    with _at(16):
        attrs = entity.extra_state_attributes

    assert "cycle_day" not in attrs
    assert attrs["about"]


def test_projection_has_no_state_class():
    """It must never reach long-term statistics.

    This is an estimate of where the cycle ends up, useful now rather than as
    a history — and the measurement it derives from, `Monthly Total`, is
    already recorded with a proper state class. Keeping this one too would
    store a derived view of a number already stored, and invite charts of what
    was once guessed rather than what happened.
    """
    description = next(d for d in SENSOR_TYPES if d.key == "data_projection")
    assert description.state_class is None
    assert description.device_class is SensorDeviceClass.DATA_SIZE
    assert description.native_unit_of_measurement == UnitOfInformation.BYTES
    assert description.suggested_unit_of_measurement == UnitOfInformation.GIGABYTES
    assert description.group == "data"
    assert description.entity_registry_enabled_default is True
    assert description.about


# --- Monthly counters reset on the billing day ------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "monthly_tx_bytes",
        "monthly_rx_bytes",
        "monthly_total_bytes",
        "monthly_tx_bytes_raw",
        "monthly_rx_bytes_raw",
        "monthly_total_bytes_raw",
    ],
)
def test_monthly_counters_are_total_increasing(key):
    """These zero on the router's billing day, and the class must say so.

    `reset_detected()` in the recorder is reached only from the
    TOTAL_INCREASING branch; under plain TOTAL a reset is recognised solely
    from a `last_reset` attribute this integration does not publish. With the
    wrong class the monthly rollover records as a large negative delta and
    walks the long-term statistics sum backwards every single month.
    """
    description = next(d for d in SENSOR_TYPES if d.key == key)
    assert description.state_class is SensorStateClass.TOTAL_INCREASING


# --- Data allowance ---------------------------------------------------------


def test_data_allowance_decodes_the_router_encoding():
    """`2_1048576` is 2 TiB — value times mebibytes-in-the-unit.

    Cross-checked against the router's own Data Management page, which shows
    "2TB" and an 80% reminder at "1.6TB" for exactly this stored value.
    """
    assert _data_allowance_bytes({"data_volume_limit_size": "2_1048576"}) == 2 * 1024**4


def test_data_allowance_is_none_when_the_limit_is_a_duration():
    """The router can cap by hours instead of bytes; that is not an allowance."""
    data = {"data_volume_limit_size": "2_1048576", "data_volume_limit_unit": "time"}
    assert _data_allowance_bytes(data) is None


def test_data_allowance_is_returned_when_the_limit_is_data():
    """The guard must key on 'time' alone, not on the field being present."""
    data = {"data_volume_limit_size": "2_1048576", "data_volume_limit_unit": "data"}
    assert _data_allowance_bytes(data) == 2 * 1024**4


@pytest.mark.parametrize(
    "raw", ["", None, "garbage", "2", "2_", "_1048576", "2_1_3", "0_1048576", "2_0"]
)
def test_data_allowance_rejects_anything_it_cannot_parse(raw):
    """A misparsed cap is worse than no cap — it would misinform an automation."""
    assert _data_allowance_bytes({"data_volume_limit_size": raw}) is None


def test_data_allowance_sensor_is_guard_banded_and_enabled():
    """Enabled by default, but still bounded against a misparse.

    It is the figure `Projected Cycle Usage` is judged against, so hiding it
    while showing the projection would be odd. The guard band stays because a
    misparsed cap would misinform an automation rather than merely look wrong.
    """
    description = next(d for d in SENSOR_TYPES if d.key == "data_allowance")
    assert description.entity_registry_enabled_default is True
    assert description.entity_category is EntityCategory.DIAGNOSTIC
    assert description.device_class is SensorDeviceClass.DATA_SIZE
    assert description.state_class is None
    assert description.min_limit == 0
    assert description.max_limit == 1024**5  # 1 PiB
    assert description.source == ENDPOINT_EXTENDED
    assert description.group == "data"
    assert description.about
