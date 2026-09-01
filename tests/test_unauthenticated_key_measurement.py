"""Measuring, rather than assuming, which keys a device answers unauthenticated.

`_UNAUTHENTICATED_KEYS` is five names measured on one MC7010 by replaying an
invalidated token. It is wrong on at least one other device: the MC888 Pro in
issue #56 answers `network_type` and `ppp_status` without a session, and the
constant classifies both as authenticated. On that device a lapsed session
shows a populated "authenticated" key, so `_classify_session` returns `live`
and a dead session scores healthy with nothing in the log.

The measurement is the fix, and the rules rejecting a bad measurement matter
more than the measurement itself — a set that swallows a batch is worse than
the constant it replaces, because the classifier can then never report an
expiry at all.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from custom_components.zte_router_5g.api import (
    _CORE_PARAMS,
    _EXTENDED_PARAMS,
    _SESSION_SENTINELS,
    _UNAUTHENTICATED_KEYS,
    ZTERouterAPI,
    _classify_session,
)
from custom_components.zte_router_5g.coordinator import CORE_KEYS

from .conftest import MockResponse

# What the MC888 Pro answered without a session, from the reporter's own
# diagnostics download (issue #56). `network_type` and `ppp_status` are the
# two the MC7010-derived constant gets wrong.
MC888_UNAUTHENTICATED = frozenset(
    {
        "network_type",
        "wa_inner_version",
        "ppp_status",
        "model_name",
        "imei",
    }
)


def _api(client, **kwargs):
    return ZTERouterAPI(client, "192.168.0.1", "admin", "password", **kwargs)


def test_contract_keys_agree() -> None:
    """The two concept mappings are mirrored, and must not drift.

    `coordinator.py` imports `api.py`, so the dependency runs one way only and
    the mapping is duplicated. Compared concept by concept and spelling by
    spelling — comparing the flattened sets alone would pass while the two
    disagreed about which spellings belong to which concept.
    """
    from custom_components.zte_router_5g.api import (
        _CONTRACT_CONCEPTS,
        _CONTRACT_KEYS,
    )
    from custom_components.zte_router_5g.coordinator import CORE_CONCEPTS

    assert _CONTRACT_CONCEPTS == CORE_CONCEPTS
    assert frozenset(CORE_KEYS) == _CONTRACT_KEYS


# ---------------------------------------------------------------------------
# The defect the measurement exists to fix
# ---------------------------------------------------------------------------


def test_the_mc888_dead_session_reads_as_live_under_the_constant() -> None:
    """The silent failure, reproduced from the reporter's payload."""
    payload = dict.fromkeys(_CORE_PARAMS, "")
    payload.update(dict.fromkeys(MC888_UNAUTHENTICATED, "value"))

    assert _classify_session(payload, _CORE_PARAMS, _UNAUTHENTICATED_KEYS) == "live"


def test_the_same_payload_reads_as_expired_under_the_measured_set() -> None:
    """With the device's own set, the dead session is detected."""
    payload = dict.fromkeys(_CORE_PARAMS, "")
    payload.update(dict.fromkeys(MC888_UNAUTHENTICATED, "value"))

    assert _classify_session(payload, _CORE_PARAMS, MC888_UNAUTHENTICATED) == "expired"


# ---------------------------------------------------------------------------
# Refusing to measure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_measurement_while_the_session_is_live(mock_aiohttp_client):
    """A live session samples an authenticated response, not the device."""
    api = _api(mock_aiohttp_client)
    api.session_active = True
    api.logout_acknowledged = True

    assert await api.measure_unauthenticated_keys() == frozenset()


@pytest.mark.asyncio
async def test_no_measurement_when_the_logout_was_not_acknowledged(
    mock_aiohttp_client,
):
    """`logout()` swallows its errors, and this router refuses a bad `AD`.

    Without the acknowledgement flag a refused logout is indistinguishable
    from a clean one, and the probe would sample a session that is still live.
    """
    api = _api(mock_aiohttp_client)
    api.session_active = False
    api.logout_acknowledged = False

    assert await api.measure_unauthenticated_keys() == frozenset()


@pytest.mark.asyncio
async def test_logout_records_a_refusal(mock_aiohttp_client):
    """`{"result":"failure"}` on LOGOUT must not read as acknowledged."""
    api = _api(mock_aiohttp_client)
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "failure"}
    )
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"wa_inner_version": "V1", "RD": "rd"}
    )

    await api.logout()

    assert api.logout_acknowledged is False


# ---------------------------------------------------------------------------
# Rejecting a measurement that cannot safely replace the constant
# ---------------------------------------------------------------------------


def test_an_empty_measurement_is_rejected() -> None:
    """Nothing answered, so nothing was learned."""
    assert ZTERouterAPI._measurement_is_usable(set()) is False


def test_a_measurement_swallowing_the_core_batch_is_rejected() -> None:
    """The failure this rule exists to prevent is worse than the constant.

    With no authenticated key left, `_classify_session` returns `undecidable`
    forever and falls back to a rule the core batch made unsatisfiable — a
    dead session scored a clean success, entities `unknown`, health green.
    """
    assert ZTERouterAPI._measurement_is_usable(set(_CORE_PARAMS)) is False


def test_a_measurement_swallowing_the_extended_batch_is_rejected() -> None:
    """Both batches are classified, so both need something authenticated."""
    measured = set(_EXTENDED_PARAMS) | {"imei"}
    assert ZTERouterAPI._measurement_is_usable(measured) is False


def test_a_measurement_claiming_every_sentinel_spelling_is_rejected() -> None:
    """`get_params` appends a sentinel to prove the session is alive.

    One spelling answered unauthenticated is survivable — the others still
    prove liveness. All of them is not: nothing left would distinguish a dead
    session from a legitimately empty read.
    """
    measured = {"imei", *_SESSION_SENTINELS}
    assert ZTERouterAPI._measurement_is_usable(measured) is False


def test_one_sentinel_spelling_answered_unauthenticated_is_survivable() -> None:
    """The MC888 Pro answers `ppp_status` without a session (issue #56)."""
    assert ZTERouterAPI._measurement_is_usable({"imei", "ppp_status"}) is True


@pytest.mark.parametrize(
    "contract_key", [k for k in CORE_KEYS if k not in _SESSION_SENTINELS]
)
def test_one_contract_key_does_not_reject_a_measurement(contract_key) -> None:
    """The drift check asks whether *any* contract key is present.

    It survives losing one, and the MC888 Pro genuinely answers `network_type`
    without a session. Rejecting on a single contract key would refuse that
    device's own true measurement and leave it on a constant that is wrong for
    it — the failure this mechanism exists to prevent.
    """
    assert ZTERouterAPI._measurement_is_usable({"imei", contract_key}) is True


def test_the_sentinels_are_contract_keys_too() -> None:
    """`connection_state` is both a contract concept and the sentinel set."""
    assert set(_SESSION_SENTINELS) <= set(CORE_KEYS)


def test_a_measurement_claiming_every_contract_key_is_rejected() -> None:
    """With none of them authenticated the drift check cannot fire at all."""
    assert ZTERouterAPI._measurement_is_usable({"imei", *CORE_KEYS}) is False


def test_the_mc7010_measurement_is_accepted() -> None:
    """The reference device's own set must pass its own rules."""
    assert ZTERouterAPI._measurement_is_usable(set(_UNAUTHENTICATED_KEYS)) is True


# ---------------------------------------------------------------------------
# The set in force
# ---------------------------------------------------------------------------


def test_the_constant_is_used_until_a_measurement_is_trusted() -> None:
    """A rejected or absent measurement leaves behavior exactly as it was."""
    api = _api(MagicMock())
    assert api.unauthenticated_key_set() == _UNAUTHENTICATED_KEYS


def test_a_trusted_measurement_replaces_the_constant() -> None:
    """A validated measurement is what the classifier then reads."""
    api = _api(MagicMock())
    api.unauthenticated_keys = MC888_UNAUTHENTICATED
    assert api.unauthenticated_key_set() == MC888_UNAUTHENTICATED


@pytest.mark.asyncio
async def test_a_rejected_measurement_is_not_adopted(mock_aiohttp_client):
    """A probe answered on a still-live session swallows the batch."""
    api = _api(mock_aiohttp_client)
    api.session_active = False
    api.logout_acknowledged = True
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data=dict.fromkeys(_CORE_PARAMS, "value")
    )

    assert await api.measure_unauthenticated_keys() == frozenset()


# ---------------------------------------------------------------------------
# Alias expansion (items 8 to 12)
# ---------------------------------------------------------------------------


def test_every_new_alias_is_requested() -> None:
    """An alias tuple naming a key nobody asks for can never resolve."""
    from custom_components.zte_router_5g import sensor

    requested = set(_CORE_PARAMS) | set(_EXTENDED_PARAMS)
    tuples = [
        getattr(sensor, name) for name in dir(sensor) if name.startswith("_ALIAS_")
    ]
    for tup in tuples:
        for key in tup:
            assert key in requested, f"{key} is aliased but never requested"


def test_a_flux_spelling_never_stands_alone_as_a_concept() -> None:
    """Superseded the rule that no `flux_` key may be a contract key.

    Drift is now judged per concept, so a `flux_` spelling belonging to a
    concept is the mechanism working — it is how a device using that
    vocabulary still reports the concept. What must not happen is a concept
    whose *only* spelling is a `flux_` one, which would make drift fire on
    every device that uses the bare name.
    """
    from custom_components.zte_router_5g.api import _CONTRACT_CONCEPTS

    for concept, spellings in _CONTRACT_CONCEPTS.items():
        bare = [k for k in spellings if not k.startswith("flux_")]
        assert bare, f"{concept} has no bare spelling"


def test_uptime_alias_matches_the_sensor_tuple() -> None:
    """`coordinator.py` mirrors `sensor._ALIAS_REALTIME_TIME` rather than importing it.

    `sensor.py` imports the coordinator, so the dependency runs one way only.
    This is what stops the uptime source and the sensor disagreeing about
    which spellings carry the value.
    """
    import inspect

    from custom_components.zte_router_5g import coordinator, sensor

    source = inspect.getsource(coordinator.ZTERouterDataUpdateCoordinator)
    for key in sensor._ALIAS_REALTIME_TIME:
        assert f'"{key}"' in source, f"uptime does not read {key}"


def test_subscriber_aliases_are_redacted() -> None:
    """Adding an alias to the request list without classifying it is a leak.

    `_sanitize_payload` matches on exact key name, and `_sweep` catches only
    IP- and MAC-shaped strings — an IMSI is bare digits and matches neither.
    Measured on the MC7010: `iccid` carries a real ICCID.
    """
    from custom_components.zte_router_5g.diagnostics import TO_REDACT

    for key in ("imsi", "iccid", "sim_imsi", "sim_iccid"):
        assert key in TO_REDACT, f"{key} is requested but never redacted"


def test_byte_counters_are_not_mistaken_for_identifiers() -> None:
    """The digit sweep must not mask ordinary telemetry.

    Byte counters, uptime seconds and channel numbers are all bare digits.
    The threshold is what separates them from an identifier, and it is chosen
    against this case rather than against the identifiers alone.
    """
    from custom_components.zte_router_5g.diagnostics import _sweep, _Tokenizer

    tok = _Tokenizer()
    for value in ("98765432109", "3600", "6300", "12345678901234"):
        assert _sweep(value, tok) == value, f"{value} was masked"


def test_identifier_shaped_digit_runs_are_masked() -> None:
    """IMSI is 15 digits, ICCID 19 or 20 — both above the threshold."""
    from custom_components.zte_router_5g.diagnostics import _sweep, _Tokenizer

    tok = _Tokenizer()
    assert _sweep("272011234567890", tok) != "272011234567890"
    assert _sweep("8935301234567890123", tok) != "8935301234567890123"


@pytest.mark.asyncio
async def test_a_probe_that_cannot_be_read_measures_nothing(mock_aiohttp_client):
    """A failed or non-dict probe leaves the constant in force."""
    api = _api(mock_aiohttp_client)
    api.session_active = False
    api.logout_acknowledged = True
    mock_aiohttp_client.get.return_value = MockResponse(json_data=["not", "a", "dict"])

    assert await api.measure_unauthenticated_keys() == frozenset()
    assert api.unauthenticated_key_set() == _UNAUTHENTICATED_KEYS


@pytest.mark.asyncio
async def test_a_probe_raising_measures_nothing(mock_aiohttp_client):
    """The router being unreachable is not a measurement."""
    import aiohttp

    api = _api(mock_aiohttp_client)
    api.session_active = False
    api.logout_acknowledged = True
    mock_aiohttp_client.get.side_effect = aiohttp.ClientError("gone")

    assert await api.measure_unauthenticated_keys() == frozenset()


@pytest.mark.asyncio
async def test_a_measurement_is_adopted_when_it_passes(mock_aiohttp_client):
    """The whole point: the device's own answer replaces the constant."""
    api = _api(mock_aiohttp_client)
    api.session_active = False
    api.logout_acknowledged = True
    core = dict.fromkeys(_CORE_PARAMS, "")
    core.update(dict.fromkeys(MC888_UNAUTHENTICATED, "value"))
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data=core),
        MockResponse(json_data=dict.fromkeys(_EXTENDED_PARAMS, "")),
    ]

    measured = await api.measure_unauthenticated_keys()

    assert measured == MC888_UNAUTHENTICATED


@pytest.mark.asyncio
async def test_a_cookie_with_no_value_is_not_adopted(mock_aiohttp_client):
    """A `Set-Cookie` clearing a cookie must not become the session."""
    api = _api(mock_aiohttp_client)
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "LD"}),
        MockResponse(json_data={"wa_inner_version": "MC888_V1"}),
        MockResponse(json_data={"RD": "RD"}),
        MockResponse(json_data={"wa_inner_version": "MC888_V1"}),
    ]
    from multidict import CIMultiDict

    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "0"},
        cookies={},
        headers=CIMultiDict(
            [
                ("Set-Cookie", "cleared=; Path=/"),
                ("Set-Cookie", "zsidn=live; Path=/"),
            ]
        ),
    )

    await api.login()

    assert api.cookies == {"zsidn": "live"}


def test_a_measurement_claiming_every_contract_key_but_not_the_sentinel() -> None:
    """The drift check cannot fire when none of its keys needs a session.

    Distinct from the sentinel rule: this rejects a set that leaves the drift
    check with nothing authenticated to judge, even where the sentinel itself
    is not claimed.
    """
    from custom_components.zte_router_5g.api import _CONTRACT_KEYS

    measured = {"imei", *_CONTRACT_KEYS}
    # The sentinel spellings are contract keys, so this set trips both rules.
    # The contract rule is checked first; testing the sentinel first left this
    # branch unreachable.
    assert set(_SESSION_SENTINELS) <= measured
    assert ZTERouterAPI._measurement_is_usable(measured) is False


def test_a_set_cookie_header_that_does_not_parse_is_ignored(mock_aiohttp_client):
    """A header the regex cannot split must not produce a nameless cookie."""
    from multidict import CIMultiDict

    api = _api(mock_aiohttp_client)
    response = MagicMock()
    response.cookies = {}
    response.headers = CIMultiDict([("Set-Cookie", ";;;")])

    assert api._extract_cookies(response) == {}


def test_the_data_limit_form_sources_every_field_through_its_aliases() -> None:
    """An all-or-nothing form: a missing field makes the write impossible.

    `set_data_volume_settings` raises rather than guessing when a field is
    absent from the last poll, so a spelling this integration does not request
    does not degrade the control — it removes it.
    """
    requested = set(_CORE_PARAMS) | set(_EXTENDED_PARAMS)
    for field, aliases in ZTERouterAPI.DATA_VOLUME_FIELDS.items():
        assert aliases, f"{field} has no alias tuple"
        for alias in aliases:
            assert alias in requested, (
                f"{field} aliases {alias}, which is never asked for"
            )


def test_every_flux_spelling_requested_is_aliased_somewhere() -> None:
    """A `flux_` name in the request list that nothing reads is dead weight.

    It costs URL budget on every poll, and the budget is what bounds the batch.
    """
    from custom_components.zte_router_5g import sensor

    consumed = {
        key
        for name in dir(sensor)
        if name.startswith("_ALIAS_")
        for key in getattr(sensor, name)
    }
    for tup in ZTERouterAPI.DATA_VOLUME_FIELDS.values():
        consumed |= set(tup)
    consumed |= {"flux_realtime_time"}  # read by the coordinator's uptime latch

    flux_requested = {
        key
        for key in set(_CORE_PARAMS) | set(_EXTENDED_PARAMS)
        if key.startswith("flux_")
    }
    assert flux_requested <= consumed, f"unread: {sorted(flux_requested - consumed)}"


def test_every_classified_concept_covers_all_its_aliases() -> None:
    """A new spelling of a classified concept is invisible to the sanitizer.

    `TO_REDACT`, `IP_KEYS` and `CELL_KEYS` enumerate by exact name, so an
    alias added to the request list without being classified is published.
    """
    from custom_components.zte_router_5g import sensor
    from custom_components.zte_router_5g.diagnostics import CELL_KEYS

    concepts = {
        "cell": (CELL_KEYS, sensor._ALIAS_5G_PCI),
    }
    for label, (classified, aliases) in concepts.items():
        overlap = classified & set(aliases)
        if overlap:
            assert set(aliases) <= classified, (
                f"{label}: {sorted(set(aliases) - classified)} share a concept "
                f"with a classified key but are not classified"
            )
    assert {"imsi", "sim_imsi", "iccid", "sim_iccid"} <= _redacted()


def _redacted() -> set[str]:
    from custom_components.zte_router_5g.diagnostics import TO_REDACT

    return set(TO_REDACT)


def test_a_sentinel_answered_unauthenticated_does_not_prove_liveness() -> None:
    """The MC888 Pro answers `ppp_status` on a dead session (issue #56).

    `get_params` appends a sentinel to prove a targeted read is alive.
    Appending a spelling the device answers without a session would make a
    dead session look alive — the opposite of the point.
    """
    api = _api(MagicMock())
    api.unauthenticated_keys = frozenset({"imei", "ppp_status"})

    request = ["ODU_led_switch"]
    unauthenticated = api.unauthenticated_key_set()
    usable = [k for k in _SESSION_SENTINELS if k not in unauthenticated]

    assert "ppp_status" not in usable
    assert usable, "no sentinel spelling left to prove liveness"


@pytest.mark.asyncio
async def test_the_appended_sentinel_set_stays_bounded(mock_aiohttp_client):
    """`_classify_session` declines once most of a request came back missing.

    Appending four spellings to a one-key read, three of them absent, crosses
    that line and returns `undecidable` — the regression the sentinel exists
    to prevent.
    """
    api = _api(mock_aiohttp_client)
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"ODU_led_switch": "1", "wan_connect_status": "connected"}
    )

    await api.get_params(["ODU_led_switch"])

    url = mock_aiohttp_client.get.call_args[0][0]
    appended = [k for k in _SESSION_SENTINELS if k in url]
    assert len(appended) <= 2
