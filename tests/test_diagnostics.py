"""Tests for diagnostics platform."""

from unittest.mock import MagicMock

from custom_components.zte_router_5g.diagnostics import (
    CARRIER_KEYS,
    CELL_KEYS,
    IP_KEYS,
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

    # Data sanitization. The IP is pseudonymized rather than blanked so it can
    # still be cross-referenced within the file (dev_standards Section 20);
    # `password` has no referential role and is blanked outright.
    assert result["data"]["signal_strength"] == 75
    assert result["data"]["wan_ipaddr"].startswith("ip-")
    assert "1.2.3.4" not in str(result)
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


async def test_sensitive_keys_are_categorized():
    """Every sensitive key must be handled, blanked or tokenized.

    Key-name membership is a weak assertion on its own — see
    test_diagnostics_sanitization.py for the properties that actually prove the
    output is safe. This only guards the categorization itself.
    """
    # No referential value — blanked.
    assert "password" in TO_REDACT
    assert "username" in TO_REDACT
    assert "imei" in TO_REDACT

    # Cross-reference value — tokenized, not blanked.
    assert "wan_ipaddr" in IP_KEYS
    assert "lan_ipaddr" in IP_KEYS
    assert "cell_id" in CELL_KEYS

    # Carrier identity locates the subscriber; no diagnostic value.
    assert "network_provider" in CARRIER_KEYS
    assert "mdm_mcc" in CARRIER_KEYS
