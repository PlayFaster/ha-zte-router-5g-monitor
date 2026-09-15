"""Learn a router's write contract from the files it serves to its own browser.

Every ZTE goform device ships the web interface that drives it, and that
interface contains the answers this integration has otherwise been guessing:
which digest builds the `AD` token, which two values the token hashes, which
commands are exempt from it, how the login form encodes a password, and what a
given write command's payload is actually called on that firmware.

**Nothing here decides anything on its own.** Every fact is returned with the
evidence that produced it, and every fact can be absent. A caller takes a
learned value where one exists and its own constant where one does not — per
fact, never wholesale, because a firmware that hides one answer still supplies
the rest. `api.py` is where that choice is made; this module only reads.

**Nothing here is called on a write path.** Parsing minified JavaScript costs
tens of milliseconds and can fail on a firmware nobody has seen; a write that
waited for it would be a write this integration could block. The profile is
learned in the background, cached against the firmware version it was read
from, and consulted from memory.

The parser is deliberately shape-based rather than literal-based. Minified code
renames every variable, so `hex_md5(rd0+rd1)` and `cookWithRequest(rd0+rd1)`
differ in the only part that is stable — the operand names, which are globals
and therefore survive minification. Matching on those and reading the function
name out of the match is what lets one parser read two firmwares that share no
identifier.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Any

# Bumped when the shape of a stored profile changes in a way that makes an
# older cached one unreadable. A profile carrying a different number is
# discarded and re-learned rather than migrated: it describes a device that is
# still there to be asked again.
PROFILE_VERSION = 1

# The file a fact is read from, when the parser needs to name one. Everything
# else is found by searching every source the crawl returned, because which
# file holds what differs between firmwares — the digest is defined in
# `js/util.js` on one device and in `js/lib/md5.js` on the other.
_CONFIG_FILE = "js/config/config.js"


# ---------------------------------------------------------------------------
# The digest name table
# ---------------------------------------------------------------------------

# **A name maps to a digest only where a real device's accepted token proves
# it.** Both entries below are evidenced: the MC7010's writes are accepted with
# lowercase MD5 built by `hex_md5`, and the MC888 Pro's accepted browser token
# of 2026-09-11 reproduces exactly as uppercase SHA-256 built by `SHA256`.
#
# A name that is not here is *unresolved*, which is a state and not a guess.
# Inventing an entry from a plausible-looking name would put a well-formed
# wrong token on the wire, and a wrong token is refused with nothing said about
# why — the failure mode this whole plan exists to remove.
_DIGEST_NAMES: dict[str, tuple[str, str]] = {
    "hex_md5": ("md5", "lower"),
    "SHA256": ("sha256", "upper"),
}

# `function cookWithRequest(e){return SHA256(e)}` — a wrapper whose whole body
# is a call to something else. Resolved one hop, then looked up in the table
# above. Two such wrappers are known and neither is in the table, because what
# they mean is whatever they forward to.
_ONE_HOP = re.compile(
    r"""function\s+(\w+)\s*\(\s*(\w+)\s*\)\s*\{\s*return\s+(\w+)\s*\(\s*\2\s*\)\s*;?\s*\}"""
)

_DEFINED_HERE = re.compile(r"""function\s+(\w+)\s*\(""")


def digest_callable(algorithm: str, case: str) -> Callable[[str], str] | None:
    """The function this firmware's named digest corresponds to, or None.

    `None` for anything the parser did not resolve, so a caller that forgets to
    check gets an error rather than a token built with the wrong digest.
    """
    if algorithm == "sha256":

        def raw(value: str) -> str:
            return hashlib.sha256(value.encode()).hexdigest()

    elif algorithm == "md5":

        def raw(value: str) -> str:
            # MD5 is the legacy ZTE web API's own choice, not this project's.
            return hashlib.md5(value.encode()).hexdigest()  # noqa: S324

    else:
        return None
    if case == "upper":

        def upper(value: str) -> str:
            return raw(value).upper()

        return upper
    if case == "lower":
        return raw
    return None


def _resolve_digest(name: str, sources: dict[str, str]) -> dict[str, Any]:
    """What a named function in this firmware computes.

    Three outcomes, and the third is as much a result as the other two: the
    name is known, the name forwards one hop to a known name, or the firmware
    implements something this project has never seen an accepted token for.
    """
    if name in _DIGEST_NAMES:
        algorithm, case = _DIGEST_NAMES[name]
        return {
            "function": name,
            "algorithm": algorithm,
            "case": case,
            "resolved_via": "name_table",
        }
    for text in sources.values():
        for match in _ONE_HOP.finditer(text):
            if match.group(1) != name:
                continue
            target = match.group(3)
            if target in _DIGEST_NAMES:
                algorithm, case = _DIGEST_NAMES[target]
                return {
                    "function": name,
                    "forwards_to": target,
                    "algorithm": algorithm,
                    "case": case,
                    "resolved_via": "one_hop",
                }
            return {
                "function": name,
                "forwards_to": target,
                "resolved_via": "one_hop_unknown_target",
            }
    # Defined somewhere the crawl did not return is a different answer from not
    # defined at all: `hex_md5` lives under `js/lib/`, which the crawl fetches
    # and deliberately does not return, so the MC7010 reaches here and the
    # distinction is what tells a reader the crawl is not at fault.
    defined = any(
        match.group(1) == name
        for text in sources.values()
        for match in _DEFINED_HERE.finditer(text)
    )
    return {
        "function": name,
        "resolved_via": "unresolved_definition_not_returned"
        if not defined
        else "unresolved_unknown_implementation",
    }


# ---------------------------------------------------------------------------
# The `AD` token expression
# ---------------------------------------------------------------------------

# `var a=F(rd0+rd1)`. `rd0` and `rd1` are globals assigned in `js/main.js`, so
# a minifier cannot rename them and this match holds across firmwares that
# share no other identifier.
_FIRST_ROUND = re.compile(r"""(\w+)\s*\(\s*(rd\d)\s*\+\s*(rd\d)\s*\)""")

# `var c=F(a+u)` immediately after, where `u` came from the `RD` read.
_SECOND_ROUND = re.compile(r"""(\w+)\s*\(\s*(\w+)\s*\+\s*(\w+)\s*\)""")

# `L_({nv:"RD"}).RD` — the salt, named twice in its own expression.
_NV_READ = re.compile(r"""\{\s*nv\s*:\s*["'](\w+)["']\s*\}\s*\)\s*\.\s*(\w+)""")

# `"LOGIN"!=e.goformId&&"SET_WEB_LANGUAGE"!=e.goformId` — the commands sent
# without a token.
_EXEMPT = re.compile(r"""["']([A-Z][A-Z0-9_]{2,40})["']\s*!==?\s*\w+\.goformId""")

# `n.ACCESSIBLE_ID_SUPPORT&&...` — the flag that decides whether a token is
# carried at all.
_GATE = re.compile(r"""(\w+)\.([A-Z][A-Z0-9_]{3,40})\s*&&[^;{]{0,40}?goformId""")

# `rd_params0=e.wa_inner_version` — which reading each operand resolves to.
_RD_PARAM = re.compile(r"""rd_params(\d)\s*[=:]\s*\w+\.(\w+)""")

# How far past the first round the second one is allowed to sit. Measured at 30
# characters on both devices; a hundred is slack, not a discovery.
_ROUND_WINDOW = 200


def parse_token(sources: dict[str, str]) -> dict[str, Any]:
    """How this firmware builds the `AD` token every write carries.

    Returns whatever was found. A caller reads each key and falls back
    independently, because a firmware that renames its digest still names its
    operands the same way.
    """
    token: dict[str, Any] = {"sites": 0}
    for path, text in sources.items():
        for first in _FIRST_ROUND.finditer(text):
            window = text[first.end() : first.end() + _ROUND_WINDOW]
            second = _SECOND_ROUND.search(window)
            salt = _NV_READ.search(window)
            if not second or not salt:
                continue
            token["sites"] = token["sites"] + 1
            if "digest_function" in token:
                # Every site on both devices names the same function. A
                # firmware where they disagree is not something to average: it
                # is recorded and left unresolved.
                if token["digest_function"] != first.group(1):
                    token["digest_conflict"] = True
                continue
            token["found_in"] = path
            token["digest_function"] = first.group(1)
            token["operands"] = [first.group(2), first.group(3)]
            # **The shape this parser recognises, not a count it measured.**
            # It looks for one call over the operands and one over the result
            # and the salt; a firmware doing three would not be reported as
            # three, it would fail to match the second round and yield no
            # token site at all. The field exists so `get_ad` can refuse a
            # shape it does not implement rather than assume every profile
            # describes the one it does.
            token["rounds"] = 2
            token["second_round_function"] = second.group(1)
            token["salt_read"] = salt.group(1)
            token["salt_key"] = salt.group(2)
            exempt = sorted(
                {
                    match.group(1)
                    for match in _EXEMPT.finditer(
                        text[max(0, first.start() - 400) : first.start()]
                    )
                }
            )
            if exempt:
                token["exempt_commands"] = exempt
            gate = _GATE.search(text[max(0, first.start() - 400) : first.start()])
            if gate:
                token["gate_flag"] = gate.group(2)

    if token.get("digest_conflict"):
        token.pop("digest_function", None)
        return token
    name = token.get("digest_function")
    if name:
        token["digest"] = _resolve_digest(name, sources)
        if token.get("second_round_function") != name:
            # Both rounds use the same function on both devices. A firmware
            # that mixes two digests is beyond what one name can describe, so
            # the digest is withdrawn rather than half-applied.
            token["digest"] = {
                "function": name,
                "resolved_via": "unresolved_rounds_disagree",
            }

    operand_values: dict[str, str] = {}
    for text in sources.values():
        for match in _RD_PARAM.finditer(text):
            operand_values[f"rd{match.group(1)}"] = match.group(2)
    if operand_values:
        token["operand_values"] = operand_values
    return token


# ---------------------------------------------------------------------------
# Firmware flags
# ---------------------------------------------------------------------------

_FLAG = re.compile(
    r"""\b([A-Z][A-Z0-9_]{2,48})\s*:\s*(!1|!0|true|false|-?\d{1,9}|"[^"]{0,60}")"""
)

# What a flag is worth reading for. Everything else in `config.js` describes a
# user interface this integration does not draw — whether to show a QR code,
# how many stations a table holds — and publishing ninety of them would bury
# the five that bear on a request.
_FLAGS_OF_INTEREST: frozenset[str] = frozenset(
    {
        "ACCESSIBLE_ID_SUPPORT",
        "DEVICE",
        "DEVICE_MODEL",
        "DEVICE_TYPE",
        "HAS_LOGIN",
        "HAS_SMS",
        "IS_SUPPORT_USERNAME",
        "LOGIN_SECURITY_SUPPORT",
        "MAX_LOGIN_COUNT",
        "PASSWORD_ENCODE",
        "PASSWORD_ENCODE_SHA256",
        "PRODUCT_TYPE",
        "SMS_DATABASE_SORT_SUPPORT",
        "WEB_ATTR_IF_SUPPORT_SHA256",
    }
)


def _flag_value(raw: str) -> Any:
    """A minified literal as the value it stands for."""
    if raw in ("!0", "true"):
        return True
    if raw in ("!1", "false"):
        return False
    if raw.startswith('"'):
        return raw[1:-1]
    return int(raw)


def parse_flags(sources: dict[str, str]) -> dict[str, Any]:
    """The firmware flags that bear on a request, from every config file.

    Read from every source rather than from `config.js` alone: the reference
    device carries a model-specific `js/config/cpe/MF253V/config.js` that
    overrides the general one, and a build whose write path differs could
    differ there and nowhere else. Later files win, which is the order the
    loader composes them in.
    """
    flags: dict[str, Any] = {}
    for path in sorted(sources, key=lambda name: (name != _CONFIG_FILE, name)):
        if "config" not in path:
            continue
        for match in _FLAG.finditer(sources[path]):
            if match.group(1) in _FLAGS_OF_INTEREST:
                flags[match.group(1)] = _flag_value(match.group(2))
    return flags


# ---------------------------------------------------------------------------
# Per-command payload fields
# ---------------------------------------------------------------------------

_GOFORM_ID = re.compile(r"""goformId\s*([=:])\s*["']([A-Z][A-Z0-9_]{2,48})["']""")

# `n.goformId="X"` names the variable the payload is being built on, so every
# other `n.field=` in the same builder is a field of that command.
_ASSIGN_PREFIX = re.compile(r"""(\w+)\s*\.\s*goformId\s*=\s*["']""")

# Keys carried by the request machinery rather than by the command. `isTest`
# picks the simulator; `notCallback` is a client-side flag; `AD` is the token.
_NOT_A_FIELD: frozenset[str] = frozenset({"isTest", "goformId", "AD", "notCallback"})

# How far a builder may run. The longest on either device is under 900
# characters; four thousand bounds a pathological match without truncating a
# real one.
_BUILDER_WINDOW = 4000


def _literal_keys(text: str, index: int) -> tuple[list[str], int, str | None]:
    """Top-level keys of the object literal containing `index`.

    Returns the keys, where the literal ends, and the name of the variable it
    is assigned to, if any.

    A brace scan rather than a regex, because a payload literal contains
    function calls with their own braces — `getEncodeType(e.message).encodeType`
    sits beside `Number:e.number` in the same object.
    """
    start = text.rfind("{", max(0, index - _BUILDER_WINDOW), index)
    if start < 0:
        return [], index, None
    depth = 0
    keys: list[str] = []
    position = start
    end = index
    while position < min(len(text), start + _BUILDER_WINDOW):
        char = text[position]
        if char in "\"'":
            quote = char
            position += 1
            while position < len(text) and text[position] != quote:
                position += 2 if text[position] == "\\" else 1
        elif char in "{[(":
            depth += 1
        elif char in "}])":
            depth -= 1
            if depth == 0:
                end = position
                break
        elif depth == 1:
            match = re.match(
                r"""[,{]?\s*(\w+)\s*:""", text[position - 1 : position + 60]
            )
            if match and text[position - 1] in ",{":
                keys.append(match.group(1))
        position += 1
    # `var i={isTest:no,goformId:"X"}` — on the mixed builder the literal is
    # only half the payload and the rest arrives as `i.field=` assignments
    # afterwards. Naming the variable here is what lets the caller collect
    # them; `DATA_LIMIT_SETTING` is built that way on both devices, and it is
    # the one command already known to differ between them.
    held_by = re.search(
        r"""(?:var\s+)?(\w+)\s*=\s*$""", text[max(0, start - 40) : start]
    )
    return (
        [key for key in keys if key not in _NOT_A_FIELD],
        end,
        held_by.group(1) if held_by else None,
    )


def parse_commands(sources: dict[str, str]) -> dict[str, list[str]]:
    """Each write command's payload field names, as this firmware builds them.

    This is what makes an alias map something the device supplies rather than
    something written here from one router's behaviour. Two commands already
    differ between the only two devices this project can read:
    `DATA_LIMIT_SETTING` is built with the `flux_` spellings on the MC888 Pro
    and without them on the MC7010, and `SET_CONNECTION_MODE` carries
    `dial_roam_setting_option` where the MC7010 carries `roam_setting_option`.
    """
    commands: dict[str, set[str]] = {}
    for text in sources.values():
        for match in _GOFORM_ID.finditer(text):
            name = match.group(2)
            fields: set[str] = set()
            variable: str | None = None
            after = match.end()
            if match.group(1) == ":":
                keys, after, variable = _literal_keys(text, match.start())
                fields.update(keys)
            else:
                assigned = None
                for candidate in _ASSIGN_PREFIX.finditer(
                    text[max(0, match.start() - 40) : match.end()]
                ):
                    assigned = candidate
                if assigned:
                    variable = assigned.group(1)
            if variable:
                window = text[after : after + _BUILDER_WINDOW]
                # Whichever boundary comes first. `return i` ends the builder
                # on the plain shapes, but `DATA_LIMIT_SETTING` returns a
                # conditional expression and reaches its `return i` well past
                # the end of the payload — far enough, on the MC888 Pro, to
                # walk into the next builder and collect a field of `USSD_PROCESS`
                # from it, because a minifier reuses variable names freely.
                stops = [
                    found
                    for found in (
                        window.find(f"return {variable}"),
                        window.find("}function "),
                    )
                    if found >= 0
                ]
                if stops:
                    window = window[: min(stops)]
                fields.update(
                    found.group(1)
                    for found in re.finditer(
                        rf"""\b{re.escape(variable)}\s*\.\s*(\w+)\s*=[^=]""", window
                    )
                    if found.group(1) not in _NOT_A_FIELD
                )
            # Recorded even when empty. `REBOOT_DEVICE` carries no payload at
            # all, and "this command has no fields" is an answer a caller can
            # act on; "this command was not found" is a different answer and
            # must not be spelled the same way.
            commands.setdefault(name, set()).update(fields)
    return {name: sorted(fields) for name, fields in sorted(commands.items())}


# ---------------------------------------------------------------------------
# The login form
# ---------------------------------------------------------------------------

_LOGIN_FORM = re.compile(
    r"""goformId\s*[=:]\s*["']LOGIN["'](?P<body>.{0,600})""", re.DOTALL
)

_PASSWORD_BRANCH = re.compile(
    r"""["'](\d)["']\s*==\s*\w+\.WEB_ATTR_IF_SUPPORT_SHA256\s*\?\s*(\w+)\("""
)


def parse_login(sources: dict[str, str]) -> dict[str, Any]:
    """How the login form encodes a password, and whether it carries a username.

    Both readable devices answer `2` and hash twice with the salt, which is
    what this integration already does — so the value of learning it is the
    device that answers something else, where today's constant is simply wrong
    and the failure is indistinguishable from a bad password.
    """
    # The first form that names an encoding wins and the search stops there.
    # Returning from inside rather than breaking out of two loops: the second
    # file to carry a `LOGIN` literal is not a second opinion to reconcile.
    for text in sources.values():
        for match in _LOGIN_FORM.finditer(text):
            body = match.group("body")
            branches = {
                branch.group(1): branch.group(2)
                for branch in _PASSWORD_BRANCH.finditer(body)
            }
            if not branches:
                continue
            login: dict[str, Any] = {
                "password_branches": dict(sorted(branches.items())),
                "carries_username": bool(
                    re.search(r"""\busername\s*:""", body[: body.find("password")])
                ),
            }
            salt = _NV_READ.search(text[max(0, match.start() - 200) : match.start()])
            if salt:
                login["salt_read"] = salt.group(1)
            name = branches.get("2")
            if name:
                login["password_digest"] = _resolve_digest(name, sources)
            return login
    return {}


# ---------------------------------------------------------------------------
# The session flag
# ---------------------------------------------------------------------------

# `kn.isLoggedIn=!n.HAS_LOGIN||"ok"==e.loginfo` — the device's own client
# deciding whether it still holds a session, which names both the key and the
# value in one expression.
_SESSION_DECISION = re.compile(
    r"""isLoggedIn\s*=\s*!\w+\.(\w+)\s*\|\|\s*["']([^"']{1,16})["']\s*===?\s*\w+\.(\w+)"""
)

# `n.cmd="loginfo"` in the builder that reads it, which proves the key is
# fetched on its own rather than only inspected inside a larger reading.
_SESSION_READ = re.compile(r"""\bcmd\s*[=:]\s*["'](\w{3,32})["']\s*[,;}]""")


def parse_session_flag(sources: dict[str, str]) -> dict[str, Any]:
    """Which reading this firmware treats as "the session is still mine".

    This is what item 28 can honestly supply. The scripts do not name the
    integration's witness keys — no firmware has an opinion about which
    readings a third-party client should watch — but every one of them names
    the flag its own client trusts, and that is the reading the pre-write check
    already uses. Learning it turns a key chosen here into a key the device
    nominated.
    """
    for text in sources.values():
        match = _SESSION_DECISION.search(text)
        if not match:
            continue
        flag: dict[str, Any] = {
            "key": match.group(3),
            "ok_value": match.group(2),
            "bypass_flag": match.group(1),
        }
        flag["read_alone"] = any(
            read.group(1) == flag["key"] for read in _SESSION_READ.finditer(text)
        )
        return flag
    return {}


# ---------------------------------------------------------------------------
# The profile
# ---------------------------------------------------------------------------


def parse_profile(sources: dict[str, Any], version: str = "") -> dict[str, Any]:
    """Everything the parser can read, with what it could not read named.

    `version` is the firmware string the sources were fetched under. It is the
    profile's identity: a cached profile whose version no longer matches the
    device's is describing a firmware that is gone, and is discarded rather
    than trusted — the same rule `cr_version` is cached under.
    """
    text_sources = {
        path: body for path, body in sources.items() if isinstance(body, str)
    }
    token = parse_token(text_sources)
    flags = parse_flags(text_sources)
    commands = parse_commands(text_sources)
    login = parse_login(text_sources)
    session_flag = parse_session_flag(text_sources)

    unlearned: list[str] = []
    if not token.get("digest_function"):
        unlearned.append("token.digest_function")
    elif "algorithm" not in token.get("digest", {}):
        unlearned.append("token.digest.algorithm")
    if not token.get("operand_values"):
        unlearned.append("token.operand_values")
    if not token.get("exempt_commands"):
        unlearned.append("token.exempt_commands")
    if "ACCESSIBLE_ID_SUPPORT" not in flags:
        unlearned.append("flags.ACCESSIBLE_ID_SUPPORT")
    if "MAX_LOGIN_COUNT" not in flags:
        unlearned.append("flags.MAX_LOGIN_COUNT")
    if not commands:
        unlearned.append("commands")
    if not login.get("password_branches"):
        unlearned.append("login.password_branches")
    if not session_flag.get("key"):
        unlearned.append("session_flag.key")

    return {
        "profile_version": PROFILE_VERSION,
        "firmware": version,
        "sources_read": sorted(text_sources),
        "token": token,
        "flags": flags,
        "commands": commands,
        "login": login,
        "session_flag": session_flag,
        "unlearned": unlearned,
    }
