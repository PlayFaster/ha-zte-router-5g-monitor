from custom_components.zte_router_5g.binary_sensor import (
    BEST_CONN_DESCRIPTION,
    ZTEBestConnectionSensor,
)


def test_binary_sensor_is_on(mock_coordinator, mock_config_entry):
    """Test the binary sensor is_on logic."""
    sensor = ZTEBestConnectionSensor(
        mock_coordinator, mock_config_entry, BEST_CONN_DESCRIPTION
    )

    # Both ENDC and ca_activated -> True
    mock_coordinator.data = {"network_type": "ENDC", "wan_lte_ca": "ca_activated"}
    assert sensor.is_on is True
    assert sensor.icon == "mdi:signal"

    # One missing -> False
    mock_coordinator.data = {"network_type": "LTE", "wan_lte_ca": "ca_activated"}
    assert sensor.is_on is False
    assert sensor.icon == "mdi:signal-cellular-1"

    # Empty data -> False
    mock_coordinator.data = {}
    assert sensor.is_on is False
