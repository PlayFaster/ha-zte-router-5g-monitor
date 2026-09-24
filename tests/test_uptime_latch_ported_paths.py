"""Paths of the ported latch that ZTE's counters do not take on their own.

3.4.2-dev7 ported the uptime latch from the Huawei project verbatim, so ZTE
carries the floor test and the `pauses` handling Huawei needs for its
`TotalConnectTime` counter. No ZTE latch pauses, and a ZTE store written by
this code always carries `written_at`. These cases drive those paths directly
so the port is covered as it stands, rather than trimmed away from the shared
mechanism.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.api import ZTERouterAPI
from custom_components.zte_router_5g.const import DOMAIN
from custom_components.zte_router_5g.coordinator import (
    ZTERouterDataUpdateCoordinator,
    _UptimeLatch,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC)
_NOW = "custom_components.zte_router_5g.coordinator.dt_util.now"


def _coordinator(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="864155042229309",
        title="ZTE 5G",
        data={"imei": "864155042229309"},
        options={
            CONF_HOST: "192.168.0.1",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "password",
        },
    )
    entry.add_to_hass(hass)
    coordinator = ZTERouterDataUpdateCoordinator(
        hass, entry, MagicMock(spec=ZTERouterAPI)
    )
    coordinator._store = MagicMock()
    return coordinator


def _read(coordinator, latch, seconds, now=NOW) -> None:
    with patch(_NOW, return_value=now):
        coordinator._apply_uptime_readings(((latch, seconds),))


@pytest.mark.parametrize(("live", "moved"), [(50, True), (5000, False)])
@pytest.mark.asyncio
async def test_a_stored_counter_without_a_date_takes_the_floor_test(hass, live, moved):
    """No `written_at`: only "did it go backwards" can be asked."""
    coordinator = _coordinator(hass)
    latch = coordinator._system_latch
    latch.boot_time = NOW - timedelta(seconds=4000)
    latch.stored_counter = 1000

    _read(coordinator, latch, live)

    assert latch.startup_reconciled is True
    assert (latch.boot_time != NOW - timedelta(seconds=4000)) is moved


@pytest.mark.asyncio
async def test_a_pausing_latch_takes_the_floor_test_and_has_no_rate(hass):
    """Huawei's `TotalConnectTime`: a counter that stops while data is down."""
    coordinator = _coordinator(hass)
    latch = _UptimeLatch(label="Total", boot_key="total", counter_key="t", pauses=True)
    latch.stored_counter = 100
    latch.stored_written_at = NOW - timedelta(hours=1)
    latch.drift_sum_wall = 10_000.0
    latch.drift_sum_counter = 9_000.0
    latch.last_counter = 90
    latch.last_poll_at = NOW - timedelta(hours=1)

    _read(coordinator, latch, 200)

    assert coordinator._drift_rate(latch) is None
    assert latch.drift_interval_count == 0
    assert latch.startup_reconciled is True


@pytest.mark.parametrize(("seconds", "implausible"), [(10, False), (5000, True)])
def test_a_pausing_latch_is_judged_on_the_high_side_only(hass, seconds, implausible):
    """Downtime makes the ratio small with nothing wrong."""
    coordinator = _coordinator(hass)
    latch = _UptimeLatch(label="Total", boot_key="total", counter_key="t", pauses=True)
    latch.boot_time = NOW - timedelta(seconds=1000)

    assert coordinator._cold_start_implausible(latch, seconds, NOW) is implausible


def test_an_anchorless_latch_is_implausible(hass):
    """Nothing to judge is judged as needing a latch."""
    coordinator = _coordinator(hass)

    assert coordinator._cold_start_implausible(coordinator._conn_latch, 10, NOW)


@pytest.mark.asyncio
async def test_a_block_without_a_counter_or_with_a_naive_date_restores_neither(hass):
    """Anything unusable is absent."""
    coordinator = _coordinator(hass)
    with patch("custom_components.zte_router_5g.coordinator.Store") as store_cls:
        store_cls.return_value.async_load = AsyncMock(
            return_value={
                "last_system_uptime": {
                    "last_uptime": None,
                    "written_at": "2026-09-24T11:00:00",
                }
            }
        )
        await coordinator.async_load_stored_uptime()

    assert coordinator._system_latch.stored_counter is None
    assert coordinator._system_latch.stored_written_at is None
