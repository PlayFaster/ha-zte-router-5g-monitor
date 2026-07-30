"""Tests for the ZTE Router switch."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.zte_router_5g.const import (
    CONF_STOP_POLLING,
    DOMAIN,
    WRITE_VERIFY_TIMEOUT,
)
from custom_components.zte_router_5g.coordinator import ENDPOINT_EXTENDED
from custom_components.zte_router_5g.switch import (
    PAUSE_POLLING_DESCRIPTION,
    SWITCH_TYPES,
    ZTEPausePollingSwitch,
    ZTERouterSwitch,
    ZTESwitchEntityDescription,
    async_setup_entry,
)

from .conftest import assert_links_to_parent


@pytest.mark.asyncio
async def test_pause_polling_switch(mock_coordinator, mock_config_entry):
    """Test turning the pause switch on and off."""
    # Start with False (not paused)
    new_options = dict(mock_config_entry.options)
    new_options[CONF_STOP_POLLING] = False
    object.__setattr__(mock_config_entry, "options", new_options)

    switch = ZTEPausePollingSwitch(
        mock_coordinator, mock_config_entry, PAUSE_POLLING_DESCRIPTION, False
    )
    switch.hass = MagicMock()
    # Mock hass.data structure
    switch.hass.data = {DOMAIN: {mock_config_entry.entry_id: mock_coordinator}}
    switch.async_write_ha_state = MagicMock()

    # 1. Turn ON (Pause)
    await switch.async_turn_on()
    switch.hass.config_entries.async_update_entry.assert_called()
    _args, kwargs = switch.hass.config_entries.async_update_entry.call_args
    assert kwargs["options"][CONF_STOP_POLLING] is True

    # 2. Turn OFF (Resume)
    await switch.async_turn_off()
    _args, kwargs = switch.hass.config_entries.async_update_entry.call_args
    assert kwargs["options"][CONF_STOP_POLLING] is False
    mock_coordinator.async_force_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_switch_setup_entry():
    """Test platform setup."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test"
    entry.options = {CONF_STOP_POLLING: False}
    entry.runtime_data = MagicMock()

    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)
    async_add_entities.assert_called_once()


def test_router_switch_is_on_no_data(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.is_on returns False when no data."""
    mock_coordinator.data = None
    desc = SWITCH_TYPES[0]
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    assert switch.is_on is False


def test_router_switch_is_on_no_value_fn(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.is_on returns False when value_fn is None."""
    mock_coordinator.data = {}
    desc = ZTESwitchEntityDescription(
        key="test_switch",
        translation_key="test_switch",
        value_fn=None,
    )
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    assert switch.is_on is False


def test_router_switch_is_on_true(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.is_on returns True when data matches."""
    mock_coordinator.data = {"ODU_led_switch": "1"}
    desc = SWITCH_TYPES[0]
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    assert switch.is_on is True


def test_router_switch_is_on_false(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.is_on returns False when data doesn't match."""
    mock_coordinator.data = {"ODU_led_switch": "0"}
    desc = SWITCH_TYPES[0]
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    assert switch.is_on is False


@pytest.mark.asyncio
async def test_router_switch_turn_on_no_setter(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.async_turn_on returns early when setter_fn is None."""
    desc = ZTESwitchEntityDescription(
        key="test_switch",
        translation_key="test_switch",
        setter_fn=None,
    )
    mock_coordinator.api = MagicMock()
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    await switch.async_turn_on()
    mock_coordinator.api.async_request_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_router_switch_turn_off_no_setter(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.async_turn_off returns early when setter_fn is None."""
    desc = ZTESwitchEntityDescription(
        key="test_switch",
        translation_key="test_switch",
        setter_fn=None,
    )
    mock_coordinator.api = MagicMock()
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    await switch.async_turn_off()
    mock_coordinator.api.async_request_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_router_switch_turn_on_success(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.async_turn_on calls setter and refreshes."""
    mock_coordinator.api = AsyncMock()
    setter_fn = AsyncMock()

    desc = ZTESwitchEntityDescription(
        key="test_switch",
        translation_key="test_switch",
        setter_fn=setter_fn,
    )
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    await switch.async_turn_on()
    setter_fn.assert_called_once_with(mock_coordinator.api, True, mock_coordinator.data)
    mock_coordinator.async_force_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_router_switch_turn_off_success(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.async_turn_off calls setter and refreshes."""
    mock_coordinator.api = AsyncMock()
    setter_fn = AsyncMock()

    desc = ZTESwitchEntityDescription(
        key="test_switch",
        translation_key="test_switch",
        setter_fn=setter_fn,
    )
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    await switch.async_turn_off()
    setter_fn.assert_called_once_with(
        mock_coordinator.api, False, mock_coordinator.data
    )
    mock_coordinator.async_force_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_router_switch_turn_on_exception(
    mock_coordinator, mock_config_entry, caplog
):
    """A refused write must reach the user, not just the log.

    This API answers `200 OK` for a command it declined, so a switch whose
    failure is only logged looks to the user like one that quietly sprang
    back. Asserted on `translation_key` rather than the message because a
    translated exception resolves its text through `hass` at `str()` time,
    which the mocked hass in this suite cannot do.
    """
    mock_coordinator.api = MagicMock()

    async def failing_setter(api, state, data):
        raise ValueError("test turn on error")

    desc = ZTESwitchEntityDescription(
        key="odu_led_switch",
        translation_key="test_switch",
        setter_fn=failing_setter,
    )
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)

    with pytest.raises(HomeAssistantError) as err:
        await switch.async_turn_on()

    assert err.value.translation_key == "switch_set_failed"
    assert "Failed to set" in caplog.text
    assert "odu_led_switch" in caplog.text
    mock_coordinator.async_force_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_router_switch_turn_off_exception(
    mock_coordinator, mock_config_entry, caplog
):
    """A refused write must reach the user, not just the log.

    This API answers `200 OK` for a command it declined, so a switch whose
    failure is only logged looks to the user like one that quietly sprang
    back. Asserted on `translation_key` rather than the message because a
    translated exception resolves its text through `hass` at `str()` time,
    which the mocked hass in this suite cannot do.
    """
    mock_coordinator.api = MagicMock()

    async def failing_setter(api, state, data):
        raise ValueError("test turn off error")

    desc = ZTESwitchEntityDescription(
        key="odu_led_switch",
        translation_key="test_switch",
        setter_fn=failing_setter,
    )
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)

    with pytest.raises(HomeAssistantError) as err:
        await switch.async_turn_off()

    assert err.value.translation_key == "switch_set_failed"
    assert "Failed to set" in caplog.text
    assert "odu_led_switch" in caplog.text
    mock_coordinator.async_force_refresh.assert_not_called()


def test_router_switch_device_info(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.device_info."""
    desc = SWITCH_TYPES[0]
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    info = switch.device_info
    assert info["identifiers"] == {("zte_router_5g", "864155042229309_system")}
    assert info["manufacturer"] == "ZTE"


def test_router_switch_device_info_data_group(mock_coordinator, mock_config_entry):
    """Test ZTERouterSwitch.device_info for data group."""
    desc = SWITCH_TYPES[1]
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, desc)
    info = switch.device_info
    assert info["identifiers"] == {("zte_router_5g", "864155042229309_data")}
    assert_links_to_parent(info, DOMAIN, "864155042229309_system")


def test_pause_polling_switch_is_on(mock_coordinator, mock_config_entry):
    """Test ZTEPausePollingSwitch.is_on."""
    switch = ZTEPausePollingSwitch(
        mock_coordinator, mock_config_entry, PAUSE_POLLING_DESCRIPTION, True
    )
    switch.hass = MagicMock()
    assert (
        switch.is_on is False
    )  # Because entry.options doesn't have CONF_STOP_POLLING=True


def test_no_switch_reads_from_a_degradable_endpoint():
    """A control's position must not come from a fetch allowed to degrade.

    Both switches were fed by the optional batch, which serves cached values
    while it has strikes left. A stale *diagnostic* is a cosmetic problem; a
    stale *control* invites a write built on a reading that is no longer true,
    which for `data_limit_switch` means composing its six-field form out of
    four cached values.
    """
    offenders = [d.key for d in SWITCH_TYPES if d.source is not None]
    assert not offenders, (
        f"switches reading from an optional endpoint: {offenders}. Promote the "
        "keys to _CORE_PARAMS instead — the budget test guards the URL length."
    )


def test_switch_unavailable_when_its_endpoint_is_degraded(
    mock_coordinator, mock_config_entry
):
    """The `source` gate still works for any switch that opts into one.

    No shipped switch sets `source` any more, so this exercises the mechanism
    with a synthetic description rather than deleting the coverage — the field
    remains for a future switch fed from the optional batch.
    """
    description = ZTESwitchEntityDescription(
        key="synthetic",
        source=ENDPOINT_EXTENDED,
        translation_key="system_odu_led_switch",
        value_fn=lambda data: False,
    )
    mock_coordinator.last_update_success = True
    mock_coordinator.endpoint_available.return_value = False
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, description)
    assert switch.available is False

    mock_coordinator.endpoint_available.return_value = True
    assert switch.available is True


def test_switch_unavailable_when_the_whole_fetch_is_down(
    mock_coordinator, mock_config_entry
):
    """A healthy endpoint cannot rescue an integration-wide outage."""
    description = next(d for d in SWITCH_TYPES if d.key == "data_limit_switch")
    mock_coordinator.last_update_success = False
    mock_coordinator.endpoint_available.return_value = True
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, description)
    assert switch.available is False


# --- Targeted write confirmation -------------------------------------------
#
# The coordinator's refresh is debounced with a ten-second cooldown, so a write
# landing inside that window did not reach the state machine for up to ten
# seconds. The frontend's optimistic toggle reverts long before that, which is
# what made the LED switch appear to toggle, revert, then correct itself.


def _verifying_switch(coordinator, entry, *, key="odu_led_switch"):
    """Build one of the two switches that confirm their own writes."""
    description = next(d for d in SWITCH_TYPES if d.key == key)
    assert description.verify_after_write, f"{key} no longer opts into verification"
    switch = ZTERouterSwitch(coordinator, entry, description)
    switch.async_write_ha_state = MagicMock()
    return switch, description


@pytest.mark.asyncio
async def test_confirmed_write_publishes_without_waiting_for_the_poll(
    mock_coordinator, mock_config_entry
):
    """The confirmed value must reach the state machine immediately."""
    mock_coordinator.data = {"ODU_led_switch": "0"}
    mock_coordinator.api = AsyncMock()
    mock_coordinator.api.get_params = AsyncMock(return_value={"ODU_led_switch": "1"})
    switch, _ = _verifying_switch(mock_coordinator, mock_config_entry)
    assert switch.is_on is False

    await switch.async_turn_on()

    mock_coordinator.api.get_params.assert_awaited_once_with(
        ["ODU_led_switch"], timeout_sec=WRITE_VERIFY_TIMEOUT
    )
    assert switch.is_on is True
    switch.async_write_ha_state.assert_called_once()
    # The poll still follows — the read-back confirms, it does not replace.
    mock_coordinator.async_force_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_write_the_router_did_not_apply_is_reported(
    mock_coordinator, mock_config_entry
):
    """A successful read reporting the old value is the one proof of refusal."""
    mock_coordinator.data = {"ODU_led_switch": "0"}
    mock_coordinator.api = AsyncMock()
    mock_coordinator.api.get_params = AsyncMock(return_value={"ODU_led_switch": "0"})
    switch, _ = _verifying_switch(mock_coordinator, mock_config_entry)

    with pytest.raises(HomeAssistantError) as err:
        await switch.async_turn_on()

    assert err.value.translation_key == "switch_write_not_applied"
    # Read twice: the second attempt is the leeway for a slower model.
    assert mock_coordinator.api.get_params.await_count == 2
    assert switch.is_on is False


@pytest.mark.asyncio
async def test_a_disagreeing_first_read_is_retried_not_reported(
    mock_coordinator, mock_config_entry
):
    """A router that applies just after answering must not be called a failure."""
    mock_coordinator.data = {"ODU_led_switch": "0"}
    mock_coordinator.api = AsyncMock()
    mock_coordinator.api.get_params = AsyncMock(
        side_effect=[{"ODU_led_switch": "0"}, {"ODU_led_switch": "1"}]
    )
    switch, _ = _verifying_switch(mock_coordinator, mock_config_entry)

    await switch.async_turn_on()

    assert mock_coordinator.api.get_params.await_count == 2
    assert switch.is_on is True


@pytest.mark.asyncio
async def test_a_failed_confirmation_is_unverified_not_failed(
    mock_coordinator, mock_config_entry
):
    """The write may well have landed; only a *read* can prove otherwise.

    Raising here would report a successful write as failed every time the
    connection blipped between the command and the confirmation.
    """
    mock_coordinator.data = {"ODU_led_switch": "0"}
    mock_coordinator.api = AsyncMock()
    mock_coordinator.api.get_params = AsyncMock(side_effect=OSError("boom"))
    switch, _ = _verifying_switch(mock_coordinator, mock_config_entry)

    await switch.async_turn_on()

    assert mock_coordinator.api.get_params.await_count == 1
    # Left to the poll, which still runs.
    mock_coordinator.async_force_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_a_confirmation_missing_the_key_is_unverified(
    mock_coordinator, mock_config_entry
):
    """An answer without the key says nothing about the write either way."""
    mock_coordinator.data = {"ODU_led_switch": "0"}
    mock_coordinator.api = AsyncMock()
    mock_coordinator.api.get_params = AsyncMock(return_value={})
    switch, _ = _verifying_switch(mock_coordinator, mock_config_entry)

    await switch.async_turn_on()

    assert mock_coordinator.api.get_params.await_count == 1
    mock_coordinator.async_force_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_a_switch_without_verification_does_not_read_back(
    mock_coordinator, mock_config_entry
):
    """Verification is opt-in — the APN and bearer writes must never do this."""
    mock_coordinator.api = AsyncMock()
    description = ZTESwitchEntityDescription(
        key="unverified",
        translation_key="test_switch",
        setter_fn=AsyncMock(),
        value_fn=lambda data: False,
    )
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, description)

    await switch.async_turn_on()

    mock_coordinator.api.get_params.assert_not_called()
    mock_coordinator.async_force_refresh.assert_called_once()


def test_a_poll_omitting_the_key_holds_the_last_known_position(
    mock_coordinator, mock_config_entry
):
    """A missing key must not render as a confident "off".

    A dead session answers 200 OK with every value blank. Defaulting to False
    made the switch appear to move on its own, which is indistinguishable from
    the router changing the setting.
    """
    mock_coordinator.data = {"ODU_led_switch": "1"}
    switch, _ = _verifying_switch(mock_coordinator, mock_config_entry)
    assert switch.is_on is True

    mock_coordinator.data = {}
    switch._handle_coordinator_update()
    assert switch.is_on is True, "absent key was read as the router reporting off"

    mock_coordinator.data = {"ODU_led_switch": "0"}
    switch._handle_coordinator_update()
    assert switch.is_on is False, "a reported off must still be honoured"


@pytest.mark.asyncio
async def test_verification_without_a_state_key_is_skipped(
    mock_coordinator, mock_config_entry
):
    """Verification needs a key to read, and must not guess one.

    `verify_after_write` without a `state_key` has nothing to confirm, and
    falling back to the entity key would be wrong — `data_limit_switch` reads
    its position from `data_volume_limit_switch`.
    """
    mock_coordinator.api = AsyncMock()
    description = ZTESwitchEntityDescription(
        key="misconfigured",
        translation_key="test_switch",
        verify_after_write=True,
        setter_fn=AsyncMock(),
        value_fn=lambda data: False,
    )
    switch = ZTERouterSwitch(mock_coordinator, mock_config_entry, description)

    await switch.async_turn_on()

    mock_coordinator.api.get_params.assert_not_called()
    mock_coordinator.async_force_refresh.assert_called_once()
