"""Tests for the ZTE Router sensor."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import UnitOfDataRate, UnitOfInformation, UnitOfTime
from homeassistant.util import dt as dt_util

from custom_components.zte_router_5g.const import DOMAIN
from custom_components.zte_router_5g.sensor import (
    SENSOR_TYPES,
    ZTERouterSensor,
    ZTESensorEntityDescription,
    async_setup_entry,
)

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
    assert "via_device" not in info

    # Signal group sensor
    description = next(d for d in SENSOR_TYPES if d.key == "lte_rsrp")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    info = sensor.device_info
    assert info["identifiers"] == {(DOMAIN, f"{mac}_signal")}
    assert info["name"] == "My ZTE Router Signal"
    assert info["via_device"] == (DOMAIN, f"{mac}_system")

    # Data group sensor
    description = next(d for d in SENSOR_TYPES if d.key == "monthly_rx_bytes")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    info = sensor.device_info
    assert info["identifiers"] == {(DOMAIN, f"{mac}_data")}
    assert info["name"] == "My ZTE Router Data"
    assert info["via_device"] == (DOMAIN, f"{mac}_system")

    # SMS group sensor
    description = next(d for d in SENSOR_TYPES if d.key == "msg_total")
    sensor = ZTERouterSensor(mock_coordinator, mock_config_entry, description)
    info = sensor.device_info
    assert info["identifiers"] == {(DOMAIN, f"{mac}_sms")}
    assert info["name"] == "My ZTE Router SMS"
    assert info["via_device"] == (DOMAIN, f"{mac}_system")


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
