"""What each control reads at the instant it publishes, not afterwards.

Chore C-019 and `x_project/stubbed_publish_tests.md`. Every write test in this
project mocks `async_write_ha_state` with a bare `MagicMock`, which records that
a publish happened and nothing about what was published. A control that wrote
the new value and then published the old one passes all of them, because by the
time the assertion runs the state has settled either way.

The fix is a `side_effect` that captures the entity's own state at the moment
the publish fires. `tests/test_switch.py:40` and `tests/test_number.py:40` are
the two sites `Tests: Depth Check` reports; this module covers the three write
paths behind them.

**This integration is not believed to carry the defect** — the switch holds a
`_last_known` latch and the other two read from options — but nothing proved it.
Verified by inverting the publish and write order in each platform and
confirming these tests fail; that check is what makes them worth keeping.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.const import (
    CONF_SCAN_INTERVAL,
    CONF_STOP_POLLING,
    DOMAIN,
)
from custom_components.zte_router_5g.number import (
    POLLING_INTERVAL_DESCRIPTION,
    ZTEPollingInterval,
)
from custom_components.zte_router_5g.switch import (
    PAUSE_POLLING_DESCRIPTION,
    SWITCH_TYPES,
    ZTEPausePollingSwitch,
    ZTERouterSwitch,
)


@pytest.fixture
def entry():
    """Return a config entry with both live options set."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="864155042229309",
        title="ZTE 5G",
        data={"imei": "864155042229309"},
        options={
            CONF_HOST: "192.168.0.1",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "password",
            CONF_STOP_POLLING: False,
            CONF_SCAN_INTERVAL: 180,
        },
    )


@pytest.fixture
def coordinator(entry):
    """Return a coordinator stub that accepts the writes these controls make."""
    coord = MagicMock()
    coord.entry = entry
    coord.data = {}
    coord.async_force_refresh = AsyncMock()
    coord.last_update_success = True
    return coord


# ------------------------------------------------- the option-backed controls


@pytest.mark.parametrize("target", [True, False])
async def test_pause_polling_publishes_the_state_it_just_wrote(
    hass: HomeAssistant, entry, coordinator, target
) -> None:
    """The pause switch reads options, which must be written before publishing.

    Seeded to the opposite of `target` first: starting from the value under
    test would pass against a publish that sent the old one, which is the whole
    class of defect this guards.
    """
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_STOP_POLLING: not target}
    )

    switch = ZTEPausePollingSwitch(
        coordinator, entry, PAUSE_POLLING_DESCRIPTION, not target
    )
    switch.hass = hass
    switch.entity_id = "switch.pause_polling"

    published: list[bool] = []
    switch.async_write_ha_state = MagicMock(
        side_effect=lambda: published.append(switch.is_on)
    )

    if target:
        await switch.async_turn_on()
    else:
        await switch.async_turn_off()

    assert published == [target], (
        "the switch published the value it replaced, not the one it wrote"
    )


async def test_the_polling_interval_publishes_the_new_value(
    hass: HomeAssistant, entry, coordinator
) -> None:
    """The slider publishes immediately, before the debounced commit.

    That is deliberate — the UI must not lag two seconds behind the drag — so
    the value published has to be the new one even though nothing is persisted
    yet.
    """
    entry.add_to_hass(hass)
    number = ZTEPollingInterval(coordinator, entry, POLLING_INTERVAL_DESCRIPTION, 180)
    number.hass = hass
    number.entity_id = "number.polling_interval"

    published: list[float | None] = []
    number.async_write_ha_state = MagicMock(
        side_effect=lambda: published.append(number.native_value)
    )

    with patch("asyncio.sleep", AsyncMock()):
        await number.async_set_native_value(300)
        if number._refresh_task:
            await number._refresh_task

    assert published[0] == 300, "the slider published its old position"


# ----------------------------------------------------- the router-backed ones


@pytest.mark.parametrize("description", SWITCH_TYPES, ids=lambda d: d.key)
@pytest.mark.parametrize("target", [True, False])
async def test_every_router_switch_publishes_its_confirmed_position(
    hass: HomeAssistant, entry, coordinator, description, target
) -> None:
    """A router switch publishes the read-back value, not the requested one.

    The distinction matters on this API specifically: it answers `200 OK` for a
    refused write, so "what we asked for" and "what the router did" are
    genuinely different values. The latch is read at the publish moment here,
    with the router confirming `target`.
    """
    entry.add_to_hass(hass)

    # The descriptions are frozen dataclasses, so the writer is swapped by
    # building a copy rather than patching the class — a class-level patch is
    # shadowed by the instance field and silently does nothing.
    written: list[bool] = []

    async def _record(_api, state, _data):
        written.append(state)

    switch = ZTERouterSwitch(
        coordinator, entry, replace(description, setter_fn=_record)
    )
    switch.hass = hass
    switch.entity_id = f"switch.{description.key}"
    switch._last_known = not target

    # The router confirms the new position on read-back.
    coordinator.api.get_params = AsyncMock(
        return_value={description.state_key: "1" if target else "0"}
    )

    published: list[bool] = []
    switch.async_write_ha_state = MagicMock(
        side_effect=lambda: published.append(switch.is_on)
    )

    if target:
        await switch.async_turn_on()
    else:
        await switch.async_turn_off()

    assert written == [target], "the switch did not send the requested position"
    assert published, "the switch never published at all"
    assert published[-1] == target, (
        "the switch published a position the router had not confirmed"
    )
