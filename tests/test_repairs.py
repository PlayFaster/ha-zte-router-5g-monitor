"""Tests for the `auth_failed` repair and its fix flow.

The Repairs panel carries only `auth_failed` and `conn_error`, and
`auth_failed` is the one fixable repair this integration raises.

The sharp edge these tests guard is not that the flow works, but that it exists
at all. Home Assistant substitutes `ConfirmRepairFlow` for a fixable issue whose
integration ships no `repairs` platform, and that flow's Fix button shows an
empty confirm box and deletes the card — dismissing the problem while leaving
the credentials wrong. `test_the_fix_flow_is_ours_not_the_confirm_fallback` is
the test that fails if `repairs.py` is deleted or renamed.
"""

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.api import (
    ZTECredentialsError,
    ZTERouterAPI,
)
from custom_components.zte_router_5g.const import (
    DOMAIN,
    FETCH_STRIKE_LIMIT,
    REPAIR_AUTH_FAILED,
    REPAIR_CONN_ERROR,
)
from custom_components.zte_router_5g.coordinator import (
    RETIRED_REPAIR_NAMES,
    ZTERouterDataUpdateCoordinator,
)
from custom_components.zte_router_5g.repairs import (
    AuthFailedRepairFlow,
    async_create_fix_flow,
)

GOOD_DATA = {
    "network_type": "ENDC",
    "signalbar": "4",
    "realtime_time": "3600",
    "wan_connect_status": "ppp_connected",
}


@pytest.fixture
def entry():
    """Return a config entry with credentials in options."""
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
        },
    )


@pytest.fixture
def coordinator(hass: HomeAssistant, entry):
    """Return a coordinator over a mocked API."""
    entry.add_to_hass(hass)
    api = MagicMock(spec=ZTERouterAPI)
    api.get_all_data = AsyncMock(return_value=dict(GOOD_DATA))
    api.get_extended_data = AsyncMock(return_value={})
    api.get_sms_capacity = AsyncMock(return_value={})
    api.get_sms_messages = AsyncMock(return_value=[])
    api.login = AsyncMock(return_value="stok=test")
    return ZTERouterDataUpdateCoordinator(hass, entry, api)


# ---------------------------------------------------------------- The repair


async def test_rejected_credentials_raise_a_fixable_repair(
    hass: HomeAssistant, coordinator
) -> None:
    """Only a refused password earns a repair, and it must be fixable.

    `is_fixable=False` here would leave the user a card describing a problem
    with no route to correcting it, which is the state the alignment moved
    away from.
    """
    coordinator.api.get_all_data = AsyncMock(
        side_effect=ZTECredentialsError("password rejected")
    )

    # Held values absorb the first FETCH_STRIKE_LIMIT failures; the repair is
    # raised on the poll that gives up and asks for reauth.
    coordinator.data = dict(GOOD_DATA)
    for _ in range(FETCH_STRIKE_LIMIT + 1):
        with contextlib.suppress(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, coordinator._repair_ids[REPAIR_AUTH_FAILED]
    )
    assert issue is not None
    assert issue.is_fixable is True
    assert issue.is_persistent is True
    assert issue.translation_key == REPAIR_AUTH_FAILED
    # The flow reads the entry from here rather than parsing the issue id.
    assert issue.data == {"entry_id": coordinator.entry.entry_id}


async def test_the_auth_repair_is_listed_as_active_on_the_health_sensor(
    coordinator,
) -> None:
    """`repairs` on the health snapshot must name what the panel shows."""
    coordinator._set_auth_repair(True)

    assert REPAIR_AUTH_FAILED in coordinator._active_repairs(False)

    coordinator._unreachable_repair_raised = True
    assert coordinator._active_repairs(False) == [
        REPAIR_CONN_ERROR,
        REPAIR_AUTH_FAILED,
    ]


async def test_a_successful_poll_clears_the_auth_repair(
    hass: HomeAssistant, coordinator
) -> None:
    """Credentials that work again must take the card down."""
    coordinator._set_auth_repair(True)
    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, coordinator._repair_ids[REPAIR_AUTH_FAILED]
        )
        is not None
    )

    await coordinator._async_update_data()

    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, coordinator._repair_ids[REPAIR_AUTH_FAILED]
        )
        is None
    )


async def test_setting_the_same_auth_state_twice_is_a_no_op(coordinator) -> None:
    """The guard stops a repeated poll re-raising the card every cycle."""
    with patch(
        "custom_components.zte_router_5g.coordinator.ir.async_create_issue"
    ) as create:
        coordinator._set_auth_repair(True)
        coordinator._set_auth_repair(True)

    assert create.call_count == 1


# ------------------------------------------------------------- The migration


async def test_startup_clears_repairs_retired_by_the_alignment(
    hass: HomeAssistant, coordinator
) -> None:
    """A card raised before the upgrade must not outlive the code that raised it.

    This is the whole risk in retiring a repair. `ir.async_delete_issue` looks
    up by id, so once nothing raises `firmware_contract_drift` any card still
    showing under that id has no route out — it was `is_fixable=False`, so the
    user cannot dismiss it either. The entry-scoped form is the generation that
    would actually be live on an upgrading installation.
    """
    for name in RETIRED_REPAIR_NAMES:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{coordinator.entry.entry_id}_{name}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=name,
        )

    registry = ir.async_get(hass)
    assert len([k for k in registry.issues if k[0] == DOMAIN]) == 3

    coordinator.clear_legacy_repairs()

    assert [k for k in registry.issues if k[0] == DOMAIN] == []


# ----------------------------------------------------------------- The flow


async def test_the_fix_flow_is_ours_not_the_confirm_fallback(
    hass: HomeAssistant,
) -> None:
    """Without `repairs.py` HA substitutes a flow that dismisses the card.

    `ConfirmRepairFlow` deletes the issue on submit and touches nothing else,
    so the Fix button would resolve the symptom and leave the credentials
    rejected. Asserting the concrete type is what makes deleting this module a
    test failure rather than a silent downgrade.
    """
    flow = await async_create_fix_flow(hass, "abc_auth_failed", {"entry_id": "abc"})

    assert isinstance(flow, AuthFailedRepairFlow)


async def test_confirming_the_fix_starts_the_reauth_flow(
    hass: HomeAssistant, entry
) -> None:
    """The card promises re-entering credentials; the flow must deliver it."""
    entry.add_to_hass(hass)
    flow = AuthFailedRepairFlow(entry.entry_id)
    flow.hass = hass

    form = await flow.async_step_init()
    assert form["type"] == "form"
    assert form["step_id"] == "confirm"

    with patch.object(entry, "async_start_reauth") as start_reauth:
        result = await flow.async_step_confirm({})

    start_reauth.assert_called_once_with(hass)
    assert result["type"] == "create_entry"


async def test_the_flow_survives_an_entry_deleted_under_it(
    hass: HomeAssistant,
) -> None:
    """Deleting the integration while the card is open must not raise.

    The repair is `is_persistent`, so it outlives a restart and can still be
    sitting there after the entry it describes is gone.
    """
    flow = AuthFailedRepairFlow("an-entry-that-no-longer-exists")
    flow.hass = hass

    result = await flow.async_step_confirm({})

    assert result["type"] == "create_entry"
