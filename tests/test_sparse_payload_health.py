"""A poll that succeeds while answering almost nothing.

The MC888 Pro in issue #56 polled successfully with six of eighty-two keys
populated. Nothing said so: the drift check asks only whether *any* contract
key is present, and one was. A handful of values is neither drift nor an
expiry, but it is not a healthy poll either, and the only place it was visible
was a diagnostics download nobody had yet asked for.

The threshold is relative to what the device has answered before. The
reference MC7010 legitimately leaves 46 of 127 names empty, so a fixed floor
would report it faulty on every cycle.
"""

from unittest.mock import MagicMock

import pytest

from custom_components.zte_router_5g.const import (
    SPARSE_PAYLOAD_FRACTION,
    SPARSE_PAYLOAD_MIN_HISTORY,
)
from custom_components.zte_router_5g.coordinator import (
    ZTERouterDataUpdateCoordinator,
)


@pytest.fixture
def finder(hass):
    """A coordinator reduced to the one method under test."""
    coordinator = ZTERouterDataUpdateCoordinator.__new__(ZTERouterDataUpdateCoordinator)
    coordinator._payload_high_water = 0
    return coordinator


def _payload(populated: int, total: int = 100) -> dict[str, str]:
    data = dict.fromkeys((f"key_{i}" for i in range(total)), "")
    for i in range(populated):
        data[f"key_{i}"] = "value"
    return data


def test_the_first_poll_sets_the_baseline_and_reports_nothing(finder) -> None:
    """There is no history to judge against yet."""
    assert finder._sparse_payload_finding(_payload(80)) is None
    assert finder._payload_high_water == 80


def test_a_growing_payload_raises_the_baseline(finder) -> None:
    """A device reporting more over time moves the mark up, never down."""
    finder._sparse_payload_finding(_payload(40))
    finder._sparse_payload_finding(_payload(80))

    assert finder._payload_high_water == 80


def test_a_collapse_against_the_devices_own_history_is_reported(finder) -> None:
    """The issue #56 shape: a successful poll answering almost nothing."""
    finder._sparse_payload_finding(_payload(82))

    finding = finder._sparse_payload_finding(_payload(6))

    assert finding is not None
    assert "6 keys populated" in finding
    assert "82" in finding


def test_a_normally_sparse_device_is_not_reported(finder) -> None:
    """The MC7010 leaves 46 of 127 empty and must stay silent."""
    finder._sparse_payload_finding(_payload(81, total=127))

    assert finder._sparse_payload_finding(_payload(81, total=127)) is None


def test_no_finding_before_the_baseline_is_worth_judging(finder) -> None:
    """A high-water mark of a few keys proves nothing about a later dip."""
    finder._sparse_payload_finding(_payload(SPARSE_PAYLOAD_MIN_HISTORY - 1))

    assert finder._sparse_payload_finding(_payload(0)) is None


def test_the_boundary_is_inclusive(finder) -> None:
    """At exactly the fraction the poll is reported, not excused."""
    finder._sparse_payload_finding(_payload(100))
    at_threshold = int(100 * SPARSE_PAYLOAD_FRACTION)

    assert finder._sparse_payload_finding(_payload(at_threshold)) is not None
    assert finder._sparse_payload_finding(_payload(at_threshold + 1)) is None


def test_the_finding_reaches_the_health_snapshot(hass) -> None:
    """A finding must publish, not merely be computed."""
    coordinator = ZTERouterDataUpdateCoordinator.__new__(ZTERouterDataUpdateCoordinator)
    coordinator._payload_high_water = 82
    coordinator._drift_baseline = set()
    coordinator._drift_strikes = 0
    coordinator.last_update_success_time = None
    coordinator.consecutive_failures = 0
    coordinator._degraded_endpoints = MagicMock(return_value=[])
    coordinator._set_unreachable_repair = MagicMock()
    coordinator._set_auth_repair = MagicMock()
    coordinator._check_contract_drift = MagicMock(return_value=False)
    coordinator._active_repairs = MagicMock(return_value=[])

    coordinator._record_health_success(_payload(6))

    snapshot = coordinator.health_snapshot
    assert snapshot["problem"] is True
    assert snapshot["severity"] == "warning"
    assert any("Sparse payload" in issue for issue in snapshot["issues"])
