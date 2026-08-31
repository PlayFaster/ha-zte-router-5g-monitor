"""Exercise the write path against a real router, and record what it answers.

Not part of CI, and not a unit test. This exists because the unit suite cannot
falsify a wrong belief about the device: a mock is written from the model, so a
test built on a wrong model passes while the code is broken. That is not
hypothetical — on 2026-07-30 a test asserting that a refused write could be
retried after re-login was green while the same code failed on hardware. The
first explanation offered for that failure was itself wrong, and this script
disproved it on its first run. Both the code and the tests now record what was
measured and stop short of claiming a mechanism.

So this script does three jobs:

  1. Round-trips every *safe* write end to end, including with the session
     deliberately taken away — the scenario a user hit by logging into the
     router's web page while Home Assistant was connected.
  2. Records the router's actual responses to `--capture`, so unit-test mocks
     can be built from observation instead of imagination.
  3. Under `--attended`, offers the writes that cannot be made quiet — real
     messages, deletions, the APN and bearer selects, and a reboot — one at a
     time, each behind its own confirmation, with the cost stated before the
     prompt. Nothing in this tier runs without a human answering `y`.

The reboot step ([G]) also **watches what the router answers on the way back**,
key by key against a settled baseline. That is not decoration. The fault found
on 2026-07-31 lived entirely inside *successful* responses: recovering, the
router served a payload with every authenticated key blanked, the integration
scored it a clean success, and every entity published `unknown` while the health
sensor stayed green. Waiting for the router to answer would have shown nothing
wrong. A `LOST` line in that step means the two-class session detection has been
defeated again — most likely by a firmware change to which keys need a session.

Usage, inside the devcontainer, **from anywhere** — paths are resolved from
`__file__`, not the working directory:

    /usr/local/bin/python scripts/hardware_check.py             # check + restore
    /usr/local/bin/python scripts/hardware_check.py --capture   # also record
    /usr/local/bin/python scripts/hardware_check.py --attended  # + prompted tier

Or run the **Hardware: Device Check** VS Code task, which does the same and tees
the output to `.reports/`.

**Use the container interpreter, not `uv run`.** This imports the integration,
which imports Home Assistant; only `/usr/local/bin/python` has those installed.
The project `.venv` that `uv` selects does not, and fails on `import aiohttp`.

Reads credentials from the configured Home Assistant entry — nothing is passed
on the command line. Every write is restored to its original value, including on
failure.

Nothing recorded by `--capture` may contain personal data. The capture holds key
*names* plus a few literal protocol responses; it must never hold identifiers,
addresses, cell IDs or message content. `_assert_capture_is_safe` enforces this
before anything is written.
"""

# The console report is this script's entire output — there is no logger to
# route it through, and a caller reading `.reports/hardware_check.txt` is the
# point.
# ruff: noqa: T201

# The session probes call `api._request(..., _retry=False)` directly, and must.
# `_request` transparently re-logs-in once on an expired session — which is the
# behavior these checks exist to observe, so every public method routes around
# what they are measuring. A public wrapper was considered and rejected: it adds
# shipped API surface for a script HACS never ships, and
# `test_every_public_method_is_covered_by_the_sweep` would then require it in
# `_CALLS`, where the sweep asserts a method "does the thing or raises" — the
# opposite of a probe built to watch one fail.
# ruff: noqa: SLF001

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import pathlib
import sys
import time
from datetime import UTC, datetime
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

try:
    import aiohttp

    from custom_components.zte_router_5g.api import (
        _CORE_PARAMS,
        _EXTENDED_PARAMS,
        _UNAUTHENTICATED_KEYS,
        ZTEAuthError,
        ZTERouterAPI,
    )
    from custom_components.zte_router_5g.const import APN_PROFILE_SLOTS
except ModuleNotFoundError as err:  # pragma: no cover - operator ergonomics
    raise SystemExit(
        f"cannot import {err.name!r}.\n\n"
        "This script imports the integration, which imports Home Assistant, so "
        "it needs the devcontainer's interpreter:\n\n"
        "    /usr/local/bin/python scripts/hardware_check.py\n\n"
        "`uv run` and the project .venv do not carry those dependencies."
    ) from err

CONFIG_ENTRIES = pathlib.Path("/config/.storage/core.config_entries")
FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures"
INVALID_STOK = "stok=0000000000000000000000000000000f"

# Writes this script is allowed to make. Each names the key its position is read
# back from — not always the entity key — and the two values to cycle through.
SAFE_WRITES: list[tuple[str, str, tuple[str, str]]] = [
    ("set_odu_led_switch", "ODU_led_switch", ("0", "1")),
]

PROBE_PATH = (
    "goform/goform_get_cmd_process?multi_data=1&isTest=false"
    "&sms_received_flag_flag=0&cmd=wan_connect_status"
)
RD_PATH = "goform/goform_get_cmd_process?isTest=false&cmd=RD"

# Seconds to let the radio re-register before reading a value back. Only the
# attended tier waits: nothing in the safe tier disturbs the connection.
RECONNECT_SETTLE = 12.0

# Gap between attempts while the router is away. The reconnect an attended
# write causes routinely outlasts a single request timeout.
RECONNECT_RETRY = 8.0

# NR5G keys the router populates only while registered on 5G. Absent on a 4G
# return, which is a network state rather than the blanked-payload fault the
# reboot check is looking for.
_NR5G_KEYS = frozenset(
    {
        "Z5g_SINR",
        "Z5g_rsrp",
        "Z5g_rsrq",
        "Z5g_rssi",
        "nr5g_action_band",
        "nr5g_action_channel",
        "nr5g_pci",
        "Z5g_CELL_ID",
        "Z5g_snr",
        "5g_rsrp",
        "5g_sinr",
        "nr5g_rsrp",
        "nr5g_sinr",
    }
)

# The router updates its SMS counters a moment after accepting a write.
SMS_SETTLE = 3.0

# A reboot on the reference MC7010 takes well under two minutes; the budget
# is generous because a slow return is not a failure, only a wait.
REBOOT_TIMEOUT = 240.0
REBOOT_POLL = 15.0

# Color is emitted unconditionally, the way `pytest --color=yes` is used by the
# sibling tasks: stdout here is a pipe into `tee`, so auto-detection would strip
# it exactly when it is wanted. The VS Code task sends the colored stream to the
# terminal and a `sed`-stripped copy to `.reports/`, so the log stays plain text.
# `NO_COLOR` (https://no-color.org) and `--no-color` both turn it off.
_COLOUR = os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    """Wrap text in an ANSI code, or return it unchanged when colour is off."""
    return f"\033[{code}m{text}\033[0m" if _COLOUR else text


def _green(text: str) -> str:
    """Return text in bold green."""
    return _c("1;32", text)


def _red(text: str) -> str:
    """Return text in bold red."""
    return _c("1;31", text)


def _yellow(text: str) -> str:
    """Return text in bold yellow."""
    return _c("1;33", text)


def _cyan(text: str) -> str:
    """Return text in bold cyan."""
    return _c("1;36", text)


def _dim(text: str) -> str:
    """Return text dimmed, for supporting detail."""
    return _c("2", text)


class Report:
    """Collects results so one failure does not hide the rest."""

    def __init__(self) -> None:
        """Start an empty report."""
        self.checks: list[tuple[bool, str, str]] = []
        self.captured: dict[str, Any] = {}

    def record(self, ok: bool, name: str, detail: str = "") -> None:
        """Print one result and remember it for the summary."""
        self.checks.append((ok, name, detail))
        badge = _green("\u2714  PASS") if ok else _red("\u2716  FAIL")
        suffix = _dim(f"  \u2014 {detail}") if detail else ""
        print(f"  {badge}  {name}{suffix}")

    @property
    def failed(self) -> int:
        """Return how many checks failed, for the exit code."""
        return sum(1 for ok, _, _ in self.checks if not ok)


def _credentials() -> dict[str, str]:
    """Read the router credentials from the configured Home Assistant entry."""
    with CONFIG_ENTRIES.open() as handle:
        data = json.load(handle)
    for entry in data["data"]["entries"]:
        if entry["domain"] == "zte_router_5g":
            return dict(entry["options"])
    raise SystemExit(f"no zte_router_5g entry in {CONFIG_ENTRIES}")


def _kill_session(api: ZTERouterAPI, session: aiohttp.ClientSession) -> None:
    """Reproduce what a web-GUI login does: take the session away.

    The router permits one session, so signing into its web page invalidates
    Home Assistant's. Replacing the stok is indistinguishable from that as far
    as every request is concerned.
    """
    api.stok = INVALID_STOK
    # The session stays *marked* active. A router-side eviction does not tell
    # the client anything, and clearing the flag here would have `_request`
    # log in again before the probe ever went out — the opposite of what
    # these checks watch for.
    api.session_active = True
    session.cookie_jar.clear(predicate=lambda cookie: cookie.key == "stok")


async def check_session_assumptions(
    api: ZTERouterAPI, session: aiohttp.ClientSession, report: Report
) -> None:
    """Assert the device beliefs the write path is built on.

    These are the load-bearing ones. Each is firmware-dependent, so a failure
    here is not necessarily a bug in the integration — it may mean the firmware
    changed and the design needs revisiting.
    """
    print(_cyan("\n[1] Session and token assumptions"))

    live = (await api._request("GET", RD_PATH, _retry=False))["RD"]
    again = (await api._request("GET", RD_PATH, _retry=False))["RD"]
    report.record(
        live == again,
        "RD is stable within a session",
        f"{live[:12]}…",
    )

    # Recorded, not scored. Whether RD survives a re-login has flip-flopped
    # across observations, and nothing in the integration now depends on the
    # answer — `_ensure_session` derives AD *after* the session is assured, so
    # the question does not arise. It is captured because a change here would
    # be the first sign that the token scheme had been reworked.
    await api.login()
    after_login = (await api._request("GET", RD_PATH, _retry=False))["RD"]
    report.captured["rd_survives_relogin"] = after_login == live
    print(
        f"  {_yellow('\u25cf  NOTE')}  RD "
        f"{'survives' if after_login == live else 'changes on'} re-login "
        + _dim("(observation only, nothing depends on it)")
    )

    _kill_session(api, session)
    try:
        await api._request("GET", PROBE_PATH, _retry=False)
    except ZTEAuthError:
        report.record(True, "a dead session is detectable on a read")
        report.captured["dead_session_read"] = {"wan_connect_status": ""}
    else:
        report.record(
            False,
            "a dead session is detectable on a read",
            "the all-values-empty rule did not fire — write recovery depends on it",
        )

    await api.login()

    # The session is one piece of state held in two fields, and a site that
    # moves one without the other is not visible from the outside: the client
    # believes it is signed in, sends no Cookie header, and the router answers
    # by echoing the authenticated keys back empty. Every entity then publishes
    # `unknown` while the health sensor stays green. The pair is asserted after
    # a kill and re-login because that is the sequence every recovery path in
    # `_request` ends with. See issue #56 Section 4.1.
    report.record(
        api.session_active and api.stok is not None,
        "the session flag and the session cookie agree after re-login",
        f"session_active={api.session_active}, stok={'set' if api.stok else 'none'}",
    )

    await _capture_cookieless_batch(api, session, report)

    # This device issues a stok. Recorded rather than scored, because a device
    # that does not is a supported configuration — an MC888 Pro on
    # `CR_ABPLMC888PROV1.0.1B04` binds the session to the client address and
    # sends no cookie at all (issue #56). Capturing it makes the reference
    # router the documented baseline for `_extract_stok`.
    report.captured["login_issues_stok_cookie"] = api.stok is not None


async def _probe_cookieless(
    api: ZTERouterAPI,
    session: aiohttp.ClientSession,
    report: Report,
    label: str,
    params: list[str],
) -> None:
    """Read one batch with no session cookie and compare against the constant."""
    cmd = ",".join(params)
    url = (
        f"{api.referer}goform/goform_get_cmd_process?multi_data=1&isTest=false"
        f"&sms_received_flag_flag=0&cmd={cmd}"
    )
    key = f"cookieless_batch_{label}"
    try:
        async with session.get(
            url,
            headers={"Referer": f"{api.referer}index.html"},
            timeout=aiohttp.ClientTimeout(total=15),
            ssl=False,
        ) as r:
            status = r.status
            body = await r.text()
    except (TimeoutError, aiohttp.ClientError) as err:
        report.captured[key] = {"error": f"{type(err).__name__}: {err}"}
        print(f"  {label}: {_yellow('request failed')} — {err}")
        return

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        preview = body.strip()[:100].replace("\n", " ")
        report.captured[key] = {
            "status": status,
            "json": False,
            "body_preview": preview,
        }
        print(f"  {label}: {_yellow('not JSON')} (status {status}) — {_dim(preview)}")
        return

    populated = sorted(k for k, v in payload.items() if v != "")
    absent = sorted(set(params) - set(payload))
    expected = sorted(_UNAUTHENTICATED_KEYS & set(params))
    matches = populated == expected

    report.captured[key] = {
        "status": status,
        "keys_returned": len(payload),
        "keys_absent": len(absent),
        "populated": populated,
        "expected_from_constant": expected,
        "matches_constant": matches,
    }

    verdict = _green("agrees") if matches else _yellow("DISAGREES")
    print(
        f"  {label}: {len(payload)}/{len(params)} keys returned, "
        f"{len(absent)} absent — {verdict}"
    )
    print(f"      populated: {populated or '(none)'}")
    print(f"      constant : {expected or '(none)'}")


async def _capture_cookieless_batch(
    api: ZTERouterAPI, session: aiohttp.ClientSession, report: Report
) -> None:
    """Record which keys answer a batch read carrying no session cookie.

    Settles a question the existing evidence does not. `_UNAUTHENTICATED_KEYS`
    was measured by replaying an **invalidated** stok; a proposal to measure
    that set per device would instead send **no cookie at all**. Those are
    different experiments, and nothing establishes that they agree — a router
    may answer an absent cookie with an HTML redirect, or omit keys rather
    than echoing them back blank.

    Both batches are probed. `_classify_session` runs on each, and a per-device
    measurement has to leave at least one authenticated key in each, so a
    result for the core batch says nothing about the extended one. The two
    `opms_` keys in the constant appear only in the extended batch.

    Recorded, not scored. A disagreement is evidence about that proposal, not
    a fault in the integration. It sits in the safe tier because it only reads.
    """
    print(_cyan("\n[1b] Cookieless batch reads (evidence for per-device measurement)"))
    await _probe_cookieless(api, session, report, "core", _CORE_PARAMS)
    await _probe_cookieless(api, session, report, "extended", _EXTENDED_PARAMS)


async def check_write_round_trip(
    api: ZTERouterAPI, report: Report, *, hostile: bool, session: aiohttp.ClientSession
) -> None:
    """Write, read back, restore — optionally with the session taken away first."""
    label = "with a DEAD session" if hostile else "with a live session"
    print(_cyan(f"\n[{3 if hostile else 2}] Safe writes {label}"))

    for setter_name, state_key, values in SAFE_WRITES:
        setter = getattr(api, setter_name)
        original = (await api.get_params([state_key]))[state_key]
        target = values[0] if original == values[1] else values[1]

        try:
            if hostile:
                _kill_session(api, session)
            started = time.monotonic()
            await setter(target)
            elapsed_ms = (time.monotonic() - started) * 1000
            observed = (await api.get_params([state_key]))[state_key]
            report.record(
                observed == target,
                f"{setter_name} {label}",
                f"{elapsed_ms:.0f} ms, router reports {observed!r}",
            )
        except Exception as err:  # noqa: BLE001 - reporting, not handling
            report.record(
                False, f"{setter_name} {label}", f"{type(err).__name__}: {err}"
            )
        finally:
            with contextlib.suppress(Exception):
                await api.login()
                if (await api.get_params([state_key]))[state_key] != original:
                    await setter(original)
                restored = (await api.get_params([state_key]))[state_key]
                report.record(
                    restored == original,
                    f"{setter_name} restored to {original!r}",
                )


async def check_data_volume_form(api: ZTERouterAPI, report: Report) -> None:
    """Round-trip the alert percentage, exercising the all-or-nothing form.

    `DATA_LIMIT_SETTING` replaces the *whole* six-field data-volume
    configuration and the router refuses a payload missing any field. The
    integration sent one field for its entire life, so the Data Limit Switch
    never worked in any release — and nobody noticed for weeks, because nobody
    used that entity.

    Only `data_volume_alert_percent` is moved, and it is put straight back. The
    cap and the limit switch are deliberately untouched: this must remain safe
    to strand, and a stranded alert percentage warns at a slightly wrong point
    whereas a stranded cap can stop the router passing traffic.
    """
    print(_cyan("\n[4] The data-volume form (alert percentage only)"))

    current = await api.get_params(list(api.DATA_VOLUME_FIELDS))
    original = current.get("data_volume_alert_percent")
    if original is None or not str(original).strip():
        report.record(
            False,
            "read the data-volume form",
            "no alert percentage reported — is Data Management enabled?",
        )
        return

    nudged = "81" if str(original).strip() != "81" else "80"
    # One retry, and the fact of it is reported. A well-formed form was seen
    # refused once (2026-07-30) immediately after the session-churn section
    # above, then accepted on the very next attempt with an identical payload.
    # Why is not established. Retrying silently would hide an intermittent
    # refusal, which is the class of fault this script exists to expose, so the
    # attempt count is always printed.
    attempts = 0
    last_error: str | None = None
    observed: Any = None
    for attempt in range(2):
        if attempt:
            await asyncio.sleep(1.0)
        attempts = attempt + 1
        try:
            await api.set_data_volume_settings(
                current, data_volume_alert_percent=nudged
            )
        except Exception as err:  # noqa: BLE001 - reporting, not handling
            last_error = str(err)
            continue
        observed = (await api.get_params(["data_volume_alert_percent"])).get(
            "data_volume_alert_percent"
        )
        last_error = None
        break

    if last_error is None:
        report.record(
            str(observed) == nudged,
            "six-field form accepted and applied",
            f"{original} -> {observed}"
            + ("" if attempts == 1 else f"  [needed {attempts} attempts]"),
        )
    else:
        report.record(
            False,
            "six-field form accepted and applied",
            f"refused {attempts}x: {last_error}",
        )

    # Restore unconditionally. The retry loop above handles its own exceptions,
    # so nothing escapes before this point — a `finally` here would imply a
    # `try` that no longer exists.
    with contextlib.suppress(Exception):
        latest = await api.get_params(list(api.DATA_VOLUME_FIELDS))
        if str(latest.get("data_volume_alert_percent")) != str(original):
            await api.set_data_volume_settings(
                latest, data_volume_alert_percent=str(original)
            )
        back = (await api.get_params(["data_volume_alert_percent"])).get(
            "data_volume_alert_percent"
        )
        report.record(
            str(back) == str(original),
            f"alert percentage restored to {original}",
        )


async def check_logout_ends_the_session(api: ZTERouterAPI, report: Report) -> None:
    """Confirm LOGOUT genuinely ends the session, then log back in.

    Worth its own check because the failure is invisible from the outside. The
    router permits one session, so an ignored LOGOUT leaves the user locked out
    of their own web UI with nothing logged anywhere. It also carries a
    non-obvious requirement — `goformId=LOGOUT` needs an `AD` token — which
    cannot be verified by loading the web UI, since logging in there terminates
    whatever session existed regardless.

    The only sound check is to replay the old token and confirm it is rejected.
    """
    print(_cyan("\n[5] Logout actually ends the session"))

    stale = api.stok
    try:
        await api.logout()
    except Exception as err:  # noqa: BLE001 - reporting, not handling
        report.record(False, "logout completed", f"{err}")
    else:
        # Restore the whole session pair, not the cookie alone: `logout()`
        # cleared both, and a replay with the flag down would log in again
        # instead of presenting the stale token this check exists to test.
        api.stok = stale
        api.session_active = True
        try:
            await api._request("GET", PROBE_PATH, _retry=False)
        except ZTEAuthError:
            report.record(True, "the old session token is rejected afterwards")
        else:
            report.record(
                False,
                "the old session token is rejected afterwards",
                "the session survived LOGOUT — the user's web UI stays locked",
            )
    finally:
        await api.login()


# ---------------------------------------------------------------------------
# Attended tier
# ---------------------------------------------------------------------------
# Everything here re-establishes the router's connection. That is recoverable,
# but a script cannot judge whether it recovered — the router answers with blank
# values while reconnecting, which is indistinguishable from a dead session.
#
# So each one is offered singly, with an explicit description of what will
# change and how to undo it by hand, and nothing proceeds without a typed `y`.
# One operation is in flight at a time, and the current value is printed before
# and after, so an interruption leaves a reader in no doubt about what state the
# device is in.


def _confirm(prompt: str) -> bool:
    """Ask before touching anything, and treat everything but `y` as no."""
    if not sys.stdin.isatty():
        print(_yellow("  SKIP  no terminal attached — attended checks need one"))
        return False
    try:
        return input(f"  {prompt} [y/N] ").strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        print()
        return False


async def _read_through_reconnect(
    api: ZTERouterAPI, key: str, tries: int = 8
) -> str | None:
    """Read one key, tolerating the router being away.

    Every attended write re-establishes the connection, so the router is
    *expected* to be unreachable immediately afterwards. Treating that as a
    failure — which the first version did — reports a successful write as
    failed and, worse, abandons the restore.
    """
    for attempt in range(tries):
        try:
            return (await api.get_params([key])).get(key)
        except Exception:  # noqa: BLE001 - absence is the expected state here
            if attempt == tries - 1:
                return None
            await asyncio.sleep(RECONNECT_RETRY)
    return None


async def _write_through_reconnect(
    api: ZTERouterAPI, setter: str, value: str, tries: int = 4
) -> str | None:
    """Send a setter, retrying while the router is still coming back.

    Safe to retry *these* commands specifically: they are idempotent settings
    changes, and the value is read back afterwards. This is not a general
    license to retry writes — see `write_classification.py`.
    """
    last: str | None = None
    for attempt in range(tries):
        try:
            await _call_setter(api, setter, value)
        except Exception as err:  # noqa: BLE001 - reporting, not handling
            last = f"{type(err).__name__}: {err}"
            if attempt == tries - 1:
                return last
            await asyncio.sleep(RECONNECT_RETRY)
        else:
            return None
    return last


async def _call_setter(api: ZTERouterAPI, setter: str, value: str) -> None:
    """Invoke a setter, supplying poll data to the ones that need it.

    `set_apn_mode` is a read-modify-write: the router refuses a mode change to
    manual unless it is also told which profile, so the call needs the current
    `apn_index` and its `APN_config` entry. Fetched fresh rather than cached,
    because this runs either side of a reconnect.
    """
    if setter == "set_apn_mode":
        # Needs the whole picture, not just the index: the profile is resolved
        # from `wan_apn` (authoritative) and falls back to `apn_index` only
        # while already manual. Fetching just the index would make every switch
        # to manual unresolvable, and the call would refuse.
        keys = ["apn_mode", "apn_index", "wan_apn"]
        keys += [f"APN_config{slot}" for slot in range(APN_PROFILE_SLOTS)]
        await api.set_apn_mode(value, await api.get_params(keys))
        return
    await getattr(api, setter)(value)


async def _attended_round_trip(
    api: ZTERouterAPI,
    report: Report,
    *,
    title: str,
    state_key: str,
    setter: str,
    target: str,
    risk: str,
    undo: str,
) -> None:
    """Offer one reconnecting write, then put the setting back."""
    original = (await api.get_params([state_key])).get(state_key)
    print(f"\n  {_yellow(title)}")
    print(f"    current   : {original!r}")
    print(f"    will set  : {target!r}, then restore {original!r}")
    print(f"    risk      : {risk}")
    print(f"    undo by hand: {undo}")

    if original in (None, ""):
        report.record(False, f"{title}: read the current value", "not reported")
        return
    if str(original) == target:
        print(_dim("    already at the target value — nothing to prove, skipping"))
        return
    if not _confirm(f"Change {state_key} to {target!r}?"):
        print(_dim("    skipped"))
        return

    error = await _write_through_reconnect(api, setter, target)
    if error is None:
        await asyncio.sleep(RECONNECT_SETTLE)
        observed = await _read_through_reconnect(api, state_key)
        report.record(str(observed) == target, f"{title}: applied", f"-> {observed!r}")
    else:
        report.record(False, f"{title}: applied", error)

    # Restore unconditionally. Even a write reported as failed may have landed —
    # this API answers 200 OK for a refusal and can lose the reply to a
    # reconnect it caused — so the only trustworthy question is what the router
    # says *now*.
    print(_dim(f"    restoring {state_key} to {original!r}…"))
    await asyncio.sleep(RECONNECT_SETTLE)
    if str(await _read_through_reconnect(api, state_key)) == str(original):
        report.record(True, f"{title}: restored", f"-> {original!r}")
        return

    restore_error = await _write_through_reconnect(api, setter, str(original))
    await asyncio.sleep(RECONNECT_SETTLE)
    back = await _read_through_reconnect(api, state_key)
    if str(back) == str(original):
        report.record(True, f"{title}: restored", f"-> {back!r}")
        return

    report.record(False, f"{title}: restored", restore_error or f"reads {back!r}")
    print(
        _red(
            f"\n  !! {state_key} MAY STILL BE {target!r} — "
            f"original was {original!r}.\n"
            f"  !! Undo by hand: {undo}\n"
        )
    )


async def check_apn_profile(api: ZTERouterAPI, report: Report) -> None:
    """Round-trip the APN profile itself, between two stored profiles.

    `set_apn` sends the complete `APN_PROC_EX` form and is the one APN write
    that always worked — which is precisely why it is worth exercising: it is
    the reference for the form the router demands, and the reason the broken
    `set_apn_mode` went unnoticed (choosing a profile flips the mode to manual
    as a side effect, so the mode appeared to follow along).

    Moves to a *different stored profile* and back. Both must already exist on
    the device; nothing is created. The restore also returns the selection mode,
    because `set_apn` changes it as a side effect and leaving that altered would
    be an unannounced change to the user's configuration.
    """
    print(_cyan("\n[B] APN profile round trip"))

    keys = ["apn_mode", "apn_index", "wan_apn"]
    keys += [f"APN_config{slot}" for slot in range(APN_PROFILE_SLOTS)]
    current = await api.get_params(keys)

    profiles: list[tuple[str, str, str]] = []
    for slot in range(APN_PROFILE_SLOTS):
        raw = current.get(f"APN_config{slot}")
        if not raw:
            continue
        parts = str(raw).split("($)")
        apn = parts[1] if len(parts) > 1 else ""
        pdp = parts[7] if len(parts) > 7 and parts[7] else "IP"
        if apn:  # the Default profile stores an empty APN and is skipped
            profiles.append((str(slot), apn, pdp))

    active_apn = str(current.get("wan_apn") or "").strip().lower()
    origin = next((p for p in profiles if p[1].strip().lower() == active_apn), None)
    other = next((p for p in profiles if p is not origin), None)

    if not profiles:
        # A router left on the carrier default stores no APN in any slot. That
        # is a normal configuration, not a fault, and the SMS checks already
        # treat "nothing to work with" as a skip rather than a failure.
        report.record(
            True,
            "APN profile: skipped, no profile configured",
            "router is on the carrier default; there is no profile to round-trip",
        )
        return

    if origin is None or other is None:
        report.record(
            False,
            "APN profile: two usable profiles available",
            f"found {len(profiles)} with an APN set; need the active one plus one more",
        )
        return

    original_mode = str(current.get("apn_mode") or "auto")
    print(f"    active    : {origin[1]!r} (slot {origin[0]}), mode {original_mode!r}")
    print(f"    will set  : {other[1]!r} (slot {other[0]}), then restore")
    print("    risk      : reconnect on each step; a profile your SIM rejects")
    print("                means no data until restored")
    print("    undo by hand: router web UI -> Settings -> APN")

    if not _confirm(f"Switch the APN profile to {other[1]!r}?"):
        print(_dim("    skipped"))
        return

    try:
        await api.set_apn(int(other[0]), other[2])
        await asyncio.sleep(RECONNECT_SETTLE)
        observed = await _read_through_reconnect(api, "wan_apn")
        report.record(
            str(observed).strip().lower() == other[1].strip().lower(),
            "APN profile: applied",
            f"Network APN -> {observed!r}",
        )
    except Exception as err:  # noqa: BLE001 - reporting, not handling
        report.record(False, "APN profile: applied", f"{type(err).__name__}: {err}")

    print(_dim(f"    restoring profile {origin[1]!r}…"))
    try:
        await api.set_apn(int(origin[0]), origin[2])
        await asyncio.sleep(RECONNECT_SETTLE)
        back = await _read_through_reconnect(api, "wan_apn")
        report.record(
            str(back).strip().lower() == origin[1].strip().lower(),
            "APN profile: restored",
            f"Network APN -> {back!r}",
        )
    except Exception as err:  # noqa: BLE001 - must be loud
        report.record(False, "APN profile: restored", f"{err}")
        print(_red(f"\n  !! APN may still be {other[1]!r} — restore by hand\n"))

    if original_mode.lower() == "auto":
        # `set_apn` forces manual, so auto has to be put back deliberately.
        print(_dim("    restoring selection mode to 'auto'…"))
        error = await _write_through_reconnect(api, "set_apn_mode", "auto")
        await asyncio.sleep(RECONNECT_SETTLE)
        mode = await _read_through_reconnect(api, "apn_mode")
        report.record(
            str(mode) == "auto",
            "APN profile: selection mode restored to auto",
            error or f"-> {mode!r}",
        )


async def check_data_limit_switch(api: ZTERouterAPI, report: Report) -> None:
    """Round-trip the data cap, but only from ON — never from OFF.

    This is the switch that had never worked in any release, so it earns an
    exercise. It is ATTENDED rather than SAFE because the router *enforces* the
    cap: turning it on stops traffic once the limit is reached, it does not
    merely warn.

    That asymmetry decides what may be automated. Starting from **on**, the
    round trip is off-then-on and the risky direction is simply restoring what
    was already there — if the script dies mid-way the cap is off, which
    inconveniences nobody. Starting from **off**, the same round trip would
    switch enforcement *on* and a crash could leave it that way, against a cap
    and a usage figure only the owner can judge. So that direction is refused
    rather than offered with a warning.

    No reconnect here — this is a settings write, not a radio change — but the
    six-field form has been seen refused once and accepted immediately after,
    so the write is retried once and the attempt count reported.
    """
    print(_cyan("\n[C] Data limit switch round trip"))

    fields = list(api.DATA_VOLUME_FIELDS)
    current = await api.get_params(fields)
    original = str(current.get("data_volume_limit_switch") or "")

    if original != "1":
        report.record(
            True,
            "data limit switch: skipped, currently off",
            "exercising it would switch enforcement ON, which a crash could strand",
        )
        return

    size = current.get("data_volume_limit_size")
    print(f"    current   : cap enforcement ON (limit {size!r})")
    print("    will set  : OFF, then restore ON")
    print("    risk      : low - the restore direction is the one already set;")
    print("                a failure part-way leaves the cap OFF, not ON")
    print("    undo by hand: router web UI -> Settings -> Data Management")

    if not _confirm("Turn the data cap off and back on?"):
        print(_dim("    skipped"))
        return

    attempts = 0
    error: str | None = None
    for attempt in range(2):
        if attempt:
            await asyncio.sleep(1.0)
        attempts = attempt + 1
        try:
            await api.set_data_limit_switch("0", current)
        except Exception as err:  # noqa: BLE001 - reporting, not handling
            error = f"{type(err).__name__}: {err}"
            continue
        error = None
        break

    if error is None:
        observed = (await api.get_params(["data_volume_limit_switch"])).get(
            "data_volume_limit_switch"
        )
        report.record(
            str(observed) == "0",
            "data limit switch: turned off",
            f"-> {observed!r}" + ("" if attempts == 1 else f"  [{attempts} attempts]"),
        )
    else:
        report.record(False, "data limit switch: turned off", error)

    # Restore from what the router reports now, not from the read taken before
    # the write — the form is all-or-nothing and must be rebuilt from current
    # values, or the restore itself would be refused.
    print(_dim("    restoring the cap to ON…"))
    latest = await api.get_params(fields)
    if str(latest.get("data_volume_limit_switch")) != "1":
        try:
            await api.set_data_limit_switch("1", latest)
        except Exception as err:  # noqa: BLE001 - must be loud
            report.record(False, "data limit switch: restored", f"{err}")
            print(_red("\n  !! THE DATA CAP IS STILL OFF — turn it back on\n"))
            return
    back = (await api.get_params(["data_volume_limit_switch"])).get(
        "data_volume_limit_switch"
    )
    report.record(str(back) == "1", "data limit switch: restored", f"-> {back!r}")
    if str(back) != "1":
        print(_red("\n  !! THE DATA CAP IS STILL OFF — turn it back on\n"))


def _ask(prompt: str) -> str:
    """Read a free-text answer, or "" when there is no terminal."""
    if not sys.stdin.isatty():
        print(_yellow("  SKIP  no terminal attached — attended checks need one"))
        return ""
    try:
        return input(f"  {prompt}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


async def _sent_count(api: ZTERouterAPI) -> int | None:
    """Return how many sent messages the router is storing.

    **Read through `sms_capacity_info`, never the batch poll.** The same key
    names exist in both and behave differently: `multi_data` returns
    `sms_nv_send_total` as an empty string, while the dedicated command returns
    a real number. Reading the batch version made this check compare 0 with 0
    forever and report a send that had demonstrably arrived as a failure.
    """
    try:
        capacity = await api.get_sms_capacity()
    except Exception:  # noqa: BLE001 - absence is an answer here
        return None
    raw = capacity.get("sms_nv_send_total")
    if raw in (None, ""):
        return None
    try:
        return int(str(raw))
    except ValueError:
        return None


async def _sent_message_ids(api: ZTERouterAPI) -> set[str] | None:
    """Return the ids of stored *sent* messages, or None if unreadable.

    Observed on the reference MC7010 (2026-07-31): a sent message is stored
    alongside received ones with `tag=2`, where received messages carry `tag=1`.
    Sample size is small, so this is used as a *second* confirmation rather than
    the primary one, and its absence is never treated as failure.
    """
    try:
        messages = await api.get_sms_messages(mem_store="1")
    except Exception:  # noqa: BLE001 - absence is an answer here
        return None
    return {str(m.get("id")) for m in messages if str(m.get("tag")) == "2"}


async def check_send_sms(api: ZTERouterAPI, report: Report) -> None:
    """Send one message to a number the operator supplies.

    This is why the tier was renamed. The command cannot run unattended — it
    costs money and reaches a third party — but with a person choosing the
    destination and confirming, it is an ordinary test.

    The destination is typed at the prompt rather than stored anywhere: a phone
    number in a committed script, or in a `.reports/` log, is exactly the kind
    of personal data that should not be lying around. It is not echoed back.
    """
    print(_cyan("\n[D] Send SMS"))
    print("    cost      : one SMS, billed by your provider")
    print("    risk      : delivers to a real handset - use a number you own")

    number = _ask("Destination number (blank to skip)")
    if not number:
        print(_dim("    skipped"))
        return

    # Nothing about the destination is printed from here on.
    print(_dim(f"    sending to a {len(number)}-character number…"))
    before_count = await _sent_count(api)
    before_ids = await _sent_message_ids(api) or set()
    stamp = datetime.now(UTC).strftime("%H:%M:%S")
    body = f"hardware_check {stamp} UTC"

    try:
        await api.send_sms(number, body)
    except Exception as err:  # noqa: BLE001 - reporting, not handling
        report.record(False, "send_sms: accepted by the router", f"{err}")
        return

    report.record(True, "send_sms: accepted by the router")

    # Two independent confirmations, because either can be unavailable. The
    # counter is the primary one; the stored-message check backs it up.
    #
    # Neither absence is failure. That distinction matters here specifically:
    # an earlier version of this check compared the batch-poll copies of these
    # counters, which are always empty, and so reported every send as broken.
    await asyncio.sleep(SMS_SETTLE)
    after_count = await _sent_count(api)
    after_ids = await _sent_message_ids(api) or set()
    new_ids = after_ids - before_ids

    if before_count is not None and after_count is not None:
        report.record(
            after_count > before_count,
            "send_sms: sent counter incremented",
            f"{before_count} -> {after_count}",
        )
    elif new_ids:
        report.record(True, "send_sms: message stored", f"new id {sorted(new_ids)}")
    else:
        print(
            _yellow(
                "  NOTE  neither the counter nor the stored-message list was "
                "readable — the send was accepted but is unconfirmed here"
            )
        )

    if new_ids:
        print(_dim(f"    stored as sent message id {min(new_ids)}"))
    print(_dim("    check the handset — delivery itself is not observable"))


async def check_delete_most_recent_sms(api: ZTERouterAPI, report: Report) -> None:
    """Delete the single newest message, whichever it is.

    Targeting the newest keeps this useful straight after the send check while
    still working on its own — but the operator sees the message identified
    before confirming, so it is never an arbitrary deletion.

    **Only the id and timestamp are printed.** Sender and body are deliberately
    withheld: this run is teed to `.reports/`, and message content does not
    belong in a file on disk.
    """
    print(_cyan("\n[E] Delete the most recent SMS"))

    try:
        messages = await api.get_sms_messages(mem_store="1", tags="10")
    except Exception as err:  # noqa: BLE001 - reporting, not handling
        report.record(False, "delete_sms: read the inbox", f"{err}")
        return

    if not messages:
        report.record(True, "delete_sms: skipped, inbox empty", "nothing to delete")
        return

    newest = max(messages, key=lambda m: int(str(m.get("id") or 0)))
    msg_id = str(newest.get("id"))
    print(f"    target    : message id {msg_id}, dated {newest.get('date_decoded')}")
    print(_dim("    sender and body withheld — this run is logged to .reports/"))
    print("    risk      : irreversible; nothing can restore a deleted message")

    if not _confirm(f"Delete message {msg_id}?"):
        print(_dim("    skipped"))
        return

    try:
        await api.delete_sms(msg_id)
    except Exception as err:  # noqa: BLE001 - reporting, not handling
        report.record(False, "delete_sms: accepted", f"{type(err).__name__}: {err}")
        return

    await asyncio.sleep(SMS_SETTLE)
    try:
        remaining = await api.get_sms_messages(mem_store="1", tags="10")
    except Exception as err:  # noqa: BLE001 - unverified, not failed
        # The delete was accepted. A read that errors leaves the question open;
        # only a successful read still showing the message proves otherwise.
        # Reporting this as a failed delete is the mistake this script's own
        # rules name — and with another client polling the router it is the
        # likely outcome, not a rare one.
        report.record(
            True,
            "delete_sms: accepted, removal UNVERIFIED",
            f"read-back failed ({type(err).__name__}); check the inbox by hand",
        )
        return
    ids = {str(m.get("id")) for m in remaining}
    report.record(
        msg_id not in ids,
        "delete_sms: the message is gone",
        f"{len(messages)} -> {len(remaining)} messages",
    )


async def check_delete_all_sms(api: ZTERouterAPI, report: Report) -> None:
    """Clear the inbox, with the count stated before the confirmation.

    The most destructive command here, and the only one with no restore of any
    kind. The prompt names how many messages will go, because "yes" to an
    unspecified number is not informed consent — that is the whole safeguard.
    """
    print(_cyan("\n[F] Delete ALL SMS"))

    try:
        messages = await api.get_sms_messages(mem_store="1", tags="10")
    except Exception as err:  # noqa: BLE001 - reporting, not handling
        report.record(False, "delete_all: read the inbox", f"{err}")
        return

    if not messages:
        report.record(True, "delete_all: skipped, inbox empty", "nothing to delete")
        return

    print(_red(f"    THIS WILL DELETE {len(messages)} MESSAGE(S), PERMANENTLY"))
    print("    risk      : no undo, no partial recovery, no confirmation dialog")
    print("                on the router either")

    if not _confirm(f"Delete all {len(messages)} messages?"):
        print(_dim("    skipped"))
        return

    try:
        await api.delete_all()
    except Exception as err:  # noqa: BLE001 - reporting, not handling
        report.record(False, "delete_all: accepted", f"{type(err).__name__}: {err}")
        return

    await asyncio.sleep(SMS_SETTLE)
    try:
        remaining = await api.get_sms_messages(mem_store="1", tags="10")
    except Exception as err:  # noqa: BLE001 - unverified, not failed
        report.record(
            True,
            "delete_all: accepted, clearance UNVERIFIED",
            f"read-back failed ({type(err).__name__}); check the inbox by hand",
        )
        return
    report.record(
        not remaining,
        "delete_all: inbox is empty",
        f"{len(messages)} -> {len(remaining)} messages",
    )


async def _core_baseline(api: ZTERouterAPI) -> set[str]:
    """Return the core keys that carry a value while the router is settled.

    The raw count of empty keys says almost nothing on this device: a healthy
    MC7010 answers ~25 of 80 core keys empty, because unused APN slots and the
    5G metrics are legitimately blank on LTE. Only the *delta* against a
    settled reading identifies a key that has genuinely gone missing.
    """
    settled = await api.get_all_data()
    return {key for key, value in settled.items() if value not in (None, "")}


async def _watch_recovery(
    api: ZTERouterAPI, baseline: set[str], report: Report
) -> None:
    """Poll while the router returns, and score what it answers.

    This is the half of the reboot check that matters. Waiting for the router
    to answer only proves it is powered; it says nothing about *what* it
    answers, and what it answered was the bug — a partly-populated payload that
    the integration scored as a clean success while every entity fed from a
    blanked key published `unknown`.

    So this asserts the property the fix restored: while recovering, the router
    is either unreachable, or reporting an expired session that drives a
    re-login, but never quietly serving a payload with the authenticated keys
    stripped out. A `LOST` line here means the two-class detection in
    `_classify_session` has been defeated again — most likely because a
    firmware update changed which keys answer without a session.
    """
    print(_dim("    watching what it answers while it comes back…"))
    deadline = time.monotonic() + REBOOT_TIMEOUT
    silent_success = 0
    recovered = False

    while time.monotonic() < deadline:
        await asyncio.sleep(RECONNECT_RETRY)
        try:
            payload = await api.get_all_data()
        except ZTEAuthError:
            print(_dim("      expired session reported — the detector fired"))
            continue
        except Exception:  # noqa: BLE001 - absence is expected while it boots
            print(_dim("      still down…"))
            continue

        blank = {k for k, v in payload.items() if v in (None, "")}
        # A router that re-registers on 4G reports no NR5G keys at all. That is
        # the network, not a stripped payload — and this check exists to catch
        # the latter. Excluding them when the radio is demonstrably not on 5G
        # keeps the check pointed at what it is for; leaving them in reported a
        # clean reboot as a failure on 2026-08-07.
        on_5g = str(payload.get("network_type") or "").upper() in ("ENDC", "NR5G", "NR")
        if not on_5g:
            blank -= _NR5G_KEYS
        lost = sorted(baseline & blank)
        if not lost:
            recovered = True
            if not on_5g:
                print(
                    _dim(
                        "      back on "
                        f"{payload.get('network_type') or 'an unknown bearer'} — "
                        "NR5G keys excluded, they are absent by network state"
                    )
                )
            break
        silent_success += 1
        print(
            _red(f"      LOST {len(lost)} normally-populated keys: ")
            + _dim(", ".join(lost[:8]) + ("…" if len(lost) > 8 else ""))
        )

    report.record(
        silent_success == 0,
        "reboot: no payload served with the authenticated keys stripped",
        (
            "clean throughout"
            if silent_success == 0
            else f"{silent_success} poll(s) succeeded while missing live keys — "
            f"session detection is defeated again"
        ),
    )
    if not recovered:
        report.record(
            False,
            "reboot: full payload restored",
            f"still incomplete after {REBOOT_TIMEOUT:.0f}s — check it by hand",
        )


async def check_reboot(api: ZTERouterAPI, report: Report) -> None:
    """Reboot, then watch what the device says on the way back.

    Left until last because it ends the session and takes the connection down
    for minutes. Nothing is *changed* by it, which is why it is only a matter of
    time rather than risk — the earlier reasoning that it "cannot be made quick
    or quiet" confused cost with danger and kept it unscripted for no good
    reason.

    Two things are checked, and the second is the one that has caught a real
    bug. The reboot itself is verified by the uptime counter going backwards,
    not merely by the router answering again: a device that never rebooted also
    answers. The recovery is then watched key by key, because the fault found on
    2026-07-31 lived entirely in *successful* responses.
    """
    print(_cyan("\n[G] Reboot and recovery"))

    baseline = await _core_baseline(api)
    before = await api.get_params(["realtime_time"])
    uptime_before = str(before.get("realtime_time") or "?")
    print(f"    uptime now: {uptime_before}s")
    print(f"    baseline  : {len(baseline)} core keys carry a value when settled")
    print("    cost      : the connection drops for a few minutes")
    print("    risk      : nothing is left changed; this is time, not danger")

    if not _confirm("Reboot the router now?"):
        print(_dim("    skipped"))
        return

    try:
        await api.reboot()
    except Exception as err:  # noqa: BLE001 - reporting, not handling
        report.record(False, "reboot: accepted", f"{type(err).__name__}: {err}")
        return

    print(_dim(f"    waiting up to {REBOOT_TIMEOUT:.0f}s for the router to return…"))
    deadline = time.monotonic() + REBOOT_TIMEOUT
    uptime_after: str | None = None
    while time.monotonic() < deadline:
        await asyncio.sleep(REBOOT_POLL)
        try:
            await api.login()
            uptime_after = str(
                (await api.get_params(["realtime_time"])).get("realtime_time")
            )
            break
        except Exception:  # noqa: BLE001 - absence is expected while it boots
            print(_dim("      still down…"))

    if uptime_after is None:
        report.record(
            False,
            "reboot: router came back",
            f"still unreachable after {REBOOT_TIMEOUT:.0f}s — check it by hand",
        )
        return

    try:
        went_back = int(uptime_after) < int(uptime_before)
    except ValueError:
        went_back = False
    report.record(
        went_back,
        "reboot: uptime reset",
        f"{uptime_before}s -> {uptime_after}s",
    )

    await _watch_recovery(api, baseline, report)


async def _guarded(report: Report, title: str, coro: Any) -> None:
    """Run one attended check so its failure cannot abandon the others.

    An unhandled error used to end the whole run, which mattered most in the
    one place it must not: after a write had already changed something and the
    restore had not yet happened.
    """
    try:
        await coro
    except Exception as err:  # noqa: BLE001 - containment is the point
        report.record(False, f"{title}: check aborted", f"{type(err).__name__}: {err}")
        print(_red(f"  !! {title} did not complete — verify this setting by hand"))


async def check_attended_writes(api: ZTERouterAPI, report: Report) -> None:
    """Run the reconnecting writes, one at a time, each individually confirmed."""
    print(_cyan("\n[A] Attended writes — each one asks first"))
    print(
        _dim(
            "    These re-establish the mobile connection. Expect a short "
            "outage per step."
        )
    )

    await _guarded(
        report,
        "APN selection mode",
        _attended_round_trip(
            api,
            report,
            title="APN selection mode",
            state_key="apn_mode",
            setter="set_apn_mode",
            target="manual",
            risk="brief reconnect; a wrong profile means no data until restored",
            undo="router web UI -> Settings -> APN -> set back to Auto",
        ),
    )

    await _guarded(report, "APN profile", check_apn_profile(api, report))

    await _guarded(report, "Data limit switch", check_data_limit_switch(api, report))

    await _guarded(
        report,
        "Bearer preference",
        _attended_round_trip(
            api,
            report,
            title="Bearer preference",
            state_key="net_select",
            setter="set_bearer_preference",
            target="LTE_AND_5G",
            risk="radio re-registration; locking a mode can drop service",
            undo="router web UI -> Settings -> Network -> set the preference back",
        ),
    )

    # SMS first, so the delete checks have something of their own to work on,
    # then reboot last because it ends the session and takes minutes.
    await _guarded(report, "Send SMS", check_send_sms(api, report))
    await _guarded(report, "Delete SMS", check_delete_most_recent_sms(api, report))
    await _guarded(report, "Delete all SMS", check_delete_all_sms(api, report))
    await _guarded(report, "Reboot", check_reboot(api, report))


async def check_refusal_is_not_retried(api: ZTERouterAPI, report: Report) -> None:
    """Check that a malformed write is reported rather than resent.

    `DATA_LIMIT_SETTING` is the one safe way to provoke a genuine refusal: the
    router requires all six fields and declines a partial form outright, without
    changing anything. Resending a declined command is the hazard that rules out
    blind retry — for `send_sms` it would deliver the message twice.
    """
    print(_cyan("\n[6] A genuinely refused write"))
    try:
        await api.set_data_volume_settings({}, data_volume_limit_switch="0")
    except Exception as err:  # noqa: BLE001 - the expected outcome
        report.record(
            True,
            "a partial DATA_LIMIT_SETTING form is refused, not silently accepted",
            type(err).__name__,
        )
        report.captured["refused_write"] = {"result": "failure"}
    else:
        report.record(
            False,
            "a partial DATA_LIMIT_SETTING form is refused, not silently accepted",
            "it was accepted — the six-field requirement may have changed",
        )


async def capture_reference_payloads(api: ZTERouterAPI, report: Report) -> None:
    """Record real responses so mocks can be built from observation."""
    print(_cyan("\n[7] Capturing reference payloads"))
    report.captured["core_keys"] = sorted(await api.get_all_data())
    report.captured["extended_keys"] = sorted(await api.get_extended_data())
    report.captured["single_key_read"] = await api.get_params(["ODU_led_switch"])
    report.record(True, "captured live payload shapes")


# Values that may appear in a capture. Everything else must be a key *name*, so
# a future check cannot quietly start recording telemetry.
_ALLOWED_CAPTURE_VALUES = {"", "failure", "0", "1", "ppp_connected"}

# Substrings of keys whose *values* must never be recorded, whatever they hold.
_NEVER_CAPTURE = (
    "imei",
    "imsi",
    "iccid",
    "ipaddr",
    "cell",
    "sms",
    "apn",
    "provider",
    "mcc",
    "mnc",
    "rd",
    "ld",
    "stok",
    "password",
)


def _assert_capture_is_safe(captured: dict[str, Any]) -> None:
    """Refuse to write a fixture containing anything personal.

    The capture exists so mocks can be built from observation, which needs the
    *shape* of a response, not its contents. This file is committed, so a check
    added later that happens to record a payload would publish an IMEI, an
    ICCID, a cell ID or a message body. Fail loudly instead.
    """
    offenders: list[str] = []
    for name, value in captured.items():
        if name.endswith("_keys") or isinstance(value, bool):
            continue  # key names and observations carry nothing
        if not isinstance(value, dict):
            offenders.append(f"{name}: unexpected {type(value).__name__}")
            continue
        for key, item in value.items():
            if any(bad in key.lower() for bad in _NEVER_CAPTURE):
                offenders.append(f"{name}.{key}: key is on the never-capture list")
            elif str(item) not in _ALLOWED_CAPTURE_VALUES:
                offenders.append(
                    f"{name}.{key}: value {item!r} is not an allowed literal"
                )

    if offenders:
        raise SystemExit(
            "refusing to write fixtures — capture may contain personal data:\n  "
            + "\n  ".join(offenders)
            + "\n\nRecord the response *shape* (key names), or add the literal to "
            "_ALLOWED_CAPTURE_VALUES if it is genuinely a protocol constant."
        )


def _warn_about_competing_sessions() -> None:
    """State the one precondition this script cannot enforce for itself.

    **The router accepts the most recent login and drops the previous one.**
    That is not a race lost occasionally — any other client that logs in takes
    the session, every time. A production Home Assistant polling every three
    minutes will therefore interrupt any step spanning three minutes, on a
    fixed cadence.

    This script *does* steal its own session on purpose, in
    `check_write_round_trip(hostile=True)`, and checks that the code notices.
    That is a controlled theft at a known point. An outside competitor is a
    different thing: it takes the session at an arbitrary point, so a failure
    can no longer be attributed. "The code failed to detect a dead session" and
    "the session died mid-write for unrelated reasons" produce the same result,
    and the run stops meaning anything.

    Hence a warning rather than a check — the competitor is usually on another
    machine, and nothing reachable from here can see it.
    """
    print(_yellow("\n  !  This run needs the router to itself."))
    print(
        _dim(
            "     The router hands the session to whoever logged in last, so"
            " any other client"
        )
    )
    print(
        _dim(
            "     silently takes it. Turn ON Pause Polling in EVERY Home"
            " Assistant instance"
        )
    )
    print(
        _dim(
            "     connected to this router — including production, which is the"
            " one most"
        )
    )
    print(
        _dim(
            "     easily forgotten — and stay out of the router's own web page"
            " until this"
        )
    )
    print(_dim("     finishes."))
    print(
        _dim("     A competitor does not make these checks fail loudly. It makes their")
    )
    print(_dim("     results unattributable, which is worse."))


async def main() -> int:
    """Run every check in order and return a shell exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capture",
        action="store_true",
        help="write observed responses to tests/fixtures/ for mock construction",
    )
    parser.add_argument(
        "--attended",
        action="store_true",
        help=(
            "also offer the writes that re-establish the connection, one at a "
            "time, each requiring a typed confirmation. Needs a terminal, and "
            "someone watching it."
        ),
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI colour (NO_COLOR in the environment does the same)",
    )
    args = parser.parse_args()
    if args.no_color:
        global _COLOUR  # noqa: PLW0603 - one flag, set once before any output
        _COLOUR = False

    options = _credentials()
    report = Report()

    async with aiohttp.ClientSession() as session:
        api = ZTERouterAPI(
            session, options["host"], options.get("username"), options["password"]
        )
        await api.try_set_protocol()
        await api.login()
        print(f"connected to {options['host']}")
        _warn_about_competing_sessions()

        await check_session_assumptions(api, session, report)
        await check_write_round_trip(api, report, hostile=False, session=session)
        await check_write_round_trip(api, report, hostile=True, session=session)
        await check_data_volume_form(api, report)
        await check_logout_ends_the_session(api, report)
        await check_refusal_is_not_retried(api, report)
        if args.attended:
            await check_attended_writes(api, report)
        await capture_reference_payloads(api, report)

        with contextlib.suppress(Exception):
            await api.logout()

    if args.capture:
        _assert_capture_is_safe(report.captured)
        FIXTURES.mkdir(parents=True, exist_ok=True)
        target = FIXTURES / "mc7010_observed.json"
        target.write_text(
            json.dumps(report.captured, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"\ncaptured -> {target}")

    total = len(report.checks)
    passed = total - report.failed
    # The banner lives here rather than in the VS Code task because `tee >(...)`
    # reports the exit status of `tee`, not of this script — a shell-side banner
    # would have to reach for PIPESTATUS to know what actually happened.
    if report.failed:
        print(_red(f"\n\u2716  Hardware check: FAILED  ({passed}/{total} passed)"))
    else:
        print(_green(f"\n\u2714  Hardware check: PASSED  ({passed}/{total})"))
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
