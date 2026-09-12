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
    _SESSION_CHECK_KEYS,
    _UNAUTHENTICATED_KEYS,
    ZTEAuthError,
    ZTEConnectionError,
    ZTECredentialsError,
    ZTERouterAPI,
    _classify_session,
    _is_classifiable,
)
from custom_components.zte_router_5g.const import DOMAIN
from custom_components.zte_router_5g.coordinator import (
    CORE_KEYS,
    ZTERouterDataUpdateCoordinator,
)

from .conftest import MockResponse


# What the router actually returned on 2026-07-31 with an invalidated stok:
# every authenticated key blank, the three unauthenticated ones intact.
def _full_core_response(populated: dict[str, str] | None = None) -> dict[str, str]:
    """Build a response carrying every core key, blank unless named.

    The router answers a batch read with every key it was asked for, whether
    or not the session is alive; only the values change. Tests that reach
    `_request` need that shape, because the session classifier now weighs how
    much of the request came back.
    """
    response = dict.fromkeys(_CORE_PARAMS, "")
    response.update(
        {
            "imei": "864155042229309",
            "model_name": "MC7010",
            "wa_inner_version": "xx_xxx_MC7010DV1.0.0B03",
        }
    )
    if populated:
        response.update(populated)
    return response


DEAD_SESSION_CORE = {
    "imei": "864155042229309",
    "model_name": "MC7010",
    "wa_inner_version": "xx_xxx_MC7010DV1.0.0B03",
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
def test_at_least_one_chunk_per_batch_can_be_classified(
    name: str, params: list[str], mock_aiohttp_client
) -> None:
    """A batch that draws no verdict at all cannot detect a dead session.

    `_batch_get` classifies a chunk only when it holds both classes of key,
    because a chunk of only authenticated names answers every one empty on a
    device that does not support them — the shape of an expired session.
    Measured when the MC888 aliases created a second core chunk of ten names
    the reference MC7010 leaves blank: every poll was scored expired and
    returned nothing. Skipping that chunk is right; skipping every chunk is
    not.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    chunks = api._split_by_url_budget(list(params))
    classifiable = [
        c
        for c in chunks
        if (_UNAUTHENTICATED_KEYS & set(c)) and (set(c) - _UNAUTHENTICATED_KEYS)
    ]

    assert classifiable, (
        f"no {name} chunk holds both classes, so this batch can never detect "
        f"an expired session"
    )


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
    api.cookies = {"stok": "dead"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    # The full batch, not an abbreviation. A dead session on this API echoes
    # every requested key back — measured on MC7010 firmware
    # `xx_xxx_MC7010DV1.0.0B03` on 2026-08-30, where a cookieless read
    # returned 80 of 80 core keys with none absent. An eight-key stand-in is
    # a shape the router does not produce, and the classifier now declines to
    # rule on a response that dropped most of its request.
    dead_full = _full_core_response()
    # A response per request rather than a fixed pair: the core list is served
    # in as many requests as the URL budget allows, so counting them here
    # would pin the test to today's key count.
    calls = {"n": 0}

    def _dead_then_live(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return MockResponse(json_data=dead_full)
        return MockResponse(json_data={**dead_full, "signalbar": "4"})

    mock_aiohttp_client.get.side_effect = _dead_then_live

    with patch.object(api, "login", AsyncMock(return_value="stok=fresh")) as login:
        result = await api.get_all_data()

    assert login.await_count == 1
    assert result["signalbar"] == "4"


async def test_a_booting_router_raises_connection_not_auth(
    mock_aiohttp_client,
) -> None:
    """`not_ready` must not burn a re-login, and must not look like bad auth."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data=dict.fromkeys(_full_core_response(), "")
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
    drifted = {"wa_inner_version": "xx_xxx_MC7010DV1.0.0B03", "unexpected": "1"}

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


# ---------------------------------------------------------------------------
# Which requests a session verdict may be drawn from
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("chunk", "expected", "why"),
    [
        (["wan_connect_status", "ODU_led_switch"], True, "carries a sentinel"),
        (["ODU_led_switch", "imei"], True, "carries an unauthenticated key"),
        (
            ["network_lte_rsrp", "flux_clear_date"],
            False,
            "neither, so empty means unsupported as readily as expired",
        ),
        (["imei", "model_name"], False, "only unauthenticated, never looks expired"),
    ],
)
def test_a_verdict_is_only_drawn_where_it_could_mean_something(
    chunk: list[str], expected: bool, why: str
) -> None:
    """A request with neither a sentinel nor an unauthenticated key is mute.

    Every name in it comes back empty both when the session is gone and when
    the firmware does not support those names, so a verdict drawn on it is a
    coin toss reported as a fact. Measured on the reference MC7010 once the
    MC888 aliases pushed the core list into two requests: the second chunk
    held ten names that device leaves blank, every poll scored expired, and
    the poll returned nothing at all.
    """
    assert _is_classifiable(chunk, _UNAUTHENTICATED_KEYS) is expected, why


# ---------------------------------------------------------------------------
# The pre-write session check, and why it reads three keys
# ---------------------------------------------------------------------------


def _check_response(**values: str) -> dict[str, str]:
    """A session-check answer, every key present, blank unless named."""
    return {key: values.get(key, "") for key in _SESSION_CHECK_KEYS}


async def test_the_session_check_reads_every_key_it_classifies_on(
    mock_aiohttp_client,
) -> None:
    """A one-key check cannot be classified, and fell through to the weak rule.

    `_classify_session` needs an unauthenticated key alongside an
    authenticated one to rule at all. A lone `wan_connect_status` supplies
    neither pairing, so the verdict was `undecidable` and the caller fell back
    to "every value is empty, so the session is gone" — permanently true on a
    device that never populates that key.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    seen: dict[str, object] = {}

    async def record(_method, path, **kwargs):
        seen["path"] = path
        seen["requested"] = kwargs.get("requested")
        return _check_response(ppp_status="ppp_connected")

    with patch.object(api, "_request", side_effect=record):
        await api._ensure_session()

    # Before a poll there is no evidence about this device, so the seeded
    # names stand — less any the constant already knows answer without a
    # session, which prove nothing and were never witnesses.
    witnesses = api.session_witnesses()
    assert witnesses == [
        k for k in _SESSION_CHECK_KEYS if k not in _UNAUTHENTICATED_KEYS
    ]
    for key in witnesses:
        assert key in str(seen["path"])
    # A companion key that answers without a session travels with them, or
    # `_classify_session` has only one class to look at and cannot rule.
    requested = seen["requested"]
    assert set(witnesses) <= set(requested)
    assert set(requested) & _UNAUTHENTICATED_KEYS, (
        "the check carries no unauthenticated key, so its verdict is undecidable"
    )


@pytest.mark.asyncio
async def test_a_write_is_not_blocked_when_no_key_can_witness_the_session(
    mock_aiohttp_client,
) -> None:
    """The MC888 Pro of issue #56, exactly as its download records it.

    `ppp_status` and `model_name` are served without a session there, so
    neither proves one, and `wan_connect_status` — the only seeded name left —
    is blank at all times. Once that device's sessionless set was measured
    rather than assumed, the check had no witness and scored every write as an
    expired session. Three writes were reported failed against an empty
    `write_failures`, because none of them was ever sent.

    A device whose session cannot be judged from a read is not a device whose
    writes should be blocked.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.unauthenticated_keys = frozenset(
        {"ppp_status", "model_name", "network_type", "wa_inner_version", "imei"}
    )
    # What his poll returns: the seeded witness blank, the populated ones all
    # served without a session.
    api._populated_keys = frozenset({"ppp_status", "model_name", "network_type"})

    called = False

    async def record(*_args, **_kwargs):
        nonlocal called
        called = True
        return {}

    with patch.object(api, "_request", side_effect=record):
        await api._ensure_session()

    assert api.session_witnesses() == []
    assert not called, "a write was blocked on a device that cannot witness itself"
    assert api.last_session_check["verdict"].startswith("no witness")


@pytest.mark.parametrize(
    ("answer", "expected", "why"),
    [
        (
            _check_response(
                wan_connect_status="pdp_connected",
                ppp_status="ppp_connected",
                model_name="MC7010",
            ),
            "live",
            "the reference device, session alive",
        ),
        (
            _check_response(ppp_status="ppp_connected", model_name="MC888 Pro"),
            "live",
            "the MC888 Pro of issue #56, whose wan_connect_status is always blank",
        ),
        (
            _check_response(model_name="MC7010"),
            "expired",
            "authenticated keys blank while the router plainly answers",
        ),
        (
            _check_response(),
            "not_ready",
            "everything blank, which is a router still starting up",
        ),
    ],
)
def test_the_session_check_keys_classify_each_state(
    answer: dict[str, str], expected: str, why: str
) -> None:
    """The three states this check has to separate, on both known devices.

    The second case is the fault in issue #56. `wan_connect_status` is blank
    at all times on that firmware, so the live session it was reporting on had
    to be recognized from another key or every write would be refused before
    it was sent.
    """
    verdict = _classify_session(answer, list(_SESSION_CHECK_KEYS))

    assert verdict == expected, why


def test_the_third_key_cannot_vote_a_dead_session_alive() -> None:
    """`model_name` is unauthenticated, which is the property being relied on.

    `modem_main_state` was the first choice and is wrong twice over. On the
    reference MC7010 a dead session answered it `modem_init_complete`, and
    because the constant classifies it as authenticated that populated value
    scores `live` — a dead session reported healthy, which is worse than the
    fault being fixed. On the MC888 Pro it came back blank, so it would not
    have helped there either.
    """
    assert set(_SESSION_CHECK_KEYS) & _UNAUTHENTICATED_KEYS == {"model_name"}

    masked = {
        "wan_connect_status": "",
        "ppp_status": "",
        "modem_main_state": "modem_init_complete",
    }
    assert _classify_session(masked, list(masked)) == "live"

    same_state_with_the_chosen_key = _check_response(model_name="MC7010")
    assert (
        _classify_session(same_state_with_the_chosen_key, list(_SESSION_CHECK_KEYS))
        == "expired"
    )


def test_witnesses_are_spread_across_name_families() -> None:
    """Three readings of one subsystem are one witness, not three.

    Alphabetical ordering over the MC888 Pro's populated keys selects
    `APN_config0`, `APN_config1` and `APN_config2` — values that blank
    together or not at all. Independent failure is the whole point of taking
    three, so a key from another family is preferred over a second from the
    same one.
    """
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    api.unauthenticated_keys = frozenset()
    api._populated_keys = frozenset(
        {"APN_config0", "APN_config1", "APN_config2", "network_type", "sms_unread_num"}
    )

    witnesses = api.session_witnesses()

    assert len(witnesses) == 3
    assert (
        len({k.split("_", 1)[0].rstrip("0123456789").lower() for k in witnesses}) == 3
    )


def test_one_family_still_yields_witnesses() -> None:
    """Preference, not exclusion: a device with a single family is not starved."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    api.unauthenticated_keys = frozenset()
    api._populated_keys = frozenset({"APN_config0", "APN_config1", "APN_config2"})

    assert len(api.session_witnesses()) == 3


@pytest.mark.asyncio
async def test_a_refusal_is_undecidable_when_no_key_can_witness(
    mock_aiohttp_client,
) -> None:
    """No witness means no verdict — and no read taken to pretend otherwise.

    The counterpart of the pre-write case: a device that cannot prove its own
    session must not have a refusal reclassified as an expiry on no evidence.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.unauthenticated_keys = frozenset({"ppp_status", "model_name"})
    api._populated_keys = frozenset({"ppp_status", "model_name"})

    with patch.object(api, "_request", new=AsyncMock()) as request:
        verdict = await api.note_write_refusal("DELETE_SMS")

    assert verdict == "undecidable"
    assert not request.called
    assert api.last_session_check["verdict"] == "undecidable after refusal"


@pytest.mark.asyncio
async def test_a_refusal_on_a_dead_session_asks_for_reauthentication(
    mock_aiohttp_client,
) -> None:
    """A refusal the read proves was an expiry is raised as an auth error.

    Home Assistant starts a reauthentication flow for `ZTEAuthError` and
    reports anything else as a failed command. A write refused because the
    session had gone is the first of those, not the second.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.unauthenticated_keys = frozenset({"model_name"})
    api._populated_keys = frozenset({"wan_connect_status", "model_name"})

    # Every authenticated key blank while the unauthenticated one answers:
    # the shape of a session the router has dropped.
    answer = {"wan_connect_status": "", "model_name": "MC7010"}

    with (
        patch.object(api, "_request", new=AsyncMock(return_value=answer)),
        pytest.raises(ZTEAuthError),
    ):
        await api.note_write_refusal("DELETE_SMS")

    assert api.last_session_check["verdict"] == "expired"
