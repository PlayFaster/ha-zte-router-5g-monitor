"""Polls driven through a real HTTP seam rather than an API-object mock.

Chore C-021 and the `fault_injection_options.md` adoption. Every test here runs
`api.py` for real over `aioclient_mock`: the payload is the input and everything
the integration reads off it is derived, which is the difference between testing
the check and testing the fixture that fed it.

`test_the_login_bootstrap_completes` comes first deliberately. The login chain
is the only part of this router's protocol a fake can get wrong in a way that
makes every other test here fail at once, so it is proved on its own before
anything is built on it.
"""

from __future__ import annotations

import contextlib

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.const import (
    DOMAIN,
    FETCH_STRIKE_LIMIT,
    HEALTH_DRIFT_STRIKE_LIMIT,
    REPAIR_AUTH_FAILED,
    REPAIR_CONN_ERROR,
    UNREACHABLE_STRIKE_LIMIT,
)
from custom_components.zte_router_5g.coordinator import (
    DRIFT_CONTRACT,
    ZTERouterDataUpdateCoordinator,
)

from .transport import GOOD_PAYLOAD, HOST, RouterFake, real_api


@pytest.fixture
def entry():
    """Return a config entry pointed at the fake router."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="864155042229309",
        title="ZTE 5G",
        data={"imei": "864155042229309"},
        options={
            CONF_HOST: HOST,
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "password",
        },
    )


@pytest.fixture
def router(aioclient_mock):
    """Return the fake router, armed with a good payload."""
    fake = RouterFake(aioclient_mock)
    fake.serve()
    return fake


@pytest.fixture
def coordinator(hass: HomeAssistant, entry, router):
    """Return a coordinator over the **real** API and the fake transport."""
    entry.add_to_hass(hass)
    return ZTERouterDataUpdateCoordinator(hass, entry, real_api(hass))


async def _failing_poll(coordinator, times: int) -> None:
    """Drive `times` failing cycles, tolerating the hold window.

    Section 8 holds the last known values for the first `FETCH_STRIKE_LIMIT`
    failures and returns them rather than raising, so a loop that expects
    `UpdateFailed` from the first cycle is asserting the wrong contract.
    """
    for _ in range(times):
        with contextlib.suppress(UpdateFailed, ConfigEntryAuthFailed):
            await coordinator._async_update_data()


async def _drive_until_it_gives_up(coordinator, times: int):
    """Absorb the hold window, then return the exception the next poll raises.

    Keeps the `pytest.raises` block to the single call that actually fails,
    which is what lets the assertion be about *which* failure it was.
    """
    await _failing_poll(coordinator, times)
    try:
        await coordinator._async_update_data()
    except Exception as err:  # noqa: BLE001 - the test asserts the type below
        return err
    return None


async def _poll(coordinator) -> None:
    """Drive one cycle, carrying `data` forward as the wrapper would.

    `_async_update_data` is called directly here, so the `DataUpdateCoordinator`
    wrapper that normally assigns `data` is not in play. Without this the next
    cycle takes the cold-start path and the strike budgets never accumulate.
    """
    coordinator.data = await coordinator._async_update_data()


# ------------------------------------------------------------- the bootstrap


async def test_the_login_bootstrap_completes(hass: HomeAssistant, router) -> None:
    """`login()` must obtain a session from the fake before anything else can.

    The chain is four calls: `LD`, `wa_inner_version`, the login POST, then one
    more `wa_inner_version` to activate the session. The session token arrives
    as a **cookie** — a fake returning a success-shaped body and no cookie
    fails here in exactly the way a wrong password does, which is the mistake
    this test exists to catch early.
    """
    api = real_api(hass)

    stok = await api.login()

    assert stok == "stok=s1"
    assert api.stok == "stok=s1"


async def test_a_poll_derives_its_values_from_the_wire(coordinator) -> None:
    """The payload is the input; `api.py` runs for real on the way through."""
    await _poll(coordinator)

    assert coordinator.data["network_type"] == "ENDC"
    assert coordinator.data["model_name"] == "MC7010"
    assert coordinator.last_update_success_time is not None


# -------------------------------------------------- the declared outcomes


async def test_conn_error_is_driven_through_a_real_poll(
    hass: HomeAssistant, coordinator, router
) -> None:
    """`conn_error` — one of two declared outcomes — end to end.

    Asserts the repair key rather than merely that a repair exists, so the test
    cannot pass when the wrong card fires.
    """
    await _poll(coordinator)
    router.fault("unreachable")

    await _failing_poll(coordinator, UNREACHABLE_STRIKE_LIMIT)

    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, coordinator._repair_ids[REPAIR_CONN_ERROR]
    )
    assert issue is not None
    assert issue.translation_key == REPAIR_CONN_ERROR


async def test_auth_failed_is_driven_through_a_real_poll(
    hass: HomeAssistant, coordinator, router
) -> None:
    """`auth_failed` — the other declared outcome — end to end.

    The rejection is served as the router serves it: a login POST with no
    `stok` cookie and a `result` the API classifies as a credentials problem.
    Nothing in this test names `ZTECredentialsError`; the exception is derived
    from the wire response, which is the point.
    """
    await _poll(coordinator)
    router.fault("credentials_rejected")

    await _failing_poll(coordinator, FETCH_STRIKE_LIMIT + 1)

    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, coordinator._repair_ids[REPAIR_AUTH_FAILED]
    )
    assert issue is not None
    assert issue.translation_key == REPAIR_AUTH_FAILED
    assert issue.is_fixable is True


# ------------------------------------------------------------- fault injection


async def test_a_router_that_stops_answering_holds_last_known_values(
    coordinator, router
) -> None:
    """Section 8: entities hold their values for the strike budget, then drop."""
    await _poll(coordinator)
    assert coordinator.data["network_type"] == "ENDC"

    router.fault("unreachable")
    for _ in range(FETCH_STRIKE_LIMIT):
        coordinator.data = await coordinator._async_update_data()

    assert coordinator.data["network_type"] == "ENDC", "should still hold"

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_a_slow_router_is_a_timeout_not_a_refusal(coordinator, router) -> None:
    """A timeout and a refused connection are different failures.

    Both end in `UpdateFailed`, but they arrive on different branches, and a
    fake that served only one would leave the other undriven — the defect
    `huawei_router_5g` found on its own `conn_error` path.
    """
    await _poll(coordinator)
    router.fault("timeout")

    await _failing_poll(coordinator, FETCH_STRIKE_LIMIT + 1)

    assert coordinator.health_snapshot["problem"] is True


async def test_an_expired_session_is_told_apart_from_a_router_still_booting(
    coordinator, router
) -> None:
    """Two near-identical payloads that must produce opposite responses.

    Both are `200 OK` with the authenticated values blank. The difference is
    whether an **unauthenticated** key still carries a value: if it does, the
    router is plainly answering and the blankness is the session, so re-login
    is right. If everything is blank the router is still starting up, and
    logging in again would burn a re-login and then prompt the user for
    credentials that were never wrong.

    Only reachable through the transport — the rule is applied inside `api.py`
    against the response body, so an API-object mock cannot exercise it at all.
    The assertion is on the **message**, not merely that something failed: any
    fault makes `problem` true, so that alone would pass for the wrong reason.
    """
    await _poll(coordinator)

    router.fault("not_ready")
    booting = await _drive_until_it_gives_up(coordinator, FETCH_STRIKE_LIMIT)
    assert isinstance(booting, UpdateFailed)
    assert "still starting up" in str(booting)

    router.fault("expired_session")
    expired = await _drive_until_it_gives_up(coordinator, 0)
    assert isinstance(expired, UpdateFailed)
    assert "still starting up" not in str(expired)


async def test_contract_drift_is_derived_from_a_real_payload(
    coordinator, router
) -> None:
    """Drift computed from the wire, not from a fixture that set the flag."""
    await _poll(coordinator)
    router.fault("contract_drift")

    for _ in range(HEALTH_DRIFT_STRIKE_LIMIT):
        await _poll(coordinator)

    assert coordinator.health_snapshot["drift"] == [DRIFT_CONTRACT]
    assert coordinator.health_snapshot["severity"] == "warning"


async def test_an_html_page_is_not_mistaken_for_a_payload(coordinator, router) -> None:
    """A login page served where JSON was expected must not parse as data."""
    await _poll(coordinator)
    router.fault("html_page")

    err = await _drive_until_it_gives_up(coordinator, FETCH_STRIKE_LIMIT)

    assert isinstance(err, UpdateFailed)
    assert "HTML" in str(err), (
        "an HTML body must be recognised as such, not parsed as a payload"
    )
    assert coordinator.data["network_type"] == GOOD_PAYLOAD["network_type"]


async def test_recovery_clears_the_verdict_in_the_same_cycle(
    hass: HomeAssistant, coordinator, router
) -> None:
    """A router that comes back must clear the card on the next good poll."""
    await _poll(coordinator)
    router.fault("unreachable")
    await _failing_poll(coordinator, UNREACHABLE_STRIKE_LIMIT)
    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, coordinator._repair_ids[REPAIR_CONN_ERROR]
        )
        is not None
    )

    router.serve()
    await _poll(coordinator)

    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, coordinator._repair_ids[REPAIR_CONN_ERROR]
        )
        is None
    )
    assert coordinator.health_snapshot["problem"] is False


# ------------------------------------------------------- the config-flow seam


async def test_validate_credentials_runs_for_real_against_the_router(
    hass: HomeAssistant, router
) -> None:
    """`_validate_credentials` driven over the transport, not patched out.

    `Tests: Depth Check` reports this helper as a stubbed seam: `test_config_flow.py`
    patches it in every flow-branch test, so the mock sits exactly where a defect
    would. Those patches are legitimate — they select which branch the flow takes
    — but they mean nothing exercises the helper itself through a real login.
    This does.
    """
    from custom_components.zte_router_5g.config_flow import _validate_credentials

    info = await _validate_credentials(
        hass,
        {CONF_HOST: HOST, CONF_USERNAME: "admin", CONF_PASSWORD: "password"},
    )

    assert info["model"] == GOOD_PAYLOAD["model_name"]
    assert info["sw_version"] == GOOD_PAYLOAD["wa_inner_version"]


async def test_validate_credentials_surfaces_a_rejected_password(
    hass: HomeAssistant, router
) -> None:
    """A refused login must reach the flow as a credentials error.

    Derived from the wire: the fake serves a login POST with no `stok` cookie
    and a `result` the API classifies. Nothing here constructs the exception.
    """
    from custom_components.zte_router_5g.api import ZTECredentialsError
    from custom_components.zte_router_5g.config_flow import _validate_credentials

    router.serve(credentials_ok=False)

    with pytest.raises(ZTECredentialsError):
        await _validate_credentials(
            hass,
            {CONF_HOST: HOST, CONF_USERNAME: "admin", CONF_PASSWORD: "wrong"},
        )
