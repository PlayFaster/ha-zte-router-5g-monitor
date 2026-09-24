"""Device uptime from `system_uptime`; connection uptime from the data session.

3.4.2-dev7. Measured on the MC7010 on 2026-09-23: `system_uptime` read 1400
with data off, and 1479 after data was turned on and 78 s of wall time had
passed, while `realtime_time` went from blank to 71. The session counter had
fed Device Uptime until then, so every reconnect moved the reported boot time.

The system latch chooses one key per run. The connection latch reads the
session counter. Both are instances of the latch ported from the Huawei
project, whose logic `test_uptime_latch.py` covers on the system latch.
"""

from datetime import UTC, datetime, timedelta
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.api import ZTERouterAPI
from custom_components.zte_router_5g.const import (
    CONNECTION_UPTIME_KEYS,
    DEVICE_UPTIME_KEYS,
    DOMAIN,
)
from custom_components.zte_router_5g.coordinator import ZTERouterDataUpdateCoordinator
from custom_components.zte_router_5g.observations import _device_uptime
from custom_components.zte_router_5g.sensor import SENSOR_TYPES
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

NOW = datetime(2026, 9, 23, 22, 30, 0, tzinfo=UTC)
_NOW = "custom_components.zte_router_5g.coordinator.dt_util.now"


def _entry(**data: Any) -> MockConfigEntry:
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
    entry.add_to_hass(hass)
    api = MagicMock(spec=ZTERouterAPI)
    coordinator = ZTERouterDataUpdateCoordinator(hass, entry, api)
    coordinator._store = MagicMock()
    return coordinator


def _feed(coordinator, payload: dict[str, Any], now: datetime = NOW) -> dict:
    data = dict(payload)
    with patch(_NOW, return_value=now):
        coordinator._postprocess_payload(data, {}, [])
    return data


def _sensor(key: str):
    return next(d for d in SENSOR_TYPES if d.key == key)


# --------------------------------------------------------------------------
# The key tuples
# --------------------------------------------------------------------------


def test_the_device_tuple_prefers_the_router_uptime() -> None:
    """`system_uptime` first, the session counter last."""
    assert DEVICE_UPTIME_KEYS == (
        "system_uptime",
        "flux_system_uptime",
        "realtime_time",
        "flux_realtime_time",
    )
    assert CONNECTION_UPTIME_KEYS == ("realtime_time", "flux_realtime_time")


# --------------------------------------------------------------------------
# Device source selection
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_uptime_feeds_device_uptime_and_the_session_does_not(hass):
    """Boot time is the router's boot, however recently data reconnected."""
    coordinator = _coordinator(hass, _entry())

    data = _feed(coordinator, {"system_uptime": "1479", "realtime_time": "71"})

    assert coordinator.uptime_source == "system_uptime"
    assert data["uptime_seconds"] == 1479
    assert data["boot_time"] == NOW - timedelta(seconds=1479)
    assert data["connection_start"] == NOW - timedelta(seconds=71)


@pytest.mark.asyncio
async def test_a_device_without_a_system_key_uses_the_session_counter(hass):
    """The MC888 Pro's `system_uptime` is not measured; this is today's behavior."""
    coordinator = _coordinator(hass, _entry())

    data = _feed(coordinator, {"flux_realtime_time": "500"})

    assert coordinator.uptime_source == "flux_realtime_time"
    assert data["boot_time"] == data["connection_start"]


@pytest.mark.asyncio
async def test_a_blank_reading_of_the_chosen_key_is_no_reading(hass):
    """Never a fallback mid-run: that reads as a counter drop and a false reboot."""
    coordinator = _coordinator(hass, _entry())
    first = _feed(coordinator, {"system_uptime": "90000", "realtime_time": "80000"})

    later = _feed(
        coordinator,
        {"system_uptime": "", "realtime_time": "35"},
        NOW + timedelta(seconds=60),
    )

    assert coordinator.uptime_source == "system_uptime"
    assert later["boot_time"] == first["boot_time"]
    assert later["uptime_seconds"] is None


@pytest.mark.asyncio
async def test_no_key_answering_chooses_nothing(hass):
    """A first poll with every counter blank leaves the choice for the next."""
    coordinator = _coordinator(hass, _entry())

    data = _feed(coordinator, {"system_uptime": "", "realtime_time": ""})

    assert coordinator.uptime_source is None
    assert data["boot_time"] is None
    assert data["connection_start"] is None


@pytest.mark.asyncio
async def test_the_flat_record_from_before_goes_to_the_connection_latch(hass):
    """Before 3.4.2-dev7 the one latch read `realtime_time`."""
    coordinator = _coordinator(hass, _entry())
    flat = {
        "last_uptime": 3500,
        "written_at": "2026-09-23T22:00:00+00:00",
        "sum_wall": 5000.0,
        "sum_counter": 4800.0,
        "interval_count": 3,
    }
    with patch("custom_components.zte_router_5g.coordinator.Store") as store_cls:
        store_cls.return_value.async_load = AsyncMock(return_value=flat)
        await coordinator.async_load_stored_uptime()

    # The drift carries over. The counter does not: the entry has no
    # `connection_start`, and a stored counter without an anchor would keep the
    # latch from ever anchoring (3.4.2-dev8).
    assert coordinator._conn_latch.stored_counter is None
    assert coordinator._conn_latch.drift_sum_wall == 5000.0
    assert coordinator._system_latch.stored_counter is None


@pytest.mark.asyncio
async def test_both_latches_are_written_in_one_record(hass):
    """One block per latch, keyed as the Huawei project keys them."""
    coordinator = _coordinator(hass, _entry())
    _feed(coordinator, {"system_uptime": "1479", "realtime_time": "71"})

    record = coordinator._store.async_delay_save.call_args[0][0]()
    assert record["last_system_uptime"]["last_uptime"] == 1479
    assert record["last_conn_uptime"]["last_uptime"] == 71


# --------------------------------------------------------------------------
# The connection latch
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_connection_start_moves_at_each_reconnect(hass):
    """The same latch logic: a drop beyond the margin re-anchors it."""
    coordinator = _coordinator(hass, _entry())
    _feed(coordinator, {"system_uptime": "10000", "realtime_time": "5000"})

    later = NOW + timedelta(seconds=600)
    data = _feed(coordinator, {"system_uptime": "10600", "realtime_time": "40"}, later)

    assert data["connection_start"] == later - timedelta(seconds=40)
    assert data["boot_time"] == NOW - timedelta(seconds=10000)


@pytest.mark.asyncio
async def test_the_connection_start_is_empty_while_data_is_off(hass):
    """The last session's start would read as a live one."""
    coordinator = _coordinator(hass, _entry())
    _feed(coordinator, {"system_uptime": "10000", "realtime_time": "5000"})

    data = _feed(
        coordinator,
        {"system_uptime": "10060", "realtime_time": ""},
        NOW + timedelta(seconds=60),
    )

    assert data["connection_start"] is None
    assert coordinator._conn_latch.boot_time is not None


@pytest.mark.asyncio
async def test_each_latch_writes_its_own_key_and_drops_the_legacy_counter(hass):
    """`boot_time` is the router's; `connection_start` is the session's."""
    entry = _entry(last_uptime=61)
    coordinator = _coordinator(hass, entry)

    _feed(coordinator, {"system_uptime": "10000", "realtime_time": "300"})

    assert entry.data["connection_start"] == (NOW - timedelta(seconds=300)).isoformat()
    assert entry.data["boot_time"] == (NOW - timedelta(seconds=10000)).isoformat()
    assert "last_uptime" not in entry.data


@pytest.mark.asyncio
async def test_each_latch_names_itself_in_the_log(hass, caplog):
    """The labels are the latch's own, as in the Huawei project."""
    coordinator = _coordinator(hass, _entry())

    with caplog.at_level(logging.INFO):
        _feed(coordinator, {"system_uptime": "10000", "realtime_time": "300"})

    assert "System boot time latched" in caplog.text
    assert "Connection start time latched" in caplog.text


# --------------------------------------------------------------------------
# Sensors, diagnostics, observations
# --------------------------------------------------------------------------


def test_the_four_uptime_sensors_read_their_values() -> None:
    """Device values from the latch source; connection values from the session."""
    start = NOW - timedelta(seconds=71)
    data = {
        "boot_time": NOW - timedelta(seconds=1479),
        "uptime_seconds": 1479,
        "connection_start": start,
        "connection_seconds": 71,
    }

    assert _sensor("device_uptime").value_fn(data) == data["boot_time"]
    assert _sensor("realtime_time").value_fn(data) == 1479
    assert _sensor("connection_uptime").value_fn(data) == start
    assert _sensor("connection_duration").value_fn(data) == 71


def test_the_connection_duration_is_empty_while_data_is_off() -> None:
    """The coordinator publishes no value while data is off, not zero."""
    assert _sensor("connection_duration").value_fn({"connection_seconds": None}) is None


def test_the_change_history_places_a_change_against_the_router_uptime() -> None:
    """`uptime_at_change` says whether a change followed a reboot."""
    assert _device_uptime({"uptime_seconds": 1479, "realtime_time": "71"}) == 1479
    assert _device_uptime({"realtime_time": "71"}) == 71


@pytest.mark.asyncio
async def test_the_download_names_the_source_and_carries_the_connection_latch(
    hass, mock_config_entry
):
    """Kees48's next download says which key his MC888 Pro answered."""
    from custom_components.zte_router_5g.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    real = _coordinator(hass, _entry())
    _feed(real, {"system_uptime": "1479", "realtime_time": "71"})
    coordinator = MagicMock()
    coordinator.data = {}
    coordinator.consecutive_failures = 0
    coordinator.last_update_success = True
    coordinator.last_update_success_time = None
    coordinator.update_interval = None
    coordinator.health_snapshot = {"problem": False, "issues": [], "severity": "ok"}
    coordinator.uptime_state = real.uptime_state
    coordinator.uptime_diagnostics = real.uptime_diagnostics
    coordinator.endpoint_failures = {}
    coordinator.api.write_failures = []
    mock_config_entry.runtime_data = coordinator
    with patch(
        "custom_components.zte_router_5g.web_sources.crawl",
        new=AsyncMock(return_value={"files": {}, "sources": {}, "fetched": 0}),
    ):
        result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    uptime = result["coordinator"]["uptime"]
    assert uptime["source"] == "system_uptime"
    assert uptime["latches"]["last_conn_uptime"]["anchor"] == (
        (NOW - timedelta(seconds=71)).isoformat()
    )
