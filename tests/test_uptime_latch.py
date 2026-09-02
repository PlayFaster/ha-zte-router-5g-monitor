"""Boot-time latch: drift measurement, the startup tests, and the guards.

The router's uptime counter is a valid reboot indicator but a poor clock. The
MC7010 this was written against runs about 4.34% slow, so a boot instant derived
as `now() - counter` walks forward while the router runs — eleven minutes after
twelve hours, four and a half hours after four days. An earlier fixed-tolerance
design was defeated by exactly that, producing a false reboot report on an
ordinary restart.

These cases are therefore driven by a simulated router whose counter advances at
a configurable rate, so "no false alarm across thirty days" is something the
suite can actually assert rather than approximate.

Everything here is offline: no router, no live Home Assistant. The design, the
drift measurement and the eight decisions behind the constants are in
`.shared/info/uptime_timestamp/uptime_drift_analyzed.md`.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.api import ZTERouterAPI
from custom_components.zte_router_5g.const import DOMAIN
from custom_components.zte_router_5g.coordinator import (
    DRIFT_ACCUMULATOR_CAP,
    DRIFT_MIN_ACCUMULATED,
    MAX_DRIFT,
    UPTIME_WRITE_INTERVAL,
    ZTERouterDataUpdateCoordinator,
)

NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
POLL = timedelta(minutes=16)
ZTE_RATE = 0.0434

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
    """Return a coordinator wired to a fully mocked API and a mocked store."""
    entry.add_to_hass(hass)
    api = MagicMock(spec=ZTERouterAPI)
    api.get_all_data = AsyncMock(return_value=dict(GOOD_DATA))
    api.get_extended_data = AsyncMock(return_value={})
    api.get_sms_capacity = AsyncMock(return_value={})
    api.get_sms_messages = AsyncMock(return_value=[])
    api.login = AsyncMock(return_value="stok=test")
    coordinator = ZTERouterDataUpdateCoordinator(hass, entry, api)
    coordinator._store = MagicMock()
    return coordinator


def _poll(coordinator, seconds, now) -> None:
    """Feed one counter reading through the latch at a pinned clock."""
    with patch(
        "custom_components.zte_router_5g.coordinator.dt_util.now", return_value=now
    ):
        coordinator._apply_uptime(int(seconds))


class Router:
    """A router whose counter advances at `rate` slower than wall time.

    Positive `rate` is a slow counter, which is what real hardware does here.
    Negative is a counter running fast, which has never been measured but is not
    ruled out.
    """

    def __init__(self, rate: float = ZTE_RATE, uptime: float = 0.0) -> None:
        """Start at `uptime` seconds, losing `rate` of every second thereafter."""
        self.rate = rate
        self.counter = uptime

    def advance(self, seconds: float) -> None:
        """Advance the counter by what this router would count in that wall time."""
        self.counter += seconds * (1.0 - self.rate)

    def reboot(self) -> None:
        """Reset the counter, as a power cycle does."""
        self.counter = 0.0


def _run(coordinator, router: Router, *, start, polls: int, interval=POLL):
    """Poll a simulated router repeatedly and return the final clock."""
    now = start
    for _ in range(polls):
        _poll(coordinator, router.counter, now)
        now += interval
        router.advance(interval.total_seconds())
    return now


# ---------------------------------------------------------------------------
# Drift measurement
# ---------------------------------------------------------------------------


# Rates deliberately span PLAUSIBILITY_TOLERANCE. A suite that stopped at the
# measured 4.34% passed a build in which any device drifting past the
# tolerance re-latched on every poll, because the anchor was not corrected
# for drift and the observed ratio therefore sat a full `rate` from the
# predicted one.
@pytest.mark.parametrize("rate", [0.0, ZTE_RATE, 0.08, 0.12, -0.02])
@pytest.mark.asyncio
async def test_the_measured_rate_converges_on_the_real_one(hass, rate):
    """The estimate is what replaces a universal constant, so it must be right."""
    router = Router(rate=rate, uptime=100_000)
    boot = NOW - timedelta(seconds=router.counter / (1 - rate))
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))

    _run(coordinator, router, start=NOW, polls=40)

    assert coordinator._drift_rate == pytest.approx(rate, abs=0.001)
    assert coordinator._drift_interval_count == 39


@pytest.mark.asyncio
async def test_the_rate_is_withheld_until_enough_has_accumulated(hass):
    """Below the minimum there is no estimate, and no division by zero."""
    coordinator = _coordinator(hass, _entry())
    assert coordinator._drift_sum_wall == 0
    assert coordinator._drift_rate is None, "a fresh install must not divide"

    router = Router(uptime=50_000)
    _run(coordinator, router, start=NOW, polls=3)

    assert coordinator._drift_sum_wall < DRIFT_MIN_ACCUMULATED
    assert coordinator._drift_rate is None

    _run(coordinator, router, start=NOW + POLL * 3, polls=6)
    assert coordinator._drift_rate is not None


@pytest.mark.asyncio
async def test_short_and_negative_intervals_are_excluded(hass):
    """Quantization dominates a short interval; a drop is a reboot, not drift."""
    coordinator = _coordinator(hass, _entry())
    coordinator._startup_reconciled = True

    _poll(coordinator, 10_000, NOW)
    _poll(coordinator, 10_030, NOW + timedelta(seconds=30))
    assert coordinator._drift_interval_count == 0, "sub-60 s interval counted"

    _poll(coordinator, 20, NOW + timedelta(seconds=60))
    assert coordinator._drift_interval_count == 0, "a reboot polluted the rate"


@pytest.mark.asyncio
async def test_a_runaway_sample_cannot_move_the_rate_past_the_clamp(hass):
    """An unbounded high rate would suppress detection; the clamp prevents it."""
    coordinator = _coordinator(hass, _entry())
    coordinator._drift_sum_wall = 100_000.0
    coordinator._drift_sum_counter = 1_000.0  # 99% "loss"

    assert coordinator._drift_rate == MAX_DRIFT

    coordinator._drift_sum_counter = 200_000.0  # counter twice wall time
    assert coordinator._drift_rate == -MAX_DRIFT


@pytest.mark.asyncio
async def test_the_cap_lets_the_estimate_follow_a_firmware_fix(hass):
    """A counter that stops drifting must not be outvoted by its own history."""
    coordinator = _coordinator(hass, _entry())
    coordinator._startup_reconciled = True

    drifting = Router(rate=ZTE_RATE, uptime=0)
    now = _run(coordinator, drifting, start=NOW, polls=200, interval=timedelta(hours=6))
    assert coordinator._drift_rate == pytest.approx(ZTE_RATE, abs=0.002)
    assert coordinator._drift_sum_wall <= DRIFT_ACCUMULATOR_CAP

    fixed = Router(rate=0.0, uptime=drifting.counter)
    _run(coordinator, fixed, start=now, polls=200, interval=timedelta(hours=6))

    assert coordinator._drift_rate < ZTE_RATE / 2, "the cap did not let it move"


# ---------------------------------------------------------------------------
# No false alarms — the failure this redesign exists to remove
# ---------------------------------------------------------------------------


# Rates deliberately span PLAUSIBILITY_TOLERANCE. A suite that stopped at the
# measured 4.34% passed a build in which any device drifting past the
# tolerance re-latched on every poll, because the anchor was not corrected
# for drift and the observed ratio therefore sat a full `rate` from the
# predicted one.
@pytest.mark.parametrize("rate", [0.0, ZTE_RATE, 0.08, 0.12, -0.02])
@pytest.mark.asyncio
async def test_a_running_router_never_moves_the_timestamp(hass, rate):
    """Thirty days of polling at any believable rate, with no reboot."""
    router = Router(rate=rate, uptime=3600)
    boot = NOW - timedelta(seconds=3600 / (1 - rate))
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))

    _poll(coordinator, router.counter, NOW)
    router.advance(POLL.total_seconds())
    latched = coordinator._boot_time
    assert latched is not None

    _run(coordinator, router, start=NOW + POLL, polls=2700)

    assert coordinator._boot_time == latched, f"timestamp moved at rate {rate}"


@pytest.mark.asyncio
async def test_restarts_across_a_month_never_move_the_timestamp(hass):
    """The original defect surfaced on restarts, so restart repeatedly.

    A new coordinator each time, as a real restart gives, carrying the store
    record forward exactly as the real one would.
    """
    router = Router(rate=ZTE_RATE, uptime=3600)
    entry = _entry(boot_time=(NOW - timedelta(seconds=3760)).isoformat())
    carried: dict = {}
    now = NOW
    latched = None

    for _ in range(30):
        coordinator = _coordinator(hass, entry)
        coordinator._stored_last_uptime = carried.get("counter")
        coordinator._stored_written_at = carried.get("written_at")
        coordinator._drift_sum_wall = carried.get("wall", 0.0)
        coordinator._drift_sum_counter = carried.get("counter_sum", 0.0)

        now = _run(coordinator, router, start=now, polls=20)

        if latched is None:
            latched = coordinator._boot_time
        assert coordinator._boot_time == latched, "a restart moved the timestamp"

        carried = {
            "counter": coordinator._stored_last_uptime,
            "written_at": coordinator._stored_written_at,
            "wall": coordinator._drift_sum_wall,
            "counter_sum": coordinator._drift_sum_counter,
        }
        now += timedelta(hours=8)
        router.advance(8 * 3600)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_counter_drop_is_a_reboot_unconditionally(hass):
    """The one signal needing no clock and no assumption. Nothing vetoes it."""
    router = Router(uptime=500_000)
    boot = NOW - timedelta(seconds=520_000)
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))
    coordinator._startup_reconciled = True
    coordinator._boot_time = boot
    coordinator._last_uptime = 500_000

    _poll(coordinator, 20, NOW)

    assert coordinator._boot_time == NOW - timedelta(seconds=20)
    assert coordinator.entry.data["boot_time"] == coordinator._boot_time.isoformat()


@pytest.mark.asyncio
async def test_a_reboot_inside_an_offline_gap_is_detected(hass):
    """Failure Mode 1: the shortfall test is what sees it."""
    boot = NOW - timedelta(days=6)
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))
    coordinator._stored_last_uptime = 432_000
    coordinator._stored_written_at = NOW - timedelta(days=1)
    coordinator._drift_sum_wall = 200_000.0
    coordinator._drift_sum_counter = 200_000.0 * (1 - ZTE_RATE)

    # Home Assistant was away a day; the router rebooted eight hours ago.
    _poll(coordinator, 28_800, NOW)

    # The anchor is corrected for the counter's drift: 28,800 counted seconds
    # represent 28,800 / (1 - rate) of wall time, so `now - counter` would sit
    # twenty minutes late.
    expected = NOW - timedelta(seconds=28_800 / (1 - ZTE_RATE))
    assert coordinator._boot_time == expected.replace(microsecond=0)
    assert coordinator._startup_reconciled


@pytest.mark.asyncio
async def test_a_simultaneous_cold_start_is_detected(hass):
    """Failure Mode 2: mains restored, both devices boot together."""
    boot = NOW - timedelta(days=5)
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))
    coordinator._stored_last_uptime = 400_000
    coordinator._stored_written_at = NOW - timedelta(minutes=30)

    _poll(coordinator, 45, NOW)

    assert coordinator._boot_time == NOW - timedelta(seconds=45)


@pytest.mark.asyncio
async def test_a_clean_restart_preserves_the_timestamp_exactly(hass):
    """No reboot, so the stored instant is kept — not recomputed."""
    boot = NOW - timedelta(days=5)
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))
    coordinator._stored_last_uptime = 400_000
    coordinator._stored_written_at = NOW - timedelta(minutes=20)

    _poll(coordinator, 400_000 + 1200 * (1 - ZTE_RATE), NOW)

    assert coordinator._boot_time == boot
    assert coordinator._startup_reconciled


@pytest.mark.asyncio
async def test_the_plausibility_backstop_catches_a_stale_anchor(hass):
    """The failure the whole design exists to prevent, caught on any poll."""
    stale = NOW - timedelta(days=24)
    coordinator = _coordinator(hass, _entry(boot_time=stale.isoformat()))
    coordinator._startup_reconciled = True
    coordinator._boot_time = stale
    coordinator._drift_sum_wall = 200_000.0
    coordinator._drift_sum_counter = 200_000.0 * (1 - ZTE_RATE)

    # Four days of counter against twenty-four days of anchor.
    _poll(coordinator, 4 * 86_400, NOW)

    expected = NOW - timedelta(seconds=4 * 86_400 / (1 - ZTE_RATE))
    assert coordinator._boot_time == expected.replace(microsecond=0)


@pytest.mark.asyncio
async def test_a_backward_candidate_is_never_treated_as_a_reboot(hass):
    """A reboot moves the boot instant forward. A backward move cannot be one."""
    boot = NOW - timedelta(hours=1)
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))
    coordinator._startup_reconciled = True
    coordinator._boot_time = boot
    coordinator._drift_sum_wall = 200_000.0
    coordinator._drift_sum_counter = 200_000.0 * (1 - ZTE_RATE)

    # A counter far larger than the anchor allows: the candidate lands earlier.
    _poll(coordinator, 10 * 86_400, NOW)

    assert coordinator._boot_time == boot


# ---------------------------------------------------------------------------
# Cold start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cold_start_retains_a_healthy_anchor(hass):
    """No store and no rate: the wide bound must not fire on a good anchor."""
    boot = NOW - timedelta(days=4)
    counter = 4 * 86_400 * (1 - ZTE_RATE)
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))

    _poll(coordinator, counter, NOW)

    assert coordinator._boot_time == boot
    assert coordinator._startup_reconciled


@pytest.mark.asyncio
async def test_cold_start_relatches_a_stale_anchor(hass):
    """The upgrade case: a reboot happened while nothing was watching."""
    coordinator = _coordinator(
        hass, _entry(boot_time=(NOW - timedelta(days=24)).isoformat())
    )

    _poll(coordinator, 4 * 86_400, NOW)

    assert coordinator._boot_time == NOW - timedelta(days=4)


@pytest.mark.asyncio
async def test_a_fresh_install_latches_unconditionally(hass):
    """Nothing stored at all, so there is nothing to preserve."""
    coordinator = _coordinator(hass, _entry())

    _poll(coordinator, 3_600, NOW)

    assert coordinator._boot_time == NOW - timedelta(seconds=3_600)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unset_clock_defers_rather_than_latching(hass):
    """A host with no battery-backed clock starts in 1970."""
    boot = NOW - timedelta(days=5)
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))

    _poll(coordinator, 3_600, datetime(1970, 1, 1, 0, 5, tzinfo=UTC))
    assert coordinator._boot_time == boot
    assert not coordinator._startup_reconciled, "deferred, not skipped"

    _poll(coordinator, 3_600, NOW)
    assert coordinator._startup_reconciled


@pytest.mark.asyncio
async def test_an_implausible_counter_is_rejected(hass):
    """Believing it would write a boot instant decades adrift."""
    boot = NOW - timedelta(days=5)
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))

    _poll(coordinator, 20 * 365 * 86_400, NOW)

    assert coordinator._boot_time == boot
    assert not coordinator._startup_reconciled


@pytest.mark.parametrize("bad", [None, -1, "abc", ""])
@pytest.mark.asyncio
async def test_a_bad_reading_leaves_the_latch_alone(hass, bad):
    """The pre-existing guard, retained deliberately."""
    boot = NOW - timedelta(days=5)
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))
    coordinator.api.get_all_data = AsyncMock(
        return_value={**GOOD_DATA, "realtime_time": bad}
    )

    data = await coordinator._async_update_data()

    assert data["boot_time"] == boot
    assert not coordinator._startup_reconciled


@pytest.mark.parametrize("value", ["2026-08-01T10:00:00", "not a datetime", ""])
@pytest.mark.asyncio
async def test_a_naive_or_unparsable_anchor_is_treated_as_absent(hass, value):
    """Mixing naive and aware raises; treat it as no stored value."""
    coordinator = _coordinator(hass, _entry(boot_time=value))
    assert coordinator._boot_time is None

    _poll(coordinator, 3_600, NOW)

    assert coordinator._boot_time == NOW - timedelta(seconds=3_600)


@pytest.mark.asyncio
async def test_a_small_backward_step_is_logged_not_absorbed(hass, caplog):
    """Nothing establishes that this counter never steps back. Say so if it does."""
    coordinator = _coordinator(hass, _entry())
    coordinator._startup_reconciled = True
    coordinator._boot_time = NOW - timedelta(hours=2)
    coordinator._last_uptime = 7_200

    _poll(coordinator, 7_190, NOW)

    assert coordinator._boot_time == NOW - timedelta(hours=2), "10 s is not a reboot"
    assert "stepped back" in caplog.text


@pytest.mark.asyncio
async def test_a_move_without_a_counter_drop_is_flagged(hass, caplog):
    """The signature of this bug class, made visible from the log alone."""
    coordinator = _coordinator(
        hass, _entry(boot_time=(NOW - timedelta(days=24)).isoformat())
    )
    coordinator._startup_reconciled = True
    coordinator._boot_time = NOW - timedelta(days=24)
    coordinator._last_uptime = 4 * 86_400
    coordinator._drift_sum_wall = 200_000.0
    coordinator._drift_sum_counter = 200_000.0 * (1 - ZTE_RATE)

    _poll(coordinator, 4 * 86_400 + 900, NOW)

    assert "without a counter drop" in caplog.text


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_store_record_carries_the_accumulators(hass):
    """What a restart needs: the counter, when it was written, and the rate."""
    coordinator = _coordinator(hass, _entry())
    coordinator._startup_reconciled = True
    coordinator._drift_sum_wall = 100_000.0
    coordinator._drift_sum_counter = 95_660.0
    coordinator._drift_rate_min = 0.0424
    coordinator._drift_rate_max = 0.0473
    coordinator._drift_interval_count = 15

    _poll(coordinator, 43_359, NOW)

    record = coordinator._store.async_delay_save.call_args.args[0]()
    assert record["last_uptime"] == 43_359
    assert record["written_at"] == NOW.isoformat()
    assert record["sum_wall"] == pytest.approx(100_000.0, abs=1000)
    assert record["rate_min"] == pytest.approx(0.0424)
    assert record["interval_count"] >= 15


@pytest.mark.parametrize(
    "payload",
    [None, "junk", {}, {"last_uptime": "nope"}, {"written_at": "2026-09-01T12:00:00"}],
)
@pytest.mark.asyncio
async def test_an_unusable_store_record_falls_back_cleanly(hass, payload):
    """A naive `written_at` cannot date the gap, so the record is not usable."""
    coordinator = _coordinator(hass, _entry())
    with patch("custom_components.zte_router_5g.coordinator.Store") as store_cls:
        store_cls.return_value.async_load = AsyncMock(return_value=payload)
        await coordinator.async_load_stored_uptime()

    assert coordinator._stored_written_at is None


@pytest.mark.parametrize(
    "failure", [ValueError("corrupt"), OSError("unreadable"), RuntimeError("odd")]
)
@pytest.mark.asyncio
async def test_a_failing_store_load_never_reaches_setup(hass, failure):
    """No storage fault may fail entry setup: the store is a cross-check."""
    coordinator = _coordinator(hass, _entry())
    with patch("custom_components.zte_router_5g.coordinator.Store") as store_cls:
        store_cls.return_value.async_load = AsyncMock(side_effect=failure)
        await coordinator.async_load_stored_uptime()

    assert coordinator._stored_last_uptime is None


@pytest.mark.asyncio
async def test_a_full_store_record_is_read_back(hass):
    """Fields are additive, so an older record without them still loads."""
    coordinator = _coordinator(hass, _entry())
    with patch("custom_components.zte_router_5g.coordinator.Store") as store_cls:
        store_cls.return_value.async_load = AsyncMock(
            return_value={
                "last_uptime": 43_359,
                "written_at": "2026-09-01T15:10:00+00:00",
                "sum_wall": 378_494.2,
                "sum_counter": 362_079.5,
                "rate_min": 0.0424,
                "rate_max": 0.0473,
                "interval_count": 15,
            }
        )
        await coordinator.async_load_stored_uptime()

    assert coordinator._stored_last_uptime == 43_359
    assert coordinator._stored_written_at == datetime(2026, 9, 1, 15, 10, tzinfo=UTC)
    assert coordinator._drift_rate == pytest.approx(0.0434, abs=0.0005)


@pytest.mark.asyncio
async def test_the_store_is_keyed_to_the_entry(hass):
    """One store per entry, so two routers cannot overwrite each other."""
    entry = _entry()
    coordinator = _coordinator(hass, entry)
    with patch("custom_components.zte_router_5g.coordinator.Store") as store_cls:
        store_cls.return_value.async_load = AsyncMock(return_value=None)
        await coordinator.async_load_stored_uptime()

    assert entry.entry_id in store_cls.call_args.args[2]


@pytest.mark.asyncio
async def test_the_counter_is_flushed_on_the_interval_not_every_poll(hass):
    """Write economy: the accumulators update in memory, not on disk."""
    coordinator = _coordinator(hass, _entry())
    coordinator._startup_reconciled = True
    coordinator._boot_time = NOW - timedelta(hours=1)

    _poll(coordinator, 3_600, NOW)
    first = coordinator._store.async_delay_save.call_count

    _poll(coordinator, 3_660, NOW + timedelta(minutes=1))
    assert coordinator._store.async_delay_save.call_count == first

    _poll(coordinator, 5_000, NOW + UPTIME_WRITE_INTERVAL)
    assert coordinator._store.async_delay_save.call_count == first + 1


@pytest.mark.asyncio
async def test_a_latch_drops_the_legacy_counter_from_entry_data(hass):
    """The key that caused the original defect must not survive the fix."""
    coordinator = _coordinator(hass, _entry(last_uptime=60))
    coordinator._startup_reconciled = True
    coordinator._boot_time = NOW - timedelta(days=5)
    coordinator._last_uptime = 400_000

    _poll(coordinator, 45, NOW)

    assert "last_uptime" not in coordinator.entry.data
    assert "boot_time" in coordinator.entry.data


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_drift_picture_is_published(hass):
    """Every constant here came from one device; this is how another reports."""
    coordinator = _coordinator(hass, _entry())
    coordinator._drift_sum_wall = 378_494.0
    coordinator._drift_sum_counter = 362_079.0
    coordinator._drift_rate_min = 0.0424
    coordinator._drift_rate_max = 0.0473
    coordinator._drift_interval_count = 15

    published = coordinator.uptime_diagnostics
    assert published["drift_rate_pct"] == pytest.approx(4.337, abs=0.01)
    assert published["drift_rate_min_pct"] == pytest.approx(4.24, abs=0.01)
    assert published["drift_intervals"] == 15
    assert published["drift_deficit_seconds"] == 16_415

    state = coordinator.uptime_state
    assert "boot_time" in state
    assert "stored_written_at" in state
    assert state["startup_reconciled"] is False


@pytest.mark.asyncio
async def test_the_drift_picture_is_empty_before_measurement(hass):
    """A fresh install reports nothing rather than a confident zero."""
    coordinator = _coordinator(hass, _entry())
    assert coordinator.uptime_diagnostics["drift_rate_pct"] is None


# ---------------------------------------------------------------------------
# Replay of the real device
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_real_recorder_series_produces_no_false_alarm(hass):
    """Real drift, a real reboot and real gaps, from the device that failed.

    Captured from `home-assistant_v2.db` on 2026-09-01 before the recorder's
    ten-day purge. No synthetic fixture carries this much awkwardness: an
    intermittently-running Home Assistant, a counter losing 4.3%, and one
    genuine router reboot inside a thirteen-hour gap.
    """
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures" / "uptime_drift_real_series.json"
        ).read_text(encoding="utf-8")
    )
    samples = [s for s in fixture["samples"] if s["counter"] is not None]
    reboot_at = datetime.fromisoformat(fixture["known_events"]["router_reboot_utc"])

    coordinator = _coordinator(hass, _entry())
    moves: list[datetime] = []

    for sample in samples:
        now = datetime.fromisoformat(sample["utc"])
        before = coordinator._boot_time
        _poll(coordinator, sample["counter"], now)
        if coordinator._boot_time != before:
            moves.append(coordinator._boot_time)

    # The counter drop is unmissable, so the reboot must be found.
    assert any(abs((m - reboot_at).total_seconds()) < 3600 for m in moves), (
        f"the real reboot at {reboot_at} was not detected; moves were {moves}"
    )
    # One latch for the first poll, one for the reboot. Anything more is the
    # drift moving the timestamp, which is the defect being fixed.
    assert len(moves) <= 2, f"timestamp moved {len(moves)} times: {moves}"
    assert coordinator._drift_rate == pytest.approx(
        fixture["measured"]["aggregate_drift_rate"], abs=0.01
    )


# ---------------------------------------------------------------------------
# Defensive paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_store_record_dated_ahead_of_now_falls_back(hass):
    """Only reachable from a clock that has since been corrected backwards."""
    boot = NOW - timedelta(days=4)
    coordinator = _coordinator(hass, _entry(boot_time=boot.isoformat()))
    coordinator._stored_last_uptime = 400_000
    coordinator._stored_written_at = NOW + timedelta(hours=2)

    _poll(coordinator, 4 * 86_400 * (1 - ZTE_RATE), NOW)

    assert coordinator._boot_time == boot, "a healthy anchor was discarded"
    assert coordinator._startup_reconciled


@pytest.mark.asyncio
async def test_a_store_record_dated_ahead_still_relatches_a_stale_anchor(hass):
    """The fallback must not become a way to keep a wrong anchor."""
    coordinator = _coordinator(
        hass, _entry(boot_time=(NOW - timedelta(days=24)).isoformat())
    )
    coordinator._stored_last_uptime = 400_000
    coordinator._stored_written_at = NOW + timedelta(hours=2)

    _poll(coordinator, 4 * 86_400, NOW)

    assert coordinator._boot_time == NOW - timedelta(days=4)


@pytest.mark.asyncio
async def test_an_anchor_dated_ahead_of_now_is_implausible_at_cold_start(hass):
    """A zero or negative elapsed cannot be judged, so it is not believed."""
    coordinator = _coordinator(
        hass, _entry(boot_time=(NOW + timedelta(hours=1)).isoformat())
    )

    _poll(coordinator, 3_600, NOW)

    assert coordinator._boot_time == NOW - timedelta(seconds=3_600)


@pytest.mark.asyncio
async def test_the_plausibility_check_skips_a_future_anchor(hass):
    """It cannot divide by a non-positive elapsed, and must not try."""
    ahead = NOW + timedelta(hours=1)
    coordinator = _coordinator(hass, _entry())
    coordinator._startup_reconciled = True
    coordinator._boot_time = ahead
    coordinator._drift_sum_wall = 200_000.0
    coordinator._drift_sum_counter = 200_000.0 * (1 - ZTE_RATE)

    _poll(coordinator, 3_600, NOW)

    assert coordinator._boot_time == ahead, "no latch from an unjudgeable anchor"


@pytest.mark.parametrize("rate", [0.0, ZTE_RATE, 0.08, 0.12, -0.02])
@pytest.mark.asyncio
async def test_the_latched_instant_is_corrected_for_drift(hass, rate):
    """`now - counter` is late by the drift the counter has accumulated.

    On a device losing 4.34%, a counter reading four days puts the instant four
    and a half hours late. Dividing by `(1 - rate)` recovers the wall time the
    counter represents, which is both a more accurate timestamp and what keeps
    the plausibility check's tolerance independent of the device.
    """
    coordinator = _coordinator(hass, _entry())
    coordinator._startup_reconciled = True
    coordinator._boot_time = NOW - timedelta(days=30)
    coordinator._last_uptime = 500_000
    coordinator._drift_sum_wall = 200_000.0
    coordinator._drift_sum_counter = 200_000.0 * (1 - rate)

    counter = 4 * 86_400
    _poll(coordinator, counter, NOW)

    expected = NOW - timedelta(seconds=counter / (1 - rate))
    assert coordinator._boot_time == expected.replace(microsecond=0)


@pytest.mark.parametrize("rate", [ZTE_RATE, 0.08, 0.12])
@pytest.mark.asyncio
async def test_a_stale_anchor_is_corrected_once_and_stays_corrected(hass, rate):
    """The upgrade case, at rates either side of the tolerance.

    Regression guard for the build in which this thrashed: 397 timestamp moves
    across 400 polls at 6% drift, which is worse than the defect being fixed.
    """
    coordinator = _coordinator(
        hass,
        _entry(boot_time=(NOW - timedelta(days=24)).isoformat(), last_uptime=60),
    )
    router = Router(rate=rate, uptime=4 * 86_400 * (1 - rate))

    moves = []
    previous = coordinator._boot_time
    now = NOW
    for _ in range(200):
        _poll(coordinator, router.counter, now)
        if coordinator._boot_time != previous:
            moves.append(coordinator._boot_time)
            previous = coordinator._boot_time
        now += POLL
        router.advance(POLL.total_seconds())

    assert len(moves) == 1, f"{len(moves)} moves at rate {rate:.2%}"
    assert "last_uptime" not in coordinator.entry.data
