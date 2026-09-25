"""The coordinator's side of the poll plan (3.4.4-dev2)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.api import POLL_UNIVERSE, ZTERouterAPI
from custom_components.zte_router_5g.const import (
    CONF_STOP_POLLING,
    DOMAIN,
    FETCH_STRIKE_LIMIT,
)
from custom_components.zte_router_5g.coordinator import (
    ENDPOINT_EXTENDED,
    ZTERouterDataUpdateCoordinator,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

GOOD = {
    "network_type": "ENDC",
    "signalbar": "4",
    "wa_inner_version": "FW1",
    "realtime_time": "3600",
    "wan_connect_status": "ppp_connected",
    "ppp_status": "ppp_connected",
    "lte_rsrp": "-97",
}


@pytest.fixture
def entry() -> MockConfigEntry:
    """A config entry with credentials in options."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="864155042229309",
        title="ZTE 5G",
        data={"imei": "864155042229309"},
        options={CONF_HOST: "192.168.0.1", CONF_USERNAME: "a", CONF_PASSWORD: "p"},
    )


@pytest.fixture
def coordinator(
    hass: HomeAssistant, entry: MockConfigEntry
) -> ZTERouterDataUpdateCoordinator:
    """A coordinator on a mocked API."""
    entry.add_to_hass(hass)
    api = MagicMock(spec=ZTERouterAPI)
    api.get_all_data = AsyncMock(return_value=dict(GOOD))
    api.get_extended_data = AsyncMock(return_value={})
    api.get_sms_capacity = AsyncMock(return_value={})
    api.get_sms_messages = AsyncMock(return_value=[])
    api.login = AsyncMock(return_value="stok")
    return ZTERouterDataUpdateCoordinator(hass, entry, api)


async def _poll(coordinator: ZTERouterDataUpdateCoordinator) -> Any:
    coordinator._force_refresh_once = True
    coordinator.data = await coordinator._async_update_data()
    return coordinator.api.get_all_data.await_args.args[0]


async def test_the_first_poll_asks_everything_and_the_next_is_narrowed(
    coordinator,
) -> None:
    """The first poll resolves; the second asks only what it needs."""
    first = await _poll(coordinator)
    assert first is None or len(first) == len(POLL_UNIVERSE)
    second = await _poll(coordinator)
    assert second is not None
    assert len(second) < len(POLL_UNIVERSE)
    assert "lte_rsrp" in second
    assert coordinator.poll_plan.last_kind == "narrowed"


async def test_refresh_now_owes_a_full_poll(coordinator) -> None:
    """`request_full_poll` makes the next poll full."""
    await _poll(coordinator)
    coordinator.request_full_poll("refresh now")
    await _poll(coordinator)
    assert coordinator.poll_plan.last_kind == "full"
    assert not coordinator.poll_plan.full_reasons


async def test_a_full_poll_served_from_the_cache_stays_owed(coordinator) -> None:
    """The extended half failing with strikes left does not count as full."""
    await _poll(coordinator)
    coordinator.api.get_extended_data = AsyncMock(side_effect=OSError("silent"))
    coordinator.request_full_poll("refresh now")
    await _poll(coordinator)
    assert "refresh now" in coordinator.poll_plan.full_reasons


async def test_an_endpoint_past_its_strikes_does_not_force_full_polls(
    coordinator,
) -> None:
    """Its failure is its own once the strikes are spent."""
    await _poll(coordinator)
    coordinator.api.get_extended_data = AsyncMock(side_effect=OSError("silent"))
    coordinator._endpoint_failures[ENDPOINT_EXTENDED] = FETCH_STRIKE_LIMIT
    coordinator.request_full_poll("refresh now")
    await _poll(coordinator)
    assert not coordinator.poll_plan.full_reasons


async def test_a_reboot_owes_a_full_poll(coordinator) -> None:
    """A counter that went backwards."""
    await _poll(coordinator)
    coordinator._poll_previous = {"uptime": 10**9, "link": "ppp_connected"}
    with patch.object(coordinator.poll_plan, "after_poll"):
        await coordinator._update_poll_plan({**GOOD, "uptime_seconds": 5})
    assert "reboot" in coordinator.poll_plan.full_reasons


async def test_the_data_connection_returning_owes_a_full_poll(coordinator) -> None:
    """Values that were blank while data was off answer again."""
    await _poll(coordinator)
    coordinator._poll_previous = {"uptime": None, "link": "ppp_disconnected"}
    with patch.object(coordinator.poll_plan, "after_poll"):
        await coordinator._update_poll_plan(GOOD)
    assert "data connection returned" in coordinator.poll_plan.full_reasons


async def test_a_firmware_change_discards_what_answered(coordinator) -> None:
    """Names learned on another firmware describe one that is gone."""
    await _poll(coordinator)
    coordinator.poll_plan.answered.add("only_on_fw1")
    with patch.object(coordinator.poll_plan, "after_poll"):
        await coordinator._update_poll_plan({**GOOD, "wa_inner_version": "FW2"})
    assert "only_on_fw1" not in coordinator.poll_plan.answered
    assert "firmware changed" in coordinator.poll_plan.full_reasons


async def test_a_fault_in_the_plan_never_fails_a_poll(coordinator) -> None:
    """Found in the dev2 live check: a stub entry without `unique_id` failed it."""
    with patch.object(
        coordinator, "_update_poll_plan", AsyncMock(side_effect=AttributeError("x"))
    ):
        coordinator._force_refresh_once = True
        data = await coordinator._async_update_data()
    assert data


async def test_stored_names_load_before_the_first_poll(coordinator, hass) -> None:
    """A restart starts narrowed from what answered before."""
    stored = {"firmware": "FW1", "answered": ["lte_rsrp"]}
    with patch("custom_components.zte_router_5g.coordinator.Store") as store:
        store.return_value.async_load = AsyncMock(return_value=stored)
        await coordinator.async_load_profile()
    assert coordinator.poll_plan.answered == {"lte_rsrp"}
    assert coordinator.poll_plan.consumers
    _, full = coordinator.poll_plan.names(datetime.now(UTC))
    assert not full


async def test_a_store_that_cannot_be_read_loads_nothing(coordinator) -> None:
    """No storage fault fails setup."""
    with patch("custom_components.zte_router_5g.coordinator.Store") as store:
        store.return_value.async_load = AsyncMock(side_effect=OSError("disk"))
        await coordinator.async_load_profile()
    assert not coordinator.poll_plan.answered


async def test_new_answers_schedule_a_delayed_save(coordinator) -> None:
    """The store is written when something new answers, not every poll."""
    coordinator._poll_store = MagicMock()
    await _poll(coordinator)
    coordinator._poll_store.async_delay_save.assert_called_once()
    saver = coordinator._poll_store.async_delay_save.call_args.args[0]
    assert saver()["answered"]
    await _poll(coordinator)
    coordinator._poll_store.async_delay_save.assert_called_once()


async def test_disabled_entities_are_read_from_the_registry(coordinator, hass) -> None:
    """A registry entry disabled for this entry is skipped."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{coordinator.entry.unique_id}_lte_rsrp",
        config_entry=coordinator.entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    assert entity.disabled_by is not None
    assert coordinator._disabled_unique_ids() == {entity.unique_id}


def test_a_registry_that_cannot_be_read_skips_nothing(coordinator) -> None:
    """No registry means every entity counts as enabled."""
    coordinator.hass = None
    assert coordinator._disabled_unique_ids() == set()


async def test_the_sparse_check_keeps_one_high_water_mark_per_poll_kind(
    coordinator,
) -> None:
    """A narrowed poll is not judged against a full poll's population.

    Judged against the full poll's mark, a narrowed poll with a quarter of its
    values would read as a collapse.
    """
    full = dict.fromkeys((f"k{i}" for i in range(200)), "v")
    narrowed = dict(list(full.items())[:50])
    coordinator._poll_kind = "full"
    assert coordinator._sparse_payload_finding(full) is None
    coordinator._poll_kind = "narrowed"
    assert coordinator._sparse_payload_finding(narrowed) is None
    coordinator._poll_kind = "full"
    assert coordinator._sparse_payload_finding(full) is None
    assert coordinator._payload_high_water == 200


async def test_paused_entries_still_skip_scheduled_polls(
    coordinator, entry, hass
) -> None:
    """The plan changes what a poll asks, never whether it runs."""
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_STOP_POLLING: True}
    )
    coordinator.data = {"cached": "value"}
    assert await coordinator._async_update_data() == {"cached": "value"}
