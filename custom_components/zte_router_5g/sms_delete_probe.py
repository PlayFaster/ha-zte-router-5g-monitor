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

if TYPE_CHECKING:
    from .coordinator import ZTERouterDataUpdateCoordinator

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
PROBE_TIMEOUT = 480

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
SCREEN_DELAY = 0.4

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
    async with api.session.post(
        f"{api.referer}goform/goform_set_cmd_process",
        data=payload,
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
        "field": variant["field"],
        "value_kind": _value_kind(variant),
        "ld_upper": bool(variant.get("ld_upper")),
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
_OPERANDS: tuple[tuple[str, Any], ...] = (
    ("wa", lambda wa, cr: wa),
    ("cr", lambda wa, cr: cr),
    ("wacr", lambda wa, cr: wa + cr),
    ("crwa", lambda wa, cr: cr + wa),
    ("wanots_cr", lambda wa, cr: _TIMESTAMP.sub("", wa) + cr),
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
) -> Any:
    """One derivation, as a function of the three values it is built from."""

    def build(wa: str, cr: str, rd: str) -> str:
        first = operand(wa, cr)
        prepared = rd_form(rd, digest)
        if rounds == 1:
            return str(outer_case(digest(first + prepared)))
        inner = inner_case(digest(first))
        return str(outer_case(digest(inner + prepared)))

    return build


def _token_space(wa: str, cr: str, rd: str) -> list[tuple[str, Any]]:
    """Every distinct derivation these rules can produce, as rules.

    **Rules, not tokens.** An `AD` is single-use on this hardware: measured on
    the reference MC7010 on 2026-09-09, the first write carrying a given token
    succeeds and every later write carrying the same one is refused, at any
    delay, while `RD` itself is unchanged. Re-reading the token inputs re-arms
    it. A pass that computed the space once and fired it would therefore spend
    its only valid attempt on whichever rule happened to come first — which is
    what an earlier version of this function did, and it reported thirty
    refusals on a device where the shipped derivation works.

    **Deduplicated against the device's own strings, not a stand-in.** Two
    rules that differ in the abstract can produce the same digest here — an
    uppercasing digest makes an `.upper()` variant a duplicate of its base, and
    an absent `cr_version` makes `wa + cr` a duplicate of `wa`. v3's
    distinctness test used a stand-in firmware string and reported twelve
    candidates where the router received nine. The values passed here decide
    which rules are worth separating; the rules themselves are what run.

    Returns `(name, rule)` pairs in a stable order, first occurrence kept.
    """
    seen: dict[str, tuple[str, Any]] = {}
    for op_name, operand in _OPERANDS:
        if not operand(wa, cr):
            continue
        for digest_name, digest in (("sha", _sha), ("md5", _md5)):
            for rd_name, rd_form in _RD_FORMS:
                for inner_name, inner_case in _CASES:
                    for outer_name, outer_case in _CASES:
                        for rounds, suffix in (
                            (2, f"{inner_name}{outer_name}"),
                            # The outer case still varies a single-round
                            # token, so it belongs in the name: without it
                            # four distinct rules shared one label and the
                            # report counted names where it meant tokens.
                            (1, f"1round{outer_name}"),
                        ):
                            rule = _rule(
                                operand, digest, rd_form, inner_case, outer_case, rounds
                            )
                            name = f"{op_name}_{digest_name}_{suffix}_rd{rd_name}"
                            seen.setdefault(rule(wa, cr, rd), (name, rule))
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
    version = await api.get_version(timeout_sec=timeout_sec) or ""
    rd = await api.get_rd(timeout_sec=timeout_sec) or ""
    cr = ""
    try:
        answer = await api.get_params(["cr_version"], timeout_sec=timeout_sec)
        cr = str((answer or {}).get("cr_version") or "")
    except Exception as err:  # noqa: BLE001 - an unanswered read is a finding
        cr = ""
        _CR_NOTE["error"] = f"{type(err).__name__}: {err!s:.120}"
    return {"wa_inner_version": version, "cr_version": cr, "rd": rd}


# Filled by `_token_inputs` when the `cr_version` read raises, and reported on
# the rung that records what the candidates were built from. `cr_version` is
# known to answer this device through the discovery pass; whether it answers a
# plain read has not been established, and a candidate skipped for a reason
# nobody recorded is a candidate that gets tried again next time.
_CR_NOTE: dict[str, str] = {}


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
    value = result.get("result")
    return value is not None and str(value).lower() in ("success", "0", "ok")


async def _data_volume_write(
    coordinator: ZTERouterDataUpdateCoordinator, token: str | None
) -> dict[str, Any]:
    """Write the data-volume form back at exactly the values it already holds.

    The workhorse of this run: it changes nothing, so it can be repeated, and
    it is not an SMS command — so a failure here says the fault is every write
    on the device rather than anything about messages.

    The values are read immediately before each write and never remembered.
    The reporter's limit has already changed once between downloads, and
    writing back a stale value would alter a setting he relies on.
    """
    api = coordinator.api
    current = dict(coordinator.data or {})
    fields: dict[str, str] = {}
    for field, aliases in api.DATA_VOLUME_FIELDS.items():
        value = next(
            (current[key] for key in aliases if current.get(key) not in ("", None)),
            None,
        )
        if value is None:
            raise ZTEConnectionError(f"the poll did not supply {field}")
        fields[field] = str(value)

    ad = token if token is not None else await api.get_ad()
    body = "&".join(f"{key}={value}" for key, value in fields.items())
    result = await api._request(  # noqa: SLF001 - a deliberate variant, not the API's own form
        "POST",
        "goform/goform_set_cmd_process",
        data=f"isTest=false&goformId=DATA_LIMIT_SETTING&{body}&AD={ad}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return cast("dict[str, Any]", result)


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
) -> dict[str, Any]:
    """Send one `DELETE_SMS` in a named variant, bypassing the normal path.

    The integration's own `delete_sms` sends exactly one form. The point here
    is to vary the form, so this builds the body directly rather than calling
    it. `token=None` means a correct one, derived now.
    """
    api = coordinator.api
    ad = token if token is not None else await api.get_ad()
    body = _delete_body(msg_id, ad, mem_store=mem_store, not_callback=not_callback)
    result = await api._request(  # noqa: SLF001 - a deliberate variant, not the API's own form
        "POST",
        "goform/goform_set_cmd_process",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return cast("dict[str, Any]", result)


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


async def run_probe(coordinator: ZTERouterDataUpdateCoordinator) -> dict[str, Any]:
    """Run every probe, record everything, and stop for nothing.

    Held under the coordinator's update lock so a routine poll cannot log in,
    re-list or otherwise interleave with a sequence whose whole value is that
    each step is attributable.
    """
    api = coordinator.api
    report: dict[str, Any] = {
        "started": datetime.now(UTC).isoformat(),
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
    # Cleared per run. It is module state so that `_token_inputs` can report a
    # failure the caller never sees, and a note left from an earlier run would
    # be attributed to this one.
    _CR_NOTE.clear()

    try:
        async with asyncio.timeout(PROBE_TIMEOUT):
            await _run_rungs(coordinator, report, probes)
    except TimeoutError:
        # Everything collected so far is kept. A run that has to be waited out
        # is one the user restarts, and a restart used to lose the report.
        report["timed_out"] = PROBE_TIMEOUT
    except Exception as err:  # noqa: BLE001 - a lost report is the worse outcome
        report["aborted"] = {
            "error_type": type(err).__name__,
            "error": str(err)[:300],
        }
    report["finished"] = datetime.now(UTC).isoformat()
    coordinator.persist_delete_probe()
    return report


async def _run_rungs(
    coordinator: ZTERouterDataUpdateCoordinator,
    report: dict[str, Any],
    probes: list[dict[str, Any]],
) -> None:
    """Every rung, in order, under the coordinator's update lock."""
    api = coordinator.api
    async with coordinator._async_update_lock:  # noqa: SLF001 - the lock is the point
        # --- 0. Can any login produce a session that writes? ----------------
        # First, because everything below assumes one. Read the docstring on
        # `_login_stage` for why this is budgeted rather than exhaustive.
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

        # --- 3-6. The write path, with nothing at risk ----------------------
        # A delete naming an id the router does not hold. If this is refused,
        # the fault is not about his messages at all.
        variants: list[tuple[str, dict[str, Any]]] = [
            ("3_absent_id", {}),
            ("4_absent_id_bad_token", {"token": BAD_TOKEN}),
            ("5_absent_id_not_callback", {"not_callback": True}),
            ("6a_absent_id_store_device", {"mem_store": SMS_STORE_DEVICE}),
            ("6b_absent_id_store_all", {"mem_store": SMS_STORE_ALL}),
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

        working, working_token = await _candidate_rungs(coordinator, report, probes)

        # --- 20. The same write, sent differently, and two questions the
        # rungs above cannot answer. None of this touches a message.
        await _transport_rungs(coordinator, report, probes)
        await _session_proof_rung(coordinator, probes)

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
        if isinstance(outcome, dict) and outcome.get("spent_an_attempt"):
            spent += 1
        probes.append(record)
        await asyncio.sleep(LOGIN_DELAY)

        established = isinstance(outcome, dict) and bool(outcome.get("cookie_names"))
        if not established:
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
            winner = name
        await asyncio.sleep(ATTEMPT_DELAY)

    report["login_variant_that_wrote"] = winner
    # Whatever happened, the run continues from a session this integration
    # would normally hold, so the rungs below measure the shipped path.
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
    wa = str(values.get("wa_inner_version") or "")
    cr = str(values.get("cr_version") or "")
    rd = str(values.get("rd") or "")
    # Lengths and presence only. The version strings identify a firmware and
    # `RD` is a session value; neither is published.
    inputs["result"] = {
        "wa_inner_version_length": len(wa),
        "cr_version_length": len(cr),
        "rd_length": len(rd),
        "cr_version_answered": bool(cr),
    }
    if _CR_NOTE:
        inputs["result"]["cr_version_note"] = _CR_NOTE.get("error")

    space = _token_space(wa, cr, rd) if wa and rd else []
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
    async def one(rule: Any) -> dict[str, Any]:
        # Read fresh, every time. The token is single-use and a read re-arms
        # it; reusing one guarantees a refusal that says nothing about the rule.
        fresh = await _token_inputs(api)
        token = rule(fresh["wa_inner_version"], fresh["cr_version"], fresh["rd"])
        return await _data_volume_write(coordinator, token)

    survivors: dict[str, Any] = {}
    for name, rule in space:
        record = await _capture(coordinator, f"7b_{name}", lambda r=rule: one(r))
        wrote = _wrote(record)
        report["candidates"][name] = "screened: wrote" if wrote else "screened: refused"
        if wrote:
            survivors[name] = rule
            probes.append(record)
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
            record = await _capture(
                coordinator, f"7h_{name}_{attempt}", lambda r=rule: one(r)
            )
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


async def _transport_rungs(
    coordinator: ZTERouterDataUpdateCoordinator,
    report: dict[str, Any],
    probes: list[dict[str, Any]],
) -> None:
    """The same write, sent differently. Nothing here concerns the token.

    Every one of these is something another implementation does and this one
    does not, or the reverse. None is attested as necessary — the projects that
    do them are not themselves attested as writing on an MC888 — so they are
    tried rather than adopted.

    All are variations on the data-volume form, so none spends a message and
    none changes a setting.
    """
    api = coordinator.api

    async def send(**kwargs: Any) -> dict[str, Any]:
        current = dict(coordinator.data or {})
        fields: dict[str, str] = {}
        for field, aliases in api.DATA_VOLUME_FIELDS.items():
            value = next(
                (current[key] for key in aliases if current.get(key) not in ("", None)),
                None,
            )
            if value is None:
                raise ZTEConnectionError(f"the poll did not supply {field}")
            fields[field] = str(value)
        ad = await api.get_ad()
        body = "&".join(f"{key}={value}" for key, value in fields.items())
        payload = f"isTest=false&goformId=DATA_LIMIT_SETTING&{body}&AD={ad}"
        return cast(
            "dict[str, Any]",
            await api._request(  # noqa: SLF001 - a deliberate variant
                kwargs.pop("method", "POST"),
                "goform/goform_set_cmd_process",
                data=None if kwargs.pop("as_query", False) else payload,
                params=None,
                **kwargs,
            ),
        )

    variants: list[tuple[str, dict[str, Any]]] = [
        # The site root rather than `index.html`, which is what both reference
        # implementations send.
        (
            "20a_referer_root",
            {
                "headers": {
                    "Referer": api.referer,
                    "Content-Type": "application/x-www-form-urlencoded",
                }
            },
        ),
        # The headers a browser sends, which `nicjac` reproduces in full.
        (
            "20b_browser_headers",
            {
                "headers": {
                    "Referer": api.referer,
                    "Origin": api.referer.rstrip("/"),
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": (
                        "application/x-www-form-urlencoded; charset=UTF-8"
                    ),
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                }
            },
        ),
        # No content type at all, which is what `Kajkac` sends.
        ("20c_no_content_type", {"headers": {"Referer": api.referer}}),
    ]
    for name, kwargs in variants:
        record = await _capture(coordinator, name, lambda k=kwargs: send(**k))
        record["wrote"] = _wrote(record)
        probes.append(record)
        await asyncio.sleep(ATTEMPT_DELAY)

    # A write issued immediately after a fresh login, with nothing between the
    # two. `Kajkac` issue #4 reports a user fixing a dead control this way.
    async def after_fresh_login() -> dict[str, Any]:
        await api.login()
        return await _data_volume_write(coordinator, None)

    record = await _capture(
        coordinator, "20d_write_after_fresh_login", after_fresh_login
    )
    record["wrote"] = _wrote(record)
    probes.append(record)

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
                token = working_token(
                    fresh["wa_inner_version"], fresh["cr_version"], fresh["rd"]
                )
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
