"""Boot-time latch: the startup checks, their resolution, and the guards.

The running-session comparison has been stable since May 2026 because it
compares the router's counter against itself. What was never covered is the
persistence boundary — what happens on the first poll after Home Assistant
starts, when the only evidence is what survived on disk. That boundary is where
the three-week-stale timestamp came from, and it is what this file exercises.

Every case here is offline: a simulated clock and simulated counter values, no
router and no live Home Assistant. The specification, including both worked
failure modes and the numbered cases below, is in
`.shared/info/uptime_timestamp/uptime_timestamp_router_vs_ha_202608.md`.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.api import ZTERouterAPI
from custom_components.zte_router_5g.const import DOMAIN
from custom_components.zte_router_5g.coordinator import (
    BOOT_MATCH_TOLERANCE,
    UPTIME_WRITE_INTERVAL,
    ZTERouterDataUpdateCoordinator,
)

NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
GOOD_DATA = {
    "network_type": "ENDC",
    "signalbar": "4",
    "wa_inner_version": "IRL_H3G_MC7010DV1.0.0B01",
    "wan_connect_status": "ppp_connected",
}


def _entry(**data) -> MockConfigEntry:
    """Return a config entry carrying the given `entry.data` keys."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="864155042229309",
        title="ZTE 5G",
        data={"imei": "864155042229309", **data},
        options={
            CONF_HOST: "192.168.0.1",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "password",
        },
    )


def _coordinator(hass: HomeAssistant, entry: MockConfigEntry):
    """Return a coordinator wired to a fully mocked API."""
    entry.add_to_hass(hass)
    api = MagicMock(spec=ZTERouterAPI)
    api.get_all_data = AsyncMock(return_value=dict(GOOD_DATA))
    api.get_extended_data = AsyncMock(return_value={})
    api.get_sms_capacity = AsyncMock(return_value={})
    api.get_sms_messages = AsyncMock(return_value=[])
    api.login = AsyncMock(return_value="stok=test")
    return ZTERouterDataUpdateCoordinator(hass, entry, api)


def _poll(coordinator, seconds, now=NOW) -> None:
    """Feed one counter reading through the latch at a pinned clock."""
    with patch(
        "custom_components.zte_router_5g.coordinator.dt_util.now", return_value=now
    ):
        coordinator._apply_uptime(seconds)


@pytest.fixture
def stored(hass: HomeAssistant):
    """A coordinator restored from a boot instant five days old."""
    boot = NOW - timedelta(days=5)
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))
    coordinator._store = MagicMock()
    return coordinator, boot


# ---------------------------------------------------------------------------
# 1-2, 11 — the running session, which is unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_steady_polling_never_moves_the_timestamp(stored):
    """1: 100 polls with jitter leave the latch untouched and write once."""
    coordinator, boot = stored
    coordinator._startup_reconciled = True
    coordinator._boot_time = boot
    coordinator._last_uptime = 500_000

    for tick in range(100):
        jitter = (tick % 11) - 5
        _poll(coordinator, 500_000 + tick * 30 + jitter)

    assert coordinator._boot_time == boot
    # One write: the interval has not elapsed against the pinned clock.
    assert coordinator._store.async_delay_save.call_count == 1


@pytest.mark.asyncio
async def test_a_live_reboot_relatches_immediately(stored):
    """2: the counter drops mid-session, so the reboot is beyond doubt."""
    coordinator, boot = stored
    coordinator._startup_reconciled = True
    coordinator._boot_time = boot
    coordinator._last_uptime = 50_000

    _poll(coordinator, 20)

    assert coordinator._boot_time == NOW - timedelta(seconds=20)
    assert coordinator.entry.data["boot_time"] == coordinator._boot_time.isoformat()
    coordinator._store.async_delay_save.assert_called()


@pytest.mark.asyncio
async def test_the_first_poll_anchors_the_running_comparison(stored):
    """11: without the anchor, the second poll has nothing to compare against."""
    coordinator, boot = stored
    coordinator._boot_time = boot
    coordinator._stored_last_uptime = 432_000

    _poll(coordinator, 432_100)
    assert coordinator._last_uptime == 432_100

    _poll(coordinator, 20, now=NOW + timedelta(seconds=30))
    assert coordinator._boot_time != boot


# ---------------------------------------------------------------------------
# 3-5, 20-22 — the startup boundary, both failure modes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("gap", [timedelta(days=21), timedelta(minutes=40)])
@pytest.mark.asyncio
async def test_an_offline_gap_is_caught_whatever_its_length(hass, gap):
    """3, 20: gap length changes the visible error, not the detection.

    Failure Mode 1, on the first start after upgrade: no store record exists,
    so the counter-regression check cannot corroborate and the decision is
    taken on the second poll.
    """
    boot = NOW - gap - timedelta(hours=8)
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))
    coordinator._store = MagicMock()

    _poll(coordinator, 28_800)
    assert coordinator._boot_time == boot, "no change on the first poll"
    assert coordinator._pending_startup_strike

    _poll(coordinator, 28_980, now=NOW + timedelta(seconds=180))
    assert coordinator._boot_time == NOW + timedelta(seconds=180) - timedelta(
        seconds=28_980
    )
    assert coordinator._startup_reconciled


@pytest.mark.asyncio
async def test_a_simultaneous_cold_start_is_caught(hass):
    """4, 21: Failure Mode 2 — mains restored, both devices boot together."""
    boot = NOW - timedelta(days=5)
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))
    coordinator._store = MagicMock()

    _poll(coordinator, 45)
    assert coordinator._boot_time == boot
    assert coordinator._pending_startup_strike

    _poll(coordinator, 225, now=NOW + timedelta(seconds=180))
    assert coordinator._boot_time == NOW + timedelta(seconds=180) - timedelta(
        seconds=225
    )


@pytest.mark.asyncio
async def test_a_clean_restart_preserves_the_timestamp_exactly(stored):
    """5: the router did not reboot, so the stored instant is kept as-is."""
    coordinator, boot = stored
    coordinator._stored_last_uptime = 432_000

    _poll(coordinator, 432_000 + 120)

    assert coordinator._boot_time == boot
    assert coordinator._startup_reconciled
    assert not coordinator._pending_startup_strike


@pytest.mark.asyncio
async def test_a_short_gap_the_counter_cannot_corroborate_waits_one_poll(hass):
    """22: the router was up only briefly when Home Assistant stopped.

    The stored counter is *lower* than the live one, so nothing regressed, and
    the boot-instant check acts alone. A short-gap case, not a long-gap one.
    """
    boot = NOW - timedelta(hours=3)
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))
    coordinator._store = MagicMock()
    coordinator._stored_last_uptime = 600

    _poll(coordinator, 1_800)
    assert coordinator._boot_time == boot
    assert coordinator._pending_startup_strike

    _poll(coordinator, 1_980, now=NOW + timedelta(seconds=180))
    assert coordinator._boot_time != boot


# ---------------------------------------------------------------------------
# 6-8, 16, 23 — the two checks, and how they are resolved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_counter_regression_latches_on_the_first_poll(stored):
    """6, 7: conclusive on its own — no clock enters the comparison."""
    coordinator, _boot = stored
    coordinator._stored_last_uptime = 432_000

    _poll(coordinator, 45)

    assert coordinator._boot_time == NOW - timedelta(seconds=45)
    assert coordinator._startup_reconciled
    assert not coordinator._pending_startup_strike


@pytest.mark.asyncio
async def test_a_deferred_decision_survives_a_failed_poll(stored):
    """16: a poll that yields nothing must not consume the pending strike."""
    coordinator, boot = stored

    _poll(coordinator, 28_800)
    assert coordinator._pending_startup_strike

    # The second poll fails upstream, so nothing reaches the latch at all.
    assert coordinator._pending_startup_strike
    assert not coordinator._startup_reconciled

    _poll(coordinator, 29_160, now=NOW + timedelta(seconds=360))
    assert coordinator._startup_reconciled
    assert coordinator._boot_time != boot


@pytest.mark.asyncio
async def test_a_transient_divergence_is_cleared_as_a_false_alarm(stored):
    """23: the second poll agrees with the stored instant after all.

    Without this branch the pending flag would never clear and startup would
    never complete.
    """
    coordinator, boot = stored
    coordinator._pending_startup_strike = True

    # Derived boot lands on the stored instant, within tolerance.
    _poll(coordinator, int((NOW - boot).total_seconds()))

    assert coordinator._boot_time == boot
    assert coordinator._startup_reconciled
    assert not coordinator._pending_startup_strike


@pytest.mark.asyncio
async def test_a_divergence_inside_the_tolerance_is_not_a_reboot(stored):
    """8: the window is what stops ordinary clock drift moving the anchor."""
    coordinator, boot = stored
    drift = BOOT_MATCH_TOLERANCE - 60

    _poll(coordinator, int((NOW - boot).total_seconds()) - drift)

    assert coordinator._boot_time == boot
    assert not coordinator._pending_startup_strike


# ---------------------------------------------------------------------------
# 9, 10, 15, 19, 24 — the guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unset_clock_defers_rather_than_latching(stored):
    """15: a host with no battery-backed clock starts in 1970."""
    coordinator, boot = stored

    coordinator._stored_last_uptime = 432_000

    _poll(coordinator, 3_600, now=datetime(1970, 1, 1, 0, 5, tzinfo=UTC))
    assert coordinator._boot_time == boot, "no latch against an unset clock"
    assert not coordinator._startup_reconciled, "deferred, not skipped"

    # Once NTP lands, the same reading reconciles normally.
    _poll(coordinator, 3_600)
    assert coordinator._startup_reconciled
    assert coordinator._boot_time == NOW - timedelta(seconds=3_600)


@pytest.mark.asyncio
async def test_an_implausible_counter_is_rejected(stored):
    """10: believing it would write a boot instant decades adrift."""
    coordinator, boot = stored

    _poll(coordinator, 20 * 365 * 24 * 3600)

    assert coordinator._boot_time == boot
    assert not coordinator._startup_reconciled


@pytest.mark.parametrize("bad", [None, -1, -100])
@pytest.mark.asyncio
async def test_a_missing_or_negative_counter_leaves_the_latch_alone(stored, bad):
    """10: the pre-existing bad-reading guard, retained deliberately."""
    coordinator, boot = stored
    coordinator.api.get_all_data = AsyncMock(
        return_value={**GOOD_DATA, "realtime_time": bad}
    )

    data = await coordinator._async_update_data()

    assert data["boot_time"] == boot
    assert not coordinator._startup_reconciled


@pytest.mark.asyncio
async def test_a_stored_boot_time_in_the_future_is_rejected(hass):
    """19: only reachable from a latch taken against a clock since corrected."""
    ahead = NOW + timedelta(hours=2)
    coordinator = _coordinator(hass, _entry(boot_time=ahead.isoformat()))
    coordinator._store = MagicMock()

    _poll(coordinator, 3_600)

    assert coordinator._boot_time == NOW - timedelta(seconds=3_600)
    assert coordinator._startup_reconciled


@pytest.mark.parametrize("value", ["2026-08-01T10:00:00", "not a datetime", ""])
@pytest.mark.asyncio
async def test_a_naive_or_unparsable_stored_boot_time_is_treated_as_absent(hass, value):
    """24: mixing naive and aware raises; treat it as no stored value.

    A naive value cannot be produced by this integration, which always writes
    an aware `isoformat()`. It can only arrive from a hand-edited entry, and a
    hardened startup path should survive that rather than raise on it.
    """
    coordinator = _coordinator(hass, _entry(boot_time=value))
    coordinator._store = MagicMock()

    assert coordinator._boot_time is None
    _poll(coordinator, 3_600)

    assert coordinator._boot_time == NOW - timedelta(seconds=3_600)
    assert coordinator._startup_reconciled


@pytest.mark.asyncio
async def test_a_backward_clock_still_detects_a_genuine_reboot(stored):
    """9: the comparison is an absolute difference, so direction is moot."""
    coordinator, _boot = stored
    earlier = NOW - timedelta(hours=6)
    coordinator._stored_last_uptime = 432_000

    _poll(coordinator, 45, now=earlier)

    assert coordinator._boot_time == earlier - timedelta(seconds=45)


# ---------------------------------------------------------------------------
# 12, 13, 14, 17, 18 — persistence, lifecycle and startup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_absent_store_record_is_a_normal_state(hass):
    """12: every entry is in this state on the first run after upgrade."""
    coordinator = _coordinator(hass, _entry())
    with patch("custom_components.zte_router_5g.coordinator.Store") as store_cls:
        store_cls.return_value.async_load = AsyncMock(return_value=None)
        await coordinator.async_load_stored_uptime()

    assert coordinator._stored_last_uptime is None


@pytest.mark.parametrize(
    "failure", [ValueError("corrupt"), OSError("unreadable"), RuntimeError("odd")]
)
@pytest.mark.asyncio
async def test_a_failing_store_load_never_reaches_setup(hass, failure):
    """12: no storage fault may fail entry setup — the store is a cross-check."""
    coordinator = _coordinator(hass, _entry())
    with patch("custom_components.zte_router_5g.coordinator.Store") as store_cls:
        store_cls.return_value.async_load = AsyncMock(side_effect=failure)
        await coordinator.async_load_stored_uptime()

    assert coordinator._stored_last_uptime is None


@pytest.mark.parametrize("payload", [{"last_uptime": "not a number"}, {}, "junk"])
@pytest.mark.asyncio
async def test_a_malformed_store_record_yields_no_counter(hass, payload):
    """12: a record that parses but says nothing usable is not a counter."""
    coordinator = _coordinator(hass, _entry())
    with patch("custom_components.zte_router_5g.coordinator.Store") as store_cls:
        store_cls.return_value.async_load = AsyncMock(return_value=payload)
        await coordinator.async_load_stored_uptime()

    assert coordinator._stored_last_uptime is None


@pytest.mark.asyncio
async def test_a_stored_counter_is_read_back(hass):
    """12: the value the counter-regression check depends on."""
    coordinator = _coordinator(hass, _entry())
    with patch("custom_components.zte_router_5g.coordinator.Store") as store_cls:
        store_cls.return_value.async_load = AsyncMock(
            return_value={"last_uptime": 432_000}
        )
        await coordinator.async_load_stored_uptime()

    assert coordinator._stored_last_uptime == 432_000


@pytest.mark.asyncio
async def test_the_store_is_keyed_to_the_entry(hass):
    """13: one store per entry, so two routers cannot overwrite each other."""
    entry = _entry()
    coordinator = _coordinator(hass, entry)
    with patch("custom_components.zte_router_5g.coordinator.Store") as store_cls:
        store_cls.return_value.async_load = AsyncMock(return_value=None)
        await coordinator.async_load_stored_uptime()

    key = store_cls.call_args.args[2]
    assert entry.entry_id in key


@pytest.mark.asyncio
async def test_the_counter_is_flushed_once_the_interval_elapses(stored):
    """The write bounds staleness for every stop, orderly or abrupt."""
    coordinator, boot = stored
    coordinator._startup_reconciled = True
    coordinator._boot_time = boot

    _poll(coordinator, 1_000)
    first = coordinator._store.async_delay_save.call_count

    _poll(coordinator, 1_030, now=NOW + timedelta(seconds=30))
    assert coordinator._store.async_delay_save.call_count == first

    _poll(coordinator, 2_000, now=NOW + UPTIME_WRITE_INTERVAL)
    assert coordinator._store.async_delay_save.call_count == first + 1


@pytest.mark.asyncio
async def test_a_latch_drops_the_legacy_counter_from_entry_data(stored):
    """The key that caused the defect must not survive the fix."""
    coordinator, _boot = stored
    coordinator.hass.config_entries.async_update_entry(
        coordinator.entry,
        data={**coordinator.entry.data, "last_uptime": 60},
    )
    coordinator._stored_last_uptime = 432_000

    _poll(coordinator, 45)

    assert "last_uptime" not in coordinator.entry.data
    assert "boot_time" in coordinator.entry.data


@pytest.mark.asyncio
async def test_reconciliation_waits_for_a_poll_that_yields_a_counter(stored):
    """14: a failed first poll defers reconciliation, it does not skip it."""
    coordinator, _boot = stored
    coordinator.api.get_all_data = AsyncMock(
        return_value={**GOOD_DATA, "realtime_time": None}
    )

    with patch(
        "custom_components.zte_router_5g.coordinator.dt_util.now", return_value=NOW
    ):
        await coordinator._async_update_data()
        assert not coordinator._startup_reconciled, "nothing to reconcile against"
        assert not coordinator._pending_startup_strike

        coordinator.api.get_all_data = AsyncMock(
            return_value={**GOOD_DATA, "realtime_time": "45"}
        )
        coordinator._stored_last_uptime = 432_000
        await coordinator._async_update_data()

    assert coordinator._startup_reconciled
    assert coordinator._boot_time == NOW - timedelta(seconds=45)
