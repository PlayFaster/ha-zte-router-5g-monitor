"""Tests for the ZTE Router number."""

import asyncio
from contextlib import suppress
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.entity import EntityCategory

from custom_components.zte_router_5g.const import CONF_SCAN_INTERVAL, DOMAIN
from custom_components.zte_router_5g.number import (
    POLLING_INTERVAL_DESCRIPTION,
    ZTENumberEntityDescription,
    ZTEPollingInterval,
    async_setup_entry,
)

from .conftest import assert_is_root, assert_links_to_parent


def _mock_hass_with_async_create_task():
    """Return a MagicMock hass where async_create_task returns a real Task."""
    hass_mock = MagicMock()

    def _async_create_task(coro):
        return asyncio.ensure_future(coro)

    hass_mock.async_create_task = _async_create_task
    return hass_mock


@pytest.mark.asyncio
async def test_polling_interval_change(mock_coordinator, mock_config_entry):
    """Test that changing the slider updates the coordinator and options."""
    number = ZTEPollingInterval(
        mock_coordinator, mock_config_entry, POLLING_INTERVAL_DESCRIPTION, 180
    )
    number.hass = _mock_hass_with_async_create_task()
    number.async_write_ha_state = MagicMock()

    # Mock the debounced apply method to run immediately
    with patch("asyncio.sleep", AsyncMock()):
        await number.async_set_native_value(300)

        # Await the background task created by async_set_native_value
        if number._refresh_task:
            await number._refresh_task

        # 1. Check local state
        assert number.native_value == 300

        # 2. Check coordinator interval update
        assert mock_coordinator.update_interval == timedelta(seconds=300)

        # 3. Check persistence call
        number.hass.config_entries.async_update_entry.assert_called_once()
        _args, kwargs = number.hass.config_entries.async_update_entry.call_args
        assert kwargs["options"][CONF_SCAN_INTERVAL] == 300

        # 4. Check refresh request
        mock_coordinator.async_force_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_number_setup_entry():
    """Test platform setup."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test"
    entry.options = {CONF_SCAN_INTERVAL: 180}
    entry.runtime_data = MagicMock()

    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)
    async_add_entities.assert_called_once()


@pytest.mark.asyncio
async def test_polling_interval_cancel_previous_task(
    mock_coordinator, mock_config_entry
):
    """Test that changing the slider cancels any pending debounce task (line 98)."""
    number = ZTEPollingInterval(
        mock_coordinator, mock_config_entry, POLLING_INTERVAL_DESCRIPTION, 180
    )
    number.hass = _mock_hass_with_async_create_task()
    number.async_write_ha_state = MagicMock()

    with patch("asyncio.sleep", AsyncMock()):
        await number.async_set_native_value(120)
        task1 = number._refresh_task
        await number.async_set_native_value(300)
        assert task1 is not None
        await asyncio.sleep(0)
        await number._refresh_task


@pytest.mark.asyncio
async def test_async_will_remove_from_hass_pending_task(
    mock_coordinator, mock_config_entry
):
    """Test that async_will_remove_from_hass cancels a pending refresh task."""
    number = ZTEPollingInterval(
        mock_coordinator, mock_config_entry, POLLING_INTERVAL_DESCRIPTION, 180
    )
    number.hass = _mock_hass_with_async_create_task()
    number.async_write_ha_state = MagicMock()

    # Create a pending refresh task
    async def never_completing():
        await asyncio.Event().wait()

    number._refresh_task = asyncio.ensure_future(never_completing())
    assert not number._refresh_task.done()

    await number.async_will_remove_from_hass()
    # Await the task so the cancellation propagates fully
    with suppress(asyncio.CancelledError):
        await number._refresh_task
    assert number._refresh_task.cancelled()


@pytest.mark.asyncio
async def test_async_will_remove_from_hass_no_task(mock_coordinator, mock_config_entry):
    """Removal with nothing pending must write nothing and cancel nothing.

    The distinction is against the flush path: an entity removed without the
    user having touched the slider has no value to commit, so teardown must
    not write options — a spurious `async_update_entry` here would schedule a
    reload of the entry that is already being torn down.
    """
    number = ZTEPollingInterval(
        mock_coordinator, mock_config_entry, POLLING_INTERVAL_DESCRIPTION, 180
    )
    number.hass = MagicMock()
    number._refresh_task = None

    await number.async_will_remove_from_hass()

    number.hass.config_entries.async_update_entry.assert_not_called()
    mock_coordinator.async_force_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_async_debounced_apply_cancelled(mock_coordinator, mock_config_entry):
    """Test that CancelledError is silently caught (lines 126-128)."""
    number = ZTEPollingInterval(
        mock_coordinator, mock_config_entry, POLLING_INTERVAL_DESCRIPTION, 180
    )
    number.hass = MagicMock()

    with patch("asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)):
        await number._async_debounced_apply(120)

    mock_coordinator.async_force_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_async_debounced_apply_exception(
    mock_coordinator, mock_config_entry, caplog
):
    """Test that unexpected exceptions are logged (lines 129-130)."""
    number = ZTEPollingInterval(
        mock_coordinator, mock_config_entry, POLLING_INTERVAL_DESCRIPTION, 180
    )
    number.hass = MagicMock()

    with patch("asyncio.sleep", AsyncMock(side_effect=ValueError("boom"))):
        await number._async_debounced_apply(120)

    assert "Failed to apply polling interval change" in caplog.text


@pytest.mark.asyncio
async def test_device_info_system_group(mock_coordinator, mock_config_entry):
    """Test device_info for system group (no via_device)."""
    mock_coordinator.api.protocol = "http"
    number = ZTEPollingInterval(
        mock_coordinator, mock_config_entry, POLLING_INTERVAL_DESCRIPTION, 180
    )

    info = number.device_info
    assert info["identifiers"] == {(DOMAIN, "864155042229309_system")}
    assert info["name"] == "My ZTE Router System"
    assert info["manufacturer"] == "ZTE"
    assert info["configuration_url"] == "http://192.168.0.1"
    assert_is_root(info)


@pytest.mark.asyncio
async def test_device_info_signal_group(mock_coordinator, mock_config_entry):
    """Test device_info with non-system group (has via_device)."""
    desc = ZTENumberEntityDescription(
        key="test",
        translation_key="test",
        native_min_value=1,
        native_max_value=100,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
        group="signal",
    )

    number = ZTEPollingInterval(mock_coordinator, mock_config_entry, desc, 50)

    info = number.device_info
    assert_links_to_parent(info, DOMAIN, "864155042229309_system")
    assert info["name"] == "My ZTE Router Signal"


@pytest.mark.asyncio
async def test_device_info_no_mac(mock_coordinator, mock_config_entry):
    """Test device_info fallback when coordinator has no mac."""
    mock_coordinator.imei = None

    number = ZTEPollingInterval(
        mock_coordinator, mock_config_entry, POLLING_INTERVAL_DESCRIPTION, 180
    )

    info = number.device_info
    assert info["identifiers"] == {(DOMAIN, "host_192.168.0.1_system")}


@pytest.mark.asyncio
async def test_a_pending_interval_change_is_flushed_on_removal(
    mock_coordinator, mock_config_entry
):
    """A value set inside the debounce window must survive a reload.

    The slider writes optimistically and commits after 2 s. An options change
    — or any reload — removes the entity inside that window, and cancelling
    the task discards the write: the number snaps back to its old value with
    no explanation, which reads as the control not working. Teardown must
    commit the pending value rather than drop it.
    """
    number = ZTEPollingInterval(
        mock_coordinator, mock_config_entry, POLLING_INTERVAL_DESCRIPTION, 180
    )
    number.hass = _mock_hass_with_async_create_task()
    number.async_write_ha_state = MagicMock()

    # No `asyncio.sleep` patch here: the point is that removal arrives while
    # the debounce is still waiting.
    await number.async_set_native_value(300)
    assert number._refresh_task is not None
    assert not number._refresh_task.done()

    await number.async_will_remove_from_hass()
    with suppress(asyncio.CancelledError):
        await number._refresh_task

    number.hass.config_entries.async_update_entry.assert_called_once()
    options = number.hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert options[CONF_SCAN_INTERVAL] == 300
