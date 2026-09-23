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
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.api import (
    _CORE_PARAMS,
    _EXTENDED_PARAMS,
    _SESSION_CHECK_KEYS,
    _UNAUTHENTICATED_KEYS,
    SESSION_CONFIRMED,
    SESSION_DENIED,
    SESSION_UNANSWERED,
    SESSION_UNPROVEN,
    ZTEAuthError,
    ZTEConnectionError,
    ZTECredentialsError,
    ZTERouterAPI,
    _classify_session,
    _first_spelling,
    _is_classifiable,
)
from custom_components.zte_router_5g.const import DOMAIN
from custom_components.zte_router_5g.coordinator import (
    CORE_KEYS,
    ZTERouterDataUpdateCoordinator,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

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


def test_the_spellings_of_an_unauthenticated_concept_cannot_convict() -> None:
    """`get_version` reads three spellings of one unauthenticated key.

    A firmware implementing one of them answers the other two empty, which
    used to read as authenticated keys blank alongside a populated
    unauthenticated one — the shape of an expired session. The MC888 Pro of
    issue #56 recorded exactly that in its diagnostics download.
    """
    assert (
        _classify_session(
            {
                "wa_inner_version": "xx_xxxxMC888PROMODV1.0.0B01",
                "wa_version": "",
                "inner_version": "",
            },
        )
        == "undecidable"
    )


def test_widening_does_not_reach_a_concept_that_needs_a_session() -> None:
    """Only the spellings of keys already in the set are added.

    `RD` is read the same multi-spelling way and is not unauthenticated, so
    `rd` must stay an authenticated key rather than arrive by association.
    """
    assert _classify_session({"rd": "", "model_name": "MC7010"}) == "expired"


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
    # The device populates the seeded names. Stated rather than assumed:
    # since v3.3.22-dev3 an API object that has not polled has no witness at
    # all, and the check it would otherwise build is skipped.
    api._populated_keys = frozenset(_SESSION_CHECK_KEYS)
    seen: dict[str, object] = {}

    async def record(_method, path, **kwargs):
        seen["path"] = path
        seen["requested"] = kwargs.get("requested")
        return _check_response(ppp_status="ppp_connected")

    with patch.object(api, "_request", side_effect=record):
        await api._ensure_session()

    # The seeded names the device populates, less any the constant already
    # knows answer without a session — those prove nothing and were never
    # witnesses.
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

    # The device does not implement `loginfo` either, so the session flag
    # cannot rule and the witness fallback has nothing to work with. Both
    # answers are "cannot tell", and neither may stop the write.
    async def record(_method, path, **_kwargs):
        return {"loginfo": ""} if "loginfo" in str(path) else {}

    with patch.object(api, "_request", side_effect=record):
        await api._ensure_session()

    assert api.session_witnesses() == []
    assert api.last_session_check["verdict"] in {
        SESSION_DENIED,
        SESSION_UNANSWERED,
    } or api.last_session_check["verdict"].startswith("no witness")


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

    # `loginfo` is read first and this device does not answer it, so the
    # witness fallback runs and finds nothing to witness with.
    async def record(_method, path, **_kwargs):
        if "loginfo" in str(path):
            raise ZTEConnectionError("no such key")
        return {}

    with patch.object(api, "_request", side_effect=record):
        verdict = await api.note_write_refusal("DELETE_SMS")

    assert verdict == "undecidable"
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

    # This device has answered `loginfo: ok` before, so a blank answer
    # from it now means the session is gone rather than that the key is
    # unsupported. See `read_session_flag`.
    api._session_flag_seen_for = ""

    # The router itself says it is not logged in. That is the only evidence
    # that raises here: a witness verdict is recorded and returned, never
    # raised, because a witness pool the device answers empty has now produced
    # a wrong `expired` on a healthy session three times.
    with (
        patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": ""})),
        pytest.raises(ZTEAuthError),
    ):
        await api.note_write_refusal("DELETE_SMS")

    assert api.last_session_check["verdict"] == SESSION_DENIED


@pytest.mark.asyncio
async def test_a_witness_verdict_after_a_refusal_is_recorded_not_raised(
    mock_aiohttp_client,
) -> None:
    """The fallback path never reclassifies a refusal as an expiry.

    `note_write_refusal` carried the same defect as the pre-write check: it ran
    the same witness selection, so a pool the device answers empty turned a
    genuine command refusal into "the session is gone". Only a direct denial
    from the router raises now.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.unauthenticated_keys = frozenset({"model_name"})
    api._populated_keys = frozenset({"wan_connect_status", "model_name"})

    async def record(_method, path, **_kwargs):
        if "loginfo" in str(path):
            raise ZTEConnectionError("this device does not answer it")
        # The shape that used to raise: every authenticated key blank while
        # the unauthenticated one answers.
        return {"wan_connect_status": "", "model_name": "MC7010"}

    with patch.object(api, "_request", side_effect=record):
        verdict = await api.note_write_refusal("DELETE_SMS")

    assert verdict == "expired"
    assert api.last_session_check["verdict"] == "expired"


@pytest.mark.asyncio
async def test_an_unpolled_device_has_no_witness_and_is_not_blocked() -> None:
    """Before the first poll there is no evidence, so no check is made.

    Returning the seeded names instead reinstates the fault this mechanism
    was written for, in the window between a restart and the first completed
    poll: on the MC888 Pro the seeded set reduces to `wan_connect_status`,
    which is blank at all times there, so the check scores an expiry and
    blocks a write that would have been accepted.

    The pre-write check is an optimisation, not a gate. Skipping it costs at
    most one refused write, which `note_write_refusal` then classifies from
    the router's own answer.
    """
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    api.unauthenticated_keys = frozenset()
    # This device has answered `loginfo: ok` before, so a blank answer
    # from it now means the session is gone rather than that the key is
    # unsupported. See `read_session_flag`.
    api._session_flag_seen_for = ""

    assert api.session_witnesses() == []

    # One request is made — the session-flag read — and this device does not
    # answer it. The property under test is that nothing is blocked, not that
    # nothing is asked.
    async def record(*_args, **_kwargs):
        return {"loginfo": ""}

    with (
        patch.object(api, "_request", side_effect=record),
        patch.object(api, "login", new=AsyncMock()) as login,
    ):
        await api._ensure_session()

    # Not confirmed, a login was attempted, and still not confirmed — and the
    # write proceeds regardless. That is the property: the check informs, it
    # does not gate.
    assert login.called
    assert api.last_session_check["verdict"] == SESSION_DENIED


@pytest.mark.asyncio
async def test_a_refusal_is_undecidable_when_the_check_cannot_be_read(
    mock_aiohttp_client,
) -> None:
    """An unreadable check says nothing about the refusal it followed.

    The read is taken after the router has already answered, so it may fail
    for its own reasons. A refusal must keep its own error in that case, not
    be reclassified as an expiry on a read that never arrived.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.unauthenticated_keys = frozenset({"model_name"})
    api._populated_keys = frozenset({"wan_connect_status", "model_name"})

    with patch.object(
        api, "_request", new=AsyncMock(side_effect=ZTEConnectionError("unreachable"))
    ):
        verdict = await api.note_write_refusal("SEND_SMS")

    assert verdict == "undecidable"
    assert api.last_session_check["verdict"] == "unreadable after refusal"
    assert api.last_session_check["after"] == "SEND_SMS"


# ---------------------------------------------------------------------------
# The pre-write check may never fail a write.
#
# This is the property the whole mechanism was missing. `_ensure_session`
# contains no `raise` of its own — it raised through `_request`, one call away,
# which is why an AST sweep for `raise` sites could never see it and why five
# test files referenced the function without one asserting this.
#
# Reproduced on hardware 2026-09-14: witnesses `['5g_rsrp', 'APN_config1',
# '5g_sinr']` with `imei` populated alongside returned `expired` on a session
# seconds old, on a healthy MC7010, while `['network_type', 'signalbar',
# 'imei']` returned `live` against the same session at the same moment.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "why"),
    [
        ({"loginfo": ""}, "the router says it is not logged in"),
        ({"loginfo": "unknown-token"}, "an answer this integration cannot read"),
        ({}, "an empty response"),
        ({"other": "value"}, "a response that does not carry the flag at all"),
    ],
)
@pytest.mark.asyncio
async def test_the_pre_write_check_never_raises(
    mock_aiohttp_client, answer: dict[str, str], why: str
) -> None:
    """No answer to the session flag may stop a write being sent."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api._populated_keys = frozenset({"wan_connect_status", "model_name"})

    with (
        patch.object(api, "_request", new=AsyncMock(return_value=answer)),
        patch.object(api, "login", new=AsyncMock()),
    ):
        await api._ensure_session()

    assert api.last_session_check is not None, why


@pytest.mark.asyncio
async def test_the_pre_write_check_never_raises_when_the_read_fails(
    mock_aiohttp_client,
) -> None:
    """A check that cannot run must not decide anything."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api._populated_keys = frozenset({"wan_connect_status", "model_name"})

    with patch.object(
        api, "_request", new=AsyncMock(side_effect=ZTEConnectionError("unreachable"))
    ):
        await api._ensure_session()

    assert api.last_session_check is not None


@pytest.mark.asyncio
async def test_a_failed_relogin_does_not_fail_the_write(mock_aiohttp_client) -> None:
    """Even a login that raises leaves the write free to proceed.

    Reaching here means the router denied the session and signing in again did
    not work. The write is still sent: the router's own answer is better
    evidence than a refusal this integration invented, and the recorded verdict
    says what happened.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    # This device has answered `loginfo: ok` before, so a blank answer
    # from it now means the session is gone rather than that the key is
    # unsupported. See `read_session_flag`.
    api._session_flag_seen_for = ""

    with (
        patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": ""})),
        patch.object(api, "login", new=AsyncMock(side_effect=ZTEAuthError("refused"))),
    ):
        await api._ensure_session()

    assert api.last_session_check["verdict"] == SESSION_DENIED
    assert "ZTEAuthError" in api.last_session_check["relogin"]


@pytest.mark.asyncio
async def test_a_confirmed_flag_skips_the_witness_path(mock_aiohttp_client) -> None:
    """`ok` is the whole check. No witness selection, no classifier."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api._populated_keys = frozenset({"wan_connect_status", "model_name"})
    paths: list[str] = []

    async def record(_method, path, **_kwargs):
        paths.append(str(path))
        return {"loginfo": "ok"}

    with patch.object(api, "_request", side_effect=record):
        await api._ensure_session()

    assert len(paths) == 1, "a confirmed session was probed more than once"
    assert api.last_session_check["verdict"] == SESSION_CONFIRMED
    assert api.last_session_check["source"] == "session_flag"


@pytest.mark.asyncio
async def test_the_session_flag_read_is_never_classified(mock_aiohttp_client) -> None:
    """`classify=False`, or a device without the key logs in twice per write.

    `{"loginfo": ""}` is a non-empty payload with every value blank, which
    `_request` scores `undecidable` and then treats as an expiry: it re-logs in
    and replays before returning. The caller would then log in again. Two or
    more logins for every write, against `MAX_LOGIN_COUNT` and a 300-second
    lockout, on hardware nobody can test.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    seen: list[dict] = []

    async def record(_method, _path, **kwargs):
        seen.append(kwargs)
        return {"loginfo": "ok"}

    with patch.object(api, "_request", side_effect=record):
        await api.read_session_flag()

    assert seen[0]["classify"] is False
    assert seen[0]["_retry"] is False


@pytest.mark.asyncio
async def test_send_sms_is_the_only_write_blocked_on_a_denied_session(
    mock_aiohttp_client,
) -> None:
    """A send is not issued when the router says it is not logged in.

    Every other write is either verified after the fact or harmless to repeat.
    A send has neither property: reporting it as unverified invites the user to
    send it again, and this API gives no way to tell whether the first one went
    out. The error says the command was never issued, which is the one thing
    the user needs to know.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    # This device implements the key. Without that the state below is one the
    # code cannot produce — a denial is only ever recorded for a device known
    # to support the flag — and the block is deliberately keyed on the
    # capability rather than on the verdict alone. See item 110.
    api._session_flag_seen_for = ""
    api.last_session_check = {"source": "session_flag", "verdict": SESSION_DENIED}

    with pytest.raises(ZTEAuthError, match="was not sent"):
        api._require_confirmed_session("SEND_SMS")


@pytest.mark.parametrize(
    ("check", "why"),
    [
        (
            {"source": "session_flag", "verdict": SESSION_CONFIRMED},
            "the router confirmed the session",
        ),
        (
            {"source": "witnesses", "verdict": "expired"},
            "a witness verdict never blocks, however confident it sounds",
        ),
        (
            {"source": "witnesses", "verdict": "no witness available"},
            "a device that cannot witness itself is not a device to block",
        ),
        (None, "no check has run at all"),
    ],
)
def test_a_send_is_not_blocked_on_anything_but_a_direct_denial(
    mock_aiohttp_client, check: dict | None, why: str
) -> None:
    """Only the router's own denial stops a send."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    # On a device that implements the key, so that each case is decided on the
    # verdict rather than on the capability gate ahead of it. A device without
    # the key is never blocked at all, which is its own test.
    api._session_flag_seen_for = ""
    api.last_session_check = check

    # Returns None rather than raising. Asserted explicitly so the test states
    # its expectation instead of relying on the absence of an exception.
    assert api._require_confirmed_session("SEND_SMS") is None, why


@pytest.mark.asyncio
async def test_witnesses_are_derived_through_a_real_poll_sequence(
    mock_aiohttp_client,
) -> None:
    """Drive `_populated_keys` through a poll, not by assignment.

    Sixteen tests set `_populated_keys` directly and none derived it, so the
    replace-versus-accumulate behaviour never executed under test. `_batch_get`
    used to *replace* the set on every call, and the coordinator polls core then
    extended, so the extended poll wiped every core key.

    Measured on an MC7010, 2026-09-14: 60 keys after the core poll, 39 after
    the extended poll, and none of the 60 core names surviving. Witness
    selection was then forced onto extended-only names, which is how a
    per-antenna 5G reading became a session witness.

    Fixed by item 92 in v3.3.25-dev9. The earlier version of this test asserted
    the defect and failed the moment it was repaired, which is what brought the
    change here rather than letting it pass unnoticed.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    core_names = {"wan_connect_status", "ppp_status", "network_type", "signalbar"}
    extended_names = {"5g_rx0_rsrp", "5g_rx1_rsrp", "APN_config1"}

    async def poll(_method, path, **_kwargs):
        wanted = core_names if "signalbar" in str(path) else extended_names
        return dict.fromkeys(wanted, "value")

    with patch.object(api, "_request", side_effect=poll):
        await api._batch_get(sorted(core_names), starts_cycle=True)
        after_core = set(api._populated_keys)
        await api._batch_get(sorted(extended_names))
        after_extended = set(api._populated_keys)

    assert core_names <= after_core
    assert core_names <= after_extended, "the extended poll discarded the core keys"
    assert extended_names <= after_extended
    # The consequence, and the reason the item existed: witnesses are drawn
    # from what the device answered across the poll, not from its second half.
    assert set(api.session_witnesses()) & core_names


@pytest.mark.asyncio
async def test_a_blank_flag_is_not_a_denial_until_the_key_is_known_to_exist(
    mock_aiohttp_client,
) -> None:
    """The MC888 Pro's shape, and the reason no key list appears here.

    This API echoes a name it does not implement as an empty string, so a
    device without `loginfo` and a device whose session has gone answer the
    check identically. Reading it as a denial would put every write on such a
    device behind a login it does not need, and would block `SEND_SMS` on it
    outright — issue #56's shape in a new place.

    Resolving it by reading other keys alongside the flag was considered and
    rejected: which keys a device populates is exactly the judgement that has
    been wrong three times, and a mechanism that needs it is the mechanism
    being replaced.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    with patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": ""})):
        assert await api.read_session_flag() == SESSION_UNPROVEN

    # And once a login has been tried and the answer is still blank, the key is
    # absent — settled for this firmware, and no longer asked about.
    api._session_flag_absent_for = ""
    with patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": ""})):
        assert await api.read_session_flag() == SESSION_UNANSWERED


@pytest.mark.asyncio
async def test_a_blank_flag_is_a_denial_once_the_device_has_answered_ok(
    mock_aiohttp_client,
) -> None:
    """`ok`, seen once, is what makes a later blank mean something.

    Nothing else establishes that a device implements the key. The evidence is
    the device's own answer, taken at a moment the session provably worked.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    with patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": "ok"})):
        assert await api.read_session_flag() == SESSION_CONFIRMED

    with patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": ""})):
        assert await api.read_session_flag() == SESSION_DENIED


@pytest.mark.asyncio
async def test_the_learned_flag_survives_the_firmware_cache_filling(
    mock_aiohttp_client,
) -> None:
    """The defect that made the rule fire exactly once, then never again.

    `_ensure_session` runs ahead of the token derivation that populates
    `_cr_version_cache`, so the first `ok` on a fresh object is always recorded
    with no version beside it. Comparing that empty string against a version
    the cache acquired moments later discarded the proof on the same write.

    Found by attacking the rule, not by a test — which is why this one exists.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    assert api._cr_version_cache is None

    with patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": "ok"})):
        assert await api.read_session_flag() == SESSION_CONFIRMED

    # What `get_ad` does next, on the very same write.
    api._cr_version_cache = ("FIRMWARE_A", "")

    with patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": ""})):
        assert await api.read_session_flag() == SESSION_DENIED


@pytest.mark.asyncio
async def test_the_learned_flag_does_not_survive_a_firmware_change(
    mock_aiohttp_client,
) -> None:
    """An upgrade may withdraw the key, and a stale belief would deny wrongly.

    Held per firmware for the same reason `_cr_version_cache` is.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api._cr_version_cache = ("FIRMWARE_A", "")

    with patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": "ok"})):
        assert await api.read_session_flag() == SESSION_CONFIRMED

    api._cr_version_cache = ("FIRMWARE_B", "")
    with patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": ""})):
        # Back to unproven, not to a denial: the new firmware has answered
        # nothing yet, so the question is open again rather than settled.
        assert await api.read_session_flag() == SESSION_UNPROVEN


@pytest.mark.asyncio
async def test_the_flag_read_asks_for_one_key_and_no_witnesses(
    mock_aiohttp_client,
) -> None:
    """No key selection may enter the deciding path.

    An earlier revision sent the device's witnesses alongside the flag, to tell
    a dead session from a device without the key in one round trip. That put
    the selection this mechanism exists to remove back into the decision.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api._populated_keys = frozenset({"wan_connect_status", "model_name"})
    seen: list[dict] = []

    async def record(_method, _path, **kwargs):
        seen.append(kwargs)
        return {"loginfo": "ok"}

    with patch.object(api, "_request", side_effect=record):
        await api.read_session_flag()

    assert seen[0]["params"]["cmd"] == "loginfo"


# ---------------------------------------------------------------------------
# The first write after a restart. See phase 2.5, items 108 to 110.
#
# Every test below constructs its `ZTERouterAPI` and seeds nothing on it. That
# is the point: the fault these pin was invisible for as long as it was,
# because the tests that reached this state set `_session_flag_seen_for`
# first — the state the code handles rather than the state a restart produces.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_first_write_meeting_a_dead_session_logs_in(
    mock_aiohttp_client,
) -> None:
    """The reported fault, as a test.

    After a restart nothing has taught this device that it implements
    `loginfo`, because only a write reads the key and no write has happened.
    The session has expired meanwhile, the flag answers blank, and a blank
    answer on an unknown flag is not evidence of anything — but declining to
    act on it sends the write on a dead session, and the router refuses it.

    The counterpart of `test_an_unpolled_device_has_no_witness_and_is_not_
    blocked`, which is the same state with the flag seeded as known. Both are
    kept: each is a real state and the code must be correct in both.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.unauthenticated_keys = frozenset()

    assert api.session_witnesses() == [], "no poll has run, so there is no fallback"

    answers = [{"loginfo": ""}, {"loginfo": "ok"}]

    async def flag(*_args, **_kwargs):
        return answers.pop(0) if answers else {"loginfo": "ok"}

    with (
        patch.object(api, "_request", side_effect=flag),
        patch.object(api, "login", new=AsyncMock()) as login,
    ):
        await api._ensure_session()

    assert login.call_count == 1, "the blank answer was never resolved"
    assert api.last_session_check["verdict"] == SESSION_CONFIRMED


@pytest.mark.asyncio
async def test_a_device_without_the_flag_is_asked_once_per_firmware(
    mock_aiohttp_client,
) -> None:
    """One login buys the answer; nothing pays for it twice.

    A device that does not implement `loginfo` answers blank whatever the
    session is doing. Proving that costs one login, and the cost must not
    repeat on every write thereafter — which is the login storm the hardening
    in `[3.3.25-dev2]` existed to prevent.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.unauthenticated_keys = frozenset()

    with (
        patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": ""})),
        patch.object(api, "login", new=AsyncMock()) as login,
    ):
        await api._ensure_session()
        assert login.call_count == 1, "the key's absence was never established"
        await api._ensure_session()
        await api._ensure_session()

    assert login.call_count == 1, "absence was proved and then asked about again"


@pytest.mark.asyncio
async def test_a_failed_login_proves_nothing_about_the_flag(
    mock_aiohttp_client,
) -> None:
    """A device is not marked as lacking the key because a login failed.

    The two are unrelated: a refused or unreachable login says nothing about
    which keys the firmware implements. Recording absence on that evidence
    would turn a momentary connectivity problem into a decision that persists
    for the life of the firmware.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.unauthenticated_keys = frozenset()

    with (
        patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": ""})),
        patch.object(
            api,
            "login",
            new=AsyncMock(side_effect=ZTEConnectionError("router unreachable")),
        ) as login,
    ):
        await api._ensure_session()
        assert login.call_count == 1

        # The next write asks again, because nothing was learned.
        await api._ensure_session()

    assert login.call_count == 2, "a failed login was recorded as an answer"


@pytest.mark.asyncio
async def test_a_blank_flag_is_unproven_until_a_login_has_been_tried(
    mock_aiohttp_client,
) -> None:
    """Three states, not two: unknown, supported, absent.

    The whole fault is that unknown and absent were treated alike. One means
    the question has not been put under conditions that would answer it; the
    other means it was put and the device does not have the key.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    with patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": ""})):
        assert await api.read_session_flag() == SESSION_UNPROVEN


@pytest.mark.asyncio
async def test_a_send_is_not_blocked_on_a_device_that_lacks_the_flag(
    mock_aiohttp_client,
) -> None:
    """Issue #56's shape, in a new place, and the reason item 110 exists.

    The send block reads `last_session_check`. Once an unproven flag has its
    own path, that path records under the flag's own source — so a block that
    keys on the source string alone would refuse every send on every device
    that does not implement `loginfo`. It must ask whether this device is
    known to support the key.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.unauthenticated_keys = frozenset()

    with (
        patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": ""})),
        patch.object(api, "login", new=AsyncMock()),
    ):
        await api._ensure_session()

    assert api._require_confirmed_session("SEND_SMS") is None


@pytest.mark.asyncio
async def test_a_send_is_blocked_when_a_supported_flag_denies_the_session(
    mock_aiohttp_client,
) -> None:
    """The property item 110 must not lose while it is being restated.

    A device that has answered `ok` and now answers blank has a dead session,
    a login has already been tried, and a send is the one write that cannot be
    reported as unverified.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.unauthenticated_keys = frozenset()

    with patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": "ok"})):
        assert await api.read_session_flag() == SESSION_CONFIRMED

    with (
        patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": ""})),
        patch.object(api, "login", new=AsyncMock()),
    ):
        await api._ensure_session()

    with pytest.raises(ZTEAuthError, match="was not sent"):
        api._require_confirmed_session("SEND_SMS")


@pytest.mark.asyncio
async def test_a_later_confirmation_does_not_erase_the_one_that_failed(
    mock_aiohttp_client,
) -> None:
    """The field that explains a failure must outlive the reads that follow it.

    Producing a diagnostics download reads the router, every read can run a
    check, and each check replaces `last_session_check`. Read after the fact it
    describes the collection rather than the fault — which is exactly the wrong
    conclusion drawn about this fault on 2026-09-14.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    api.last_session_check = {"source": "session_flag", "verdict": SESSION_DENIED}
    api.last_session_check = {"source": "session_flag", "verdict": SESSION_CONFIRMED}

    assert api.last_session_check["verdict"] == SESSION_CONFIRMED
    kept = api.last_non_confirmed_session_check
    assert kept["verdict"] == SESSION_DENIED
    assert kept["at"], "a historical record without a time cannot be placed"


def test_the_flag_state_says_which_of_the_three_it_is(mock_aiohttp_client) -> None:
    """`supported: false` is the answer to two different questions.

    A device that does not implement the key and a device no write has reached
    both report it, and telling them apart is the whole of this phase.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    assert api.session_flag_state() == "unknown"

    api._session_flag_absent_for = "FIRMWARE_A"
    api._cr_version_cache = ("FIRMWARE_A", "")
    assert api.session_flag_state() == "absent"

    api._session_flag_seen_for = "FIRMWARE_A"
    assert api.session_flag_state() == "supported"

    # The report carries the state and the firmware each belief was decided on.
    report = api.session_flag_report()
    assert report["state"] == "supported"
    assert report["absent_on_firmware"] == "FIRMWARE_A"


def test_a_token_read_that_answers_nothing_usable_yields_an_empty_string() -> None:
    """The alias resolver must not raise on a response that is not a mapping.

    `get_rd` degrades quietly by contract — an absent `RD` returns `""` and the
    caller raises with a message naming the token rather than the transport.
    A response of the wrong shape entirely has to take the same path.
    """
    assert _first_spelling(None, ("RD", "rd")) == ""
    assert _first_spelling({"RD": ""}, ("RD", "rd")) == ""
    assert _first_spelling({"rd": "abc"}, ("RD", "rd")) == "abc"


@pytest.mark.asyncio
async def test_a_new_cycle_discards_the_previous_one(mock_aiohttp_client) -> None:
    """The pool is a poll, not a running total.

    A key populated at core time and blank by the time a write happens would
    otherwise stay a witness for the life of the object, and a witness that
    reads blank scores as an expiry. That verdict is recorded and never raised,
    so the cost is a misleading line in a download — but it is why the set is
    bounded to one cycle rather than accumulated.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    first = {"wan_connect_status": "1", "signalbar": "4"}
    second = {"network_type": "LTE"}
    answers = [first, second]

    async def poll(*_args, **_kwargs):
        return answers.pop(0)

    with patch.object(api, "_request", side_effect=poll):
        await api._batch_get(["wan_connect_status", "signalbar"], starts_cycle=True)
        await api._batch_get(["network_type"], starts_cycle=True)

    assert set(api._populated_keys) == {"network_type"}


@pytest.mark.asyncio
async def test_a_read_outside_a_cycle_adds_rather_than_discards(
    mock_aiohttp_client,
) -> None:
    """The canary pool is not a poll and must not end one.

    It reads both parameter lists for its own purposes. Treating that as the
    start of a cycle would throw away the poll the coordinator had just
    completed, which is the fault this item fixed, reintroduced from the other
    direction.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    answers = [{"wan_connect_status": "1"}, {"5g_rx0_rsrp": "-90"}]

    async def poll(*_args, **_kwargs):
        return answers.pop(0)

    with patch.object(api, "_request", side_effect=poll):
        await api._batch_get(["wan_connect_status"], starts_cycle=True)
        await api._batch_get(["5g_rx0_rsrp"])

    assert set(api._populated_keys) == {"wan_connect_status", "5g_rx0_rsrp"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (TimeoutError("slow"), "TimeoutError"),
        ("not a mapping", "not a mapping"),
        ({"something_else": "1"}, "key absent"),
    ],
)
async def test_an_unanswered_flag_read_records_why(answer, expected) -> None:
    """`unanswered` alone cannot be told apart from a timeout or a bad shape.

    The verdict is the same in all three cases, so a download that carries only
    the verdict cannot say whether the router refused, timed out, or answered
    something this code could not read.
    """
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")

    async def reply(*_args, **_kwargs):
        if isinstance(answer, Exception):
            raise answer
        return answer

    with patch.object(api, "_request", side_effect=reply):
        assert await api.read_session_flag() == SESSION_UNANSWERED

    assert api.session_flag_report()["unanswered_because"] == expected


@pytest.mark.asyncio
async def test_an_answered_flag_read_clears_the_reason() -> None:
    """A stale reason would outlive the failure it describes."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    api._session_flag_unanswered_because = "TimeoutError"

    with patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": "ok"})):
        assert await api.read_session_flag() == SESSION_CONFIRMED

    assert api.session_flag_report()["unanswered_because"] is None
