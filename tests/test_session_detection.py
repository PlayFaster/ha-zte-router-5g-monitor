"""How an expired session is told apart from a router with nothing to say.

This router never reports an ended session as an error. It answers `200 OK`
with the authenticated values echoed back blank, so the only defense is reading
the response correctly. Getting that wrong has now failed twice, both times the
same way, and both times silently:

  * `[3.3.0-dev12]` — the rule named batch-poll keys, so it could not fire on an
    SMS response, and an expired session read as an empty inbox.
  * `[3.3.2]` — the rule became "every value is blank", which is a property of
    *what was requested* rather than of the session. Adding `imei`,
    `model_name` and `wa_inner_version` to the core batch made it permanently
    false: a dead session was scored a clean success, every entity published
    `unknown`, and nothing re-authenticated. Measured on hardware 2026-07-31,
    a dead session left 3 of 80 core keys populated and 2 of 36 extended.

Both escaped because the rule's validity depended on the request's composition
and nothing asserted that dependency. So the load-bearing test here is not any
single classification — it is `test_every_batch_carries_both_classes`, which
fails the moment a batch edit makes the rule undecidable again.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.api import (
    _CORE_PARAMS,
    _EXTENDED_PARAMS,
    _UNAUTHENTICATED_KEYS,
    ZTEAuthError,
    ZTEConnectionError,
    ZTECredentialsError,
    ZTERouterAPI,
    _classify_session,
)
from custom_components.zte_router_5g.const import DOMAIN
from custom_components.zte_router_5g.coordinator import (
    CORE_KEYS,
    ZTERouterDataUpdateCoordinator,
)

from .conftest import MockResponse

# What the router actually returned on 2026-07-31 with an invalidated stok:
# every authenticated key blank, the three unauthenticated ones intact.
DEAD_SESSION_CORE = {
    "imei": "864155042229309",
    "model_name": "MC7010",
    "wa_inner_version": "IRL_H3G_MC7010DV1.0.0B03",
    "network_type": "",
    "signalbar": "",
    "wan_connect_status": "",
    "realtime_time": "",
    "lte_rsrp": "",
}


# ---------------------------------------------------------------------------
# The invariant the rule depends on
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "params"),
    [("core", _CORE_PARAMS), ("extended", _EXTENDED_PARAMS)],
)
def test_every_batch_carries_both_classes(name: str, params: list[str]) -> None:
    """Each batch must contain keys of both classes, or the rule is undecidable.

    This is the test that stops the bug recurring, and it is worth being
    precise about why. `_classify_session` distinguishes "no session" from
    "nothing to report" by comparing two groups of key. A batch containing only
    authenticated keys cannot tell those apart; a batch containing only
    unauthenticated ones can never look expired at all — which is exactly the
    state the core batch drifted into.

    If this fails after a batch edit, do not delete the assertion. Either keep
    a key of the missing class in the batch, or change `_classify_session` to
    stop claiming a distinction it can no longer make.
    """
    unauthenticated = _UNAUTHENTICATED_KEYS & set(params)
    authenticated = set(params) - _UNAUTHENTICATED_KEYS

    assert unauthenticated, (
        f"the {name} batch has no unauthenticated key, so an expired session "
        f"is indistinguishable from a router that is still starting up"
    )
    assert authenticated, (
        f"the {name} batch has only unauthenticated keys, so it can never "
        f"look expired — the {name} poll would never renew its session"
    )


def test_contract_keys_all_require_a_session() -> None:
    """No drift key may answer without a session.

    `wa_inner_version` sat in `CORE_KEYS` and answers unauthenticated, so
    `present` was never empty, the strike counter reset every cycle, and the
    drift check could not fire under any circumstances — including on the
    firmware change it exists to catch.
    """
    offenders = _UNAUTHENTICATED_KEYS & set(CORE_KEYS)
    assert not offenders, (
        f"{sorted(offenders)} answer without a session, so they are always "
        f"populated and silently disable the contract-drift check"
    )


def test_unauthenticated_keys_are_actually_requested() -> None:
    """A key in the list that nothing asks for is dead weight and misleading."""
    requested = set(_CORE_PARAMS) | set(_EXTENDED_PARAMS)
    assert requested >= _UNAUTHENTICATED_KEYS


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_dead_session_is_recognised_despite_populated_identity_keys() -> None:
    """The exact regression: a payload that used to be scored a success."""
    assert _classify_session(DEAD_SESSION_CORE) == "expired"

    # And the rule it replaced would still get this wrong, which is the point.
    assert not all(v == "" for v in DEAD_SESSION_CORE.values())


def test_a_working_session_is_left_alone() -> None:
    """One populated authenticated key is enough to prove the session works."""
    assert _classify_session({**DEAD_SESSION_CORE, "signalbar": "4"}) == "live"


def test_a_wholly_blank_response_is_not_ready_rather_than_expired() -> None:
    """A booting router must not be mistaken for an expired session.

    Everything blank, unauthenticated keys included, means the router is
    answering but has nothing to report. Re-logging in would not help, so this
    has to take the reachability path and hold last known values instead.
    """
    blank = dict.fromkeys(DEAD_SESSION_CORE, "")
    assert _classify_session(blank) == "not_ready"


def test_a_response_without_unauthenticated_keys_is_undecidable() -> None:
    """SMS responses carry no unauthenticated key, so the older rule applies."""
    assert _classify_session({"sms_capacity_info": ""}) == "undecidable"
    assert _classify_session({}) == "undecidable"


def test_a_response_of_only_unauthenticated_keys_is_undecidable() -> None:
    """Nothing authenticated was asked for, so nothing is proven either way."""
    assert _classify_session({"imei": "864155042229309"}) == "undecidable"


# ---------------------------------------------------------------------------
# The behavior those classifications drive
# ---------------------------------------------------------------------------


async def test_expired_session_triggers_a_relogin(mock_aiohttp_client) -> None:
    """The recovery path already existed; it was simply never reached."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=dead"
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data=DEAD_SESSION_CORE),
        MockResponse(json_data={**DEAD_SESSION_CORE, "signalbar": "4"}),
    ]

    with patch.object(api, "login", AsyncMock(return_value="stok=fresh")) as login:
        result = await api.get_all_data()

    assert login.await_count == 1
    assert result["signalbar"] == "4"


async def test_a_booting_router_raises_connection_not_auth(
    mock_aiohttp_client,
) -> None:
    """`not_ready` must not burn a re-login, and must not look like bad auth."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.stok = "stok=live"
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data=dict.fromkeys(DEAD_SESSION_CORE, "")
    )

    with (
        patch.object(api, "login", AsyncMock()) as login,
        pytest.raises(ZTEConnectionError, match="still starting up"),
    ):
        await api.get_all_data()

    assert login.await_count == 0


async def test_missing_password_is_a_credentials_error(mock_aiohttp_client) -> None:
    """Only a credentials fault may reach the reauth prompt."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "")
    with (
        patch.object(api, "get_ld", AsyncMock(return_value="ABC")),
        patch.object(api, "get_version", AsyncMock(return_value="MC7010")),
        pytest.raises(ZTECredentialsError),
    ):
        await api.login()


async def test_rejected_password_is_a_credentials_error(mock_aiohttp_client) -> None:
    """A router that rejects the password raises the narrower subclass.

    `ZTECredentialsError` derives from `ZTEAuthError`, so every existing
    handler still catches it; only the coordinator looks for the distinction.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "wrong")
    rejection = MagicMock(stok=None, auth_error="password rejected", conn_error=None)

    with (
        patch.object(api, "get_ld", AsyncMock(return_value="ABC")),
        patch.object(api, "get_version", AsyncMock(return_value="MC7010")),
        patch.object(api, "_attempt_login", AsyncMock(return_value=rejection)),
        pytest.raises(ZTECredentialsError) as excinfo,
    ):
        await api.login()

    assert isinstance(excinfo.value, ZTEAuthError)


# ---------------------------------------------------------------------------
# Coordinator: which failure earns a reauth prompt
# ---------------------------------------------------------------------------


@pytest.fixture
def coordinator(hass):
    """Return a coordinator with a mocked API and one good poll behind it."""
    entry = MockConfigEntry(
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
    entry.add_to_hass(hass)
    api = MagicMock(spec=ZTERouterAPI)
    api.login = AsyncMock()
    return ZTERouterDataUpdateCoordinator(hass, entry, api)


async def test_credentials_rejection_asks_the_user_to_reauthenticate(
    coordinator,
) -> None:
    """A wrong password is the user's to fix, so the prompt is right."""
    coordinator.data = {"signalbar": "4"}
    coordinator.consecutive_failures = 99
    coordinator.api.get_all_data = AsyncMock(side_effect=ZTECredentialsError("bad"))
    coordinator.api.login = AsyncMock(side_effect=ZTECredentialsError("bad"))

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_a_lapsed_session_does_not_ask_the_user_to_reauthenticate(
    coordinator,
) -> None:
    """The regression this split exists to prevent.

    A session that merely lapsed is the integration's problem, and re-login has
    already been tried. Raising `ConfigEntryAuthFailed` here would tell the user
    their credentials were wrong when they were not, and re-entering the same
    password would change nothing.
    """
    coordinator.data = {"signalbar": "4"}
    coordinator.consecutive_failures = 99
    coordinator.api.get_all_data = AsyncMock(side_effect=ZTEAuthError("expired"))
    coordinator.api.login = AsyncMock()

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_drift_can_now_fire(coordinator) -> None:
    """The check was inert while an unauthenticated key sat in CORE_KEYS.

    A response carrying only that key resolved `present` to something truthy,
    which reset the strike counter every cycle. With the key removed, the same
    response is correctly seen as resolving none of the contract.
    """
    coordinator._drift_baseline = {"network_type", "signalbar"}
    drifted = {"wa_inner_version": "IRL_H3G_MC7010DV1.0.0B03", "unexpected": "1"}

    verdicts = [coordinator._check_contract_drift(drifted) for _ in range(3)]

    # Pin the whole sequence, not just the firing edge. Asserting only the last
    # verdict leaves the persistence requirement unguarded: `>= 1`, `> 0` and
    # `>= FETCH_STRIKE_LIMIT - 2` all satisfy it, and under any of them a
    # WARNING-severity, non-fixable Repair appears on the *first* odd response
    # — the false-alarm class a Repair's "persistence plus agency" bar exists
    # to prevent, on a router that demonstrably produces odd single responses.
    assert verdicts == [False, False, True], (
        "drift must require FETCH_STRIKE_LIMIT consecutive bad polls, not one"
    )
