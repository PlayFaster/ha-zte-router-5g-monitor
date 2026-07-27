"""Options reload-vs-live-apply, and session release on unload.

Both behaviours only exist through the real config-entry pipeline, so every
test drives a real ``hass`` and blocks on the loop after the change.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g import _async_options_updated
from custom_components.zte_router_5g.api import ZTEConnectionError, ZTERouterAPI
from custom_components.zte_router_5g.const import (
    CONF_SCAN_INTERVAL,
    CONF_STOP_POLLING,
    DOMAIN,
    LIVE_OPTION_KEYS,
)

ROUTER_DATA = {
    "network_type": "ENDC",
    "signalbar": "4",
    "wa_inner_version": "IRL_H3G_MC7010DV1.0.0B01",
    "realtime_time": "3600",
    "wan_connect_status": "ppp_connected",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the custom component importable by the real hass fixture."""
    return


@pytest.fixture
def entry():
    """Return a config entry ready for a real setup pass."""
    return MockConfigEntry(
        domain=DOMAIN,
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
        api.get_sms_capacity = AsyncMock(return_value={})
        api.get_sms_messages = AsyncMock(return_value=[])
        yield api


async def _setup(hass: HomeAssistant, entry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def test_live_keys_are_the_tuning_options_only() -> None:
    """Connection settings must never be live-applied."""
    assert set(LIVE_OPTION_KEYS) == {CONF_SCAN_INTERVAL, CONF_STOP_POLLING}
    assert CONF_HOST not in LIVE_OPTION_KEYS
    assert CONF_PASSWORD not in LIVE_OPTION_KEYS
    assert CONF_USERNAME not in LIVE_OPTION_KEYS


async def test_changing_the_host_reloads_the_entry(
    hass: HomeAssistant, entry, mock_api
) -> None:
    """The defect this fixes: a new host must reach the API client.

    Before the update listener existed, the options flow wrote a new host into
    the entry and nothing reloaded, so the running client kept talking to the
    old device until Home Assistant restarted.
    """
    await _setup(hass, entry)

    with patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload:
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_HOST: "10.0.0.5"}
        )
        await hass.async_block_till_done()

    schedule_reload.assert_called_once_with(entry.entry_id)


async def test_changing_the_password_reloads_the_entry(
    hass: HomeAssistant, entry, mock_api
) -> None:
    """Credentials are connection state, so they reload too."""
    await _setup(hass, entry)

    with patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload:
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_PASSWORD: "new-secret"}
        )
        await hass.async_block_till_done()

    schedule_reload.assert_called_once_with(entry.entry_id)


async def test_moving_the_slider_does_not_reload(
    hass: HomeAssistant, entry, mock_api
) -> None:
    """A reload per slider nudge would tear down every entity mid-drag."""
    await _setup(hass, entry)
    coordinator = entry.runtime_data

    with patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload:
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_SCAN_INTERVAL: 600}
        )
        await hass.async_block_till_done()

    schedule_reload.assert_not_called()
    assert coordinator.update_interval.total_seconds() == 600


async def test_pausing_does_not_reload(hass: HomeAssistant, entry, mock_api) -> None:
    """Pause is read fresh each cycle, so it needs no rebuild."""
    await _setup(hass, entry)

    with patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload:
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_STOP_POLLING: True}
        )
        await hass.async_block_till_done()

    schedule_reload.assert_not_called()


async def test_options_listener_is_a_noop_without_a_coordinator(
    hass: HomeAssistant, entry
) -> None:
    """The listener must tolerate firing with no runtime_data.

    `runtime_data` is set during setup and torn down by Home Assistant on
    unload, so there is a window in which the listener can be invoked with
    nothing to act on. Reloading — or dereferencing the coordinator — would
    raise, and an exception here surfaces as an unhandled error in the config
    entry pipeline rather than anywhere useful.
    """
    entry.add_to_hass(hass)
    assert getattr(entry, "runtime_data", None) is None

    with patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload:
        await _async_options_updated(hass, entry)

    schedule_reload.assert_not_called()


async def test_unload_releases_the_router_session(
    hass: HomeAssistant, entry, mock_api
) -> None:
    """The router permits one session; unload must give it back."""
    await _setup(hass, entry)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    mock_api.logout.assert_awaited_once()


async def test_logout_swallows_errors_and_clears_session(hass: HomeAssistant) -> None:
    """An unreachable router must not block teardown.

    Exercises the real client rather than the double: logout runs on unload, so
    a raising logout would leave the entry stuck. It must clear local session
    state regardless of what the router does.
    """
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    api.stok = "stok=live-session"

    with patch.object(
        api, "_request", AsyncMock(side_effect=ZTEConnectionError("router gone"))
    ):
        await api.logout()

    assert api.stok is None


async def test_logout_sends_an_ad_token(hass: HomeAssistant) -> None:
    """LOGOUT without an AD token is silently ignored by the router.

    Verified against MC7010 firmware V1.0.0B03: `goformId=LOGOUT` alone returns
    `{"result":"failure"}` and the session stays live, so omitting AD would
    make this method look like it worked while changing nothing.
    """
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    api.stok = "stok=live-session"

    with (
        patch.object(api, "get_ad", AsyncMock(return_value="deadbeef")),
        patch.object(api, "_request", AsyncMock()) as request,
    ):
        await api.logout()

    payload = request.await_args.kwargs["data"]
    assert "goformId=LOGOUT" in payload
    assert "AD=deadbeef" in payload


async def test_logout_is_a_noop_without_a_session(hass: HomeAssistant) -> None:
    """No session means nothing to release — and no request to make."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    api.stok = None

    with patch.object(api, "_request", AsyncMock()) as request:
        await api.logout()

    request.assert_not_awaited()
