"""Tests for diagnostics platform."""

from unittest.mock import MagicMock

from custom_components.zte_router_5g.diagnostics import (
    TO_REDACT,
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_basic(mock_coordinator, mock_config_entry):
    """Test that diagnostics returns expected structure with data and redaction."""
    mock_coordinator.consecutive_failures = 0
    mock_coordinator.last_update_success = True
    mock_coordinator.last_update_success_time = MagicMock()
    mock_coordinator.last_update_success_time.isoformat.return_value = (
        "2024-01-15T10:30:00"
    )
    mock_coordinator.data = {
        "wan_ipaddr": "1.2.3.4",
        "signal_strength": 75,
        "password": "secret",
    }
    mock_config_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(None, mock_config_entry)

    # Entry info
    assert result["entry"]["title"] == "My ZTE Router"
    assert result["entry"]["data"]["model"] == "MC7010"
    assert result["entry"]["options"]["password"] == "**REDACTED**"
    assert result["entry"]["options"]["username"] == "**REDACTED**"

    # Coordinator info
    assert result["coordinator"]["consecutive_failures"] == 0
    assert result["coordinator"]["last_update_success"] is True
    assert result["coordinator"]["last_update_success_time"] == "2024-01-15T10:30:00"
    assert result["coordinator"]["data_available"] is True

    # Data redaction
    assert result["data"]["signal_strength"] == 75
    assert result["data"]["wan_ipaddr"] == "**REDACTED**"
    assert result["data"]["password"] == "**REDACTED**"


async def test_diagnostics_no_data(mock_coordinator, mock_config_entry):
    """Test diagnostics when coordinator.data is None."""
    mock_coordinator.data = None
    mock_coordinator.last_update_success_time = None
    mock_config_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(None, mock_config_entry)

    assert result["data"] == {}
    assert result["coordinator"]["data_available"] is False
    assert result["coordinator"]["last_update_success_time"] is None


async def test_diagnostics_redaction_fields():
    """Test that TO_REDACT contains expected fields."""
    assert "password" in TO_REDACT
    assert "username" in TO_REDACT
    assert "wan_ipaddr" in TO_REDACT
    assert "lan_ipaddr" in TO_REDACT
