"""Tests for the ZTE Router binary sensor."""

from unittest.mock import MagicMock

import pytest

from custom_components.zte_router_5g.binary_sensor import (
    BEST_CONN_DESCRIPTION,
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
