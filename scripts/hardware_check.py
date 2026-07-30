"""Exercise the write path against a real router, and record what it answers.

Not part of CI, and not a unit test. This exists because the unit suite cannot
falsify a wrong belief about the device: a mock is written from the model, so a
test built on a wrong model passes while the code is broken. That is not
hypothetical — on 2026-07-30 a test asserting that a refused write could be
retried after re-login was green while the same code failed on hardware. The
first explanation offered for that failure was itself wrong, and this script
disproved it on its first run. Both the code and the tests now record what was
measured and stop short of claiming a mechanism.

So this script does two jobs:

  1. Round-trips every *safe* write end to end, including with the session
     deliberately taken away — the scenario a user hit by logging into the
     router's web page while Home Assistant was connected.
  2. Records the router's actual responses to `--capture`, so unit-test mocks
     can be built from observation instead of imagination.

Deliberately excluded, and not by oversight:

  * `send_sms` / `delete_sms`  — real messages, real cost.
  * `reboot`                   — takes the router down.
  * APN and bearer selects     — re-establish the connection; the router
                                 answers blank while it does, which reads as an
                                 expired session. Testing these needs a human
                                 watching, not a script.

Usage, inside the devcontainer, **from anywhere** — paths are resolved from
`__file__`, not the working directory:

    /usr/local/bin/python scripts/hardware_check.py             # check + restore
    /usr/local/bin/python scripts/hardware_check.py --capture   # also record

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
# point. This is the only rule the file cannot satisfy on its own terms.
# ruff: noqa: T201

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import pathlib
import sys
import time
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

try:
    import aiohttp

    from custom_components.zte_router_5g.api import ZTEAuthError, ZTERouterAPI
except ModuleNotFoundError as err:  # pragma: no cover - operator ergonomics
    raise SystemExit(
        f"cannot import {err.name!r}.\n\n"
        "This script imports the integration, which imports Home Assistant, so "
        "it needs the devcontainer's interpreter:\n\n"
        "    /usr/local/bin/python scripts/hardware_check.py\n\n"
        "`uv run` and the project .venv do not carry those dependencies."
    ) from err

CONFIG_ENTRIES = "/config/.storage/core.config_entries"
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

# Colour is emitted unconditionally, the way `pytest --color=yes` is used by the
# sibling tasks: stdout here is a pipe into `tee`, so auto-detection would strip
# it exactly when it is wanted. The VS Code task sends the coloured stream to the
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
    with open(CONFIG_ENTRIES) as handle:
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
    api.stok = await api.login()
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

    api.stok = await api.login()


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
                api.stok = await api.login()
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

    current = await api.get_params(list(api._DATA_VOLUME_FIELDS))
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
        latest = await api.get_params(list(api._DATA_VOLUME_FIELDS))
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
        api.stok = stale
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
        api.stok = await api.login()


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

    changed = False
    try:
        await getattr(api, setter)(target)
        changed = True
        await asyncio.sleep(RECONNECT_SETTLE)
        observed = (await api.get_params([state_key])).get(state_key)
        report.record(str(observed) == target, f"{title}: applied", f"-> {observed!r}")
    except Exception as err:  # noqa: BLE001 - reporting, not handling
        report.record(False, f"{title}: applied", f"{type(err).__name__}: {err}")
    finally:
        if changed:
            print(_dim(f"    restoring {state_key} to {original!r}…"))
            try:
                await getattr(api, setter)(str(original))
                await asyncio.sleep(RECONNECT_SETTLE)
                back = (await api.get_params([state_key])).get(state_key)
                report.record(
                    str(back) == str(original),
                    f"{title}: restored",
                    f"-> {back!r}",
                )
            except Exception as err:  # noqa: BLE001 - must be loud
                report.record(False, f"{title}: restored", f"{err}")
                print(
                    _red(
                        f"\n  !! {state_key} MAY STILL BE {target!r} — "
                        f"original was {original!r}.\n"
                        f"  !! Undo by hand: {undo}\n"
                    )
                )


async def check_attended_writes(api: ZTERouterAPI, report: Report) -> None:
    """Run the reconnecting writes, one at a time, each individually confirmed."""
    print(_cyan("\n[A] Attended writes — each one asks first"))
    print(
        _dim(
            "    These re-establish the mobile connection. Expect a short "
            "outage per step."
        )
    )

    await _attended_round_trip(
        api,
        report,
        title="APN selection mode",
        state_key="apn_mode",
        setter="set_apn_mode",
        target="manual",
        risk="brief reconnect; a wrong APN profile means no data until restored",
        undo="router web UI -> Settings -> APN -> set back to Auto",
    )

    await _attended_round_trip(
        api,
        report,
        title="Bearer preference",
        state_key="net_select",
        setter="set_bearer_preference",
        target="LTE_AND_5G",
        risk="radio re-registration; locking to a single mode can drop service",
        undo="router web UI -> Settings -> Network -> set the preference back",
    )


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
        api.stok = await api.login()
        print(f"connected to {options['host']}")

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
