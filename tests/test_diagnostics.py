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


def test_witness_list_survives_a_collaborator_that_did_not_return_a_list():
    """`session_witnesses` is read through a guard that answers `None` on error.

    The download is serialized only after every section has been built, so a
    value of the wrong type fails the whole file at the last moment and past
    every other check. An unreadable witness list is reported as no witnesses.
    """
    from custom_components.zte_router_5g.diagnostics import _string_list

    assert _string_list(None) == []
    assert _string_list("wan_connect_status") == []
    assert _string_list(["wan_connect_status", 7, None]) == ["wan_connect_status"]


async def test_the_session_flag_state_is_published(mock_coordinator, mock_config_entry):
    """Whether this device implements `loginfo`, and what the check has done.

    The field that settles the one question the reference hardware cannot
    answer. The MC888 Pro has never been observed with a dead session and its
    downloads redact the flag's value by name, so whether it implements the key
    at all is unknown — and that decides whether the pre-write check applies
    there. `supported` answers it from that device's next download, with no
    write and nothing asked of its owner.

    The raw value is deliberately absent: it is denied by name and is not what
    anyone needs.
    """
    mock_coordinator.data = {}
    mock_coordinator.api.session_flag_report = MagicMock(
        return_value={
            "supported": True,
            "confirmed_on_firmware": "IRL_H3G_MC7010DV1.0.0B03",
            "checks": {"checks": 4, "not_confirmed": 1},
        }
    )
    mock_config_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(None, mock_config_entry)

    assert result["session_flag"]["supported"] is True
    assert result["session_flag"]["confirmed_on_firmware"].startswith("IRL")
    assert result["session_flag"]["checks"]["checks"] == 4
    assert "loginfo" not in str(result["session_flag"])
