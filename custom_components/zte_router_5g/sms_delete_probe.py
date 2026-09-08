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
PROBE_TIMEOUT = 240

# How many times each token variant is tried against the harmless write. One
# success is not a working method and one failure is not a broken one; the
# question is whether a variant works *every* time.
WRITE_ATTEMPTS = 3

# Between attempts, so a variant is not measuring the router's recovery from
# the attempt before it.
ATTEMPT_DELAY = 1.0

# The keys the shipped session check now reads, imported rather than repeated
# so this rung reports on what the integration actually does. The download is
# read against a device whose behavior is being characterized; a probe testing
# its own private copy of the list would answer a question nobody asked.
LIVENESS_KEYS = _SESSION_CHECK_KEYS

# The timestamp a ZTE firmware string carries, e.g.
# `BD_ABPLMC888PROMODV1.0.0B01 [Oct 16 2025 21:15:14]`. One candidate strips it
# on the theory that the router's own JavaScript hashes the bare version.
_TIMESTAMP = re.compile(r"\s*\[[^\]]*\]\s*$")


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


# Every way of deriving the `AD` token that is worth trying on this device.
#
# The integration builds `H(H(wa_inner_version) + RD)`, SHA-256 upper case on
# an MC888 or MC889 and MD5 lower case otherwise. The reference implementation
# most widely cited for these routers builds `H(H(wa_inner_version +
# cr_version) + RD)` in natural case. Two differences, either or both of which
# could be why every write on the reporter's device is answered
# `{"result": "failure"}` — the same answer it gives to a deliberately
# malformed token.
#
# **The digest is the device's own, not a constant here.** `_ad_hash_func`
# chooses it per firmware, and a run of v3 against the reference MC7010 built
# every token with SHA-256 against a router that uses MD5: all three candidates
# that ran failed for one reason unrelated to their structure, and the control
# failed alongside them while the integration's own write in the same run
# succeeded. Each builder therefore takes the digest as its first argument.
#
# Each entry is a name, whether it needs `cr_version`, whether it wants the
# *other* digest rather than this device's, and the builder. A builder of
# `None` marks the control.
_CANDIDATES: tuple[tuple[str, bool, bool, Any], ...] = (
    ("a_control_current", False, False, None),
    ("b_wa_cr_lower", True, False, lambda h, wa, cr, rd: h(h(wa + cr) + rd)),
    ("c_wa_cr_upper", True, False, lambda h, wa, cr, rd: h(h(wa + cr) + rd).upper()),
    ("d_wa_lower", False, False, lambda h, wa, cr, rd: h(h(wa) + rd)),
    ("e_cr_lower", True, False, lambda h, wa, cr, rd: h(h(cr) + rd)),
    ("f_cr_upper", True, False, lambda h, wa, cr, rd: h(h(cr) + rd).upper()),
    (
        "g_wa_no_timestamp_cr_lower",
        True,
        False,
        lambda h, wa, cr, rd: h(h(_TIMESTAMP.sub("", wa) + cr) + rd),
    ),
    ("h_cr_wa_lower", True, False, lambda h, wa, cr, rd: h(h(cr + wa) + rd)),
    ("i_wa_hashed_rd_lower", False, False, lambda h, wa, cr, rd: h(h(wa) + h(rd))),
    ("j_single_round_lower", True, False, lambda h, wa, cr, rd: h(wa + cr + rd)),
    (
        "k_wa_cr_hashed_rd_lower",
        True,
        False,
        lambda h, wa, cr, rd: h(h(wa + cr) + h(rd)),
    ),
    (
        "l_other_digest_wa_cr_lower",
        True,
        True,
        lambda h, wa, cr, rd: h(h(wa + cr) + rd),
    ),
)


def _digests(api: Any, version: str) -> tuple[Any, Any]:
    """This device's digest, and the other one.

    `_ad_hash_func` reads the firmware string and returns MD5 or SHA-256. It is
    asked rather than reproduced, so a candidate cannot silently disagree with
    what the integration itself would send. The other digest is offered as one
    deliberate variant, because "the firmware uses the other hash" is a
    hypothesis worth one candidate and not worth twelve.
    """
    native = api._ad_hash_func(version)  # noqa: SLF001 - the device's own choice
    other = _md5 if len(str(native("probe"))) > 32 else _sha
    return native, other


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


async def _candidate_token(api: Any, builder: Any, alternate: bool) -> Any:
    """Build one candidate's token from values read moments ago.

    `RD` may be a nonce, so the values are read per attempt rather than once.
    A `None` builder is the control, which asks the integration for the token
    the ordinary way — reproducing that formula here is what made the control
    of v3 disagree with the code it was supposed to be controlling.
    """
    if builder is None:
        return await api.get_ad()
    fresh = await _token_inputs(api)
    native, other = _digests(api, fresh["wa_inner_version"])
    digest = other if alternate else native
    return builder(digest, fresh["wa_inner_version"], fresh["cr_version"], fresh["rd"])


async def _candidate_rungs(
    coordinator: ZTERouterDataUpdateCoordinator,
    report: dict[str, Any],
    probes: list[dict[str, Any]],
) -> tuple[str | None, Any]:
    """Every way of deriving an `AD` token, against a write that destroys nothing.

    The data-volume form written back at exactly the values it already holds is
    not an SMS command, so a refusal here says no write works on this device
    rather than anything about messages. It changes nothing, so it can be
    repeated, and repetition is the point: one success is not a working formula
    and one failure is not a broken one.

    **Every candidate runs, whatever the earlier ones did.** Stopping at the
    first success would establish that one formula works and leave the other
    eleven unknown, which is another round trip with the reporter for a fact
    this run could have recorded.

    Returns the accepted candidate and its builder, or `(None, None)`.
    """
    api = coordinator.api
    inputs = await _capture(coordinator, "7a_token_inputs", lambda: _token_inputs(api))
    raw = inputs.get("result")
    values: dict[str, Any] = raw if isinstance(raw, dict) else {}
    # Lengths and presence only. The version strings identify a firmware and
    # `RD` is a session value; neither is published.
    inputs["result"] = {
        "wa_inner_version_length": len(values.get("wa_inner_version", "")),
        "cr_version_length": len(values.get("cr_version", "")),
        "rd_length": len(values.get("rd", "")),
        "cr_version_answered": bool(values.get("cr_version")),
    }
    if _CR_NOTE:
        inputs["result"]["cr_version_note"] = _CR_NOTE.get("error")
    probes.append(inputs)

    have_cr = bool(values.get("cr_version"))
    accepted: str | None = None
    accepted_choice: tuple[Any, bool] | None = None
    passed: list[str] = []
    report["candidates"] = {}

    for name, needs_cr, alternate, builder in _CANDIDATES:
        if needs_cr and not have_cr:
            # Named, not silently dropped. A candidate that was never tried
            # and a candidate that failed are different findings.
            probes.append(
                {
                    "probe": f"7b_{name}",
                    "outcome": "skipped",
                    "reason": ("needs cr_version, which this device did not answer"),
                }
            )
            report["candidates"][name] = "skipped: no cr_version"
            continue

        outcomes: list[bool] = []
        for attempt in range(1, WRITE_ATTEMPTS + 1):

            async def one(b: Any = builder, alt: bool = alternate) -> dict[str, Any]:
                token = await _candidate_token(api, b, alt)
                return await _data_volume_write(coordinator, token)

            record = await _capture(coordinator, f"7b_{name}_{attempt}", one)
            record["wrote"] = _wrote(record)
            outcomes.append(record["wrote"])
            probes.append(record)
            await asyncio.sleep(ATTEMPT_DELAY)

        succeeded = sum(outcomes)
        report["candidates"][name] = f"{succeeded}/{WRITE_ATTEMPTS}"
        if succeeded == WRITE_ATTEMPTS:
            passed.append(name)
            if accepted is None:
                accepted, accepted_choice = name, (builder, alternate)

    # Every formula that passed, not only the one used. A device accepting
    # several says something different about its firmware than one accepting
    # exactly one, and that is a fact about the device worth carrying.
    report["candidates_passed"] = passed
    report["working_variant"] = accepted

    if accepted is None or accepted_choice is None:
        return None, None

    # --- 7h. Confirm it before spending a message -----------------------
    # A formula that works three times and fails the next three is not a
    # formula. Confirming costs nothing here and a message later.
    confirmed: list[bool] = []
    for attempt in range(1, WRITE_ATTEMPTS + 1):

        async def again(choice: tuple[Any, bool] = accepted_choice) -> dict[str, Any]:
            token = await _candidate_token(api, *choice)
            return await _data_volume_write(coordinator, token)

        record = await _capture(coordinator, f"7h_confirm_{attempt}", again)
        record["wrote"] = _wrote(record)
        confirmed.append(record["wrote"])
        probes.append(record)
        await asyncio.sleep(ATTEMPT_DELAY)

    if not all(confirmed):
        accepted, accepted_choice = None, None
    report["working_variant_confirmed"] = accepted
    return accepted, accepted_choice


async def _confirmed_variant_rungs(
    coordinator: ZTERouterDataUpdateCoordinator,
    probes: list[dict[str, Any]],
    working: str | None,
    working_token: Any,
) -> None:
    """Deletes through whichever token variant wrote the harmless form.

    Reached only when one variant succeeded six times out of six. Three
    separate messages rather than one, so a single success cannot be mistaken
    for a working delete, and a batch, because that is the form the Delete All
    button sends.
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
                # Built from the accepted formula on values read moments ago,
                # the same way it was built for the write that accepted it.
                token = await _candidate_token(api, *working_token)
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
