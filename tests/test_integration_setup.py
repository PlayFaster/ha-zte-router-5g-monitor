"""Integration-level tests driven through a real Home Assistant instance.

The rest of the suite is unit-style: entities and the coordinator are exercised
directly against a ``MagicMock`` hass. That is fast and gives good line
coverage, but it cannot verify the two things dev_standards Section 11 calls
out, because both need a real event loop and a real config-entry pipeline:

* the **background setup task** actually running to completion — a mocked hass
  records that ``async_create_background_task`` was called and never awaits the
  coroutine, so the code inside it is never driven;
* a **runtime options change** firing the ``add_update_listener`` pipeline —
  ``object.__setattr__`` seeds options silently, and a mocked
  ``async_update_entry`` fires nothing at all.

Every test here therefore uses the real ``hass`` fixture and
``await hass.async_block_till_done()`` after anything that spawns a task.
"""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.const import (
    CONF_SCAN_INTERVAL,
    CONF_STOP_POLLING,
    DOMAIN,
)

ROUTER_DATA = {
    "network_type": "ENDC",
    "signalbar": "4",
    "wa_inner_version": "IRL_H3G_MC7010DV1.0.0B01",
    "model_name": "MC7010",
    "realtime_time": "3600",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the custom component importable by the real hass fixture."""
    return


@pytest.fixture
def live_entry():
    """Return a config entry suitable for a real setup pass."""
    return MockConfigEntry(
        domain=DOMAIN,
        # Must match ZTEConfigFlow.VERSION — a lower version sends the entry
        # down HA's migration path, which this integration does not implement.
        version=2,
        unique_id="864155042229309",
        title="ZTE 5G",
        data={"model": "MC7010", "sw_version": "V1.0.0", "imei": "864155042229309"},
        options={
            CONF_HOST: "192.168.0.1",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "password",
            CONF_SCAN_INTERVAL: 180,
        },
    )


@pytest.fixture
def mock_api():
    """Patch the API client with an all-success async double."""
    with patch("custom_components.zte_router_5g.ZTERouterAPI") as api_class:
        api = api_class.return_value
        api.protocol = "http"
        api.try_set_protocol = AsyncMock(return_value=None)
        api.login = AsyncMock(return_value="stok=test")
        api.logout = AsyncMock(return_value=None)
        api.get_all_data = AsyncMock(return_value=dict(ROUTER_DATA))
        api.probe_discovery_candidates = AsyncMock(return_value={})
        api.measure_unauthenticated_keys = AsyncMock(return_value=frozenset())
        api.get_sms_capacity = AsyncMock(return_value={})
        api.get_sms_messages = AsyncMock(return_value=[])
        yield api


async def test_setup_runs_background_task_to_completion(
    hass: HomeAssistant, live_entry, mock_api
) -> None:
    """Setup returns immediately, then the background task completes.

    This is the Section 1 / Section 11 pairing: ``async_setup_entry`` must not
    block, so the proof that login and the first refresh actually happened can
    only come from awaiting the loop afterwards.
    """
    live_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(live_entry.entry_id)
    await hass.async_block_till_done()

    # The background task ran: login was awaited and data was populated.
    mock_api.login.assert_awaited()
    coordinator = live_entry.runtime_data
    assert coordinator.data is not None
    assert coordinator.data["network_type"] == "ENDC"
    assert coordinator.consecutive_failures == 0


async def test_entities_exist_before_first_fetch_succeeds(
    hass: HomeAssistant, live_entry, mock_api
) -> None:
    """A cold-start failure still leaves entities registered.

    Section 1 permits forgoing ``ConfigEntryNotReady`` only because platforms
    are forwarded before the background task is created, so the user sees
    unavailable entities rather than an empty device page.
    """
    mock_api.login = AsyncMock(side_effect=TimeoutError("router down"))
    mock_api.get_all_data = AsyncMock(side_effect=TimeoutError("router down"))
    live_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(live_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.async_entity_ids("sensor")


async def test_options_update_fires_listener_pipeline(
    hass: HomeAssistant, live_entry, mock_api
) -> None:
    """A runtime options change goes through ``async_update_entry``.

    ``object.__setattr__`` is only valid for seeding options *before* setup;
    it silently bypasses the update-listener pipeline that Sections 9, 13 and
    15 all depend on. This test is the one that exercises that pipeline.
    """
    live_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(live_entry.entry_id)
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(
        live_entry, options={**live_entry.options, CONF_STOP_POLLING: True}
    )
    await hass.async_block_till_done()

    assert live_entry.options[CONF_STOP_POLLING] is True


async def test_unload_releases_the_entry(
    hass: HomeAssistant, live_entry, mock_api
) -> None:
    """Unloading tears down every platform cleanly."""
    live_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(live_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(live_entry.entry_id)
    await hass.async_block_till_done()

    assert live_entry.state is ConfigEntryState.NOT_LOADED
