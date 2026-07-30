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


class Report:
    """Collects results so one failure does not hide the rest."""

    def __init__(self) -> None:
        """Start an empty report."""
        self.checks: list[tuple[bool, str, str]] = []
        self.captured: dict[str, Any] = {}

    def record(self, ok: bool, name: str, detail: str = "") -> None:
        """Print one result and remember it for the summary."""
        self.checks.append((ok, name, detail))
        print(
            f"  {'PASS' if ok else 'FAIL'}  {name}{f'  — {detail}' if detail else ''}"
        )

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
    print("\n[1] Session and token assumptions")

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
        f"  NOTE  RD {'survives' if after_login == live else 'changes on'} "
        "re-login (observation only, nothing depends on it)"
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
    print(f"\n[{3 if hostile else 2}] Safe writes {label}")

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


async def check_refusal_is_not_retried(api: ZTERouterAPI, report: Report) -> None:
    """Check that a malformed write is reported rather than resent.

    `DATA_LIMIT_SETTING` is the one safe way to provoke a genuine refusal: the
    router requires all six fields and declines a partial form outright, without
    changing anything. Resending a declined command is the hazard that rules out
    blind retry — for `send_sms` it would deliver the message twice.
    """
    print("\n[4] A genuinely refused write")
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
    print("\n[5] Capturing reference payloads")
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
    args = parser.parse_args()

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
        await check_refusal_is_not_retried(api, report)
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
    print(f"\n{total - report.failed}/{total} checks passed")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
