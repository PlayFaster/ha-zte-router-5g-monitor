"""Learning, caching and publishing the profile — on the paths that go wrong.

Item 43's rule applied to Part 2's own fallbacks: every one of them is driven
by a test that makes it fail, not by one that watches it succeed. A profile
that cannot be read, cannot be stored, or describes a firmware the device is no
longer running must each leave the integration working exactly as it worked
before there was a profile at all.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.zte_router_5g import device_profile
from custom_components.zte_router_5g.diagnostics import _profile_section

from .test_device_profile import _MC7010_SERVICE, MC888

# ---------------------------------------------------------------------------
# The parser's remaining edges
# ---------------------------------------------------------------------------


def test_a_known_algorithm_with_an_unknown_case_resolves_to_nothing() -> None:
    """Half an answer is not an answer: the case decides the bytes on the wire."""
    assert device_profile.digest_callable("md5", "lower") is not None
    assert device_profile.digest_callable("md5", "titlecase") is None


def test_an_expression_carrying_no_exempt_list_and_no_gate_learns_neither() -> None:
    """No exempt list and no gate flag is an answer, not a parse failure.

    A firmware that tokens every command names no exemption, and what it
    does not name is a learned fact about it.
    """
    bare = 'var o=hex_md5(rd0+rd1),u=B({nv:"RD"}).RD,c=hex_md5(o+u);e.AD=c'
    token = device_profile.parse_token({"js/service.js": bare})

    assert token["digest_function"] == "hex_md5"
    assert "exempt_commands" not in token
    assert "gate_flag" not in token


def test_a_second_round_without_a_salt_is_not_counted_as_a_site() -> None:
    """Two rounds and a salt read together, or the match is some other code."""
    token = device_profile.parse_token(
        {"js/service.js": "var o=hex_md5(rd0+rd1),c=hex_md5(o+u);"}
    )
    assert token == {"sites": 0}


def test_an_unterminated_literal_does_not_run_away_with_the_parse() -> None:
    """An unterminated literal does not run away with the parse.

    Minified source is not guaranteed well-formed once the crawl's return
    cap has truncated it, and a brace scan that never closes must stop at
    its window rather than at the end of the file.
    """
    keys, _end, held = device_profile._literal_keys('x={goformId:"A",b:1', 3)
    assert keys == ["b"]
    assert held == "x"


def test_a_goform_id_with_no_enclosing_literal_yields_no_fields() -> None:
    """A command named outside any builder has no fields to read."""
    commands = device_profile.parse_commands({"js/service.js": 'goformId:"ALONE"'})
    assert commands["ALONE"] == []


def test_a_builder_that_never_returns_its_variable_stops_at_its_window() -> None:
    """The boundary that keeps one command's fields out of the next one's."""
    text = 'var n={};n.goformId="AAA",n.first=1,' + "n.pad=2," * 800 + "n.last=3"
    commands = device_profile.parse_commands({"js/service.js": text})
    assert "first" in commands["AAA"]
    assert "last" not in commands["AAA"], "the window did not bound the builder"


def test_a_login_form_with_no_encoding_branch_is_looked_past() -> None:
    """The first `LOGIN` literal in a file need not be the form builder."""
    text = (
        'goformId:"LOGIN",note:"not the builder here"'
        + "x" * 700
        + 'var r=B({nv:"LD"}).LD;goformId:"LOGIN",password:'
        '"2"==n.WEB_ATTR_IF_SUPPORT_SHA256?paswordAlgorithmsCookie(e.password):0'
    )
    login = device_profile.parse_login({"js/service.js": text})

    assert login["password_branches"] == {"2": "paswordAlgorithmsCookie"}
    assert login["salt_read"] == "LD"


def test_a_login_form_with_no_salt_and_no_known_branch_says_only_what_it_read() -> None:
    """A form on the Base64 branch names no salt and no digest."""
    text = (
        'goformId:"LOGIN",password:"1"==n.WEB_ATTR_IF_SUPPORT_SHA256?'
        "paswordAlgorithmsCookie(Base64.encode(e.password)):0"
    )
    login = device_profile.parse_login({"js/service.js": text})

    assert login["password_branches"] == {"1": "paswordAlgorithmsCookie"}
    assert "salt_read" not in login, "a salt was invented"
    assert "password_digest" not in login, "a digest was taken from the wrong branch"


def test_the_first_file_that_answers_ends_the_search() -> None:
    """Two files carrying a login form is one file too many to average over."""
    sources = {
        "a.js": 'goformId:"LOGIN",password:"2"==n.WEB_ATTR_IF_SUPPORT_SHA256?'
        "paswordAlgorithmsCookie(e.password):0",
        "b.js": 'goformId:"LOGIN",password:"2"==n.WEB_ATTR_IF_SUPPORT_SHA256?'
        "SomethingElse(e.password):0",
    }
    assert device_profile.parse_login(sources)["password_branches"] == {
        "2": "paswordAlgorithmsCookie"
    }


def test_repeated_sites_naming_the_same_function_are_counted_not_re_read() -> None:
    """Three sites on the MC7010 and four on the Pro, all naming one function.

    Agreement is the normal case and must cost nothing; only disagreement is
    an event.
    """
    one = 'var o=hex_md5(rd0+rd1),u=B({nv:"RD"}).RD,c=hex_md5(o+u);e.AD=c;'
    token = device_profile.parse_token({"js/service.js": one * 3})

    assert token["sites"] == 3
    assert token["digest_function"] == "hex_md5"
    assert "digest_conflict" not in token


def test_a_bare_goform_id_assignment_names_no_payload_variable() -> None:
    """`goformId="X"` with nothing in front of it builds no form here."""
    assert device_profile.parse_commands({"js/service.js": 'goformId="LOOSE"'}) == {
        "LOOSE": []
    }


def test_a_source_set_naming_no_login_form_leaves_the_field_empty() -> None:
    """Every file read, nothing found, and nothing invented to fill the gap."""
    assert device_profile.parse_login({"a.js": "no form", "b.js": "none here"}) == {}


def test_the_session_flag_is_absent_rather_than_invented() -> None:
    """A firmware naming no session decision leaves the field empty."""
    assert device_profile.parse_session_flag({"js/service.js": "nothing here"}) == {}


# ---------------------------------------------------------------------------
# The coordinator: loading, learning, storing
# ---------------------------------------------------------------------------


def _coordinator(api: Any = None) -> Any:
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    coordinator = MagicMock(spec=ZTERouterDataUpdateCoordinator)
    coordinator.api = api if api is not None else MagicMock()
    coordinator.api.profile = {}
    coordinator.entry = MagicMock()
    coordinator.entry.title = "Router"
    coordinator.entry.entry_id = "abc"
    coordinator.hass = MagicMock()
    coordinator._profile_store = None
    # 3.4.4-dev2: `async_load_profile` also loads the poll plan's store.
    coordinator.poll_plan = MagicMock()
    coordinator.poll_plan.load.return_value = ""
    # A real coordinator always has `data`; `None` until the first poll. Read
    # since 3.4.4 to decide whether to re-render entities after a learn.
    coordinator.data = None
    coordinator.async_load_profile = (
        ZTERouterDataUpdateCoordinator.async_load_profile.__get__(coordinator)
    )
    coordinator.async_learn_profile = (
        ZTERouterDataUpdateCoordinator.async_learn_profile.__get__(coordinator)
    )
    return coordinator


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (None, {}),
        ("not a mapping", {}),
        # A record written by a build whose profile had a different shape.
        ({"profile_version": 999, "token": {}}, {}),
    ],
)
async def test_an_unusable_stored_profile_leaves_the_api_without_one(
    stored: Any, expected: dict
) -> None:
    """Missing, malformed and superseded records all mean no profile."""
    coordinator = _coordinator()
    with patch("custom_components.zte_router_5g.coordinator.Store") as store:
        store.return_value.async_load = AsyncMock(return_value=stored)
        await coordinator.async_load_profile()

    assert coordinator.api.profile == expected


@pytest.mark.asyncio
async def test_a_current_stored_profile_is_handed_to_the_api_unchanged() -> None:
    """Principle 5: startup reads it and parses nothing."""
    coordinator = _coordinator()
    stored = device_profile.parse_profile(MC888, "FW1")
    with patch("custom_components.zte_router_5g.coordinator.Store") as store:
        store.return_value.async_load = AsyncMock(return_value=stored)
        await coordinator.async_load_profile()

    assert coordinator.api.profile == stored


@pytest.mark.asyncio
async def test_a_store_that_cannot_be_read_does_not_fail_setup() -> None:
    """A store that cannot be read does not fail setup.

    Deliberately broad, for the reason the uptime store is: no storage
    fault may fail an entry setup that has no need of the store at all.
    """
    coordinator = _coordinator()
    with patch("custom_components.zte_router_5g.coordinator.Store") as store:
        store.return_value.async_load = AsyncMock(side_effect=OSError("disk"))
        await coordinator.async_load_profile()

    assert coordinator.api.profile == {}


@pytest.mark.asyncio
async def test_a_current_profile_is_not_learned_again() -> None:
    """A profile keyed to the running firmware costs no requests."""
    coordinator = _coordinator()
    coordinator.api.profile = {"firmware": "FW1"}
    coordinator.api.get_version = AsyncMock(return_value="FW1")
    coordinator.api.learn_profile = AsyncMock(
        side_effect=AssertionError("re-learned a current profile")
    )

    await coordinator.async_learn_profile()

    coordinator.api.learn_profile.assert_not_awaited()
    assert coordinator.api.profile == {"firmware": "FW1"}


@pytest.mark.asyncio
async def test_a_changed_firmware_is_learned_again_and_stored() -> None:
    """An upgrade can change every answer, so it re-learns and re-stores."""
    coordinator = _coordinator()
    coordinator.api.profile = {"firmware": "FW0"}
    coordinator.api.get_version = AsyncMock(return_value="FW1")
    learned = device_profile.parse_profile(MC888, "FW1")
    coordinator.api.learn_profile = AsyncMock(return_value=learned)
    coordinator._profile_store = MagicMock()
    coordinator._profile_store.async_save = AsyncMock()

    await coordinator.async_learn_profile()

    coordinator._profile_store.async_save.assert_awaited_once_with(learned)


@pytest.mark.asyncio
async def test_a_partial_profile_is_kept_and_its_gaps_are_logged() -> None:
    """A partial profile is kept, and its gaps are logged.

    Per-fact, never wholesale: a firmware that hides one answer still
    supplies the rest, and the rest is worth having.
    """
    coordinator = _coordinator()
    coordinator.api.get_version = AsyncMock(return_value="FW1")
    partial = device_profile.parse_profile({"js/service.js": _MC7010_SERVICE}, "FW1")
    coordinator.api.learn_profile = AsyncMock(return_value=partial)
    coordinator._profile_store = MagicMock()
    coordinator._profile_store.async_save = AsyncMock()

    await coordinator.async_learn_profile()

    assert partial["unlearned"], "this fixture was supposed to be incomplete"
    coordinator._profile_store.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_router_that_will_not_serve_its_scripts_costs_only_the_profile() -> (
    None
):
    """A failed learn leaves the previous profile and raises nothing."""
    coordinator = _coordinator()
    coordinator.api.profile = {"firmware": "FW0"}
    coordinator.api.get_version = AsyncMock(return_value="FW1")
    coordinator.api.learn_profile = AsyncMock(side_effect=TimeoutError)

    await coordinator.async_learn_profile()

    assert coordinator.api.profile == {"firmware": "FW0"}


@pytest.mark.asyncio
async def test_a_profile_that_cannot_be_stored_is_still_used_this_session() -> None:
    """A store that refuses a write must not discard what was learned."""
    coordinator = _coordinator()
    coordinator.api.get_version = AsyncMock(return_value="FW1")
    coordinator.api.learn_profile = AsyncMock(
        return_value=device_profile.parse_profile(MC888, "FW1")
    )
    coordinator._profile_store = MagicMock()
    coordinator._profile_store.async_save = AsyncMock(side_effect=OSError("full"))

    await coordinator.async_learn_profile()

    # The learn ran and its result was offered to the store. What the store
    # then did with it cannot un-learn it: `learn_profile` has already put the
    # profile on the API, which is what this session will consult.
    coordinator._profile_store.async_save.assert_awaited_once()
    coordinator.api.learn_profile.assert_awaited_once()


@pytest.mark.asyncio
async def test_learning_before_the_store_exists_writes_nothing() -> None:
    """A learn that runs ahead of the store writes nothing and raises nothing."""
    coordinator = _coordinator()
    coordinator.api.get_version = AsyncMock(return_value="FW1")
    coordinator.api.learn_profile = AsyncMock(
        return_value=device_profile.parse_profile(MC888, "FW1")
    )
    coordinator._profile_store = None

    await coordinator.async_learn_profile()

    coordinator.api.learn_profile.assert_awaited_once()


# ---------------------------------------------------------------------------
# The download
# ---------------------------------------------------------------------------


def test_the_download_names_the_gap_between_the_cache_and_the_device() -> None:
    """The download names the gap between the cache and the device.

    A cached profile describing a firmware that is gone is a fault nothing
    else in the file would show.
    """
    api = MagicMock()
    api.profile = device_profile.parse_profile(MC888, "xx_xxxxMC888PROMODV1.0.0B01")
    api.profile_decisions = {"ad_digest": "learned"}
    coordinator = MagicMock()
    coordinator.api = api

    section = _profile_section(coordinator, MC888)

    assert section["reparsed"]["matches_in_force"] is True
    # The fixture carries the write-path files only (3.4.4: see
    # `test_nothing_is_left_unlearned_on_either_device`).
    assert section["reparsed"]["unlearned"] == ["device_config.auto_modes"]
    assert section["digest_learned"] == "sha256"
    assert section["digest_from_model_string"] == "sha256"
    assert section["digest_agrees_with_model_heuristic"] is True
    assert section["decisions"] == {"ad_digest": "learned"}


def test_the_download_reports_a_digest_the_model_string_would_have_got_wrong() -> None:
    """The comparison that is the whole reason to publish this.

    Both answers are well-formed tokens and the router refuses either one the
    same way, so a disagreement is invisible anywhere else.
    """
    api = MagicMock()
    api.profile = device_profile.parse_profile(MC888, "xx_xxx_MC7010DV1.0.0B03")
    api.profile_decisions = {}
    coordinator = MagicMock()
    coordinator.api = api

    section = _profile_section(coordinator, MC888)

    assert section["digest_agrees_with_model_heuristic"] is False


def test_a_download_with_no_crawl_says_so_rather_than_reporting_agreement() -> None:
    """No sources is a different answer from the two sides agreeing."""
    api = MagicMock()
    api.profile = {"firmware": "FW"}
    api.profile_decisions = {}
    coordinator = MagicMock()
    coordinator.api = api

    section = _profile_section(coordinator, {})

    assert section["reparsed"] is None
    assert "digest_agrees_with_model_heuristic" not in section


def test_a_download_taken_before_anything_was_learned_publishes_the_absence() -> None:
    """An absent profile publishes as absent, not as an empty success."""
    api = MagicMock()
    api.profile = None
    api.profile_decisions = {}
    coordinator = MagicMock()
    coordinator.api = api

    section = _profile_section(coordinator, MC888)

    assert section["in_force"] == {}
    assert section["reparsed"]["matches_in_force"] is None
    assert "digest_learned" in section
