"""Tests for the ZTE Router binary sensor."""

from unittest.mock import MagicMock

import pytest

from custom_components.zte_router_5g.binary_sensor import (
    BEST_CONN_DESCRIPTION,
    ZTEBestConnectionSensor,
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

    # 3. None active
    mock_coordinator.data = {}
    assert sensor.is_on is False


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
