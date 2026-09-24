"""The uptime latches through an upgrade, a restart and a second poll.

Added in 3.4.2-dev8. Dev7's tests loaded a store and fed a poll on separate
coordinators, so none ran the sequence an existing install goes through, and
Connection Uptime stayed unknown after the upgrade: the pre-dev7 flat record
gave the connection latch a stored counter with no anchor. Each case here runs
on one entry, in order: a starting store, the first poll, a restart built from
what the first run wrote, and a poll after the restart.

Two routers: the MC7010 answers `system_uptime`; a router that does not, as
the MC888 Pro may not, uses the session counter for Device Uptime as well.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.api import ZTERouterAPI
from custom_components.zte_router_5g.const import DOMAIN
from custom_components.zte_router_5g.coordinator import ZTERouterDataUpdateCoordinator
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME

NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC)
_NOW = "custom_components.zte_router_5g.coordinator.dt_util.now"
_STORE = "custom_components.zte_router_5g.coordinator.Store"

# The router booted 10,000 s before NOW; data connected 3,000 s before NOW.
SYSTEM = 10_000
SESSION = 3_000
BOOT = NOW - timedelta(seconds=SYSTEM)
CONNECTED = NOW - timedelta(seconds=SESSION)

# What 3.4.2-dev6 left behind: `boot_time` latched from the session counter,
# and one flat store record from that counter.
DEV6_ENTRY = {"boot_time": CONNECTED.isoformat(), "last_uptime": 61}
DEV6_STORE = {
    "last_uptime": SESSION - 600,
    "written_at": (NOW - timedelta(seconds=600)).isoformat(),
    "sum_wall": 50_000.0,
    "sum_counter": 47_830.0,
    "interval_count": 40,
}
# What 3.4.2-dev7 left behind on the devcontainer: the system latch anchored,
# the connection latch holding a counter and no anchor.
DEV7_ENTRY = {"boot_time": BOOT.isoformat()}
DEV7_STORE = {
    "last_system_uptime": {
        "last_uptime": SYSTEM - 600,
        "written_at": (NOW - timedelta(seconds=600)).isoformat(),
        "sum_wall": 0.0,
        "sum_counter": 0.0,
        "interval_count": 0,
    },
    "last_conn_uptime": {
        "last_uptime": SESSION - 600,
        "written_at": (NOW - timedelta(seconds=600)).isoformat(),
        "sum_wall": 50_000.0,
        "sum_counter": 47_830.0,
        "interval_count": 40,
    },
}


def _entry(hass, data: dict[str, Any]) -> MockConfigEntry:
    entry = MockConfigEntry(
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
    entry.add_to_hass(hass)
    return entry


async def _start(hass, entry, stored: Any) -> ZTERouterDataUpdateCoordinator:
    """A coordinator as setup builds it: constructed, then its store loaded."""
    coordinator = ZTERouterDataUpdateCoordinator(
        hass, entry, MagicMock(spec=ZTERouterAPI)
    )
    with patch(_STORE) as store_cls:
        store_cls.return_value.async_load = AsyncMock(return_value=stored)
        await coordinator.async_load_stored_uptime()
    coordinator._store = MagicMock()
    return coordinator


def _poll(coordinator, payload: dict[str, Any], now: datetime) -> dict[str, Any]:
    data = dict(payload)
    with patch(_NOW, return_value=now):
        coordinator._postprocess_payload(data, {}, [])
    return data


def _written(coordinator) -> Any:
    """The record the run would have saved, as the next start reads it."""
    return coordinator._store.async_delay_save.call_args.args[0]()


def _payload(system: bool, elapsed: int = 0) -> dict[str, Any]:
    data: dict[str, Any] = {"realtime_time": str(SESSION + elapsed)}
    if system:
        data["system_uptime"] = str(SYSTEM + elapsed)
    return data


def _close(actual: Any, expected: datetime, seconds: float = 2.0) -> bool:
    return actual is not None and abs((actual - expected).total_seconds()) <= seconds


@pytest.mark.parametrize("system", [True, False], ids=["mc7010", "no_system_key"])
@pytest.mark.parametrize(
    ("entry_data", "stored"),
    [(DEV6_ENTRY, DEV6_STORE), (DEV7_ENTRY, DEV7_STORE), ({}, None)],
    ids=["from_dev6", "from_dev7", "fresh"],
)
@pytest.mark.asyncio
async def test_upgrade_poll_restart_poll(hass, entry_data, stored, system) -> None:
    """All four uptime values right after the first poll and after a restart."""
    entry = _entry(hass, entry_data)
    expected_boot = BOOT if system else CONNECTED

    coordinator = await _start(hass, entry, stored)
    data = _poll(coordinator, _payload(system), NOW)

    # The stored session record carries a learned drift of 4.34%, and the
    # latch corrects the anchor for it: `now - counter / (1 - rate)`.
    assert _close(data["connection_start"], CONNECTED, seconds=SESSION * 0.05)
    assert data["uptime_seconds"] == (SYSTEM if system else SESSION)
    if system:
        # A dev6 anchor from the session counter is 7,000 s late against the
        # router's uptime; the cold start rejects it.
        assert _close(data["boot_time"], expected_boot)
    assert entry.data.get("connection_start") is not None
    assert "last_uptime" not in entry.data

    # Restart: a new coordinator from the entry and the record just written.
    later = NOW + timedelta(seconds=300)
    restarted = await _start(hass, entry, _written(coordinator))
    after = _poll(restarted, _payload(system, 300), later)

    assert after["connection_start"] == data["connection_start"]
    assert after["boot_time"] == data["boot_time"]
    assert restarted._conn_latch.startup_reconciled is True


@pytest.mark.asyncio
async def test_data_off_at_startup_latches_when_data_returns(hass) -> None:
    """A blank session counter is no reading; the latch waits for one."""
    entry = _entry(hass, DEV7_ENTRY)
    coordinator = await _start(hass, entry, DEV7_STORE)

    off = _poll(coordinator, {"system_uptime": str(SYSTEM), "realtime_time": ""}, NOW)
    assert off["connection_start"] is None
    assert off["boot_time"] is not None

    later = NOW + timedelta(seconds=120)
    on = _poll(
        coordinator, {"system_uptime": str(SYSTEM + 120), "realtime_time": "5"}, later
    )
    assert _close(on["connection_start"], later - timedelta(seconds=5))


@pytest.mark.asyncio
async def test_a_reconnect_after_the_upgrade_moves_only_the_connection(hass) -> None:
    """Device Uptime holds across a data reconnect; Connection Uptime moves."""
    entry = _entry(hass, DEV6_ENTRY)
    coordinator = await _start(hass, entry, DEV6_STORE)
    first = _poll(coordinator, _payload(True), NOW)

    later = NOW + timedelta(seconds=600)
    second = _poll(
        coordinator, {"system_uptime": str(SYSTEM + 600), "realtime_time": "20"}, later
    )

    assert second["boot_time"] == first["boot_time"]
    assert _close(second["connection_start"], later - timedelta(seconds=20))


@pytest.mark.asyncio
async def test_a_reboot_after_the_upgrade_moves_both(hass) -> None:
    """The system counter drops; both anchors move."""
    entry = _entry(hass, DEV7_ENTRY)
    coordinator = await _start(hass, entry, DEV7_STORE)
    _poll(coordinator, _payload(True), NOW)

    later = NOW + timedelta(seconds=900)
    after = _poll(coordinator, {"system_uptime": "90", "realtime_time": "40"}, later)

    assert _close(after["boot_time"], later - timedelta(seconds=90))
    assert _close(after["connection_start"], later - timedelta(seconds=40))


# --------------------------------------------------------------------------
# Found by the dev8 review
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_dev6_anchor_inside_the_band_is_still_replaced(hass) -> None:
    """Up 10,000 s, connected 9,000 s: the ratio 1.11 is inside MAX_DRIFT.

    The cold start keeps an anchor it cannot tell from drift, and the
    plausibility check never moves an anchor earlier, so the reconnect time
    would stay as Device Uptime until the next reboot.
    """
    connected = NOW - timedelta(seconds=9_000)
    entry = _entry(hass, {"boot_time": connected.isoformat()})
    coordinator = await _start(hass, entry, None)

    data = _poll(
        coordinator, {"system_uptime": str(SYSTEM), "realtime_time": "9000"}, NOW
    )

    assert _close(data["boot_time"], BOOT)


@pytest.mark.asyncio
async def test_a_source_that_changes_between_runs_re_anchors(hass) -> None:
    """A run that fell back to the session counter must not bind the next."""
    entry = _entry(hass, {})
    first = await _start(hass, entry, None)
    _poll(first, {"system_uptime": "", "realtime_time": "9000"}, NOW)
    assert first.uptime_source == "realtime_time"

    later = NOW + timedelta(seconds=300)
    second = await _start(hass, entry, _written(first))
    data = _poll(
        second, {"system_uptime": str(SYSTEM + 300), "realtime_time": "9300"}, later
    )

    assert second.uptime_source == "system_uptime"
    assert _close(data["boot_time"], BOOT)


@pytest.mark.asyncio
async def test_a_zero_session_counter_is_data_off(hass) -> None:
    """The MC7010 reads 0 as well as blank while data is off."""
    entry = _entry(hass, DEV7_ENTRY)
    coordinator = await _start(hass, entry, DEV7_STORE)
    _poll(coordinator, _payload(True), NOW)

    off_at = NOW + timedelta(seconds=60)
    off = _poll(
        coordinator, {"system_uptime": str(SYSTEM + 60), "realtime_time": "0"}, off_at
    )
    assert off["connection_start"] is None
    # Connection Duration read 0.0 here on the MC7010 before 3.4.2-dev8.
    assert off["connection_seconds"] is None

    on_at = NOW + timedelta(seconds=600)
    on = _poll(
        coordinator, {"system_uptime": str(SYSTEM + 600), "realtime_time": "30"}, on_at
    )
    assert _close(on["connection_start"], on_at - timedelta(seconds=30))


@pytest.mark.asyncio
async def test_a_zero_session_counter_is_not_chosen_as_the_source(hass) -> None:
    """A blank `system_uptime` beside `realtime_time` "0" chooses nothing yet."""
    entry = _entry(hass, {})
    coordinator = await _start(hass, entry, None)

    _poll(coordinator, {"system_uptime": "", "realtime_time": "0"}, NOW)

    assert coordinator.uptime_source is None


@pytest.mark.asyncio
async def test_a_blank_reading_of_a_chosen_session_key_is_no_reading(hass) -> None:
    """On a router without a system key, a blank session counter changes nothing."""
    entry = _entry(hass, {})
    coordinator = await _start(hass, entry, None)
    first = _poll(coordinator, {"realtime_time": "500"}, NOW)

    blank = _poll(coordinator, {"realtime_time": ""}, NOW + timedelta(seconds=30))
    zero = _poll(coordinator, {"realtime_time": "0"}, NOW + timedelta(seconds=60))

    assert blank["uptime_seconds"] is None
    assert zero["uptime_seconds"] is None
    assert zero["boot_time"] == first["boot_time"]
