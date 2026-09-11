"""TEMPORARY — a one-off probe for the SMS deletion fault on issue #56.

**This module is not part of the integration's contract and must be removed.**
It exists to characterise one device that accepts `DELETE_SMS`, answers
success, and keeps the messages. Four diagnostics downloads produced no
evidence, because the failing path raises before anything is recorded.

Remove this file, its registration in `__init__.py`, its block in
`services.yaml`, its translation entries and its tests once the fault is
understood. `.notes/issues/other_router_access/` records that as outstanding
work so it does not rest on memory.

**What it does, in order.** Every probe that risks nothing runs first: they
read state, or they name a message id the router does not hold, so there is
nothing to destroy. Only then does it touch real messages, and every one it
touches is one the user has already asked to delete.

It does not stop at the first success. A device that behaves this differently
from the reference hardware is worth characterising once, properly, rather than
learning one fact and having to ask again.

**Version 3.** The earlier runs established that no write of any kind reaches
this device — the data-limit form, which is not an SMS command, was refused on
all eighteen attempts — and that the router answers a correctly derived token
exactly as it answers a deliberately malformed one. That points at the
derivation itself, so this version tries twelve of them against the harmless
write and uses whichever one the router accepts to delete with.

Success is judged on the router's own `result` field. Version 2 judged it on
whether the call raised, and reported a variant confirmed while every one of
its writes was refused.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import re
from copy import deepcopy
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING, Any, cast

import aiohttp

from .api import (
    _CORE_PARAMS,
    _EXTENDED_PARAMS,
    _SESSION_CHECK_KEYS,
    SMS_STORE_ALL,
    SMS_STORE_DEVICE,
    SMS_STORE_SIM,
    ZTEConnectionError,
    _classify_session,
)
from .const import JS_BUNDLES

if TYPE_CHECKING:
    from .coordinator import ZTERouterDataUpdateCoordinator

# What a run is asked to do. The probe grew a write ladder that takes most of
# a fifteen-minute budget and can exhaust a router's login attempts, and a
# capture that needs neither. Keeping them in one run meant the cheap stage
# could be lost to a failure in the expensive one.
ACTION_CAPTURE = "capture"
ACTION_CONFIRM = "confirm"
ACTION_FULL = "full"
PROBE_ACTIONS: tuple[str, ...] = (ACTION_CAPTURE, ACTION_CONFIRM, ACTION_FULL)
# Read-only, and the only stage still expected to return something new.
DEFAULT_ACTION = ACTION_CAPTURE

# An id no router holds. Naming it exercises the entire write path — token,
# form, session — while putting nothing at risk.
ABSENT_ID = "999999"

# A deliberately malformed token, so the router's answer to a bad one can be
# compared against its answer to a real refusal. Same length as a real digest.
BAD_TOKEN = "0" * 32

# Seconds to wait before the delayed re-list. Long enough to distinguish a
# lazy deletion from a refusal, short enough not to stall the action.
LAZY_DELETE_WAIT = 5

# The whole run, capped. A router that refuses every write provokes a re-login
# and a replay per attempt, and there is no other limit — the first version
# could in principle have run for twenty minutes with the action still
# spinning, and a user watching that will restart Home Assistant.
PROBE_TIMEOUT = 900

# A failed login answers `{"result":"3"}` on both devices this project can
# reach, measured 2026-09-09 for a wrong password and for a wrong username with
# the right one. It is the only marker of a spent attempt: neither device
# exposes a countdown, so the probe counts its own.
FAILED_LOGIN_RESULT = "3"

# Failed logins tolerated before a correct one is made to clear the allowance.
#
# Both devices report `psw_fail_num_str: 5` and `login_lock_time: 300`, read as
# five attempts and a five-minute lockout. Neither value moves: measured on the
# reference MC7010 across two failed logins, with the session held so nothing
# could reset it, none of 230 readable names changed except radio noise and
# traffic counters. Of 78 login-shaped names mined from the MC888's own web UI,
# only those two and `loginfo` answer at all, and all three are static.
#
# So there is nothing to watch, and the group size is a discipline rather than
# a measurement. Three leaves a margin of two against a limit that is itself
# only inferred, and a correct login between groups is assumed to clear the
# count — unverified, and unverifiable without deliberately provoking a
# lockout.
BAD_LOGIN_GROUP = 3

# Between login attempts. Longer than `ATTEMPT_DELAY` because a login is what
# the lockout counts, and a burst of them is what it exists to stop.
LOGIN_DELAY = 5.0

# How many times each token variant is tried against the harmless write. One
# success is not a working method and one failure is not a broken one; the
# question is whether a variant works *every* time.
WRITE_ATTEMPTS = 3

# Between attempts, so a variant is not measuring the router's recovery from
# the attempt before it.
ATTEMPT_DELAY = 1.0

# Between screening writes. Shorter than `ATTEMPT_DELAY` because the screening
# pass is long — the generated space is 150 distinct tokens on the reporter's
# firmware — and a screened token is only ever ruled *out* here. Anything it
# rules in is re-tried at the slower pace before it counts.
SCREEN_DELAY = 0.15

# One screened attempt in this many is read back rather than believed. A
# read-back on every rule would roughly double a sweep approaching a thousand
# attempts; a sample establishes that the refusals are real, and anything
# claiming success is re-run verified whatever the sample says.
VERIFY_EVERY = 25

# The keys the shipped session check now reads, imported rather than repeated
# so this rung reports on what the integration actually does. The download is
# read against a device whose behavior is being characterized; a probe testing
# its own private copy of the list would answer a question nobody asked.
LIVENESS_KEYS = _SESSION_CHECK_KEYS

# The timestamp a ZTE firmware string carries, e.g.
# `BD_ABPLMC888PROMODV1.0.0B01 [Oct 16 2025 21:15:14]`. One candidate strips it
# on the theory that the router's own JavaScript hashes the bare version.
_TIMESTAMP = re.compile(r"\s*\[[^\]]*\]\s*$")


async def _login_variants(api: Any) -> list[dict[str, Any]]:
    """Every way of presenting the same credentials that is worth trying.

    The reporter's device answers `result: "0"` to the login this integration
    sends, issues a cookie, and then refuses every write — while a correctly
    derived token and a deliberately malformed one draw the identical refusal.
    That pattern is what a session with no write rights would look like, and
    the login is the only step never varied.

    The field name and value are the substance. `teixeluis/zte-lte-modem`
    documents the MF266 login field as `user` with a default of `admin`;
    Kajkac issue #30 reports an MC888A whose own web UI posts `LOGIN` with a
    `user` field, and a Reboot that answered `200` and did nothing until a
    username was supplied. `user` is also the factory default on an MC7010.
    The reporter has no username configured, so this integration sends no such
    field at all.

    Ordered by expected likelihood, because a run may be cut short by the
    lockout budget and the first attempts may be all there is.
    """
    configured = api.username or ""
    variants: list[dict[str, Any]] = [
        {
            "name": "L1_current",
            "form": "LOGIN",
            "field": "username",
            "value": configured,
        },
        {"name": "L2_user_user", "form": "LOGIN", "field": "user", "value": "user"},
        {"name": "L3_user_admin", "form": "LOGIN", "field": "user", "value": "admin"},
        {
            "name": "L4_username_user",
            "form": "LOGIN",
            "field": "username",
            "value": "user",
        },
        {
            "name": "L5_multi_admin",
            "form": "LOGIN_MULTI_USER",
            "field": "user",
            "value": "admin",
            "with_ad": True,
        },
        {
            "name": "L6_multi_user",
            "form": "LOGIN_MULTI_USER",
            "field": "user",
            "value": "user",
            "with_ad": True,
        },
        {
            "name": "L7_username_admin",
            "form": "LOGIN",
            "field": "username",
            "value": "admin",
        },
        {
            "name": "L8_login_with_ad",
            "form": "LOGIN",
            "field": "username",
            "value": configured,
            "with_ad": True,
        },
        {"name": "L9_no_field", "form": "LOGIN", "field": None, "value": None},
        # `nicjac` logs in by GET against this same endpoint, with the password
        # in the query string. It is the only login form in either reference
        # implementation that this integration has never sent.
        {
            "name": "L10_get_query",
            "form": "LOGIN",
            "field": "username",
            "value": configured,
            "as_query": True,
        },
        # A second login form, selected by a `developer_login` flag in
        # `tpoechtrager`'s script and present among the 187 write commands
        # mined from the reporter's own router. Same credentials, same token,
        # different `goformId` — and it is the only login form either
        # reference implementation sends that this integration never has.
        {
            "name": "L11_developer_option",
            "form": "DEVELOPER_OPTION_LOGIN",
            "field": "username",
            "value": configured,
            "with_ad": True,
        },
        {
            "name": "L12_developer_option_no_ad",
            "form": "DEVELOPER_OPTION_LOGIN",
            "field": "username",
            "value": configured,
        },
        # The gist hashes the password without uppercasing either round. This
        # integration uppercases both. The difference has never been sent.
        {
            "name": "L13_password_plain_case",
            "form": "LOGIN",
            "field": "username",
            "value": configured,
            "password_case": "plain",
        },
        # For builds predating the SHA-256 transition.
        {
            "name": "L14_password_md5",
            "form": "LOGIN",
            "field": "username",
            "value": configured,
            "password_digest": "md5",
        },
        # Completing the `LD` case set alongside as-returned and uppercased.
        {
            "name": "L15_ld_lower",
            "form": "LOGIN",
            "field": "username",
            "value": configured,
            "ld_lower": True,
        },
        # `LOGIN_MULTI_USER` has only ever been sent with `user=`.
        {
            "name": "L16_multi_username_spelling",
            "form": "LOGIN_MULTI_USER",
            "field": "username",
            "value": "admin",
            "with_ad": True,
        },
    ]
    # The MF266 documentation hashes the password against an uppercased `LD`.
    # Ours uses it as returned. Repeating the leading forms doubles the stage,
    # so only the three most likely carry it.
    for base in ("L2_user_user", "L3_user_admin", "L1_current"):
        original = next(v for v in variants if v["name"] == base)
        variants.append({**original, "name": f"{base}_ld_upper", "ld_upper": True})
    return variants


async def _try_login(api: Any, variant: dict[str, Any]) -> dict[str, Any]:
    """Post one login form and report everything the router did about it.

    Every cookie is recorded by name. The reporter's device only ever issues
    `zsidn`; a variant that draws a differently named cookie, or a second one,
    would be the finding — and it is one no amount of guessing at cookie names
    could produce.
    """
    ld = await api.get_ld()
    if variant.get("ld_upper"):
        ld = ld.upper()
    if variant.get("ld_lower"):
        ld = ld.lower()
    if variant.get("password_digest") == "md5":
        zte_pass = _md5(_md5(api.password).upper() + ld).upper()
    elif variant.get("password_case") == "plain":
        # `SHA256(SHA256(password) + LD)`, neither round uppercased, exactly as
        # `tpoechtrager`'s script sends it.
        zte_pass = _sha(_sha(api.password) + ld)
    else:
        zte_pass = api._hash(api._hash(api.password).upper() + ld).upper()  # noqa: SLF001

    payload: dict[str, str] = {
        "isTest": "false",
        "goformId": variant["form"],
        "password": zte_pass,
    }
    if variant["field"] is not None:
        payload[variant["field"]] = str(variant["value"] or "")
    if variant.get("with_ad"):
        with contextlib.suppress(Exception):
            payload["AD"] = await api.get_ad()

    api._clear_session()  # noqa: SLF001 - each variant starts from nothing
    result: Any = None
    cookies: dict[str, str] = {}
    as_query = bool(variant.get("as_query"))
    url = f"{api.referer}goform/goform_set_cmd_process"
    if as_query:
        url += "?" + "&".join(f"{key}={value}" for key, value in payload.items())
    async with api.session.request(
        "GET" if as_query else "POST",
        url,
        data=None if as_query else payload,
        headers={"Referer": api.referer},
        ssl=False,
    ) as response:
        body: Any = None
        with contextlib.suppress(Exception):
            body = await response.json(content_type=None)
        if isinstance(body, dict):
            result = body.get("result")
        cookies = api._extract_cookies(response, resp_json=body)  # noqa: SLF001

    if cookies:
        api.cookies = dict(cookies)
        api.session_active = True
        api.last_activity = datetime.now(UTC)
    return {
        "form": variant["form"],
        "method": "GET" if as_query else "POST",
        "field": variant["field"],
        "value_kind": _value_kind(variant),
        "ld_upper": bool(variant.get("ld_upper")),
        "ld_lower": bool(variant.get("ld_lower")),
        "password_digest": str(variant.get("password_digest") or "sha"),
        "password_case": str(variant.get("password_case") or "upper"),
        "carried_ad": bool(variant.get("with_ad")),
        "result": result,
        "cookie_names": sorted(cookies),
        "spent_an_attempt": str(result) == FAILED_LOGIN_RESULT,
    }


def _value_kind(variant: dict[str, Any]) -> str:
    """What was sent in the username field, without sending his own back.

    A configured username is the reporter's; the literal defaults are not.
    """
    if variant["field"] is None:
        return "field absent"
    value = str(variant["value"] or "")
    if not value:
        return "empty"
    return value if value in ("user", "admin") else "the configured username"


# --- reading the router's own web UI ---------------------------------------
#
# Every version of this probe decided what to send from constants written here.
# The router publishes the answer itself: the page its browser loads is the
# same client, hitting the same API, and it works. Reading that code turns a
# guess into a measurement — and where the two disagree, the disagreement is
# the finding.
#
# All of this is read-only, and none of it is the reporter's data: it is the
# script the router serves to anyone who opens its address.

# `<script src="...">`, and the RequireJS entry point the index names instead.
_SCRIPT_SRC = re.compile(r"""<script[^>]+src\s*=\s*["']([^"']+)["']""")
_DATA_MAIN = re.compile(r"""data-main\s*=\s*["']([^"']+)["']""")
# `require.config({paths:{name:"path", ...}})`, which is where a module loader
# keeps the list an index page does not carry.
_REQUIRE_PATHS = re.compile(r"""paths\s*:\s*\{([^}]*)\}""")
_PATH_PAIR = re.compile(r"""["']?([\w$-]+)["']?\s*:\s*["']([^"']+)["']""")

# What a bundle is searched for, and what each occurrence is worth capturing.
_MARKERS: tuple[str, ...] = (
    "goform_set_cmd_process",
    "goform_get_cmd_process",
    "DELETE_SMS",
    "ALL_DELETE_SMS",
    "DATA_LIMIT_SETTING",
    "NIGHT_MODE_INFO_SETTINGS",
    "ACCESSIBLE_ID_SUPPORT",
    "rd0",
    "rd1",
    "hex_md5",
    "hex_sha256",
    "SHA256",
    "which_cgi",
)

# Characters of source kept either side of a marker. Enough to hold a payload
# builder and its callback; small enough that a dozen captures do not dominate
# the download.
_CAPTURE_WINDOW = 700

# Bundles fetched in one run, and bytes read from each. A module loader can
# name a great many, and a probe that reads all of them on a slow router is a
# probe that times out.
_MAX_BUNDLES = 40
_MAX_BUNDLE_BYTES = 400_000


async def _fetch_text(api: Any, path: str) -> tuple[int | None, list[str], str]:
    """Fetch one page or script, returning status, header names and body."""
    url = f"{api.referer}{path.lstrip('/')}"
    try:
        async with api.session.get(
            url,
            headers={"Referer": f"{api.referer}index.html"},
            timeout=aiohttp.ClientTimeout(total=15),
            ssl=False,
        ) as response:
            body = await response.text(errors="replace")
            return response.status, sorted(response.headers), body
    except Exception as err:  # noqa: BLE001 - a miss is a finding, not a failure
        return None, [], f"{type(err).__name__}: {err}"


def _module_paths(entry_text: str) -> dict[str, str]:
    """Every module a RequireJS entry point declares.

    The reference MC7010's index names three library scripts and
    `data-main="js/main"`; the modules the application actually uses are listed
    inside that entry point and nowhere else. An index that "names no scripts"
    — which is what the reporter's device reported for four downloads — is an
    index whose scripts are declared here.
    """
    return {
        pair.group(1): pair.group(2)
        for block in _REQUIRE_PATHS.finditer(entry_text)
        for pair in _PATH_PAIR.finditer(block.group(1))
    }


# A RequireJS module list is not the loader's whole answer. On the reference
# MC7010 the index names three scripts and `data-main`, the `paths` map in the
# entry point names a dozen more, and the browser loads thirty-one — the rest
# arrive through dependency arrays inside `js/app.js` and its children. The
# assignment that resolves the write token was in one of the nine files that
# difference accounts for, and six probe runs never fetched it.
#
# So the list is built by following references until no new name appears,
# rather than by reading any one declaration.
_DEP_ARRAY = re.compile(r"""(?:define|require)\s*\(\s*\[([^\]]{0,4000})\]""")
# `shim:{jq_simplemodal:["lib/bootstrap"]}`. The loader follows these; the
# first rehearsal did not, and missed `js/lib/bootstrap.js`.
#
# Scoped to the shim block rather than to any bracketed list of strings: the
# looser form matched a table of country codes and filled the crawl's budget
# with two hundred names the router has never served.
_SHIM_BLOCK = re.compile(r"""shim\s*:\s*\{([^}]{0,4000})\}""")
# `DEVICE:"cpe/MF253V"`, which names a directory of model-specific modules the
# loader composes at runtime. Nothing refers to those files by name, so no
# amount of reference-following reaches them.
_DEVICE = re.compile(r"""\bDEVICE\s*:\s*["']([\w./-]{1,60})["']""")
_DEP_ITEM = re.compile(r"""["']([^"']{1,120})["']""")
# A string that could be a module path: no spaces, no scheme, not a sentence.
_MODULE_LITERAL = re.compile(r"""["']((?:\.{0,2}/)?[\w][\w./-]{1,80})["']""")

# Names a loader can reach without ever naming them in a file we parse. Swept
# once at the end so a crawl that stalls still returns the modules that carry
# the write path.
_KNOWN_MODULES: tuple[str, ...] = (
    "js/main.js",
    "js/app.js",
    "js/service.js",
    "js/util.js",
    "js/router.js",
    "js/home.js",
    "js/login.js",
    "js/logout.js",
    "js/language.js",
    "js/tooltip.js",
    "js/status/statusBar.js",
    "js/config/config.js",
    "js/config/menu.js",
    "js/lib/md5.js",
    "js/lib/base64.js",
    "tmpl/login.html",
)

# Given `DEVICE:"cpe/MF253V"`, the files that directory is known to hold.
_DEVICE_MODULES: tuple[str, ...] = ("config.js", "menu_bridge.js")

# A library is followed, because it names modules, but not returned: jQuery and
# Knockout are a megabyte that tells us nothing about this firmware.
_LIB_PREFIX = "js/lib/"

# The crawl, capped. A loader can name a great many files and a slow router
# turns that into a timeout.
# Ninety rather than sixty: the reference MC7010 used 43, and the MC888 Pro's
# web UI is a later and larger one that has never been measured. A crawl capped
# part-way through returns a partial answer to a question that costs a round
# trip with the reporter to ask again.
_MAX_CRAWL_FILES = 90
_MAX_CRAWL_BYTES = 3_000_000
_MAX_RETURN_BYTES = 400_000


def _resolve(
    name: str,
    base: str = "js/",
    aliases: dict[str, str] | None = None,
) -> str | None:
    """A module reference as a path this probe can fetch, or None.

    RequireJS names are extensionless and may be relative. `text!tmpl/x.html`
    names a template through the text plugin. Most of them are aliases rather
    than paths: a dependency array asks for `jquery`, and the `paths` map says
    where `jquery` lives. Resolving without that map invents `js/jquery.js`,
    which does not exist — eighteen of the fifty-one names the first rehearsal
    fetched were fabricated that way, and each one was reported as a file the
    router failed to serve.
    """
    name = name.strip()
    if not name or "://" in name or name.startswith(("//", "#")):
        return None
    if "!" in name:
        name = name.split("!", 1)[1]
        if not name:
            return None
    name = name.split("?", 1)[0]
    if aliases:
        head, _sep, rest = name.partition("/")
        if head in aliases:
            name = aliases[head] + ("/" + rest if rest else "")
    if name.startswith("/"):
        name = name[1:]
    elif not name.startswith(("js/", "tmpl/", "css/", "img/")):
        name = base + name
    while "/./" in name:
        name = name.replace("/./", "/")
    while "/../" in name:
        head, _sep, rest = name.partition("/../")
        name = head.rsplit("/", 1)[0] + "/" + rest if "/" in head else rest
    if not name.endswith((".js", ".html")):
        name += ".js"
    if any(part in {"", ".", ".."} for part in name.split("/")):
        return None
    if name.rsplit("/", 1)[-1] in {".js", ".html"}:
        return None
    return name


def _aliases(text: str) -> dict[str, str]:
    """The loader's `paths` map: the alias a dependency array asks for."""
    return {
        pair.group(1): pair.group(2)
        for block in _REQUIRE_PATHS.finditer(text)
        for pair in _PATH_PAIR.finditer(block.group(1))
    }


def _referenced(
    text: str,
    aliases: dict[str, str] | None = None,
    literals: bool = True,
) -> set[str]:
    """Every module path one file refers to, by any of the three routes.

    `literals` is the loosest of the three and is turned off for third-party
    libraries, whose documentation comments carry example paths — the first
    rehearsal followed `js/one/two/three.js` out of the RequireJS banner and
    reported it as a file the router failed to serve.
    """
    names: set[str] = set()
    for block in _REQUIRE_PATHS.finditer(text):
        for pair in _PATH_PAIR.finditer(block.group(1)):
            names.add(pair.group(2))
    for pattern in (_DEP_ARRAY, _SHIM_BLOCK):
        for block in pattern.finditer(text):
            names.update(item.group(1) for item in _DEP_ITEM.finditer(block.group(1)))
    if literals:
        names.update(
            match.group(1)
            for match in _MODULE_LITERAL.finditer(text)
            if match.group(1).endswith((".js", ".html"))
        )
    resolved = {_resolve(name, aliases=aliases) for name in names}
    return {name for name in resolved if name}


async def _crawl(api: Any) -> dict[str, Any]:
    """Follow the router's own references until no new file appears.

    Returns one record per file — status, byte count and digest — and the
    source of every file that is not a third-party library. The digest is
    there so two devices' downloads can be compared without diffing a
    megabyte, and so a truncated body is visible as such.
    """
    # Seeded from the static list as well as the index. Four downloads from
    # the MC888 Pro of issue #56 reported "index: no scripts named", so a crawl
    # that starts only from what the index declares starts, on that device,
    # from nothing.
    queue: list[str] = ["index.html", "js/main.js", *JS_BUNDLES]
    seen: set[str] = set()
    files: dict[str, Any] = {}
    sources: dict[str, str] = {}
    total = 0
    truncated: list[str] = []
    missing: list[str] = []
    aliases: dict[str, str] = {}

    async def take(path: str) -> str:
        nonlocal total
        status, _headers, body = await _fetch_text(api, path)
        size = len(body)
        record: dict[str, Any] = {"status": status, "bytes": size}
        if status == 200:
            record["sha256"] = hashlib.sha256(body.encode(errors="replace")).hexdigest()
            if not path.startswith(_LIB_PREFIX):
                kept = body[:_MAX_RETURN_BYTES]
                if len(kept) < size:
                    truncated.append(path)
                    record["returned_bytes"] = len(kept)
                sources[path] = kept
                total += len(kept)
        else:
            missing.append(path)
        files[path] = record
        return body if status == 200 else ""

    while queue and len(seen) < _MAX_CRAWL_FILES and total < _MAX_CRAWL_BYTES:
        # Nothing reaches the queue twice: every producer below checks both
        # `seen` and `queue` before appending.
        path = queue.pop(0)
        seen.add(path)
        body = await take(path)
        if not body or path.endswith(".html"):
            # A template refers to nothing this crawl can follow, and an index
            # is seeded separately below.
            if path == "index.html":
                for src in _SCRIPT_SRC.findall(body) + _DATA_MAIN.findall(body):
                    resolved = _resolve(src, aliases=aliases)
                    if resolved and resolved not in seen and resolved not in queue:
                        queue.append(resolved)
            continue
        aliases.update(_aliases(body))
        for name in sorted(
            _referenced(body, aliases, not path.startswith(_LIB_PREFIX))
        ):
            if name not in seen and name not in queue:
                queue.append(name)

    # The model-specific directory, composed rather than referenced. On the
    # reference device it holds the config that overrides the general one, so a
    # build whose write path differs could differ here and nowhere else.
    device_modules: list[str] = []
    for text in sources.values():
        for match in _DEVICE.finditer(text):
            device_modules += [
                f"js/config/{match.group(1)}/{name}" for name in _DEVICE_MODULES
            ]

    for known in (*_KNOWN_MODULES, *dict.fromkeys(device_modules)):
        if known not in seen and len(seen) < _MAX_CRAWL_FILES:
            seen.add(known)
            await take(known)

    return {
        "files": files,
        "sources": sources,
        "fetched": len(files),
        "returned": len(sources),
        "returned_bytes": total,
        "missing": missing,
        "truncated": truncated,
        "unvisited_queue": queue[:20],
        "capped": len(seen) >= _MAX_CRAWL_FILES or total >= _MAX_CRAWL_BYTES,
    }


def _which_cgi_values(text: str) -> set[str]:
    """Every literal the router's script assigns to `which_cgi`.

    The delete-all builder passes a variable, so the values live wherever that
    variable is set. Reading them is the difference between sending what the
    device sends and sending what this project assumes it sends.
    """
    return {
        match.group(1)
        for match in re.finditer(r"""which_cgi\s*[:=]\s*["']([^"']+)["']""", text)
    }


def _captures(text: str, marker: str) -> list[str]:
    """The source around each occurrence of a marker, bounded."""
    out: list[str] = []
    for match in re.finditer(re.escape(marker), text):
        start = max(0, match.start() - _CAPTURE_WINDOW)
        out.append(text[start : match.start() + _CAPTURE_WINDOW])
        if len(out) >= 4:
            break
    return out


def _fields_for(text: str, goform_id: str) -> list[str]:
    """The field names the router's own code assembles for one command.

    **Read from the object literal that carries the `goformId`, and only from
    it.** A first version scanned a fixed window either side and picked up
    whatever happened to be nearby: on the reference MC7010 it reported the
    data-limit form as carrying `monthlySent`, `monthlyReceived` and `result`,
    which belong to a neighbouring reader. Those names would then have been
    sent in `23a` as "the router's own form", and a refusal blamed on the
    device rather than on this function.

    Balanced braces from the literal's opening, keys at its top level only. An
    empty list means the pattern was not found, which is recorded rather than
    filled in from a constant.
    """
    names: set[str] = set()
    for match in re.finditer(re.escape(f'goformId:"{goform_id}"'), text):
        opening = text.rfind("{", 0, match.start())
        if opening == -1:
            continue
        depth = 0
        for index in range(opening, min(len(text), opening + 4000)):
            character = text[index]
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    body = text[opening + 1 : index]
                    break
        else:
            continue
        # Keys at the literal's own level, so a nested object's keys are not
        # read as fields of this command.
        level = 0
        key = ""
        for character in body:
            if character in "{[(":
                level += 1
            elif character in "}])":
                level -= 1
            elif character == ":" and level == 0:
                stripped = key.strip().strip("\"'")
                if re.fullmatch(r"\w+", stripped):
                    names.add(stripped)
                key = ""
            elif character == "," and level == 0:
                key = ""
            elif level == 0:
                # Only what sits at the literal's own level can be a key. A
                # nested object's keys belong to it, and `[k]: 2` is computed
                # at runtime — its `k` is not a field name this probe could
                # send. Skipping everything inside a bracket covers both, and
                # is why no reset is needed when one opens.
                key += character
        # Fields assigned to the literal afterwards, which is how the
        # data-limit form is built: `var _={isTest:Dn,goformId:"..."}` and then
        # `_.data_volume_limit_unit=...` under a condition. Reading only the
        # literal finds none of them; reading a fixed window finds them and a
        # neighbouring reader's fields too.
        prefix = text[max(0, opening - 40) : opening]
        holder = re.search(r"(\w+)\s*=\s*$", prefix)
        if holder:
            tail = text[index : index + 2000]
            names |= {
                m.group(1)
                for m in re.finditer(
                    r"\b" + re.escape(holder.group(1)) + r"\.(\w+)\s*=",
                    tail,
                )
            }
    return sorted(names - {"goformId", "isTest"})


async def _capture(
    coordinator: ZTERouterDataUpdateCoordinator,
    name: str,
    run: Any,
    *,
    sent: str | None = None,
) -> dict[str, Any]:
    """Run one probe and record its outcome, whether it returns or raises.

    A refusal is the finding, so the record has to survive the raise with the
    router's own answer in it. `error` alone is not enough: the first live run
    of this probe recorded `Request failed:` with nothing behind it, on the one
    rung that failed.
    """
    api = coordinator.api
    started = monotonic()
    record: dict[str, Any] = {"probe": name, "at": datetime.now(UTC).isoformat()}
    if sent is not None:
        record["sent"] = sent
    # Read before the request: the flag is cleared once one has gone out.
    record["session_was_fresh"] = api._session_was_fresh  # noqa: SLF001
    try:
        record["result"] = await run()
        record["outcome"] = "returned"
    except Exception as err:  # noqa: BLE001 - the outcome is the finding
        record["outcome"] = "raised"
        record["error_type"] = type(err).__name__
        record["error"] = str(err)[:300]
        # What the router actually said. `_request` records this against every
        # non-live verdict, and the next successful poll clears it, so it is
        # snapshotted here or lost. Sanitized on the way into the download.
        rejection = api.last_rejection
        if isinstance(rejection, dict):
            record["rejection"] = deepcopy(rejection)
    record["elapsed_seconds"] = round(monotonic() - started, 3)
    record["status"] = api.last_response_status
    record["body_preview"] = api.last_response_preview
    names = getattr(api, "last_response_header_names", None)
    if names:
        record["response_header_names"] = list(names)
    if _LAST_SENT:
        record["carried"] = dict(_LAST_SENT)
        _LAST_SENT.clear()
    return record


def _sha(value: str) -> str:
    """SHA-256, lower case hex."""
    return hashlib.sha256(value.encode()).hexdigest()


def _md5(value: str) -> str:
    """MD5, lower case hex."""
    return hashlib.md5(value.encode()).hexdigest()  # noqa: S324 - the router's choice


# The operand of the first round. `wa` is the firmware string, `cr` the
# `cr_version` the MC888 Pro answers and the MC7010 does not.
#
# Every published derivation for this hardware family uses one of these, and
# they disagree on which: miononno documents `wa + cr` for the MC888 Pro,
# `nicjac` uses `wa + cr` for the MC801A, `teixeluis` documents `cr + wa` for
# the MF266, and `Kajkac` concatenates a `cr_version` it never populates, which
# is `wa` alone.
# Ordered by what a source documents, not by convenience. The screening pass
# runs to the cap and a run cut short loses the tail, so the derivations with a
# citation behind them go first: `wa + cr` is what miononno documents for the
# MC888 Pro and what `nicjac` uses for the MC801A, `wa` alone is what `Kajkac`
# computes and what this integration ships, and `cr + wa` is the MF266's order.
#
# That ordering is a judgement about likelihood, not a measurement.
# Each takes the four strings the device reports and returns what the first
# round hashes.
#
# `wav` is `wa_version`, and it is the reason this list grew. The reporter's
# router reports three version strings and two of them disagree:
# `wa_inner_version` is `V1.0.0B01` built October 2025, `wa_version` is
# `V1.0.1B03`, and `cr_version` is `V1.0.1B04`. Every token this project has
# ever built used the first. The internally consistent pair — both `1.0.1` — is
# `wa_version` with `cr_version`, and it had never been sent.
_OPERANDS: tuple[tuple[str, Any], ...] = (
    ("wavcr", lambda v: v["wav"] + v["cr"]),
    ("wacr", lambda v: v["wa"] + v["cr"]),
    ("wav", lambda v: v["wav"]),
    ("wa", lambda v: v["wa"]),
    ("crwav", lambda v: v["cr"] + v["wav"]),
    ("crwa", lambda v: v["cr"] + v["wa"]),
    ("wanots_cr", lambda v: _TIMESTAMP.sub("", v["wa"]) + v["cr"]),
    ("cr", lambda v: v["cr"]),
    ("all_three", lambda v: v["wa"] + v["wav"] + v["cr"]),
    ("ld", lambda v: v["ld"]),
    ("hw", lambda v: v["hw"]),
    ("model", lambda v: v["model"]),
    # No version string at all, for a firmware that seeds only from `RD`.
    ("none", lambda v: ""),
)

# What is done to `RD` before the second round. `teixeluis` documents an
# uppercased `RD` for the MF266; everyone else uses it as returned.
_RD_FORMS: tuple[tuple[str, Any], ...] = (
    ("plain", lambda rd, digest: rd),
    ("upper", lambda rd, digest: rd.upper()),
    ("lower", lambda rd, digest: rd.lower()),
    ("hashed", lambda rd, digest: digest(rd)),
)

# Case is varied per round rather than fixed per model.
#
# This is where v3 was blind. `_ad_hash_func` returns an uppercasing digest on
# an MC888, every candidate inherited it, and so the twelve collapsed to nine
# distinct tokens on the reporter's device and **no lowercase token was ever
# sent to it**. The case was a property of the model branch rather than
# something the sweep could vary.
_CASES: tuple[tuple[str, Any], ...] = (
    ("l", str.lower),
    ("u", str.upper),
)


def _rule(
    operand: Any,
    digest: Any,
    rd_form: Any,
    inner_case: Any,
    outer_case: Any,
    rounds: int,
    rd_first: bool = False,
) -> Any:
    """One derivation, as a function of the values it is built from."""

    def build(values: dict[str, str]) -> str:
        first = operand(values)
        prepared = rd_form(values["rd"], digest)
        if rounds == 1:
            joined = prepared + first if rd_first else first + prepared
            return str(outer_case(digest(joined)))
        inner = inner_case(digest(first))
        joined = prepared + inner if rd_first else inner + prepared
        if rounds == 3:
            return str(outer_case(digest(digest(joined))))
        return str(outer_case(digest(joined)))

    return build


def _token_space(values: dict[str, str]) -> list[tuple[str, Any]]:
    """Every distinct derivation these rules can produce, as rules.

    **Rules, not tokens.** An `AD` is single-use on this hardware: measured on
    the reference MC7010, the first write carrying a given token succeeds and
    every later write carrying the same one is refused, at any delay, while
    `RD` itself is unchanged. Re-reading the token inputs re-arms it.

    **Deduplicated against the device's own strings, not a stand-in.** Two
    rules that differ in the abstract can produce the same digest here — an
    uppercasing digest makes an `.upper()` variant a duplicate of its base, and
    a string the device does not answer collapses one operand onto another. The
    values passed here decide which rules are worth separating; the rules
    themselves are what run.

    Returns `(name, rule)` pairs in a stable order, first occurrence kept.
    """
    seen: dict[str, tuple[str, Any]] = {}
    for op_name, operand in _OPERANDS:
        if op_name != "none" and not operand(values):
            continue
        for digest_name, digest in (("sha", _sha), ("md5", _md5)):
            for rd_name, rd_form in _RD_FORMS:
                for rd_first in (False, True):
                    for inner_name, inner_case in _CASES:
                        for outer_name, outer_case in _CASES:
                            for rounds in (2, 1, 3):
                                rule = _rule(
                                    operand,
                                    digest,
                                    rd_form,
                                    inner_case,
                                    outer_case,
                                    rounds,
                                    rd_first,
                                )
                                # The inner case is part of the name for
                                # every round count that uses it. Leaving it
                                # out of the three-round names put two rules
                                # with different tokens under one label — the
                                # same defect the single-round names carried in
                                # v3.3.17-dev3.
                                suffix = (
                                    f"{inner_name}{outer_name}"
                                    if rounds == 2
                                    else f"{rounds}round{inner_name}{outer_name}"
                                )
                                where = "rdfirst" if rd_first else "rd"
                                name = (
                                    f"{op_name}_{digest_name}_{suffix}_{where}{rd_name}"
                                )
                                seen.setdefault(rule(values), (name, rule))
    return list(seen.values())


async def _token_inputs(api: Any, timeout_sec: int | None = None) -> dict[str, Any]:
    """Read the three values every candidate is built from.

    Read fresh on every attempt rather than once. `RD` is a nonce on some
    firmwares, and a candidate judged against a stale one would fail for a
    reason that has nothing to do with its formula.

    Lengths are recorded because they identify the digest without publishing
    the value: 64 characters is SHA-256, 32 is MD5. Measured, the MC888 Pro
    answers `RD` at 64 and the reference MC7010 at 32.
    """
    # `RD` is the only value that has to be re-read. It is the nonce the token
    # is armed against; the version strings are properties of the firmware and
    # do not change within a run. Reading all five per attempt cost four
    # requests where one will do, and the generated space is 1,548 rules on the
    # reporter's device — the difference is roughly seven minutes.
    rd = await api.get_rd(timeout_sec=timeout_sec) or ""
    if _STATIC_INPUTS:
        return {**_STATIC_INPUTS, "rd": rd}

    version = await api.get_version(timeout_sec=timeout_sec) or ""
    ld = ""
    with contextlib.suppress(Exception):
        ld = await api.get_ld(timeout_sec=timeout_sec) or ""
    extra: dict[str, Any] = {}
    try:
        extra = (
            await api.get_params(
                ["cr_version", "wa_version", "hardware_version", "model_name"],
                timeout_sec=timeout_sec,
            )
            or {}
        )
    except Exception as err:  # noqa: BLE001 - an unanswered read is a finding
        _CR_NOTE["error"] = f"{type(err).__name__}: {err!s:.120}"
    _STATIC_INPUTS.update(
        {
            "wa": version,
            "wav": str(extra.get("wa_version") or ""),
            "cr": str(extra.get("cr_version") or ""),
            "hw": str(extra.get("hardware_version") or ""),
            "model": str(extra.get("model_name") or ""),
            "ld": ld,
        }
    )
    return {**_STATIC_INPUTS, "rd": rd}


# Filled by `_token_inputs` when the `cr_version` read raises, and reported on
# the rung that records what the candidates were built from. `cr_version` is
# known to answer this device through the discovery pass; whether it answers a
# plain read has not been established, and a candidate skipped for a reason
# nobody recorded is a candidate that gets tried again next time.
_CR_NOTE: dict[str, str] = {}

# The version strings, read once per run. Properties of the firmware, not of
# the session, so re-reading them on every one of a thousand-odd attempts buys
# nothing and costs three requests each time.
_STATIC_INPUTS: dict[str, str] = {}


def _verified(record: dict[str, Any]) -> bool | None:
    """Whether a read-back confirmed the value actually changed.

    `None` where the attempt did not verify. This is the only judgement in the
    run that does not rest on the router's own account of its own write.
    """
    result = record.get("result")
    if isinstance(result, dict) and "verified_changed" in result:
        return bool(result["verified_changed"])
    return None


def _wrote(record: dict[str, Any]) -> bool:
    """Whether the router said it carried the write out.

    **Judged on the router's own `result` field, never on whether the call
    raised.** Probe v2 counted any call that returned, and reported a variant
    confirmed while all six of its writes answered `{"result": "failure"}`.
    This API answers `200 OK` for a refused write, so a call that returns
    proves only that the router was reachable.

    An explicit success is required rather than the absence of a refusal: a
    response with no `result` at all says nothing, and treating silence as
    success is the same mistake in a quieter form.
    """
    if record.get("outcome") != "returned":
        return False
    result = record.get("result")
    if not isinstance(result, dict):
        return False
    # A read-back beats the claim. Where one was taken, it decides.
    if "verified_changed" in result:
        return bool(result["verified_changed"])
    value = result.get("result")
    return value is not None and str(value).lower() in ("success", "0", "ok")


# How a write is carried, as opposed to what it says.
#
# A write on this API has four independent axes — the session it runs under,
# the token it carries, how it is carried, and which command it is — and this
# is the third. Holding it as a value rather than as a set of one-off rungs is
# what lets a proven transport be adopted for everything below it: the login
# stage already works that way, and the two audits that preceded this release
# both found the same defect, a value discovered and then not used.
# The transport in force. Replaced in place when a variant is proven, so
# every rung below inherits it without being told.
_ADOPTED: dict[str, Any] = {}

# What the most recent attempt carried, for the record that wraps it. Module
# state for the same reason `_CR_NOTE` is: the value is produced deep inside a
# call whose return value has no room for it.
_LAST_SENT: dict[str, Any] = {}

# Login variants that established a session, whether or not they went on to
# write. The combination pass runs the other axes under each of them: a fix
# needing two axes at once — a particular login *and* a particular carrier —
# is invisible to a run that varies one at a time, and nothing in three
# downloads rules that out.
_WITH_SESSION: list[dict[str, Any]] = []

# Where each toggle stood before the run touched it.
_STARTED_AT: dict[str, str] = {}

# The switch every probe write flips, and how to read it back.
#
# **A write that writes back the value already there is not a write.** Every
# attempt from v2 to v4 sent the data-volume form at its current values, so no
# request this project ever made to the reporter's router changed anything. A
# firmware that refuses or short-circuits a no-op write would produce exactly
# the uniform refusal that was measured, and nothing in 396 attempts could tell
# the two apart.
#
# So the workhorse toggles. Each attempt sets the switch to the opposite of
# what it reads, which makes every attempt a real change: refused, and the
# value is untouched; accepted, and it flipped, and the next attempt flips it
# back. The sweep alternates on its own and the run restores the starting value
# whatever happened.
#
# Chosen because it is reversible and observable. On the reference MC7010,
# turning the data limit off hides the other fields in the web UI and retains
# them; turning it back on restores them untouched.
_TOGGLES: tuple[tuple[str, str, tuple[str, ...], str, str], ...] = (
    (
        "data_limit",
        "DATA_LIMIT_SETTING",
        ("data_volume_limit_switch", "flux_data_volume_limit_switch"),
        "data_volume_limit_switch",
        "0",
    ),
    # A second command from an unrelated part of the firmware, under the same
    # rule. If this is refused too, "no write of any kind works" stops being an
    # inference drawn from one form.
    (
        "led_night",
        # The command name is the reporter's own, not a guess: it is one of
        # the 187 write commands mined from his router's JavaScript. An
        # earlier draft invented `LED_NIGHT_MODE_SET`, which exists nowhere,
        # and the rung would have tested the spelling rather than the device.
        "NIGHT_MODE_INFO_SETTINGS",
        ("led_night_mode_switch",),
        "led_night_mode_switch",
        "0",
    ),
)

# The rest of the night-mode form, sent alongside the flipped switch. Like the
# data-volume form, a `goform` setting is usually all-or-nothing, so a field
# left out draws a refusal that says nothing about what is being tested.
_NIGHT_MODE_FIELDS: tuple[str, ...] = (
    "is_led_night_mode",
    "led_night_mode_start_time",
    "led_night_mode_end_time",
)

_DEFAULT_TRANSPORT: dict[str, Any] = {
    "method": "POST",
    "as_query": False,
    "not_callback": False,
    "cookies": None,
    "headers": {"Content-Type": "application/x-www-form-urlencoded"},
    # Where the token goes, and what it is called.
    "token_field": "AD",
    "token_first": False,
    "token_in_header": False,
    "token_in_query": False,
    "is_test": "false",
    "multi_data": False,
    # The router's own code attaches `AD` only when `ACCESSIBLE_ID_SUPPORT` is
    # set, and never on `LOGIN` or `SET_WEB_LANGUAGE`. A firmware with that
    # flag unset expects no token at all, and every request this project has
    # ever sent carried one.
    "no_token": False,
}


async def _read_switch(api: Any, aliases: tuple[str, ...]) -> tuple[str, str | None]:
    """Read a toggle's current value, trying each spelling the device may use.

    Returns the alias that answered and its value, or `(aliases[0], None)` when
    the device answers none of them — which is a finding, not an error: a
    toggle nobody can read is a toggle nobody can verify.
    """
    with contextlib.suppress(Exception):
        answer = await api.get_params(list(aliases))
        for alias in aliases:
            value = (answer or {}).get(alias)
            if value not in ("", None):
                return alias, str(value)
    return aliases[0], None


def _flip(value: str | None) -> str:
    """The opposite of a boolean-shaped router value."""
    return "0" if str(value).strip() in ("1", "true", "on") else "1"


async def _attempt(
    coordinator: ZTERouterDataUpdateCoordinator,
    *,
    token: str | None = None,
    transport: dict[str, Any] | None = None,
    command: str = "DATA_LIMIT_SETTING",
    fields: dict[str, str] | None = None,
    toggle: tuple[str, str, tuple[str, ...], str, str] | None = None,
    verify: bool = False,
) -> dict[str, Any]:
    """One write, on one session, with one token, carried one way.

    The single place a write is built, so that a variation of any axis is a
    parameter rather than another hand-written rung. Everything above it
    chooses values; nothing above it constructs a request.

    `token` of `None` asks the integration for one the ordinary way. The token
    is single-use on this hardware, so a caller repeating an attempt must
    supply a freshly derived one rather than the value that just worked.

    The session is not a parameter: it is whatever `api.cookies` holds, which
    `_login_stage` may have set to a variant it proved. `cookies` in the
    transport overrides that for the duration of the call and is put back.

    **`toggle` names a switch to flip.** The write then changes something, and
    `verify` reads it back afterwards so the outcome does not rest on the
    router's own `result` — an API this project's own code documents as
    answering `200 OK` to a refused write.
    """
    api = coordinator.api
    carried = {**_DEFAULT_TRANSPORT, **(transport or {})}
    flipped_from: str | None = None
    flipped_to: str | None = None

    if toggle is not None:
        _name, _command, aliases, field, default = toggle
        _alias, current_value = await _read_switch(api, aliases)
        flipped_from = current_value if current_value is not None else default
        flipped_to = _flip(flipped_from)

        if fields is None:
            # The whole form, with one field flipped. `DATA_LIMIT_SETTING` is
            # all-or-nothing — `api.py` records that the router refuses it
            # outright when a field is missing — so sending the switch alone
            # would draw a refusal that says nothing about the token, the
            # carrier or the session. Everything else goes back at the value it
            # already holds.
            fields = {}
            if _name == "led_night":
                with contextlib.suppress(Exception):
                    answer = await api.get_params(list(_NIGHT_MODE_FIELDS))
                    fields = {
                        key: str(value)
                        for key, value in (answer or {}).items()
                        if key in _NIGHT_MODE_FIELDS and value not in ("", None)
                    }
            else:
                current = dict(coordinator.data or {})
                for name, spellings in api.DATA_VOLUME_FIELDS.items():
                    value = next(
                        (
                            current[key]
                            for key in spellings
                            if current.get(key) not in ("", None)
                        ),
                        None,
                    )
                    if value is not None:
                        fields[name] = str(value)

        # Applied whether this function built the form or a caller supplied
        # one. Computing the flip only in the first case meant `23a` compared
        # its read-back against `None` and could not report success whatever
        # the router did — a false negative of exactly the kind that rung
        # exists to detect.
        fields = {**fields, field: str(flipped_to)}

    if fields is None:
        current = dict(coordinator.data or {})
        fields = {}
        for field, aliases in api.DATA_VOLUME_FIELDS.items():
            value = next(
                (current[key] for key in aliases if current.get(key) not in ("", None)),
                None,
            )
            if value is None:
                raise ZTEConnectionError(f"the poll did not supply {field}")
            fields[field] = str(value)

    ad = (
        ""
        if carried["no_token"]
        else (token if token is not None else await api.get_ad())
    )
    token_field = str(carried["token_field"])
    parts = [f"isTest={carried['is_test']}", f"goformId={command}"]
    if carried["multi_data"]:
        parts.append("multi_data=1")
    if carried["token_first"]:
        parts.insert(0, f"{token_field}={ad}")
    parts += [f"{key}={value}" for key, value in fields.items()]
    if carried["not_callback"]:
        parts.append("notCallback=true")
    if (
        not carried["no_token"]
        and not carried["token_first"]
        and not carried["token_in_header"]
        and not carried["token_in_query"]
    ):
        parts.append(f"{token_field}={ad}")
    payload = "&".join(parts)

    held = dict(api.cookies)
    if carried["cookies"] is not None:
        api.cookies = dict(carried["cookies"])
    # What actually went out, kept where `_capture` can find it. Without this,
    # a variant that silently failed to carry its override is indistinguishable
    # in the download from one the router refused — and the whole run turns on
    # telling those two apart.
    #
    # The token is described, never published: its length and case identify the
    # digest, which is all any reader needs.
    _LAST_SENT.clear()
    _LAST_SENT.update(
        {
            "method": str(carried["method"]),
            "as_query": bool(carried["as_query"]),
            "command": command,
            "fields": sorted(fields),
            "not_callback": bool(carried["not_callback"]),
            "header_names": sorted(dict(carried["headers"])),
            "cookie_names": sorted(api.cookies),
            "token_sent": not carried["no_token"],
            "token_length": len(str(ad)),
            "token_case": _case_of(str(ad)),
        }
    )
    try:
        as_query = bool(carried["as_query"])
        path = "goform/goform_set_cmd_process"
        headers = dict(carried["headers"])
        if carried["token_in_header"]:
            headers[token_field] = str(ad)
        if carried["token_in_query"]:
            path += f"?{token_field}={ad}"
        elif as_query:
            path += f"?{payload}"
        result = await api._request(  # noqa: SLF001 - the point is to vary a fixed form
            str(carried["method"]),
            path,
            data=None if as_query else payload,
            headers=headers,
        )
    finally:
        api.cookies = held

    answered = cast("dict[str, Any]", result)
    if toggle is not None:
        answered = dict(answered)
        answered["flipped_from"] = flipped_from
        answered["flipped_to"] = flipped_to
        if verify:
            # The only measurement in this run that does not depend on the
            # router telling the truth about its own write.
            _name, _command, aliases, _field, _default = toggle
            _alias, now = await _read_switch(api, aliases)
            answered["value_after"] = now
            answered["verified_changed"] = now is not None and now == flipped_to
    return answered


def _case_of(token: str) -> str:
    """Whether a hex digest is upper, lower or neither, without publishing it."""
    letters = [c for c in token if c.isalpha()]
    if not letters:
        return "no letters"
    if all(c.isupper() for c in letters):
        return "upper"
    if all(c.islower() for c in letters):
        return "lower"
    return "mixed"


async def _data_volume_write(
    coordinator: ZTERouterDataUpdateCoordinator,
    token: str | None,
    *,
    verify: bool = False,
) -> dict[str, Any]:
    """Write the data-volume form back at exactly the values it already holds.

    The workhorse of this run: it changes nothing, so it can be repeated, and
    it is not an SMS command — so a failure here says the fault is every write
    on the device rather than anything about messages.

    **It flips the switch rather than writing the value back.** Writing back
    what is already there is not a write, and every attempt this project ever
    sent the reporter's router did exactly that — so a firmware that refuses or
    short-circuits a no-op would have produced the same uniform refusal, and
    nothing in 396 attempts could tell the two apart.

    The value is read immediately before each attempt and never remembered. It
    alternates: refused leaves it untouched, accepted flips it, and the next
    attempt flips it back. `run_probe` restores the starting value at the end
    whatever happened in between.
    """
    return await _attempt(
        coordinator,
        token=token,
        transport=_ADOPTED,
        command=_TOGGLES[0][1],
        toggle=_TOGGLES[0],
        verify=verify,
    )


async def _surviving_ids(coordinator: ZTERouterDataUpdateCoordinator) -> list[str]:
    """Ids the router still holds, across both storage banks."""
    messages = await coordinator.api.get_sms_messages(mem_store=SMS_STORE_ALL)
    return [str(msg.get("id")) for msg in messages if msg.get("id") is not None]


async def _counters(coordinator: ZTERouterDataUpdateCoordinator) -> dict[str, Any]:
    """The router's own message totals.

    A second view of the same fact. The listing and the counters have
    disagreed before on this issue — a device reporting a total it will not
    list is the shape the whole SMS thread started from — so a report carrying
    only one of them can be read the wrong way round.
    """
    return dict(await coordinator.api.get_sms_capacity())


async def _message_summary(
    coordinator: ZTERouterDataUpdateCoordinator,
) -> list[dict[str, Any]]:
    """Id, tag and date for each message. Never the message.

    Whether deletion depends on read state or on age is a live question, and
    the tag and date answer it. The content and the sender answer nothing and
    would put a stranger's message into a file written to be posted publicly,
    so they are not read here at all.
    """
    messages = await coordinator.api.get_sms_messages(mem_store=SMS_STORE_ALL)
    return [
        {
            "id": str(msg.get("id")),
            "tag": msg.get("tag"),
            "date": msg.get("date_decoded") or msg.get("date"),
        }
        for msg in messages
        if msg.get("id") is not None
    ]


def _delete_body(
    msg_id: str,
    ad: str,
    *,
    mem_store: str | None = None,
    not_callback: bool = False,
) -> str:
    """The exact body one variant sends. Shared so the record cannot drift."""
    # A trailing semicolon is how at least one account of this API describes
    # the field. This integration has never sent one, on a single id or a
    # batch. It cannot explain a refusal of a command that carries no `msg_id`
    # at all, so it is a tick-off rather than a lead.
    parts = ["isTest=false", "goformId=DELETE_SMS", f"msg_id={msg_id}"]
    if not_callback:
        parts.append("notCallback=true")
    if mem_store is not None:
        parts.append(f"mem_store={mem_store}")
    parts.append(f"AD={ad}")
    return "&".join(parts)


async def _delete_raw(
    coordinator: ZTERouterDataUpdateCoordinator,
    msg_id: str,
    *,
    token: str | None = None,
    mem_store: str | None = None,
    not_callback: bool = False,
    trailing_semicolon: bool = False,
) -> dict[str, Any]:
    """Send one `DELETE_SMS` in a named variant, bypassing the normal path.

    The integration's own `delete_sms` sends exactly one form. The point here
    is to vary the form, so this builds the body directly rather than calling
    it. `token=None` means a correct one, derived now.
    """
    fields: dict[str, str] = {"msg_id": f"{msg_id};" if trailing_semicolon else msg_id}
    if mem_store is not None:
        fields["mem_store"] = mem_store
    # Carried the way a write was proven to work, where one was. A delete sent
    # through the transport the device refuses would fail for a reason this
    # run has already solved, which is the defect two audits of this release
    # found in two other places.
    transport = {**_ADOPTED}
    if not_callback:
        transport["not_callback"] = True
    return await _attempt(
        coordinator,
        token=token,
        transport=transport,
        command="DELETE_SMS",
        fields=fields,
    )


def _redacted_body(
    msg_id: str,
    *,
    mem_store: str | None = None,
    not_callback: bool = False,
) -> str:
    """The body as it will be sent, with the write token replaced.

    Recorded so a reader can see the exact form rather than infer it from a
    variant's name. The token is a credential and never leaves the device.
    """
    return _delete_body(
        msg_id, "REDACTED", mem_store=mem_store, not_callback=not_callback
    )


async def run_probe(
    coordinator: ZTERouterDataUpdateCoordinator,
    action: str = DEFAULT_ACTION,
) -> dict[str, Any]:
    """Run the stages the action calls for, record everything, stop for nothing.

    `action` selects how far the run goes. `capture` is read-only and is the
    default; `confirm` adds a short set of writes, each read back; `full` is
    every rung, including the token sweep, which no run has yet learned
    anything from but which is kept rather than deleted.

    Held under the coordinator's update lock so a routine poll cannot log in,
    re-list or otherwise interleave with a sequence whose whole value is that
    each step is attributable.
    """
    api = coordinator.api
    report: dict[str, Any] = {
        "started": datetime.now(UTC).isoformat(),
        "action": action,
        "probes": [],
        "completed": False,
        "note": (
            "Temporary diagnostic for issue #56. Probes 1-7 destroy nothing; "
            "8 onward delete messages already targeted for deletion. Probes "
            "3-14 build their own request and never reach the integration's "
            "own recording, so an empty sms.write_failures means probe 15 "
            "succeeded rather than that the recording failed. The 7b rungs "
            "try twelve ways of deriving the write token against a form that "
            "changes nothing; candidates records how many of three attempts "
            "each was accepted for."
        ),
    }
    probes: list[dict[str, Any]] = report["probes"]

    # Stored before anything runs, and mutated in place. The assignment used to
    # be the last line, so any failure anywhere discarded every finding
    # collected up to it — on the one device where a failure is expected.
    # `completed` says whether the run reached the end, so a partial report is
    # not mistaken for a complete one.
    api.delete_probe = report
    coordinator.persist_delete_probe()
    # Cleared per run. Both are module state so that helpers can report to a
    # caller that never sees them, and either left from an earlier run would be
    # attributed to this one — a transport most of all, since an adopted one
    # silently changes how every write below it is carried.
    _CR_NOTE.clear()
    _STATIC_INPUTS.clear()
    _ADOPTED.clear()
    _LAST_SENT.clear()
    _WITH_SESSION.clear()
    _STARTED_AT.clear()
    # Where each switch stood before anything was flipped, so the run can put
    # it back. Read here rather than inside the sweep: by then the first
    # attempt has already changed it.
    for name, _command, aliases, _field, _default in _TOGGLES:
        with contextlib.suppress(Exception):
            _alias, value = await _read_switch(api, aliases)
            if value is not None:
                _STARTED_AT[name] = value

    try:
        async with asyncio.timeout(PROBE_TIMEOUT):
            await _run_rungs(coordinator, report, probes, action)
    except TimeoutError:
        # Everything collected so far is kept. A run that has to be waited out
        # is one the user restarts, and a restart used to lose the report.
        report["timed_out"] = PROBE_TIMEOUT
    except Exception as err:  # noqa: BLE001 - a lost report is the worse outcome
        report["aborted"] = {
            "error_type": type(err).__name__,
            "error": str(err)[:300],
        }
    # Put every switch back where it started, whatever happened above. The
    # sweep alternates, so the value may be one flip away from where it began.
    restored: dict[str, Any] = {}
    for name, command, aliases, field, _default in _TOGGLES:
        started = _STARTED_AT.get(name)
        if started is None:
            continue
        with contextlib.suppress(Exception):
            _alias, now = await _read_switch(api, aliases)
            if now is not None and now != started:
                await _attempt(
                    coordinator,
                    command=command,
                    fields={field: started},
                    transport=_ADOPTED,
                )
                _alias, now = await _read_switch(api, aliases)
            restored[name] = {"started": started, "ended": now}
    if restored:
        report["switches_restored"] = restored

    report["finished"] = datetime.now(UTC).isoformat()
    coordinator.persist_delete_probe()
    return report


# Where a build assigns the write-token globals. On the MC7010 these are plain
# assignments in `js/language.js` and `js/login.js`; a build that does it
# anywhere else is the finding.
_RD_ASSIGN = re.compile(r"""\brd[01]\s*=[^=]""")


async def _capture_stage(
    coordinator: ZTERouterDataUpdateCoordinator,
    report: dict[str, Any],
    probes: list[dict[str, Any]],
) -> None:
    """Return the router's own source, whole, and the two reads that bear on it.

    Read-only throughout. Nothing here is the reporter's data: it is the
    script the router serves to anyone who opens its address, plus two
    version strings.
    """
    api = coordinator.api

    async def crawl() -> dict[str, Any]:
        result = await _crawl(api)
        # Held on the report rather than the probe record so a reader can find
        # the sources without walking the rung list.
        report["source_capture"] = {
            "files": result["files"],
            "sources": result["sources"],
        }
        return {
            key: result[key]
            for key in (
                "fetched",
                "returned",
                "returned_bytes",
                "missing",
                "truncated",
                "unvisited_queue",
                "capped",
            )
        }

    probes.append(await _capture(coordinator, "24a_source_crawl", crawl))

    async def rd_assignment() -> dict[str, Any]:
        """Every site that assigns `rd0` or `rd1`, with its surroundings."""
        sources: dict[str, str] = report.get("source_capture", {}).get("sources", {})
        sites: dict[str, list[str]] = {}
        for path, text in sources.items():
            found = [
                text[max(0, m.start() - 300) : m.start() + 300]
                for m in _RD_ASSIGN.finditer(text)
            ]
            if found:
                sites[path] = found
        return {
            "files_with_an_assignment": sorted(sites),
            "sites": sites,
            "reference_device_assigns_in": ["js/language.js", "js/login.js"],
        }

    probes.append(await _capture(coordinator, "24b_rd_assignment", rd_assignment))

    async def token_operands() -> dict[str, Any]:
        """Does this device answer `cr_version`, and with what?

        The shipped derivation uses `wa_inner_version` alone. That matches the
        firmware only where `cr_version` is unanswered, which is true of the
        reference device and need not be true here.
        """
        keys = ["cr_version", "wa_inner_version", "wa_version", "hardware_version"]
        # `requested=` so the session guard knows which names were asked for.
        # Without it, a device that answers one of four — which is this
        # reference device, three of them being unanswered here — is judged to
        # have an expired session and the rung raises instead of reporting.
        answer = await api._request(  # noqa: SLF001
            "GET",
            "goform/goform_get_cmd_process?isTest=false&multi_data=1&cmd="
            + ",".join(keys),
            requested=keys,
            _retry=False,
        )
        cr = str(answer.get("cr_version") or "")
        wa = str(answer.get("wa_inner_version") or "")
        return {
            "cr_version_answered": bool(cr),
            "cr_version_length": len(cr),
            "wa_inner_version_length": len(wa),
            "operands_differ_from_shipped": bool(cr),
        }

    probes.append(await _capture(coordinator, "24c_token_operands", token_operands))


async def _run_rungs(
    coordinator: ZTERouterDataUpdateCoordinator,
    report: dict[str, Any],
    probes: list[dict[str, Any]],
    action: str = DEFAULT_ACTION,
) -> None:
    """Every rung the chosen action calls for, in order, under the lock.

    The order is not the rung numbering. Capture runs first because it is the
    only stage expected to return something not already known, and because the
    stages below it can lock the account out or exhaust the run's budget; a
    run that sweeps first and captures afterwards can lose the capture to a
    failure in work whose answer is already recorded.

    `capture` stops after the read-only stages. `confirm` adds the writes that
    are few enough to read back individually. `full` is every rung this module
    has ever carried, including the token sweep, and is kept because nothing
    here has yet explained the fault — not because a repeat is expected to.
    """
    api = coordinator.api
    writes = action in (ACTION_CONFIRM, ACTION_FULL)
    sweep = action == ACTION_FULL
    report["action"] = action
    async with coordinator._async_update_lock:  # noqa: SLF001 - the lock is the point
        # --- 24. The router's own source, in full ---------------------------
        # First, and read-only. Six runs of marker mining answered questions
        # chosen in advance; this returns the files themselves, so a question
        # nobody thought to ask can still be answered from the download.
        await _capture_stage(coordinator, report, probes)
        # Persisted before a single write is attempted, so a lockout or a
        # timeout in any stage below cannot cost the capture.
        coordinator.persist_delete_probe()

        # --- 22. What the router's own web client does ----------------------
        # Read-only, and it supplies the forms the write rungs below send.
        web = await _web_ui_rungs(coordinator, report, probes)

        if sweep:
            # --- 0. Can any login produce a session that writes? ----------------
            # First, because everything below assumes one, and the session it
            # settles on is the session the rest of the pass runs under. Read the
            # docstring on `_login_stage` for why this is budgeted rather than
            # exhaustive.
            #
            # Rungs below that log in again — `1_token_rotation` and
            # `13_single_id_fresh_session` — use the shipped form by design, since
            # what they measure is what a renewal does. Where an adopted session
            # was in force, `report["session_in_use"]` says so and those two rungs
            # are read against it rather than against the adopted one.
            await _login_stage(coordinator, report, probes)

        # --- 1. Does the write token change when the session is renewed? ----
        # If it does, a replayed write carrying its original token was always
        # going to be refused. Read-only.
        async def token_rotation() -> dict[str, Any]:
            before_rd = await api.get_rd()
            before_ad = await api.get_ad()
            await api.login()
            after_rd = await api.get_rd()
            after_ad = await api.get_ad()
            return {
                "rd_changed_on_login": before_rd != after_rd,
                "ad_changed_on_login": before_ad != after_ad,
            }

        probes.append(await _capture(coordinator, "1_token_rotation", token_rotation))

        # The router's own totals, before anything is deleted.
        with contextlib.suppress(Exception):
            report["counters_before"] = await _counters(coordinator)

        # --- 1b. Which step of deriving a write token fails? ----------------
        # Every rung that derived a token failed and the one rung that supplied
        # its own succeeded, so the fault is inside that derivation. It makes
        # three calls and any of them could be the one; these separate them,
        # and none of them writes anything.

        async def liveness_keys() -> dict[str, Any]:
            path = (
                "goform/goform_get_cmd_process?isTest=false&multi_data=1&cmd="
                + ",".join(LIVENESS_KEYS)
            )
            answer = await api._request("GET", path, _retry=False)  # noqa: SLF001
            return {
                "answer": dict(answer),
                "verdict": _classify_session(
                    answer, list(LIVENESS_KEYS), api.unauthenticated_key_set()
                ),
                "unauthenticated_keys": sorted(api.unauthenticated_key_set()),
            }

        probes.append(await _capture(coordinator, "1b_liveness_keys", liveness_keys))

        async def session_check() -> str:
            await api._ensure_session()  # noqa: SLF001 - the step under suspicion
            return "returned"

        probes.append(await _capture(coordinator, "1c_session_check", session_check))

        async def version_read() -> dict[str, Any]:
            return {"version": await api.get_version()}

        probes.append(await _capture(coordinator, "1d_version", version_read))

        async def rd_read() -> dict[str, Any]:
            value = await api.get_rd()
            return {"rd_length": len(value or "")}

        probes.append(await _capture(coordinator, "1e_rd", rd_read))

        async def token_full() -> dict[str, Any]:
            return {"token_length": len(await api.get_ad())}

        probes.append(await _capture(coordinator, "1f_token", token_full))

        # --- 1g. What does this device answer on a session seconds old? -----
        # Names and counts only, no values. Groundwork for replacing the
        # hand-picked session-check key list with one drawn from the device
        # itself; `.notes/issues/other_router_access/` carries that plan.
        #
        # **This takes an inventory. It does not test discrimination.** Knowing
        # which of these keys go blank when the session dies would need a
        # session that can be made to die on demand, and this device does not
        # acknowledge a logout, so `measure_unauthenticated_keys` returns
        # nothing on it. What can be established is how much a baseline would
        # have to work with: the MC888 Pro answered 62 of 128 core keys on
        # first contact, so a device having enough populated keys to draw on is
        # not a given.
        async def login_baseline() -> dict[str, Any]:
            await api.login()
            payload: dict[str, Any] = {}
            for params in (_CORE_PARAMS, _EXTENDED_PARAMS):
                with contextlib.suppress(Exception):
                    payload.update(await api._batch_get(params))  # noqa: SLF001
            populated = sorted(
                key
                for key, value in payload.items()
                if isinstance(value, str) and value
            )
            unauthenticated = api.unauthenticated_key_set()
            return {
                "read": len(payload),
                "populated_count": len(populated),
                "populated_keys": populated,
                "session_check_keys_populated": [
                    key for key in LIVENESS_KEYS if key in populated
                ],
                "identity": {
                    "model_name": str(payload.get("model_name") or ""),
                    "wa_inner_version": str(payload.get("wa_inner_version") or ""),
                },
                "excluded_as_unauthenticated": sorted(set(populated) & unauthenticated),
            }

        probes.append(await _capture(coordinator, "1g_login_baseline", login_baseline))

        # --- 2. Where do the messages actually live? ------------------------
        async def bank_listing() -> dict[str, Any]:
            counts = {}
            for label, store in (
                ("device", SMS_STORE_DEVICE),
                ("sim", SMS_STORE_SIM),
                ("all", SMS_STORE_ALL),
            ):
                messages = await api.get_sms_messages(mem_store=store)
                counts[label] = [
                    str(m.get("id")) for m in messages if m.get("id") is not None
                ]
            return counts

        probes.append(await _capture(coordinator, "2_bank_listing", bank_listing))

        if not writes:
            report["completed"] = True
            return

        # --- 3-6. The write path, with nothing at risk ----------------------
        # A delete naming an id the router does not hold. If this is refused,
        # the fault is not about his messages at all.
        variants: list[tuple[str, dict[str, Any]]] = [
            ("3_absent_id", {}),
            ("4_absent_id_bad_token", {"token": BAD_TOKEN}),
            ("5_absent_id_not_callback", {"not_callback": True}),
            ("6a_absent_id_store_device", {"mem_store": SMS_STORE_DEVICE}),
            ("6b_absent_id_store_all", {"mem_store": SMS_STORE_ALL}),
            # A trailing semicolon on a single id, which one account of this
            # API says the field expects. Never sent before, on a single or a
            # batch. It cannot explain a refusal of a command carrying no
            # `msg_id` at all, so it is a tick-off rather than a lead.
            ("6c_absent_id_trailing_semicolon", {"trailing_semicolon": True}),
        ]
        for name, kwargs in variants:
            probes.append(
                await _capture(
                    coordinator,
                    name,
                    lambda k=kwargs: _delete_raw(coordinator, ABSENT_ID, **k),
                    sent=_redacted_body(
                        ABSENT_ID,
                        mem_store=kwargs.get("mem_store"),
                        not_callback=bool(kwargs.get("not_callback")),
                    ),
                )
            )

        # --- 7. Does any write work on this device? -------------------------
        # The data limit written back at exactly the values it already holds.
        # Chosen because this firmware populates it and the outdoor-unit LED
        # command it does not. Nothing changes.
        async def harmless_write() -> dict[str, Any]:
            # `set_data_volume_settings` is a read-modify-write and refuses a
            # partial form, so it takes the whole poll payload and picks the
            # fields out itself. Passing no changes writes back exactly what
            # is already set.
            current = dict(coordinator.data or {})
            result = await api.set_data_volume_settings(current)
            return {"result": result}

        probes.append(await _capture(coordinator, "7_harmless_write", harmless_write))

        # --- 20. The same write, sent differently, and two questions the
        # rungs above cannot answer. None of this touches a message.
        #
        # **Before the token sweep, not after.** Finding a carrier costs seven
        # writes and the sweep costs a hundred and fifty; running them the
        # other way round screens every rule through a carrier that may be the
        # thing being refused, and reports a hundred and fifty refusals for a
        # reason the run went on to solve two rungs later. The MC7010 download
        # of 2026-09-10 showed exactly that: every screened attempt carried
        # `Content-Type` alone, because the root `Referer` was not adopted
        # until afterwards.
        #
        # The rung numbers are left as they are so a download stays comparable
        # with the three that came before it.
        await _transport_rungs(coordinator, report, probes)

        working: str | None = None
        working_token: str | None = None
        if sweep:
            working, working_token = await _candidate_rungs(coordinator, report, probes)

        await _web_ui_write_rungs(coordinator, report, probes, web)
        await _session_proof_rung(coordinator, probes)

        if not sweep:
            report["completed"] = True
            return

        # --- 21. The axes crossed, where a session allows it ------------
        await _combination_rungs(coordinator, report, probes)

        await _real_message_rungs(coordinator, report, probes)

        await _confirmed_variant_rungs(coordinator, probes, working, working_token)
        # --- 15. The integration's own path, unmodified ---------------------
        # Everything above builds its own request, so none of it exercises
        # delete_all, its verification step, or the write-failure recording
        # this release added. Without this rung a report can show every variant
        # succeeding while the button the user presses still fails.
        #
        # api.delete_all() directly, never the service handler: that ends in a
        # refresh which takes the lock this run is already holding.
        record = await _capture(
            coordinator, "15_integration_delete_all", api.delete_all
        )
        with contextlib.suppress(Exception):
            record["ids_after"] = await _surviving_ids(coordinator)
        probes.append(record)

        with contextlib.suppress(Exception):
            report["ids_remaining"] = await _surviving_ids(coordinator)
        with contextlib.suppress(Exception):
            report["counters_after"] = await _counters(coordinator)
        report["completed"] = True


async def _real_message_rungs(
    coordinator: ZTERouterDataUpdateCoordinator,
    report: dict[str, Any],
    probes: list[dict[str, Any]],
) -> None:
    """The delete ladder, one variant per message, messages already doomed.

    Extracted from the sequence so that reading the sequence shows which
    stages an action runs, rather than sixty lines of one of them.
    """
    api = coordinator.api
    # --- 8 onward. Real messages, one variant each ----------------------
    # Id, tag and date only. Whether deletion depends on read state or on
    # age is a live question; the message itself answers nothing.
    # Guarded: a listing that fails here used to abort the run and take
    # every finding above it with it.
    report["messages_before"] = []
    with contextlib.suppress(Exception):
        report["messages_before"] = await _message_summary(coordinator)
    available = [str(entry["id"]) for entry in report["messages_before"]]
    report["messages_available"] = list(available)
    real_variants: list[tuple[str, dict[str, Any], int]] = [
        ("8_single_id", {}, 1),
        # Repeated so a failure can be told apart from a one-off.
        ("9_single_id_repeat", {}, 1),
        ("10_single_id_store_all", {"mem_store": SMS_STORE_ALL}, 1),
        ("11_single_id_not_callback", {"not_callback": True}, 1),
        ("12_single_id_delayed_relist", {}, 1),
        ("13_single_id_fresh_session", {}, 1),
        # The form the Delete All button actually sends. Nothing above
        # tests it, and a router that accepts one id but refuses a batch
        # would pass every rung above while the button kept failing.
        ("14_batch_semicolon", {}, 2),
    ]
    consumed = 0
    for name, kwargs, needs in real_variants:
        targets = available[consumed : consumed + needs]
        if len(targets) < needs:
            probes.append(
                {
                    "probe": name,
                    "outcome": "skipped",
                    "reason": f"needs {needs} message(s), not enough left",
                }
            )
            continue
        consumed += needs
        msg_id = ";".join(targets)
        if name.endswith("fresh_session"):
            # Guarded for the same reason: a re-login that fails is a
            # finding about the device, not a reason to lose the run.
            with contextlib.suppress(Exception):
                await api.login()
        record = await _capture(
            coordinator,
            name,
            lambda i=msg_id, k=kwargs: _delete_raw(coordinator, i, **k),
            sent=_redacted_body(
                msg_id,
                mem_store=kwargs.get("mem_store"),
                not_callback=bool(kwargs.get("not_callback")),
            ),
        )
        record["id_targeted"] = msg_id
        if name.endswith("delayed_relist"):
            # A router that deletes lazily would be reported as refusing,
            # because the check re-lists at once.
            await asyncio.sleep(LAZY_DELETE_WAIT)
            record["waited_seconds"] = LAZY_DELETE_WAIT
        with contextlib.suppress(Exception):
            record["ids_after"] = await _surviving_ids(coordinator)
        probes.append(record)


async def _login_stage(
    coordinator: ZTERouterDataUpdateCoordinator,
    report: dict[str, Any],
    probes: list[dict[str, Any]],
) -> str | None:
    """Find a login whose session can write, before anything else is tried.

    Every other question in this run assumes a session that may write. If the
    reporter's device has never granted one, every rung below is measuring the
    same refusal over and over — which is what three downloads have shown.

    **Budgeted against a lockout that cannot be observed.** A failed login is
    recognised only by `result: "3"`; no readable field counts them on either
    device. After `BAD_LOGIN_GROUP` of them a known-good login is made, on the
    assumption that a correct login clears the allowance. Attempts are spaced
    by `LOGIN_DELAY`, and the stage stops early if the router stops answering
    logins at all, which is what a lockout would look like from here.

    Returns the name of the variant whose session wrote, or `None`.
    """
    api = coordinator.api
    spent = 0
    winner: str | None = None
    winning_variant: dict[str, Any] | None = None
    with_session: list[dict[str, Any]] = []
    report["login_variants"] = {}

    for variant in await _login_variants(api):
        name = variant["name"]

        if spent >= BAD_LOGIN_GROUP:
            # Assumed to clear the allowance. Recorded either way, because if
            # the assumption is wrong this is the rung that will show it.
            reset = await _capture(
                coordinator, f"0z_reset_after_{spent}_failures", api.login
            )
            probes.append(reset)
            spent = 0
            await asyncio.sleep(LOGIN_DELAY)
            if reset["outcome"] == "raised":
                report["login_stage_stopped"] = (
                    "a known-good login failed, which is what a lockout looks "
                    "like from here; the remaining variants were not tried"
                )
                break

        record = await _capture(
            coordinator, f"0a_{name}", lambda v=variant: _try_login(api, v)
        )
        outcome = record.get("result")
        probes.append(record)
        await asyncio.sleep(LOGIN_DELAY)

        established = isinstance(outcome, dict) and bool(outcome.get("cookie_names"))
        if established:
            with_session.append(variant)
        # Anything that did not establish a session is counted as spent, not
        # only what answered `result: "3"`. That code is measured on one
        # device; a router that refuses some other way, or answers nothing,
        # would leave the counter still and quietly bypass the budget — and
        # this is the one place where being wrong costs the user a locked
        # router rather than a missing finding.
        if not established:
            spent += 1
            report["login_variants"][name] = "no session"
            continue

        # A session is not the finding. A session that writes is.
        write = await _capture(
            coordinator,
            f"0b_{name}_write",
            lambda: _data_volume_write(coordinator, None),
        )
        write["wrote"] = _wrote(write)
        probes.append(write)
        report["login_variants"][name] = "wrote" if write["wrote"] else "session only"
        if write["wrote"] and winner is None:
            winner, winning_variant = name, variant
        await asyncio.sleep(ATTEMPT_DELAY)

    report["login_variant_that_wrote"] = winner
    report["logins_with_a_session"] = [v["name"] for v in with_session]
    _WITH_SESSION.clear()
    _WITH_SESSION.extend(with_session)

    # --- adopt it -------------------------------------------------------
    # Every rung below this one asks a question that only means something on a
    # session that can write. Recording which login unlocked the device and
    # then running the rest of the pass on the shipped one would answer the
    # hardest question in the run and then decline to use the answer, which
    # costs another round trip with the reporter for work this pass already
    # had the router in front of it to do.
    if winning_variant is not None:
        adopted = await _capture(
            coordinator,
            f"0y_adopt_{winner}",
            lambda v=winning_variant: _try_login(api, v),
        )
        probes.append(adopted)
        result = adopted.get("result")
        report["session_in_use"] = (
            winner
            if isinstance(result, dict) and result.get("cookie_names")
            else "shipped login: the winning variant did not re-establish"
        )
        if isinstance(result, dict) and result.get("cookie_names"):
            return winner

    # Nothing won, or the winner would not come back. The run continues on the
    # session this integration would normally hold, so the rungs below at least
    # measure the shipped path rather than no path at all.
    report.setdefault("session_in_use", "shipped login")
    with contextlib.suppress(Exception):
        await api.login()
    return winner


async def _candidate_rungs(
    coordinator: ZTERouterDataUpdateCoordinator,
    report: dict[str, Any],
    probes: list[dict[str, Any]],
) -> tuple[str | None, Any]:
    """Every distinct token these rules can produce, against a harmless write.

    The data-volume form written back at exactly the values it already holds is
    not an SMS command, so a refusal here says no write works on this device
    rather than anything about messages. It changes nothing, so it can be
    repeated.

    **Screened once, then confirmed three times.** A wrong token is refused
    deterministically — the reporter's device answered a correct one and a
    deliberately malformed one identically across sixty probes — so one attempt
    is enough to rule a token out, and the space is far too large to spend
    three on each. Acceptance still requires three successes out of three; the
    screening pass only decides what is worth confirming.

    Every candidate is screened whatever the earlier ones did. Stopping at the
    first success would leave the rest unknown, which is another round trip
    with the reporter for a fact this run had the router in front of it to
    settle.

    Returns the accepted candidate and its token, or `(None, None)`.
    """
    api = coordinator.api
    inputs = await _capture(coordinator, "7a_token_inputs", lambda: _token_inputs(api))
    raw = inputs.get("result")
    values: dict[str, Any] = raw if isinstance(raw, dict) else {}
    wa = str(values.get("wa") or "")
    cr = str(values.get("cr") or "")
    rd = str(values.get("rd") or "")
    # Lengths and presence only. The version strings identify a firmware and
    # `RD` is a session value; neither is published.
    inputs["result"] = {
        "wa_inner_version_length": len(wa),
        "wa_version_length": len(str(values.get("wav") or "")),
        "wa_version_differs": bool(values.get("wav")) and values.get("wav") != wa,
        "cr_version_length": len(cr),
        "ld_length": len(str(values.get("ld") or "")),
        "hardware_version_answered": bool(values.get("hw")),
        "model_name_answered": bool(values.get("model")),
        "rd_length": len(rd),
        "cr_version_answered": bool(cr),
    }
    if _CR_NOTE:
        inputs["result"]["cr_version_note"] = _CR_NOTE.get("error")

    space = _token_space(values) if rd else []
    inputs["result"]["distinct_tokens"] = len(space)
    probes.append(inputs)
    report["candidates"] = {}
    report["candidates_passed"] = []
    report["working_variant"] = None

    if not space:
        probes.append(
            {
                "probe": "7b_token_space",
                "outcome": "skipped",
                "reason": "the firmware string or RD did not read, so no token "
                "could be built",
            }
        )
        return None, None

    # --- 7b. The screening pass -----------------------------------------
    # One attempt each, recorded as a table rather than one probe record per
    # token: 150 records of the same refusal is not evidence, it is volume.
    async def one(rule: Any, verify: bool = False) -> dict[str, Any]:
        # Read fresh, every time. The token is single-use and a read re-arms
        # it; reusing one guarantees a refusal that says nothing about the rule.
        fresh = await _token_inputs(api)
        token = rule(fresh)
        return await _data_volume_write(coordinator, token, verify=verify)

    survivors: dict[str, Any] = {}
    for index, (name, rule) in enumerate(space):
        # Verified on a sample rather than on every attempt: a read-back per
        # rule would roughly double a sweep of nearly a thousand. The sample
        # proves the refusals are real refusals, and any attempt that claims
        # success is re-run verified immediately below.
        sample = index % VERIFY_EVERY == 0
        record = await _capture(
            coordinator, f"7b_{name}", lambda r=rule, v=sample: one(r, v)
        )
        if _wrote(record) and not sample:
            # It said yes. Do not take its word for it.
            record = await _capture(
                coordinator, f"7b_{name}_verified", lambda r=rule: one(r, True)
            )
        record["verified"] = _verified(record)
        wrote = _wrote(record)
        # Every attempt is kept, not only the ones that worked. Collapsing a
        # refusal to the word "refused" discards the router's own answer, the
        # status, the timing and what was carried — on the part of the run most
        # likely to hold the finding. A token refused *differently* from its
        # neighbours would have been invisible.
        probes.append(record)
        report["candidates"][name] = "screened: wrote" if wrote else "screened: refused"
        if wrote:
            survivors[name] = rule
        await asyncio.sleep(SCREEN_DELAY)

    report["screened"] = len(space)
    if not survivors:
        return None, None

    # --- 7h. Confirm before spending a message --------------------------
    # A token that works once and fails the next three is not a method.
    accepted: str | None = None
    accepted_rule: Any = None
    for name, rule in survivors.items():
        outcomes: list[bool] = []
        for attempt in range(1, WRITE_ATTEMPTS + 1):
            # Verified, always. This is the gate that decides whether real
            # messages are spent, so it is the last place to take the
            # router's word for its own write.
            record = await _capture(
                coordinator, f"7h_{name}_{attempt}", lambda r=rule: one(r, True)
            )
            record["verified"] = _verified(record)
            record["wrote"] = _wrote(record)
            outcomes.append(record["wrote"])
            probes.append(record)
            await asyncio.sleep(ATTEMPT_DELAY)
        passed = all(outcomes)
        report["candidates"][name] = f"{sum(outcomes)}/{WRITE_ATTEMPTS} confirmed"
        if passed:
            report["candidates_passed"].append(name)
            if accepted is None:
                accepted, accepted_rule = name, rule

    report["working_variant"] = accepted
    report["working_variant_confirmed"] = accepted
    return accepted, accepted_rule


def _carriers(api: Any) -> list[tuple[str, dict[str, Any]]]:
    """Every way of carrying a write that is worth trying on this device.

    Shared by the single-axis pass and the combination pass, so a carrier
    cannot be tried in one and forgotten in the other.
    """
    root = api.referer
    values: list[tuple[str, dict[str, Any]]] = [
        # The site root rather than `index.html`, which is what both reference
        # implementations send.
        (
            "20a_referer_root",
            {
                "headers": {
                    "Referer": root,
                    "Content-Type": "application/x-www-form-urlencoded",
                }
            },
        ),
        # The headers a browser sends, which `nicjac` reproduces in full.
        (
            "20b_browser_headers",
            {
                "headers": {
                    "Referer": root,
                    "Origin": root.rstrip("/"),
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                }
            },
        ),
        # No content type at all, which is what `Kajkac` sends.
        ("20c_no_content_type", {"headers": {"Referer": root}}),
        # `Kajkac` carries `notCallback` on its writes; this integration sends
        # it only on a delete, so it has never been tried on anything else.
        ("20n_not_callback", {"not_callback": True}),
        # A query string rather than a body. `nicjac` logs in by GET against
        # this same endpoint, so the firmware reads parameters from the query
        # on at least one command.
        ("20i_write_as_query", {"method": "GET", "as_query": True}),
        # `Kajkac` attaches a cookie only when it is named `stok`, so on a
        # device issuing `zsidn` it sends none at all.
        ("20j_no_cookie", {"cookies": {}}),
        # The same value under the other name, which asks whether the firmware
        # reads the name rather than the value.
        (
            "20k_cookie_named_stok",
            {"cookies": {"stok": next(iter(dict(api.cookies).values()), "")}},
        ),
        # Both names at once, in case the firmware reads one and the session
        # is keyed on the other.
        (
            "20o_both_cookies",
            {
                "cookies": {
                    **dict(api.cookies),
                    "stok": next(iter(dict(api.cookies).values()), ""),
                }
            },
        ),
        # Where the token sits in the request, and what it is called. None of
        # these is supported by anything read; all are cheap, and nothing has
        # worked, so nothing is held back.
        ("20p_token_first", {"token_first": True}),
        ("20q_token_lowercase", {"token_field": "ad"}),
        ("20r_token_in_header", {"token_in_header": True}),
        ("20s_token_in_query", {"token_in_query": True}),
        ("20t_is_test_true", {"is_test": "true"}),
        ("20u_multi_data", {"multi_data": True}),
    ]

    return values


# The derivations with a source behind them, for the combination pass. The
# full space is too large to cross with anything; these six are what miononno,
# `nicjac`, `Kajkac`, the MF266 documentation and this integration actually
# use.
def _operand(name: str) -> Any:
    """One operand builder, by the name it is listed under."""
    return next(builder for listed, builder in _OPERANDS if listed == name)


_CITED_RULES: tuple[tuple[str, Any], ...] = (
    (
        "wacr_sha_ll",
        _rule(_operand("wacr"), _sha, _RD_FORMS[0][1], str.lower, str.lower, 2),
    ),
    (
        "wacr_sha_uu",
        _rule(_operand("wacr"), _sha, _RD_FORMS[0][1], str.upper, str.upper, 2),
    ),
    (
        "wacr_md5_ll",
        _rule(_operand("wacr"), _md5, _RD_FORMS[0][1], str.lower, str.lower, 2),
    ),
    (
        "wa_sha_uu",
        _rule(_operand("wa"), _sha, _RD_FORMS[0][1], str.upper, str.upper, 2),
    ),
    (
        "wa_md5_ll",
        _rule(_operand("wa"), _md5, _RD_FORMS[0][1], str.lower, str.lower, 2),
    ),
    (
        "crwa_md5_lu",
        _rule(_operand("crwa"), _md5, _RD_FORMS[0][1], str.lower, str.upper, 2),
    ),
    # The pair that is internally consistent on the reporter's firmware — both
    # `1.0.1` — in the two cases a source documents for this family.
    (
        "wavcr_sha_uu",
        _rule(_operand("wavcr"), _sha, _RD_FORMS[0][1], str.upper, str.upper, 2),
    ),
    (
        "wavcr_sha_ll",
        _rule(_operand("wavcr"), _sha, _RD_FORMS[0][1], str.lower, str.lower, 2),
    ),
)


async def _transport_rungs(
    coordinator: ZTERouterDataUpdateCoordinator,
    report: dict[str, Any],
    probes: list[dict[str, Any]],
) -> None:
    """Every way of carrying the same write, and the first that works is kept.

    Each value is something another implementation does and this one does not,
    or the reverse. None is attested as necessary — neither reference project
    is itself attested as writing on an MC888 — so they are tried rather than
    adopted on authority.

    **A proven transport is held for the rest of the run.** Two audits of this
    release found the same defect in two places: a value discovered and then
    not used, so every rung below went on failing in a way the run had already
    shown how to fix. `_ADOPTED` is replaced in place, and everything that
    writes through `_attempt` inherits it without being told.

    All of these carry the data-volume form, so none spends a message and none
    changes a setting.
    """
    api = coordinator.api
    values = _carriers(api)

    report["transport_variants"] = {}
    for name, transport in values:
        record = await _capture(
            coordinator, name, lambda t=transport: _attempt(coordinator, transport=t)
        )
        record["wrote"] = _wrote(record)
        probes.append(record)
        report["transport_variants"][name] = "wrote" if record["wrote"] else "refused"
        if record["wrote"] and not _ADOPTED:
            _ADOPTED.update(transport)
            report["transport_in_use"] = name
        await asyncio.sleep(ATTEMPT_DELAY)

    report.setdefault("transport_in_use", "shipped transport")

    # --- 20d, 20g, 20h, 20l. When the token is derived, relative to the write
    # The token is single-use: measured on the reference MC7010, a second write
    # carrying the same one is refused at any delay, and re-reading the inputs
    # re-arms it. What that did not settle is whether an unrelated request
    # between deriving and posting also spends it — which matters because
    # `get_ad` makes three calls of its own before the write follows.
    async def after_fresh_login() -> dict[str, Any]:
        await api.login()
        return await _attempt(coordinator, transport=_ADOPTED)

    async def derive_then_post() -> dict[str, Any]:
        token = await api.get_ad()
        return await _attempt(coordinator, token=token, transport=_ADOPTED)

    async def derive_read_then_post() -> dict[str, Any]:
        token = await api.get_ad()
        # One read, deliberately unrelated to the token.
        await api.get_params(["signalbar"])
        return await _attempt(coordinator, token=token, transport=_ADOPTED)

    async def token_captured_at_login() -> dict[str, Any]:
        # `Kajkac` computes `AD` during authentication and reuses it for every
        # protected write; `nicjac` derives fresh per write, as this
        # integration does. The two disagree and neither is attested here.
        token = await api.get_ad()
        await api.login()
        return await _attempt(coordinator, token=token, transport=_ADOPTED)

    for name, run in (
        ("20d_write_after_fresh_login", after_fresh_login),
        ("20g_derive_then_post", derive_then_post),
        ("20h_derive_read_then_post", derive_read_then_post),
        ("20l_token_captured_at_login", token_captured_at_login),
    ):
        record = await _capture(coordinator, name, run)
        record["wrote"] = _wrote(record)
        probes.append(record)
        await asyncio.sleep(ATTEMPT_DELAY)

    # Does the firmware carry the RED payload encryption `Kajkac` implements
    # for newer MC888 builds? Read only; nothing is negotiated or sent.
    async def red_present() -> dict[str, Any]:
        answer = await api._request(  # noqa: SLF001 - a name the integration never asks for
            "GET",
            "goform/goform_get_cmd_process?isTest=false&cmd=web_crt_get",
        )
        value = (answer or {}).get("web_crt_get") or (answer or {}).get("result") or ""
        return {
            "answered": bool(value),
            "looks_like_a_public_key": "BEGIN PUBLIC KEY" in str(value),
        }

    probes.append(await _capture(coordinator, "20e_red_crypto_present", red_present))

    # Names from bundles the earlier mining could not read. The reporter's
    # discovery pass recorded `js/statusBar.js: HTTP 404`, so its 997 names
    # came from the bundles that answered.
    async def remine() -> dict[str, Any]:
        names, notes = await api.mine_candidate_names()
        return {"mined": len(names), "notes": notes}

    probes.append(await _capture(coordinator, "20m_remine_bundles", remine))

    # --- 20v. A second command, from an unrelated part of the firmware -----
    # Everything else here writes the data-volume form. If the refusal is
    # device-wide rather than specific to that command, a switch from the LED
    # subsystem is refused too — and if it is not, we have found a write that
    # works and can compare it against the ones that do not.
    second = _TOGGLES[1]

    async def other_subsystem() -> dict[str, Any]:
        return await _attempt(
            coordinator,
            transport=_ADOPTED,
            command=second[1],
            toggle=second,
            verify=True,
        )

    # Only where the device answers the switch. A router that does not carry
    # this field at all — the reference MC7010 does not — would otherwise
    # record a refusal that looks like the finding this rung exists to make,
    # when it is really "we could not read it".
    _alias, present = await _read_switch(api, second[2])
    if present is None:
        probes.append(
            {
                "probe": "20v_led_night_toggle",
                "outcome": "skipped",
                "reason": (
                    f"this device does not answer {second[3]}, so the write "
                    f"could not be verified and was not sent"
                ),
            }
        )
    else:
        record = await _capture(coordinator, "20v_led_night_toggle", other_subsystem)
        record["wrote"] = _wrote(record)
        record["verified"] = _verified(record)
        probes.append(record)
        await asyncio.sleep(ATTEMPT_DELAY)


async def _combination_rungs(
    coordinator: ZTERouterDataUpdateCoordinator,
    report: dict[str, Any],
    probes: list[dict[str, Any]],
) -> None:
    """Cross the axes, where a session can be established to cross them under.

    Every rung above this one varies a single axis and holds the others at
    their shipped value. A fault needing two at once — a particular login *and*
    a particular carrier, or a particular login and a particular derivation —
    would pass through all of them unseen, and nothing measured on the
    reporter's device rules that out.

    **Bounded deliberately.** The full product is twelve logins by seven
    carriers by a hundred and fifty rules, which cannot run. This crosses the
    logins that actually established a session — one to three, on the evidence
    so far — against the seven carriers and against the derivations that have
    a source behind them. A write is cheap; only the login axis is constrained
    by the lockout, and these reuse sessions already established rather than
    spending new attempts on them.
    """
    api = coordinator.api
    report["combinations"] = {}
    if not _WITH_SESSION:
        probes.append(
            {
                "probe": "21_combinations",
                "outcome": "skipped",
                "reason": "no login variant established a session to cross under",
            }
        )
        return

    cited = list(_CITED_RULES)
    for variant in _WITH_SESSION:
        login = variant["name"]
        established = await _capture(
            coordinator, f"21a_{login}_session", lambda v=variant: _try_login(api, v)
        )
        probes.append(established)
        result = established.get("result")
        if not (isinstance(result, dict) and result.get("cookie_names")):
            report["combinations"][login] = "the session would not come back"
            continue

        wrote: list[str] = []
        for carrier, transport in _carriers(api):
            record = await _capture(
                coordinator,
                f"21b_{login}_{carrier}",
                lambda t=transport: _attempt(coordinator, transport=t),
            )
            record["wrote"] = _wrote(record)
            probes.append(record)
            if record["wrote"]:
                wrote.append(carrier)
            await asyncio.sleep(SCREEN_DELAY)

        for rule_name, rule in cited:

            async def one(r: Any = rule) -> dict[str, Any]:
                fresh = await _token_inputs(api)
                token = r(fresh)
                return await _attempt(coordinator, token=token)

            record = await _capture(coordinator, f"21c_{login}_{rule_name}", one)
            record["wrote"] = _wrote(record)
            probes.append(record)
            if record["wrote"]:
                wrote.append(rule_name)
            await asyncio.sleep(SCREEN_DELAY)

        report["combinations"][login] = wrote or "nothing wrote under this session"

    # Back to whatever the run had settled on.
    with contextlib.suppress(Exception):
        await api.login()


async def _web_ui_rungs(
    coordinator: ZTERouterDataUpdateCoordinator,
    report: dict[str, Any],
    probes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Read the client the router ships, and record where it disagrees with us.

    Five probe versions decided what to send from constants written in this
    project, checked against one device. The router serves a working client of
    its own API; what that client sends is not a guess.

    Read-only throughout, and none of it is the reporter's data.

    Returns what was extracted, so the write rungs below can send the router's
    own form alongside ours.
    """
    api = coordinator.api
    found: dict[str, Any] = {"bundles": {}, "commands": {}, "captures": {}}

    # --- 22a. The index, and what it names ------------------------------
    async def index() -> dict[str, Any]:
        status, headers, body = await _fetch_text(api, "index.html")
        srcs = _SCRIPT_SRC.findall(body) if status == 200 else []
        main = _DATA_MAIN.findall(body) if status == 200 else []
        found["entry"] = main[0] if main else ""
        found["index_scripts"] = srcs
        return {
            "status": status,
            "bytes": len(body),
            "header_names": headers,
            "script_src": srcs,
            "data_main": main,
            # The head, so a page naming nothing is diagnosed rather than
            # guessed at a second time.
            "head": body[: body.find("</head>") + 7][:1500] if status == 200 else "",
            "sets_a_cookie": "Set-Cookie" in headers,
        }

    probes.append(await _capture(coordinator, "22a_index", index))

    # --- 22b. The module list the loader carries ------------------------
    async def modules() -> dict[str, Any]:
        entry = found.get("entry") or ""
        if not entry:
            return {"entry": "", "note": "the index named no entry point"}
        path = entry if entry.endswith(".js") else f"{entry}.js"
        status, _headers, body = await _fetch_text(api, path)
        paths = _module_paths(body) if status == 200 else {}
        found["modules"] = paths
        return {
            "entry": path,
            "status": status,
            "bytes": len(body),
            "declared": paths,
            "declared_count": len(paths),
        }

    probes.append(await _capture(coordinator, "22b_module_list", modules))

    # --- 22c. Every bundle, and what each contains ----------------------
    async def bundles() -> dict[str, Any]:
        # Query strings are cache-busters; the path is what answers.
        wanted: list[str] = [
            str(name).split("?")[0] for name in found.get("index_scripts", [])
        ]
        entry = found.get("entry") or ""
        if entry:
            wanted.append(entry if entry.endswith(".js") else f"{entry}.js")
        base = (entry.rsplit("/", 1)[0] + "/") if "/" in entry else ""
        for path in (found.get("modules") or {}).values():
            candidate = path if path.endswith(".js") else f"{path}.js"
            wanted.append(
                candidate if candidate.startswith(("/", "js/")) else base + candidate
            )
        wanted += list(JS_BUNDLES)

        seen: dict[str, Any] = {}
        for path in list(dict.fromkeys(wanted))[:_MAX_BUNDLES]:
            status, _headers, body = await _fetch_text(api, path)
            if status != 200:
                seen[path] = {"status": status}
                continue
            body = body[:_MAX_BUNDLE_BYTES]
            hits = {m: body.count(m) for m in _MARKERS if m in body}
            seen[path] = {"status": 200, "bytes": len(body), "markers": hits}
            for marker in ("goform_set_cmd_process", "rd0", "ACCESSIBLE_ID_SUPPORT"):
                if marker in body and marker not in found["captures"]:
                    found["captures"][marker] = _captures(body, marker)
            found.setdefault("which_cgi_values", [])
            found["which_cgi_values"] = sorted(
                set(found["which_cgi_values"]) | _which_cgi_values(body)
            )
            for command in (
                "DELETE_SMS",
                "ALL_DELETE_SMS",
                "DATA_LIMIT_SETTING",
                "NIGHT_MODE_INFO_SETTINGS",
            ):
                fields = _fields_for(body, command)
                if fields and command not in found["commands"]:
                    found["commands"][command] = fields
        found["bundles"] = seen
        return {
            "read": len([v for v in seen.values() if v.get("status") == 200]),
            "missing": [k for k, v in seen.items() if v.get("status") != 200],
            "bundles": seen,
        }

    probes.append(await _capture(coordinator, "22c_bundles", bundles))

    # --- 22d. The code that builds a write, verbatim --------------------
    async def write_path_source() -> dict[str, Any]:
        return {
            "captures": found["captures"],
            "note": (
                "the router's own script, as served to any browser; bounded "
                f"to {_CAPTURE_WINDOW} characters either side of each "
                "occurrence"
            ),
        }

    # Through `_capture` like every other rung, so one record shape holds for
    # the whole run and a reader can compare any two of them.
    probes.append(
        await _capture(coordinator, "22d_write_path_source", write_path_source)
    )

    # --- 22e. What the router's client sends, against what we send ------
    ours = {
        "DATA_LIMIT_SETTING": sorted(api.DATA_VOLUME_FIELDS),
        "NIGHT_MODE_INFO_SETTINGS": sorted((*_NIGHT_MODE_FIELDS, _TOGGLES[1][3])),
        "DELETE_SMS": ["msg_id"],
        "ALL_DELETE_SMS": [],
    }
    differences = {
        command: {
            "router_sends": found["commands"].get(command, []),
            "we_send": ours.get(command, []),
            "only_the_router": sorted(
                set(found["commands"].get(command, [])) - set(ours.get(command, []))
            ),
            "only_us": sorted(
                set(ours.get(command, [])) - set(found["commands"].get(command, []))
            ),
        }
        for command in ours
    }
    report["command_field_differences"] = differences

    async def field_differences() -> dict[str, Any]:
        return differences

    probes.append(
        await _capture(coordinator, "22e_field_differences", field_differences)
    )
    return found


async def _web_ui_write_rungs(
    coordinator: ZTERouterDataUpdateCoordinator,
    report: dict[str, Any],
    probes: list[dict[str, Any]],
    web: dict[str, Any],
) -> None:
    """Writes shaped the way the router's own client shapes them.

    Everything above sends a form assembled from constants in this module.
    These send what was read from the device's own script, and one that sends
    no token at all — which is what that script does when the firmware's
    `ACCESSIBLE_ID_SUPPORT` flag is unset.

    Where the extraction found nothing, the rung is skipped with that reason
    rather than falling back to the constants and reporting a result that
    looks like a test of the router.
    """
    api = coordinator.api
    commands = web.get("commands") or {}

    # --- 23a. The data-limit form, with the fields its own code assembles
    fields = commands.get("DATA_LIMIT_SETTING") or []
    if not fields:
        probes.append(
            {
                "probe": "23a_data_limit_router_form",
                "outcome": "skipped",
                "reason": "the router's script did not yield a field list",
            }
        )
    else:
        current = dict(coordinator.data or {})
        toggle = _TOGGLES[0]
        payload = {
            name: str(current.get(name, ""))
            for name in fields
            if current.get(name) not in ("", None)
        }
        # A field the poll does not carry is read directly rather than dropped.
        # Dropping it sends our form under the router's name: the first run of
        # this rung reported six fields where the router's code assembles
        # seven, and the missing one is the whole reason the rung exists.
        absent = [name for name in fields if name not in payload]
        if absent:
            with contextlib.suppress(Exception):
                answer = await api.get_params(absent)
                payload.update(
                    {
                        name: str(value)
                        for name, value in (answer or {}).items()
                        if name in absent and value not in ("", None)
                    }
                )
        still_absent = sorted(name for name in fields if name not in payload)

        async def router_form() -> dict[str, Any]:
            return await _attempt(
                coordinator,
                transport=_ADOPTED,
                command="DATA_LIMIT_SETTING",
                fields=payload,
                toggle=toggle,
                verify=True,
            )

        record = await _capture(coordinator, "23a_data_limit_router_form", router_form)
        record["wrote"] = _wrote(record)
        record["verified"] = _verified(record)
        record["fields_from"] = "the router's own script"
        record["fields_the_device_would_not_answer"] = still_absent
        probes.append(record)
        await asyncio.sleep(ATTEMPT_DELAY)

    # --- 23b. The same write carrying no token at all -------------------
    async def no_token() -> dict[str, Any]:
        return await _attempt(
            coordinator,
            transport={**_ADOPTED, "no_token": True},
            command=_TOGGLES[0][1],
            toggle=_TOGGLES[0],
            verify=True,
        )

    record = await _capture(coordinator, "23b_write_without_a_token", no_token)
    record["wrote"] = _wrote(record)
    record["verified"] = _verified(record)
    probes.append(record)
    await asyncio.sleep(ATTEMPT_DELAY)

    # --- 23c. A delete shaped exactly as the browser sends it ------------
    # The router's script builds `msg_id` as `ids.join(";") + ";"` and always
    # carries `notCallback`. This project has sent each of those separately and
    # never both, which is not the same request.
    remaining: list[str] = []
    with contextlib.suppress(Exception):
        remaining = await _surviving_ids(coordinator)
    if not remaining:
        probes.append(
            {
                "probe": "23c_delete_browser_form",
                "outcome": "skipped",
                "reason": "no message left to target",
            }
        )
    else:
        target = remaining[0]

        async def browser_form() -> Any:
            return await _delete_raw(
                coordinator,
                target,
                not_callback=True,
                trailing_semicolon=True,
            )

        record = await _capture(
            coordinator,
            "23c_delete_browser_form",
            browser_form,
            sent=_redacted_body(f"{target};", not_callback=True),
        )
        record["id_targeted"] = target
        with contextlib.suppress(Exception):
            record["ids_after"] = await _surviving_ids(coordinator)
        probes.append(record)
        await asyncio.sleep(ATTEMPT_DELAY)

    # --- 23d. Delete-all with the parameter its own code carries --------
    # The router's script sends `which_cgi: e.location`, and what `e.location`
    # holds is not in the payload builder. A first version assumed the storage
    # constant this integration uses elsewhere, sent it, drew a refusal on a
    # device where delete-all works, and recorded that as a finding. It was a
    # guess reported as a measurement.
    #
    # Every value the script assigns to `which_cgi` is now taken from the
    # source, and each is tried. Where none was found, the rung says so.
    values = web.get("which_cgi_values") or []
    if not values:
        probes.append(
            {
                "probe": "23d_all_delete_which_cgi",
                "outcome": "skipped",
                "reason": (
                    "the router's script did not yield a value for which_cgi, "
                    "and sending a guess would report our assumption as its "
                    "behaviour"
                ),
            }
        )
        return

    for value in values[:3]:

        async def all_delete(v: str = value) -> dict[str, Any]:
            return await _attempt(
                coordinator,
                transport={**_ADOPTED, "not_callback": True},
                command="ALL_DELETE_SMS",
                fields={"which_cgi": v},
            )

        record = await _capture(
            coordinator, f"23d_all_delete_which_cgi_{value}", all_delete
        )
        record["wrote"] = _wrote(record)
        record["which_cgi_from"] = "the router's own script"
        with contextlib.suppress(Exception):
            record["ids_after"] = await _surviving_ids(coordinator)
        probes.append(record)
        await asyncio.sleep(ATTEMPT_DELAY)


async def _session_proof_rung(
    coordinator: ZTERouterDataUpdateCoordinator,
    probes: list[dict[str, Any]],
) -> None:
    """Does a successful read prove a session on this device at all?

    The assumption that it does is why three downloads read as "reads work,
    writes do not". If this firmware serves the same keys with no session, that
    sentence means nothing and the session was never established.

    The session is discarded rather than logged out — the reporter's router
    does not acknowledge a logout — and the same keys are read again. Anything
    still populated is served without a session.
    """
    api = coordinator.api
    held: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        held = await api._batch_get(list(_CORE_PARAMS))  # noqa: SLF001

    cookies = dict(api.cookies)
    active = api.session_active

    async def sessionless() -> dict[str, Any]:
        api.cookies = {}
        api.session_active = False
        try:
            answer = await api._request(  # noqa: SLF001 - deliberately unauthenticated
                "GET",
                "goform/goform_get_cmd_process?isTest=false&multi_data=1&cmd="
                + ",".join(_CORE_PARAMS[:40]),
                authenticated=False,
            )
        finally:
            api.cookies = cookies
            api.session_active = active
        answered = {
            key
            for key, value in (answer or {}).items()
            if isinstance(value, str) and value
        }
        with_session = {
            key
            for key, value in held.items()
            if isinstance(value, str) and value and key in (answer or {})
        }
        return {
            "populated_with_a_session": len(with_session),
            "populated_without_one": len(answered),
            "served_without_a_session": sorted(answered)[:25],
        }

    probes.append(
        await _capture(coordinator, "20f_reads_without_a_session", sessionless)
    )


async def _confirmed_variant_rungs(
    coordinator: ZTERouterDataUpdateCoordinator,
    probes: list[dict[str, Any]],
    working: str | None,
    working_token: Any,
) -> None:
    """Deletes through whichever token variant wrote the harmless form.

    Reached only when a token was screened and then confirmed three times out
    of three. Three separate messages rather than one, so a single success
    cannot be mistaken for a working delete, and a batch, because that is the
    form the Delete All button sends.
    """
    api = coordinator.api
    # --- 16 onward. The confirmed variant, against real messages --------
    if working is None:
        probes.append(
            {
                "probe": "16_confirmed_variant_deletes",
                "outcome": "skipped",
                "reason": (
                    "no candidate formula wrote the harmless form reliably, so "
                    "deleting would prove nothing and would spend a message"
                ),
            }
        )
    else:
        remaining = []
        with contextlib.suppress(Exception):
            remaining = await _surviving_ids(coordinator)
        edges: list[tuple[str, int, dict[str, Any]]] = [
            ("16_confirmed_single", 1, {}),
            ("17_confirmed_single_again", 1, {}),
            ("18_confirmed_single_third", 1, {}),
            ("19_confirmed_batch", 2, {}),
        ]
        used = 0
        for name, needs, kwargs in edges:
            targets = remaining[used : used + needs]
            if len(targets) < needs:
                probes.append(
                    {
                        "probe": name,
                        "outcome": "skipped",
                        "reason": f"needs {needs} message(s), not enough left",
                    }
                )
                continue
            used += needs
            msg_id = ";".join(targets)

            async def delete_one(i: str = msg_id, k: dict[str, Any] = kwargs) -> Any:
                # Derived again, not replayed: a token is single-use, and the
                # one that proved the rule has already been spent.
                fresh = await _token_inputs(api)
                token = working_token(fresh)
                return await _delete_raw(coordinator, i, token=token, **k)

            record = await _capture(
                coordinator, name, delete_one, sent=_redacted_body(msg_id)
            )
            record["id_targeted"] = msg_id
            record["variant"] = working
            with contextlib.suppress(Exception):
                record["ids_after"] = await _surviving_ids(coordinator)
            probes.append(record)
            await asyncio.sleep(ATTEMPT_DELAY)
