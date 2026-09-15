"""The device profile: what is read from a router's own scripts, and what is not.

Item 40. The fixtures below are written by hand rather than copied from either
device's firmware, and they are written to the *shape* the parser matches
rather than to a transcript: the identifier names that survive minification
(`rd0`, `rd1`, `goformId`, `rd_params0`, `ACCESSIBLE_ID_SUPPORT`) are real and
are the whole reason one parser reads two firmwares, while everything a
minifier renames is arbitrary here exactly as it is arbitrary there.

Each fixture is annotated with the device whose structure it reproduces. Both
were verified against the real captures on 2026-09-15 — seventeen files from
the reference MC7010 and seventeen from the MC888 Pro of issue #56 — where the
parser learned every fact it asks for on both, with nothing left unlearned.

The one-hop digest resolution is exercised only by the Pro's shape, and the
unresolved state only by the MC7010's: that device's `hex_md5` is defined in
`js/lib/md5.js`, which the crawl fetches and deliberately does not return, so
the reference hardware is the device that reaches the *cannot resolve* branch
rather than the device that never needs it.
"""

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.zte_router_5g import device_profile
from custom_components.zte_router_5g.api import ZTERouterAPI

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# The MC7010's shape: the digest is named directly in the expression, and its
# definition is not among the files the crawl returns.
_MC7010_SERVICE = (
    'define(["underscore","jquery","config/config"],function(e,t,n){'
    "function s(e,r,_,s,i){var a=null;"
    'if(n.ACCESSIBLE_ID_SUPPORT&&i&&"LOGIN"!=e.goformId&&'
    '"SET_WEB_LANGUAGE"!=e.goformId){'
    'var o=hex_md5(rd0+rd1),u=Bt({nv:"RD"}).RD,c=hex_md5(o+u);e.AD=c}'
    "return e.isTest?a:t.ajax({})}"
    "function u(){function e(e,t){var n={};"
    'return n.cmd="Language,cr_version,wa_inner_version",n.multi_data=1,n}'
    "function t(e){if(e){var t={};"
    "return t.rd_params0=e.wa_inner_version,t.rd_params1=e.cr_version,t}"
    "return Mn}return i(arguments,{},e,t,null,!1)}"
    'function ee(){function e(e,t){var n={};return n.isTest=Dn,n.cmd="loginfo",'
    "n.multi_data=1,n}function r(e){"
    'kn.isLoggedIn=!n.HAS_LOGIN||"ok"==e.loginfo}}'
    'function $(){function e(e,t){var r=Bt({nv:"LD"}).LD;'
    'return{isTest:Dn,goformId:"LOGIN",username:e.username,'
    'password:"2"==n.WEB_ATTR_IF_SUPPORT_SHA256?'
    "paswordAlgorithmsCookie(paswordAlgorithmsCookie(e.password)+r):"
    '"1"==n.WEB_ATTR_IF_SUPPORT_SHA256?'
    "paswordAlgorithmsCookie(Base64.encode(e.password)):"
    "Base64.encode(e.password)}}}"
    # The three builder shapes, in the order the parser has to cope with them.
    'function del_(){function e(e,t){var n=e.ids.join(";")+";";'
    'return{isTest:Dn,goformId:"DELETE_SMS",msg_id:n,notCallback:!0}}}'
    "function Ze(){function e(e,t){var n={};"
    'return n.goformId="ODU_LED_SWITCH_SET",n.isTest=Dn,'
    "n.ODU_led_switch=e.oduLedSwitch,n}function t(e){return e||Mn}}"
    "function nt(){function e(e,t){"
    'var r="1"==e.dataLimitTypeChecked,_={isTest:Dn,goformId:"DATA_LIMIT_SETTING"};'
    'return"1"==e.dataLimitChecked&&(_.data_volume_limit_unit=r?"data":"time",'
    "_.data_volume_limit_size=r?e.limitDataMonth:e.limitTimeMonth),"
    "_.wan_auto_clear_flow_data_switch=e.wan_auto_clear_flow_data_switch,"
    "_.traffic_clear_date=e.traffic_clear_date,_}}"
    "function ht(){function e(e,t){var n={};"
    'return n.isTest=Dn,n.goformId="REBOOT_DEVICE",n}}'
    "function H(){function e(e,t){var n={};"
    'return n.goformId="SET_CONNECTION_MODE",n.isTest=Dn,'
    "n.ConnectionMode=e.connectionMode,n.roam_setting_option=e.isAllowedRoaming,n}}"
)

# `SHA256` is defined here on both devices. `hex_md5` is not, on either.
_MC7010_UTIL = (
    "function paswordAlgorithmsCookie(e){return SHA256(e)}function SHA256(e){return e}"
)

_MC7010_CONFIG = (
    "define([],function(){return{ACCESSIBLE_ID_SUPPORT:!0,MAX_LOGIN_COUNT:5,"
    'DEVICE_MODEL:"MC7010",DEVICE:"cpe/MF253V",PASSWORD_ENCODE:!0,'
    "WEB_ATTR_IF_SUPPORT_SHA256:2,IS_SUPPORT_USERNAME:!0,HAS_LOGIN:!0,"
    # Kept in the fixture precisely because it is of no interest: the parser
    # reads ninety of these on a real device and publishes the handful that
    # bear on a request.
    "AP_STATION_LIST_LENGTH:10}})"
)

MC7010 = {
    "js/service.js": _MC7010_SERVICE,
    "js/util.js": _MC7010_UTIL,
    "js/config/config.js": _MC7010_CONFIG,
}

# The MC888 Pro's shape: the same structure with a wrapper in front of the
# digest, and the `flux_`/`dial_` field spellings.
_MC888_SERVICE = (
    _MC7010_SERVICE.replace("hex_md5", "cookWithRequest")
    .replace("data_volume_", "flux_data_volume_")
    .replace("wan_auto_clear_flow_data_switch", "flux_auto_clear_flow_data_switch")
    .replace("traffic_clear_date", "flux_clear_date")
    .replace("roam_setting_option", "dial_roam_setting_option")
    .replace(',goformId:"LOGIN",username:e.username', ',goformId:"LOGIN"')
)

_MC888_UTIL = (
    "function paswordAlgorithmsCookie(e){return SHA256(e)}"
    "function cookWithRequest(e){return SHA256(e)}"
    "function SHA256(e){return e}"
)

MC888 = {
    "js/service.js": _MC888_SERVICE,
    "js/util.js": _MC888_UTIL,
    "js/config/config.js": _MC7010_CONFIG.replace("MC7010", "MC888Pro"),
}


# ---------------------------------------------------------------------------
# The token expression
# ---------------------------------------------------------------------------


def test_the_reference_device_names_its_digest_in_the_expression() -> None:
    """`hex_md5(rd0+rd1)` … `hex_md5(o+u)`, with both operands and the salt."""
    token = device_profile.parse_profile(MC7010)["token"]

    assert token["digest_function"] == "hex_md5"
    assert token["operands"] == ["rd0", "rd1"]
    assert token["rounds"] == 2
    assert token["salt_key"] == "RD"
    assert token["exempt_commands"] == ["LOGIN", "SET_WEB_LANGUAGE"]
    assert token["gate_flag"] == "ACCESSIBLE_ID_SUPPORT"
    assert token["operand_values"] == {
        "rd0": "wa_inner_version",
        "rd1": "cr_version",
    }


def test_a_digest_defined_in_a_library_file_is_unresolved_not_guessed() -> None:
    """The MC7010's own branch, and the reason item 9 needed a name table.

    `hex_md5` is in `_DIGEST_NAMES` because an accepted MC7010 token proves
    what it computes. Nothing in the returned sources defines it — it lives
    under `js/lib/`, which the crawl fetches and does not return — so a parser
    that resolved only by reading definitions would have learned nothing from
    the one device this project can put a write on.
    """
    assert device_profile._DIGEST_NAMES["hex_md5"] == ("md5", "lower")

    unknown = {"js/service.js": _MC7010_SERVICE.replace("hex_md5", "zte_digest_x")}
    digest = device_profile.parse_profile(unknown)["token"]["digest"]

    assert digest["resolved_via"] == "unresolved_definition_not_returned"
    assert "algorithm" not in digest
    assert device_profile.digest_callable("", "") is None


def test_a_wrapper_resolves_one_hop_to_what_it_forwards_to() -> None:
    """The MC888 Pro's shape, which only that device exercises."""
    digest = device_profile.parse_profile(MC888)["token"]["digest"]

    assert digest["function"] == "cookWithRequest"
    assert digest["forwards_to"] == "SHA256"
    assert digest["algorithm"] == "sha256"
    assert digest["case"] == "upper"
    assert digest["resolved_via"] == "one_hop"

    derive = device_profile.digest_callable("sha256", "upper")
    assert derive is not None
    assert derive("a") == derive("a").upper()


def test_a_wrapper_forwarding_to_something_unknown_stays_unresolved() -> None:
    """One hop is a resolution step, not a licence to assume the target."""
    sources = dict(MC888)
    sources["js/util.js"] = "function cookWithRequest(e){return ZteDigest(e)}"
    digest = device_profile.parse_profile(sources)["token"]["digest"]

    assert digest["forwards_to"] == "ZteDigest"
    assert digest["resolved_via"] == "one_hop_unknown_target"


def test_a_name_defined_here_but_unrecognised_says_so_differently() -> None:
    """Two unresolved states, because they point at different next steps.

    "Defined in a file we did not return" is a crawl question. "Defined here
    and not recognised" is a firmware this project has never seen a token
    from, and the only thing that settles it is an accepted write.
    """
    sources = {
        "js/service.js": _MC7010_SERVICE.replace("hex_md5", "zte_digest_x"),
        "js/util.js": "function zte_digest_x(e){var t=e;return t+t}",
    }
    digest = device_profile.parse_profile(sources)["token"]["digest"]

    assert digest["resolved_via"] == "unresolved_unknown_implementation"


def test_two_rounds_using_different_functions_withdraw_the_digest() -> None:
    """One name cannot describe two digests, so it describes neither."""
    mixed = {
        "js/service.js": _MC7010_SERVICE.replace("hex_md5(o+u)", "SHA256(o+u)"),
        "js/util.js": _MC7010_UTIL,
    }
    digest = device_profile.parse_profile(mixed)["token"]["digest"]

    assert digest["resolved_via"] == "unresolved_rounds_disagree"


def test_sites_disagreeing_on_the_digest_withdraw_it_rather_than_averaging() -> None:
    """A firmware whose sites disagree is left to the fallback.

    Both devices name the same function at every one of theirs, so a
    disagreement is beyond what a single name can describe.
    """
    conflicting = _MC7010_SERVICE + _MC7010_SERVICE.replace(
        "hex_md5", "cookWithRequest"
    )
    token = device_profile.parse_profile({"js/service.js": conflicting})["token"]

    assert token["digest_conflict"] is True
    assert "digest_function" not in token
    assert (
        "token.digest_function"
        in device_profile.parse_profile({"js/service.js": conflicting})["unlearned"]
    )


def test_an_expression_with_no_salt_read_is_not_a_token_site() -> None:
    """Two rounds and a salt, or it is some other use of the same operands."""
    partial = {"js/service.js": "var o=hex_md5(rd0+rd1);e.AD=o"}
    token = device_profile.parse_profile(partial)["token"]

    assert token["sites"] == 0
    assert "digest_function" not in token


# ---------------------------------------------------------------------------
# Fields, flags, login and the session flag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "mc7010_fields", "mc888_fields"),
    [
        # The literal shape, identical on both.
        ("DELETE_SMS", ["msg_id"], ["msg_id"]),
        # The var shape, identical on both.
        ("ODU_LED_SWITCH_SET", ["ODU_led_switch"], ["ODU_led_switch"]),
        # The var shape, differing — and the difference is a prefix on the
        # same tail, which is what `profile_field` matches on.
        (
            "SET_CONNECTION_MODE",
            ["ConnectionMode", "roam_setting_option"],
            ["ConnectionMode", "dial_roam_setting_option"],
        ),
        # A command that carries no payload at all. Recorded as empty, which
        # is an answer; absent would be a different one.
        ("REBOOT_DEVICE", [], []),
    ],
)
def test_each_builder_shape_yields_the_fields_that_device_sends(
    command: str, mc7010_fields: list[str], mc888_fields: list[str]
) -> None:
    """Each of the three builder shapes, on both devices."""
    assert device_profile.parse_profile(MC7010)["commands"][command] == mc7010_fields
    assert device_profile.parse_profile(MC888)["commands"][command] == mc888_fields


def test_the_mixed_builder_is_read_past_its_literal() -> None:
    """The mixed builder is read past its literal.

    `var i={...goformId...}` then `i.field=` — the shape that carries the
    difference issue #56 turned on.
    """
    assert device_profile.parse_profile(MC7010)["commands"]["DATA_LIMIT_SETTING"] == [
        "data_volume_limit_size",
        "data_volume_limit_unit",
        "traffic_clear_date",
        "wan_auto_clear_flow_data_switch",
    ]
    assert device_profile.parse_profile(MC888)["commands"]["DATA_LIMIT_SETTING"] == [
        "flux_auto_clear_flow_data_switch",
        "flux_clear_date",
        "flux_data_volume_limit_size",
        "flux_data_volume_limit_unit",
    ]


def test_flags_are_read_as_the_values_the_minified_literals_stand_for() -> None:
    """`!0` is True, `!1` is False, and a bare number is a number."""
    flags = device_profile.parse_profile(MC7010)["flags"]

    assert flags["ACCESSIBLE_ID_SUPPORT"] is True
    assert flags["MAX_LOGIN_COUNT"] == 5
    assert flags["DEVICE_MODEL"] == "MC7010"
    assert flags["WEB_ATTR_IF_SUPPORT_SHA256"] == 2
    assert "AP_STATION_LIST_LENGTH" not in flags, "an uninteresting flag was kept"


def test_a_model_specific_config_overrides_the_general_one() -> None:
    """The loader composes them in that order, and so does this."""
    sources = dict(MC7010)
    sources["js/config/cpe/MF253V/config.js"] = "return{ACCESSIBLE_ID_SUPPORT:!1}"
    flags = device_profile.parse_profile(sources)["flags"]

    assert flags["ACCESSIBLE_ID_SUPPORT"] is False


def test_a_false_flag_is_read_as_false_and_not_as_absent() -> None:
    """`!1` and "no such flag" route to opposite behaviour in `_token_required`."""
    assert device_profile._flag_value("!1") is False
    assert device_profile._flag_value("false") is False
    assert device_profile._flag_value("true") is True
    assert device_profile._flag_value('"x"') == "x"
    assert device_profile._flag_value("-3") == -3


def test_the_login_form_names_its_password_encoding_and_whether_it_takes_a_user() -> (
    None
):
    """The MC888 Pro's form carries no username; the MC7010's does."""
    mc7010 = device_profile.parse_profile(MC7010)["login"]
    mc888 = device_profile.parse_profile(MC888)["login"]

    assert mc7010["carries_username"] is True
    assert mc888["carries_username"] is False
    assert mc7010["salt_read"] == "LD"
    assert mc7010["password_branches"]["2"] == "paswordAlgorithmsCookie"
    assert mc7010["password_digest"]["algorithm"] == "sha256"


def test_the_session_flag_is_the_one_the_device_trusts_itself() -> None:
    """Item 28, delivered as what the scripts can actually answer."""
    for sources in (MC7010, MC888):
        flag = device_profile.parse_profile(sources)["session_flag"]
        assert flag["key"] == "loginfo"
        assert flag["ok_value"] == "ok"
        assert flag["bypass_flag"] == "HAS_LOGIN"
        assert flag["read_alone"] is True


def test_nothing_is_left_unlearned_on_either_device() -> None:
    """The measurement this whole section rests on."""
    assert device_profile.parse_profile(MC7010, "v")["unlearned"] == []
    assert device_profile.parse_profile(MC888, "v")["unlearned"] == []


def test_an_empty_crawl_names_everything_it_could_not_learn() -> None:
    """A device that serves nothing must say so field by field, not silently."""
    empty = device_profile.parse_profile({}, "v")

    assert empty["profile_version"] == device_profile.PROFILE_VERSION
    assert empty["firmware"] == "v"
    assert set(empty["unlearned"]) == {
        "token.digest_function",
        "token.operand_values",
        "token.exempt_commands",
        "flags.ACCESSIBLE_ID_SUPPORT",
        "flags.MAX_LOGIN_COUNT",
        "commands",
        "login.password_branches",
        "session_flag.key",
    }


def test_a_non_text_source_is_skipped_rather_than_crashing_the_parse() -> None:
    """The crawl records a failed fetch as a note, not as a body."""
    sources: dict[str, object] = dict(MC7010)
    sources["js/broken.js"] = {"status": 404}
    assert device_profile.parse_profile(sources)["unlearned"] == []


# ---------------------------------------------------------------------------
# What the API does with it
# ---------------------------------------------------------------------------


def _api(profile: dict | None = None) -> ZTERouterAPI:
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    if profile is not None:
        api.profile = profile
    return api


def test_the_digest_comes_from_the_script_and_not_from_the_model_string() -> None:
    """The heuristic's own counter-example, run both ways.

    A firmware string with no `MC888` in it would take the MD5 branch. Where
    the script says SHA-256, the script wins — which is the entire point of
    item 19, because `config.js` is comparable between the two devices on
    every flag that could plausibly select a digest.
    """
    api = _api(device_profile.parse_profile(MC888, "xx_xxx_MC7010DV1.0.0B03"))
    learned = api._ad_hash_func("xx_xxx_MC7010DV1.0.0B03")

    assert learned("a") == learned("a").upper()
    assert len(learned("a")) == 64
    assert api.profile_decisions["ad_digest"] == "learned"


def test_an_unresolved_digest_falls_back_to_the_model_string() -> None:
    """Item 30. The fallback is today's behaviour, and it is recorded as such."""
    profile = device_profile.parse_profile(
        {"js/service.js": _MC7010_SERVICE.replace("hex_md5", "zte_digest_x")}
    )
    api = _api(profile)

    assert len(api._ad_hash_func("xx_xxx_MC7010DV1.0.0B03")("a")) == 32
    assert api.profile_decisions["ad_digest"] == "fallback_unresolved"

    bare = _api()
    assert len(bare._ad_hash_func("MC888PRO")("a")) == 64
    assert bare.profile_decisions["ad_digest"] == "fallback_not_learned"


@pytest.mark.parametrize(
    ("command", "canonical", "expected", "decision"),
    [
        ("ODU_LED_SWITCH_SET", "ODU_led_switch", "ODU_led_switch", "learned_exact"),
        (
            "SET_CONNECTION_MODE",
            "roam_setting_option",
            "dial_roam_setting_option",
            "learned_suffix",
        ),
        ("REBOOT_DEVICE", "anything", "anything", "fallback_not_learned"),
        ("SET_CONNECTION_MODE", "unheard_of", "unheard_of", "fallback_not_named"),
    ],
)
def test_a_field_is_spelled_the_way_this_firmware_spells_it(
    command: str, canonical: str, expected: str, decision: str
) -> None:
    """Exact match, suffix match, and the two ways of having no answer."""
    api = _api(device_profile.parse_profile(MC888, "v"))

    assert api.profile_field(command, canonical) == expected
    assert api.profile_decisions[f"field:{command}.{canonical}"] == decision


def test_two_fields_sharing_a_tail_resolve_to_the_canonical_name() -> None:
    """An ambiguous suffix is not a licence to pick one.

    Guessing here replaces the whole form with a payload the router refuses,
    and the refusal says nothing about which field was wrong.
    """
    api = _api(
        {"commands": {"X": ["flux_limit_size", "dial_limit_size"]}},
    )

    assert api.profile_field("X", "limit_size") == "limit_size"
    assert api.profile_decisions["field:X.limit_size"] == "fallback_ambiguous"


@pytest.mark.asyncio
async def test_a_command_the_firmware_exempts_carries_no_token() -> None:
    """Item 20 and item 35, on the same switch.

    `LOGIN` is exempt on both devices, and the session is still asserted —
    needing no token is not the same as needing no session.
    """
    api = _api(device_profile.parse_profile(MC7010, "v"))
    with patch.object(api, "_ensure_session", new=AsyncMock()) as ensure:
        assert await api.ad_suffix("LOGIN") == ""
    ensure.assert_awaited_once()
    assert api.profile_decisions["token:LOGIN"] == "learned_exempt"


@pytest.mark.asyncio
async def test_a_device_whose_gate_flag_is_off_carries_no_token_at_all() -> None:
    """A device whose gate flag is off carries no token at all.

    No device has been seen with `ACCESSIBLE_ID_SUPPORT` off. The branch is
    the device's own, read from its own config, and that is why the gate is
    read rather than assumed.
    """
    profile = device_profile.parse_profile(MC7010, "v")
    profile["flags"]["ACCESSIBLE_ID_SUPPORT"] = False
    api = _api(profile)

    with patch.object(api, "_ensure_session", new=AsyncMock()):
        assert await api.ad_suffix("DELETE_SMS") == ""
    assert api.profile_decisions["token:DELETE_SMS"] == "learned_not_required_gate_off"


@pytest.mark.asyncio
async def test_every_other_command_still_carries_one() -> None:
    """The default, learned and unlearned alike: a write carries a token."""
    api = _api(device_profile.parse_profile(MC7010, "v"))
    with patch.object(api, "get_ad", new=AsyncMock(return_value="TOKEN")):
        assert await api.ad_suffix("DELETE_SMS") == "&AD=TOKEN"
    assert api.profile_decisions["token:DELETE_SMS"] == "learned_required"

    bare = _api()
    with patch.object(bare, "get_ad", new=AsyncMock(return_value="TOKEN")):
        assert await bare.ad_suffix("DELETE_SMS") == "&AD=TOKEN"
    assert bare.profile_decisions["token:DELETE_SMS"] == "fallback_required"


def test_the_login_budget_never_exceeds_what_the_device_tolerates() -> None:
    """Item 24: the budget never exceeds what the device tolerates.

    Exceeding `MAX_LOGIN_COUNT` is a lockout measured in minutes, and one
    attempt is held back for the person typing into the web interface.
    """
    api = _api({"flags": {"MAX_LOGIN_COUNT": 2}})
    assert api.login_budget() == 1
    assert api.profile_decisions["login_budget"] == "learned"

    generous = _api({"flags": {"MAX_LOGIN_COUNT": 99}})
    assert generous.login_budget() == 3

    assert _api().login_budget() == 3
    assert _api({"flags": {"MAX_LOGIN_COUNT": 1}}).login_budget() == 3
    assert _api({"flags": {"MAX_LOGIN_COUNT": "many"}}).login_budget() == 3


@pytest.mark.asyncio
async def test_a_firmware_naming_other_operands_is_read_the_way_it_asks() -> None:
    """Item 18, on the branch no known device takes.

    Both readable devices name `wa_inner_version` and `cr_version`, so the
    learned answer confirms the shipped readers rather than replacing them.
    A firmware naming anything else is read generically instead — and that is
    the difference between a profile and a formula written here.
    """
    profile = device_profile.parse_profile(MC7010, "v")
    profile["token"]["operand_values"] = {"rd0": "sw_version", "rd1": "hw_version"}
    api = _api(profile)

    reads: list[str] = []

    async def request(_method, path, **_kwargs):
        reads.append(path)
        return {"sw_version": "S", "hw_version": "H", "RD": "R"}

    with (
        patch.object(api, "_ensure_session", new=AsyncMock()),
        patch.object(api, "get_version", new=AsyncMock(return_value="V")),
        patch.object(api, "get_rd", new=AsyncMock(return_value="R")),
        patch.object(api, "_request", side_effect=request),
    ):
        token = await api.get_ad()

    assert api.profile_decisions["ad_operands"] == "learned_other"
    assert any("sw_version,hw_version" in path for path in reads)
    derive = device_profile.digest_callable("md5", "lower")
    assert derive is not None
    assert token == derive(derive("SH") + "R")


@pytest.mark.asyncio
async def test_learning_reads_the_crawl_and_keeps_what_it_says() -> None:
    """A learn pass crawls, parses, and keeps the result on the API."""
    api = _api()
    with (
        patch(
            "custom_components.zte_router_5g.web_sources.crawl",
            new=AsyncMock(return_value={"sources": MC888}),
        ),
        patch.object(api, "get_version", new=AsyncMock(return_value="FW1")),
    ):
        profile = await api.learn_profile()

    assert profile["firmware"] == "FW1"
    assert api.profile is profile
    assert profile["token"]["digest"]["algorithm"] == "sha256"


@pytest.mark.asyncio
async def test_learning_from_handed_sources_fetches_nothing() -> None:
    """The diagnostics download crawls once and both consumers read it."""
    api = _api()
    with (
        patch(
            "custom_components.zte_router_5g.web_sources.crawl",
            new=AsyncMock(side_effect=AssertionError("crawled twice")),
        ),
        patch.object(api, "get_version", new=AsyncMock(return_value="FW1")),
    ):
        assert (await api.learn_profile(MC7010))["unlearned"] == []


# ---------------------------------------------------------------------------
# Item 25 — the login form's password encoding
# ---------------------------------------------------------------------------


def _expected_fallback(password: str, ld: str) -> str:
    """The salted double hash this integration has always sent."""
    import hashlib

    inner = hashlib.sha256(password.encode()).hexdigest().upper()
    return hashlib.sha256((inner + ld).encode()).hexdigest().upper()


def test_a_learned_encoding_agrees_with_the_one_that_ships() -> None:
    """Both readable devices answer `2`, and the learned form matches.

    This is the assertion that makes the change safe rather than the one that
    makes it interesting: on every device this project can reach, learning the
    encoding changes nothing about what goes on the wire.
    """
    api = _api(device_profile.parse_profile(MC7010, "v"))

    assert api._login_password("secret", "LD1") == _expected_fallback("secret", "LD1")
    assert api.profile_decisions["login_password"] == "learned_salted_double_hash"


@pytest.mark.parametrize(
    ("flag", "decision"),
    [(1, "learned_hashed_base64"), (0, "learned_base64")],
)
def test_the_other_two_branches_are_the_forms_the_script_names(
    flag: int, decision: str
) -> None:
    """A device on either of these fails to log in today, silently.

    Its refusal is `result=3`, which this integration reports as a wrong
    password — so the user is sent to check a credential that was correct all
    along.
    """
    profile = device_profile.parse_profile(MC7010, "v")
    profile["flags"]["WEB_ATTR_IF_SUPPORT_SHA256"] = flag
    api = _api(profile)

    assert api._login_password("secret", "LD1") != _expected_fallback("secret", "LD1")
    assert api.profile_decisions["login_password"] == decision


@pytest.mark.parametrize(
    ("mutate", "decision"),
    [
        (lambda p: p.update(flags={}), "fallback_not_learned"),
        (lambda p: p.update(login={}), "fallback_not_learned"),
        (
            lambda p: p["flags"].update(WEB_ATTR_IF_SUPPORT_SHA256=7),
            "fallback_unknown_flag",
        ),
        (
            lambda p: p["login"].update(password_digest={}),
            "fallback_digest_unresolved",
        ),
    ],
)
def test_anything_unresolved_sends_the_form_that_ships(
    mutate: Callable[[dict], None], decision: str
) -> None:
    """A login is the one request that must not be experimented with.

    `MAX_LOGIN_COUNT` is five on both known devices and the lockout is minutes
    long, so every gap in the profile routes back to the known-good form.
    """
    profile = device_profile.parse_profile(MC7010, "v")
    mutate(profile)
    api = _api(profile)

    assert api._login_password("secret", "LD1") == _expected_fallback("secret", "LD1")
    assert api.profile_decisions["login_password"] == decision


def test_a_device_with_no_profile_sends_the_form_that_ships() -> None:
    """The path every installation takes before the first background learn."""
    api = _api()

    assert api._login_password("secret", "LD1") == _expected_fallback("secret", "LD1")
    assert api.profile_decisions["login_password"] == "fallback_not_learned"
