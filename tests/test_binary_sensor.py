"""Tests for the ZTE Router binary sensor."""

from unittest.mock import MagicMock

import pytest
from homeassistant.const import EntityCategory

from custom_components.zte_router_5g.binary_sensor import (
    BEST_CONN_DESCRIPTION,
    BINARY_SENSORS,
    ZTEBestConnectionSensor,
    ZTEBinarySensorEntityDescription,
    ZTERouterBinarySensor,
    async_setup_entry,
)
from custom_components.zte_router_5g.const import DOMAIN


def test_binary_sensor_is_on(mock_coordinator, mock_config_entry):
    """Test the optimal connection logic."""
    sensor = ZTEBestConnectionSensor(
        mock_coordinator, mock_config_entry, BEST_CONN_DESCRIPTION
    )

    # 1. Both active
    mock_coordinator.data = {"network_type": "ENDC", "wan_lte_ca": "ca_activated"}
    assert sensor.is_on is True

    # 2. Only one active
    mock_coordinator.data = {"network_type": "LTE", "wan_lte_ca": "ca_activated"}
    assert sensor.is_on is False

    # 3. No data yet — unknown, not "off". Asserting off here would claim the
    #    router is not on its best connection before we have read it at all
    #    (dev_standards Section 18).
    mock_coordinator.data = {}
    assert sensor.is_on is None


def test_binary_sensor_device_info(mock_coordinator, mock_config_entry):
    """Test device_info links to router."""
    sensor = ZTEBestConnectionSensor(
        mock_coordinator, mock_config_entry, BEST_CONN_DESCRIPTION
    )
    info = sensor.device_info
    assert info["identifiers"] == {(DOMAIN, "864155042229309_signal")}
    assert info["manufacturer"] == "ZTE"


@pytest.mark.asyncio
async def test_binary_sensor_setup_entry():
    """Test platform setup."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test"
    entry.runtime_data = MagicMock()

    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)
    async_add_entities.assert_called_once()


# ── Strategy 2: Combinatorial / Path Coverage ──────────────────────────────


def test_binary_sensor_endc_without_ca_activated(mock_coordinator, mock_config_entry):
    """2A: ENDC network with non-activated CA returns False."""
    sensor = ZTEBestConnectionSensor(
        mock_coordinator, mock_config_entry, BEST_CONN_DESCRIPTION
    )

    mock_coordinator.data = {"network_type": "ENDC", "wan_lte_ca": "ca_deactivated"}
    assert sensor.is_on is False

    mock_coordinator.data = {"network_type": "ENDC", "wan_lte_ca": ""}
    assert sensor.is_on is False

    mock_coordinator.data = {"network_type": "ENDC"}
    assert sensor.is_on is False


# ── Coverage Expansion: ZTERouterBinarySensor ────────────────────────────────


def test_router_binary_sensor_is_on_no_data(mock_coordinator, mock_config_entry):
    """Test ZTERouterBinarySensor.is_on returns None (unknown) when no data."""
    mock_coordinator.data = None
    desc = ZTEBinarySensorEntityDescription(
        key="reboot_schedule",
        translation_key="system_reboot_schedule",
        value_fn=lambda data: (
            data.get("reboot_schedule_enable") == "1" if data else False
        ),
    )
    sensor = ZTERouterBinarySensor(mock_coordinator, mock_config_entry, desc)
    assert sensor.is_on is None


def test_router_binary_sensor_is_on_no_value_fn(mock_coordinator, mock_config_entry):
    """Test ZTERouterBinarySensor.is_on returns None when value_fn is None."""
    mock_coordinator.data = {"some": "data"}
    desc = ZTEBinarySensorEntityDescription(
        key="test_sensor",
        translation_key="test_sensor",
        value_fn=None,
    )
    sensor = ZTERouterBinarySensor(mock_coordinator, mock_config_entry, desc)
    assert sensor.is_on is None


def test_router_binary_sensor_is_on_true(mock_coordinator, mock_config_entry):
    """Test ZTERouterBinarySensor.is_on returns True when value_fn matches."""
    mock_coordinator.data = {"reboot_schedule_enable": "1"}
    desc = ZTEBinarySensorEntityDescription(
        key="reboot_schedule",
        translation_key="system_reboot_schedule",
        value_fn=lambda data: (
            data.get("reboot_schedule_enable") == "1" if data else False
        ),
    )
    sensor = ZTERouterBinarySensor(mock_coordinator, mock_config_entry, desc)
    assert sensor.is_on is True


def test_router_binary_sensor_is_on_false(mock_coordinator, mock_config_entry):
    """Test ZTERouterBinarySensor.is_on returns False when value_fn doesn't match."""
    mock_coordinator.data = {"reboot_schedule_enable": "0"}
    desc = ZTEBinarySensorEntityDescription(
        key="reboot_schedule",
        translation_key="system_reboot_schedule",
        value_fn=lambda data: (
            data.get("reboot_schedule_enable") == "1" if data else False
        ),
    )
    sensor = ZTERouterBinarySensor(mock_coordinator, mock_config_entry, desc)
    assert sensor.is_on is False


def test_router_binary_sensor_extra_attributes_no_data(
    mock_coordinator, mock_config_entry
):
    """Test extra_state_attributes returns {} when no data."""
    mock_coordinator.data = None
    desc = ZTEBinarySensorEntityDescription(
        key="reboot_schedule",
        translation_key="system_reboot_schedule",
        value_fn=lambda data: False,
        extra_attrs_fn=lambda data: {
            "reboot_hour1": data.get("reboot_hour1") if data else None,
        },
    )
    sensor = ZTERouterBinarySensor(mock_coordinator, mock_config_entry, desc)
    assert sensor.extra_state_attributes == {}


def test_router_binary_sensor_extra_attributes_no_attrs_fn(
    mock_coordinator, mock_config_entry
):
    """Test extra_state_attributes returns {} when extra_attrs_fn is None."""
    mock_coordinator.data = {"some": "data"}
    desc = ZTEBinarySensorEntityDescription(
        key="test_sensor",
        translation_key="test_sensor",
        value_fn=lambda data: True,
        extra_attrs_fn=None,
    )
    sensor = ZTERouterBinarySensor(mock_coordinator, mock_config_entry, desc)
    assert sensor.extra_state_attributes == {}


def test_router_binary_sensor_extra_attributes_with_data(
    mock_coordinator, mock_config_entry
):
    """Test extra_state_attributes returns computed attrs."""
    mock_coordinator.data = {"reboot_hour1": "3", "reboot_min1": "30"}
    desc = ZTEBinarySensorEntityDescription(
        key="reboot_schedule",
        translation_key="system_reboot_schedule",
        value_fn=lambda data: True,
        extra_attrs_fn=lambda data: {
            "reboot_hour1": data.get("reboot_hour1") if data else None,
            "reboot_min1": data.get("reboot_min1") if data else None,
        },
    )
    sensor = ZTERouterBinarySensor(mock_coordinator, mock_config_entry, desc)
    attrs = sensor.extra_state_attributes
    assert attrs["reboot_hour1"] == "3"
    assert attrs["reboot_min1"] == "30"


def test_router_binary_sensor_device_info(mock_coordinator, mock_config_entry):
    """Test device_info for non-best-connection binary sensor."""
    desc = ZTEBinarySensorEntityDescription(
        key="reboot_schedule",
        translation_key="system_reboot_schedule",
        group="system",
        value_fn=lambda data: False,
    )
    sensor = ZTERouterBinarySensor(mock_coordinator, mock_config_entry, desc)
    info = sensor.device_info
    assert info["identifiers"] == {(DOMAIN, "864155042229309_system")}
    assert info["manufacturer"] == "ZTE"


def test_router_binary_sensor_device_info_signal_group(
    mock_coordinator, mock_config_entry
):
    """Test device_info for signal group has via_device."""
    desc = ZTEBinarySensorEntityDescription(
        key="upnp_enabled",
        translation_key="system_upnp_enabled",
        group="signal",
        value_fn=lambda data: data.get("upnpEnabled") == "1" if data else False,
    )
    sensor = ZTERouterBinarySensor(mock_coordinator, mock_config_entry, desc)
    info = sensor.device_info
    assert "via_device" in info


def test_best_connection_sensor_is_on_no_data(mock_coordinator, mock_config_entry):
    """Test ZTEBestConnectionSensor.is_on returns None (unknown) when no data."""
    mock_coordinator.data = None
    sensor = ZTEBestConnectionSensor(
        mock_coordinator, mock_config_entry, BEST_CONN_DESCRIPTION
    )
    assert sensor.is_on is None


def test_best_connection_sensor_device_info(mock_coordinator, mock_config_entry):
    """Test ZTEBestConnectionSensor.device_info."""
    sensor = ZTEBestConnectionSensor(
        mock_coordinator, mock_config_entry, BEST_CONN_DESCRIPTION
    )
    info = sensor.device_info
    assert "via_device" in info


# --- Newly discovered read-only switches and reboot-schedule detail ---


@pytest.mark.parametrize(
    ("key", "raw_key"),
    [("web_sleep", "web_sleep_switch"), ("web_wake", "web_wake_switch")],
)
@pytest.mark.parametrize(("raw", "expected"), [("1", True), ("0", False)])
def test_web_power_sensors_read_the_router_flag(
    mock_coordinator, mock_config_entry, key, raw_key, raw, expected
):
    """The router reports these as '1'/'0' strings, not booleans."""
    description = next(d for d in BINARY_SENSORS if d.key == key)
    mock_coordinator.data = {raw_key: raw}
    sensor = ZTERouterBinarySensor(mock_coordinator, mock_config_entry, description)
    assert sensor.is_on is expected


@pytest.mark.parametrize("key", ["web_sleep", "web_wake"])
def test_web_power_sensors_are_diagnostic_and_disabled(key):
    """No write command exists for either, so they ship read-only and off."""
    description = next(d for d in BINARY_SENSORS if d.key == key)
    assert description.entity_registry_enabled_default is False
    assert description.entity_category is EntityCategory.DIAGNOSTIC
    assert description.group == "system"
    assert description.about
    assert description.value_fn is not None


def test_reboot_schedule_publishes_the_day_fields_unresolved(
    mock_coordinator, mock_config_entry
):
    """Mode-to-day mapping is unconfirmed, so all three are published raw."""
    description = next(d for d in BINARY_SENSORS if d.key == "reboot_schedule")
    mock_coordinator.data = {
        "reboot_schedule_enable": "1",
        "reboot_hour1": "3",
        "reboot_min1": "0",
        "reboot_schedule_mode": "1",
        "reboot_dow": "2",
        "reboot_dod": "1",
    }
    sensor = ZTERouterBinarySensor(mock_coordinator, mock_config_entry, description)
    attrs = sensor.extra_state_attributes

    assert attrs["schedule_mode"] == "1"
    assert attrs["day_of_week"] == "2"
    assert attrs["day_of_month"] == "1"


def test_reboot_schedule_day_fields_are_not_recorded(
    mock_coordinator, mock_config_entry
):
    """Static config in attributes must not be written to history (Section 14)."""
    description = next(d for d in BINARY_SENSORS if d.key == "reboot_schedule")
    sensor = ZTERouterBinarySensor(mock_coordinator, mock_config_entry, description)
    assert {"schedule_mode", "day_of_week", "day_of_month"} <= (
        sensor._unrecorded_attributes
    )


def test_binary_sensor_unavailable_when_its_endpoint_is_degraded(
    mock_coordinator, mock_config_entry
):
    """An entity fed by the optional batch must follow that batch's health."""
    description = next(d for d in BINARY_SENSORS if d.key == "web_sleep")
    mock_coordinator.last_update_success = True
    mock_coordinator.endpoint_available.return_value = False
    sensor = ZTERouterBinarySensor(mock_coordinator, mock_config_entry, description)
    assert sensor.available is False

    mock_coordinator.endpoint_available.return_value = True
    assert sensor.available is True


def test_binary_sensor_unavailable_when_the_whole_fetch_is_down(
    mock_coordinator, mock_config_entry
):
    """A healthy endpoint cannot rescue an integration-wide outage."""
    description = next(d for d in BINARY_SENSORS if d.key == "web_sleep")
    mock_coordinator.last_update_success = False
    mock_coordinator.endpoint_available.return_value = True
    sensor = ZTERouterBinarySensor(mock_coordinator, mock_config_entry, description)
    assert sensor.available is False
