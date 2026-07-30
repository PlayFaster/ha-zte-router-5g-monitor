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

Usage, inside the devcontainer:

    python scripts/hardware_check.py                # exercise, restore, report
    python scripts/hardware_check.py --capture      # also write fixtures

Reads credentials from the configured Home Assistant entry. Every write is
restored to its original value, including on failure.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import pathlib
import sys
import time
from typing import Any

import aiohttp

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from custom_components.zte_router_5g.api import (
    ZTEAuthError,
    ZTERouterAPI,
)

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
        self.checks: list[tuple[bool, str, str]] = []
        self.captured: dict[str, Any] = {}

    def record(self, ok: bool, name: str, detail: str = "") -> None:
        self.checks.append((ok, name, detail))
        print(
            f"  {'PASS' if ok else 'FAIL'}  {name}{f'  — {detail}' if detail else ''}"
        )

    @property
    def failed(self) -> int:
        return sum(1 for ok, _, _ in self.checks if not ok)


def _credentials() -> dict[str, str]:
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
    """A malformed write must be reported, never resent.

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


async def main() -> int:
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
