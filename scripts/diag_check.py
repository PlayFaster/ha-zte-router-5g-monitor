"""Produce a real diagnostics download against the router, and check it.

Not part of CI, and not a unit test. It exists because the unit suite asserts
on what `run_discovery` *returns*, while the user receives what
`_sanitize_discovery` *publishes*, and those are different things separated by
an allow-list. A field missing from that list is dropped in silence: branch
coverage cannot see it, because the list is data and the loop over it runs
either way.

That gap has cost two releases. `session_alive_after` was caught by memory
before v3.3.9-dev4 shipped. `canary` was not — it was added to the API in
v3.3.9-dev5, asserted by five green unit tests, and absent from every download
that release produced. The field records whether the pass could detect its own
degradation, so without it a reader cannot tell "these 444 names do not exist
on this firmware" from "we may not have been logged in". Three downloads taken
from the reference MC7010 on 2026-09-02 carry the full mining trace and no
canary at all, and the fault was found by a human reading the files.

So this script does three jobs:

  1. Builds a real coordinator against the real router and calls the real
     `async_get_config_entry_diagnostics`, producing the artefact rather than
     a model of it.
  2. Asserts over the produced file: required fields present, counts
     internally consistent, and no unredacted identifier.
  3. Runs the whole thing **twice** and diffs the two, which is the check that
     found the v3.3.9-dev4 truncation — two downloads minutes apart differing
     by 6 kB, one having answered 3 names and the other 90. Radio values drift
     between runs and are ignored; a structural difference is a failure.

Usage, inside the devcontainer, **from anywhere** — paths are resolved from
`__file__`, not the working directory:

    /usr/local/bin/python scripts/diag_check.py           # two runs, diffed
    /usr/local/bin/python scripts/diag_check.py --once    # one run, no diff
    /usr/local/bin/python scripts/diag_check.py --keep    # also save the files

**Use the container interpreter, not `uv run`.** This imports the integration,
which imports Home Assistant; only `/usr/local/bin/python` has those installed.

Reads credentials from the configured Home Assistant entry — nothing is passed
on the command line. It makes no writes: the diagnostics download is a read
path. It does log the router out and back in, because `run_discovery` starts
from a session it established itself rather than one it happens to hold, and
the hardware permits only one session at a time.

Saved files under `--keep` contain live sanitized diagnostics and are written
to `.notes/local_only/`, which is not tracked.
"""

# The console report is this script's entire output — there is no logger to
# route it through.
# ruff: noqa: T201

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import pathlib
import re
import sys
from datetime import UTC, datetime
from itertools import combinations
from typing import TYPE_CHECKING, Any, cast

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

try:
    import aiohttp

    from custom_components.zte_router_5g.api import ZTERouterAPI
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )
    from custom_components.zte_router_5g.diagnostics import (
        DISCOVERY_METADATA_PUBLISHED,
        async_get_config_entry_diagnostics,
    )
except ModuleNotFoundError as err:  # pragma: no cover - operator ergonomics
    raise SystemExit(
        f"cannot import {err.name!r}.\n\n"
        "This script imports the integration, which imports Home Assistant, so "
        "it needs the devcontainer's interpreter:\n\n"
        "    /usr/local/bin/python scripts/diag_check.py\n\n"
        "`uv run` and the project .venv do not carry those dependencies."
    ) from err

if TYPE_CHECKING:  # pragma: no cover - typing only
    from homeassistant.config_entries import ConfigEntry

CONFIG_ENTRIES = pathlib.Path("/config/.storage/core.config_entries")
OUTPUT_DIR = (
    pathlib.Path(__file__).resolve().parent.parent / ".notes" / "local_only" / "diag_dl"
)

# Values that legitimately differ between two runs minutes apart: radio
# measurements, counters and anything clocked. A difference here is the device
# living its life, not the download changing shape. Matched against the leaf
# path, so `/data/discovery/values/lte_snr_1` is covered by `lte_snr`.
_VOLATILE = re.compile(
    r"(?i)(rsrp|rsrq|rssi|snr|sinr|_time|uptime|timestamp|cell_info|sig_info"
    r"|_bars?$|signalbar|realtime|flux_|monthly_|_rx_|_tx_|traffic|volume"
    # Carrier aggregation comes and goes with the network, not with us:
    # observed changing from `ca_activated` to `ca_deconfigured` between two
    # passes ten seconds apart.
    r"|lte_ca|_band$|_bandwidth$|_pci$|_arfcn$|cell_id"
    r"|_update|_date$|_temp|temperature"
    # This script's own bookkeeping, and the free-text notes, which are a
    # list compared by position: a pass emitting one extra note shifts every
    # entry after it and reports a dozen differences for one real one. The
    # counts those notes carry are asserted directly below instead, which is
    # the precise form of the same check.
    r"|^/_elapsed$|^/discovery/notes/)"
)

# An identifier that reached the file unredacted. The tokenizer replaces these
# with stable pseudonyms, so a raw one is a sanitization failure and not a
# cosmetic one. IMSI is 15 digits and ICCID 19-20; the reference MC7010 serves
# an 11-digit byte counter, so the digit rule starts above it.
_RAW_IDENTIFIER = re.compile(
    r"(?:\b(?:\d{1,3}\.){3}\d{1,3}\b"  # IPv4
    r"|\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b"  # MAC
    r"|\b\d{15,}\b)"  # IMSI / ICCID / IMEI
)

# How many polls to allow the coordinator before giving up on a payload. Three
# are needed cold on the reference hardware; the rest is headroom, and running
# out is a failure the shape check reports rather than something to retry past.
POLL_ATTEMPTS = 6

# How large the unasked list may grow before a pass is judged unhealthy. A few
# names fail their own request repeatedly on the reference MC7010 — 11 of 538
# probed — and reporting them as unasked is correct. Hundreds would mean the
# pass is not completing.
UNASKED_PROPORTION_LIMIT = 0.05

# How much of a clean pass's harvest a sabotaged pass must still return. Not
# 1.0: the router's own answers drift, and a name that was populated a minute
# ago may legitimately be empty now. A recovery that keeps 95% has worked; one
# that keeps a third has not.
SABOTAGE_RECOVERY_FLOOR = 0.95

# Default seconds between survey passes. Long enough that two passes are not
# back-to-back, short enough that a dozen of them is a coffee break rather than
# an afternoon.
SURVEY_GAP_SECONDS = 20

# Addresses that are not identifying and appear in the file by design.
_ALLOWED_ADDRESSES = frozenset(
    {
        "0.0.0.0",  # noqa: S104 - matched as text in a file, never bound to
        "255.255.255.255",
        "127.0.0.1",
    }
)

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

    def record(self, ok: bool, name: str, detail: str = "") -> None:
        """Print one result and remember it for the summary."""
        self.checks.append((ok, name, detail))
        badge = _green("✔  PASS") if ok else _red("✖  FAIL")
        suffix = _dim(f"  — {detail}") if detail else ""
        print(f"  {badge}  {name}{suffix}")

    @property
    def failed(self) -> int:
        """Return how many checks failed, for the exit code."""
        return sum(1 for ok, _, _ in self.checks if not ok)


def _credentials() -> tuple[dict[str, Any], dict[str, Any], str, str]:
    """Read the router entry from the configured Home Assistant instance."""
    with CONFIG_ENTRIES.open() as handle:
        data = json.load(handle)
    for entry in data["data"]["entries"]:
        if entry["domain"] == "zte_router_5g":
            return (
                dict(entry["options"]),
                dict(entry["data"]),
                entry["entry_id"],
                entry["title"],
            )
    raise SystemExit(f"no zte_router_5g entry in {CONFIG_ENTRIES}")


class _StubEntry:
    """The parts of a `ConfigEntry` the diagnostics path actually reads.

    `async_get_config_entry_diagnostics` takes `hass` but never touches it, and
    reads only `title`, `data`, `options` and `runtime_data` from the entry.
    `async_on_unload` is here for `DataUpdateCoordinator.__init__`, which
    registers its shutdown against the entry.

    A stub rather than the live entry on purpose: this builds its own
    coordinator so a run cannot disturb the one serving the user's entities.
    """

    def __init__(
        self, options: dict[str, Any], data: dict[str, Any], entry_id: str, title: str
    ) -> None:
        """Hold the entry fields the diagnostics path reads."""
        self.options = options
        self.data = data
        self.entry_id = entry_id
        self.title = title
        self.runtime_data: Any = None

    def async_on_unload(self, func: Any) -> Any:
        """Accept and return the shutdown callback, registering nothing."""
        return func


def _sabotaging_chunk(original: Any, sabotage_at: int) -> Any:
    """Wrap `_probe_chunk` so the nth call finds the session already gone."""
    state = {"n": 0}

    async def chunk(self: Any, names: list[str], canaries: Any = ()) -> Any:
        state["n"] += 1
        if state["n"] == sabotage_at:
            # A competing login does not clear our cookie; it makes it
            # meaningless. Replacing the value reproduces that exactly.
            self.cookies = dict.fromkeys(self.cookies, "0" * 32)
            print(_dim(f"           [session invalidated before chunk {sabotage_at}]"))
        return await original(self, names, canaries=canaries)

    return chunk


async def produce(label: str, sabotage_at: int = 0) -> dict[str, Any]:
    """Build a coordinator against the live router and return one download.

    `sabotage_at` invalidates the session before the nth probe chunk, which is
    exactly what another client logging into the router does to us: the cookie
    stays in place and stops meaning anything. A pass that recovers answers the
    same names as a clean one; a pass that does not loses everything after that
    point and, before this release, published those names as absent.
    """
    from homeassistant.core import HomeAssistant

    options, data, entry_id, title = _credentials()
    entry = _StubEntry(options, data, entry_id, title)
    hass = HomeAssistant("/config")

    async with aiohttp.ClientSession() as session:
        api = ZTERouterAPI(
            session, options["host"], options.get("username"), options["password"]
        )
        # `_StubEntry` carries the four attributes the diagnostics path reads
        # plus the one hook the coordinator registers; it is not a ConfigEntry
        # and cannot be, since building a real one needs a running Home
        # Assistant. The cast states that deliberately rather than widening
        # either signature for a script's benefit.
        entry_as_config = cast("ConfigEntry[Any]", entry)
        coordinator = ZTERouterDataUpdateCoordinator(hass, entry_as_config, api)
        entry.runtime_data = coordinator

        # This mirrors `__init__._async_background_setup` step for step, and
        # must keep mirroring it. The artefact is only evidence about the real
        # download if the state behind it was built the same way: measuring
        # the unauthenticated key set needs a *confirmed logout*, so taking it
        # in the wrong order leaves `measurement_note` reading "not measured:
        # session still active" and the file silently unlike a real one.
        start = datetime.now(UTC)
        await api.try_set_protocol(5)
        await api.login(5)
        await coordinator.async_refresh()

        await api.logout()
        measured = await api.measure_unauthenticated_keys(timeout_sec=20)
        if measured:
            api.unauthenticated_keys = measured
        await api.login(5)
        api.setup_completed = True

        # A cold coordinator does not produce a payload on its first poll.
        # Startup reconciliation defers one cycle to tell a genuine counter
        # reset from a reboot, and on a *paused* entry — `stop_polling`, which
        # the reference instance has set — the deferred poll takes the safe
        # startup bypass and returns `{}`. The live coordinator did that months
        # ago; this one starts cold every time, and a harness that polled once
        # would produce an empty `data` block and call it a download.
        #
        # Measured on the reference MC7010: poll 1 and 2 return nothing, poll 3
        # returns 137 keys with 97 populated, which is what the real download
        # carries. Polled to a payload rather than a fixed count, because the
        # number of deferrals is the coordinator's business and not this
        # script's to encode.
        #
        # `async_force_refresh` is the supported route and what the integration
        # itself calls, but it goes through the debouncer, which needs a running
        # Home Assistant to fire. Nothing here runs one, so the flag is set
        # directly and the refresh awaited — the same two steps, minus the
        # scheduling.
        for _ in range(POLL_ATTEMPTS):
            coordinator._force_refresh_once = True  # noqa: SLF001 - nothing to debounce on
            coordinator.data = await coordinator._async_update_data()  # noqa: SLF001
            if coordinator.data:
                break

        original_chunk = ZTERouterAPI._probe_chunk  # noqa: SLF001
        if sabotage_at:
            ZTERouterAPI._probe_chunk = _sabotaging_chunk(  # type: ignore[method-assign]  # noqa: SLF001
                original_chunk, sabotage_at
            )
        try:
            result = await async_get_config_entry_diagnostics(hass, entry_as_config)
        finally:
            ZTERouterAPI._probe_chunk = original_chunk  # type: ignore[method-assign]  # noqa: SLF001
        elapsed = (datetime.now(UTC) - start).total_seconds()

        with contextlib.suppress(Exception):
            await api.logout()

    result["_elapsed"] = elapsed
    discovery = result.get("discovery", {})
    print(
        f"  {_cyan(label)}  {elapsed:5.1f}s"
        f"  data={result.get('data_populated')}/{len(result.get('data', {}))}"
        f"  answered={discovery.get('mined_names_answered')}"
        f"  canaries={len(discovery.get('canaries', []))}"
        f"  no_session={_note_count(discovery, 'read without a session')}"
        f"  unasked={len(discovery.get('not_reprobed', []))}"
        f"  refused={len(discovery.get('refused', []))}"
    )
    for note in discovery.get("notes", []):
        print(_dim(f"           {note}"))
    return result


def _note_count(discovery: dict[str, Any], phrase: str) -> int:
    """Return the leading number of the first note containing `phrase`.

    The probe already records how many names it had to re-read because the
    canary came back blank — the signature of a session lost mid-pass. It was
    in every download and simply never surfaced, which is why a degraded pass
    looked like a mystery rather than an eviction.
    """
    for note in discovery.get("notes", []):
        if isinstance(note, str) and phrase in note:
            head = note.split(" ", 1)[0]
            if head.isdigit():
                return int(head)
    return 0


def _leaves(obj: Any, path: str = "") -> Any:
    """Yield every scalar leaf in the document as a (path, value) pair."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _leaves(value, f"{path}/{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from _leaves(value, f"{path}/{index}")
    else:
        yield path, obj


def check_shape(result: dict[str, Any], report: Report) -> None:
    """Assert the download carries what a reader needs to judge it."""
    for field in (
        "data",
        "coordinator",
        "discovery",
        "entry",
        "errors",
        "measurement_note",
        "unauthenticated_keys",
    ):
        report.record(field in result, f"[1] top-level `{field}` present")

    report.record(
        not result.get("errors"),
        "[1] no section failed to build",
        str(result.get("errors") or "none"),
    )
    note = result.get("measurement_note")
    report.record(
        isinstance(note, str) and bool(note),
        "[1] measurement_note is a non-empty string",
        repr(note),
    )
    # v3.3.8 published this field without ever assigning it, and two downloads
    # carried `null` while being reported correct. "Not measured" is a valid
    # answer from a device, but not from a run that simply skipped the step.
    report.record(
        isinstance(note, str) and note.startswith("measured:"),
        "[1] the unauthenticated key set was actually measured",
        repr(note),
    )

    # A download whose payload is empty is the case this file is most often
    # requested for, and it is also what a mis-sequenced harness produces. The
    # reference MC7010 answers well over a hundred keys, so an empty `data`
    # here means the run failed to poll, not that the router said nothing.
    payload = result.get("data") or {}
    populated = result.get("data_populated")
    report.record(
        bool(payload),
        "[1] the payload is not empty",
        f"{len(payload)} keys requested",
    )
    report.record(
        isinstance(populated, int) and populated > 0,
        "[1] the payload carries values",
        f"{populated} populated of {len(payload)}",
    )


def check_discovery(result: dict[str, Any], report: Report) -> None:
    """Assert every classified discovery field reached the artefact.

    This is the check the release process was missing. `run_discovery`
    populates each of these on every non-aborted pass, so absence here means
    the field was produced and then dropped on the way out.
    """
    discovery = result.get("discovery", {})
    aborted = any(
        isinstance(n, str) and n.startswith("discovery aborted")
        for n in discovery.get("notes", [])
    )
    report.record(not aborted, "[2] the discovery pass completed")
    if aborted:
        return

    for field in sorted(DISCOVERY_METADATA_PUBLISHED):
        report.record(field in discovery, f"[2] discovery `{field}` published")

    canaries = discovery.get("canaries")
    census = discovery.get("canary_pool") or {}
    report.record(
        isinstance(canaries, list),
        "[2] the pass names the keys that guarded it",
        f"canaries={canaries!r}",
    )
    # An empty list is a legitimate answer and must stay distinguishable from a
    # missing field: a pass that could not guard itself has to say so, because
    # `probed_no_answer` means nothing without it. The census says which of the
    # two causes applied.
    if not canaries:
        report.record(
            bool(census),
            "[2] no canary was available, and the file records why",
            f"{census.get('populated')} populated, "
            f"{census.get('served_without_a_session')} served without a session",
        )
    else:
        report.record(
            census.get("chosen") == len(canaries),
            "[2] the census agrees with the canaries chosen",
            f"chosen={census.get('chosen')} of {census.get('populated')} populated",
        )

    values = discovery.get("values", {})
    verdicts = discovery.get("verdicts", {})
    report.record(
        set(values) == set(verdicts),
        "[2] every value carries a verdict",
        f"{len(values)} values, {len(verdicts)} verdicts",
    )
    report.record(
        not (set(canaries or []) & set(values)),
        "[2] no canary is republished as a discovered value",
    )

    answered = discovery.get("mined_names_answered", 0)
    probed = discovery.get("mined_names_probed", 0)
    report.record(
        answered <= probed,
        "[2] answered never exceeds probed",
        f"{answered} of {probed}",
    )
    # Four outcomes, and a name belongs to exactly one. Answered, asked and
    # silent, asked and declined, and could not be asked are four different
    # claims; a name in two of them asserts something nobody measured.
    outcomes = {
        "answered": set(values),
        "silent": set(discovery.get("probed_no_answer", [])),
        "refused": set(discovery.get("refused", [])),
        "unasked": set(discovery.get("not_reprobed", [])),
    }
    for left, right in combinations(outcomes, 2):
        overlap = outcomes[left] & outcomes[right]
        report.record(
            not overlap,
            f"[2] {left} and {right} are disjoint",
            f"{len(outcomes[left])} {left}, {len(outcomes[right])} {right}"
            + (f", overlap {sorted(overlap)[:3]}" if overlap else ""),
        )


def check_sanitization(result: dict[str, Any], report: Report) -> None:
    """Assert no identifier reached the file unredacted."""
    leaks = [
        f"{path} = {match}"
        for path, value in _leaves(result)
        if isinstance(value, str)
        for match in _RAW_IDENTIFIER.findall(value)
        if match not in _ALLOWED_ADDRESSES
    ]
    report.record(
        not leaks,
        "[3] no unredacted address, MAC or long identifier",
        "; ".join(leaks[:4]) if leaks else "swept clean",
    )


def check_stability(
    first: dict[str, Any], second: dict[str, Any], report: Report
) -> None:
    """Diff two consecutive downloads, ignoring what the device changes itself.

    Two downloads a minute apart caught the v3.3.9-dev4 truncation: they
    differed by 6 kB because one answered 3 names and the other 90, while both
    reported the session alive. Structural equality between consecutive runs is
    the cheapest evidence that a pass is doing the same work every time.
    """
    left = dict(_leaves(first))
    right = dict(_leaves(second))

    report.record(
        set(left) == set(right),
        "[4] both runs produce the same set of fields",
        f"only in first: {sorted(set(left) - set(right))[:3]}, "
        f"only in second: {sorted(set(right) - set(left))[:3]}",
    )

    structural = [
        path
        for path in set(left) & set(right)
        if left[path] != right[path] and not _VOLATILE.search(path)
    ]
    report.record(
        not structural,
        "[4] no structural difference between the two runs",
        "; ".join(f"{p}: {left[p]!r} vs {right[p]!r}" for p in structural[:4])
        if structural
        else "differences are radio and counter drift only",
    )

    # Not "nothing unasked": a handful of names fail their own request
    # repeatedly on the reference MC7010 and are honestly unresolvable. What
    # matters is that they stay a rounding error and stay reported — a pass
    # that starts leaving hundreds unasked has a problem, and one that reports
    # them as absent instead has a worse one.
    discovery = first.get("discovery", {})
    unasked = len(discovery.get("not_reprobed", []))
    probed = max(discovery.get("mined_names_probed") or 1, 1)
    report.record(
        unasked / probed < UNASKED_PROPORTION_LIMIT,
        "[4] unasked names are a small fraction of those probed",
        f"{unasked} of {probed}",
    )

    for field in (
        "mined_names_answered",
        "mined_names_probed",
        "names_from_union_only",
    ):
        one = first.get("discovery", {}).get(field)
        two = second.get("discovery", {}).get(field)
        report.record(one == two, f"[4] `{field}` is stable", f"{one} then {two}")

    # Read from the notes rather than diffed as text: these two are the numbers
    # that separate a healthy pass from one that lost a session, and a pass
    # that silently starts losing them is the regression this mode exists for.
    # Not "names re-probed singly": that count follows how many chunks came
    # back blank, which follows the device's own live values, so it varies
    # legitimately between two passes a minute apart — measured at 198 and 190.
    # The counts below do not.
    one = _note_count(first.get("discovery", {}), "declined by the router")
    two = _note_count(second.get("discovery", {}), "declined by the router")
    report.record(
        one == two, "[4] names declined by the router is stable", f"{one} then {two}"
    )

    # Not an equality check on names read without a session. A session lost
    # partway is an environmental event — another client taking the router's
    # single session, or a chunk timing out — and asserting two runs saw the
    # same number of them tests the environment rather than this code. Measured
    # over six spaced passes: one reported eight, five reported none, and all
    # six answered the same 99 names with nothing left unestablished.
    #
    # The property that matters is that the pass survives it, which is what
    # this asserts.
    for label, download in (("first", first), ("second", second)):
        discovery = download.get("discovery", {})
        lost = _note_count(discovery, "read without a session")
        if lost:
            report.record(
                not discovery.get("not_reprobed"),
                f"[4] the {label} run recovered from losing its session",
                f"{lost} names read without a session, "
                f"{len(discovery.get('not_reprobed', []))} left unestablished",
            )


def _save(result: dict[str, Any], label: str, title: str) -> pathlib.Path:
    """Write a download to the untracked local folder, the way HA names them."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    target = OUTPUT_DIR / f"diag_check_{stamp}_{label}.json"
    target.write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return target


async def survey(runs: int, gap: int) -> int:
    """Run the pass repeatedly and report the spread of what it answered.

    A rate on its own says how often something goes wrong, not what. So each
    pass also reports how many names it had to re-read because the canary came
    back blank: that count is the difference between "this firmware does not
    report these names" and "we were not logged in for part of the pass".

    The router permits one session, so anything else logging into it — a live
    Home Assistant polling on its own schedule — evicts this pass midway. That
    is a property of the environment, not of the download, and this mode exists
    to measure it rather than argue about it.
    """
    print(f"survey: {runs} passes, {gap}s apart\n")
    rows: list[tuple[int, float, int, int, int]] = []
    for index in range(1, runs + 1):
        result = await produce(f"pass {index}")
        discovery = result.get("discovery", {})
        rows.append(
            (
                index,
                float(result.get("_elapsed", 0.0)),
                int(discovery.get("mined_names_answered") or 0),
                _note_count(discovery, "read without a session"),
                _note_count(discovery, "queued for re-probe"),
            )
        )
        if index < runs:
            await asyncio.sleep(gap)

    best = max(row[2] for row in rows)
    degraded = [row for row in rows if row[2] < best]
    print("\nsummary")
    print(f"  best pass answered      : {best}")
    print(f"  degraded passes         : {len(degraded)} of {len(rows)}")
    if degraded:
        print(f"  degraded answered       : {sorted(row[2] for row in degraded)}")
        print(
            "  no-session names, healthy vs degraded: "
            f"{sorted(row[3] for row in rows if row[2] == best)} vs "
            f"{sorted(row[3] for row in degraded)}"
        )
    # Reported, never asserted. A survey measures; it is not a pass/fail gate,
    # and returning failure here would make a rate look like a verdict.
    return 0


async def sabotage_check(gap: int) -> int:
    """Take the session away mid-pass and require the pass to answer anyway.

    The unit suite cannot falsify this: a mock is written from the model, so a
    test built on a wrong belief about the device passes while the code is
    broken. This takes a real session away from a real router at a real point
    in a real pass.
    """
    report = Report()
    print("clean pass")
    clean = await produce("clean")
    await asyncio.sleep(gap)
    print("\nsabotaged pass")
    harmed = await produce("sabotaged", sabotage_at=5)

    clean_names = set(clean["discovery"].get("values", {}))
    harmed_names = set(harmed["discovery"].get("values", {}))
    lost = clean_names - harmed_names

    report.record(
        len(harmed_names) >= len(clean_names) * SABOTAGE_RECOVERY_FLOOR,
        "[5] a pass that lost its session still answers",
        f"{len(harmed_names)} against {len(clean_names)} clean, "
        f"{len(lost)} not seen again",
    )
    notes = harmed["discovery"].get("notes", [])
    report.record(
        any("re-established" in note for note in notes),
        "[5] the pass recorded re-establishing the session",
        next((n for n in notes if "re-established" in n), "no such note"),
    )
    report.record(
        not (
            set(harmed["discovery"].get("probed_no_answer", []))
            & set(harmed["discovery"].get("not_reprobed", []))
        ),
        "[5] the sabotaged pass still separates silent from unasked",
    )

    total = len(report.checks)
    passed = total - report.failed
    if report.failed:
        print(_red(f"\n✖  Sabotage check: FAILED  ({passed}/{total} passed)"))
    else:
        print(_green(f"\n✔  Sabotage check: PASSED  ({passed}/{total})"))
    return 1 if report.failed else 0


async def main() -> int:
    """Produce the artefact, check it, and return a shell exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="produce one download instead of two; skips the stability diff",
    )
    parser.add_argument(
        "--survey",
        type=int,
        metavar="N",
        help=(
            "run N passes with a gap between them and report the spread, "
            "instead of checking one artefact. For measuring how often a pass "
            "comes back degraded, and whether the degraded ones lost a session."
        ),
    )
    parser.add_argument(
        "--gap",
        type=int,
        default=SURVEY_GAP_SECONDS,
        metavar="SECONDS",
        help=(
            "seconds between survey passes (default %(default)s). Use a gap "
            "longer than the competing poll interval to test one pass in "
            "isolation."
        ),
    )
    parser.add_argument(
        "--sabotage",
        action="store_true",
        help=(
            "run a clean pass and a pass whose session is invalidated partway, "
            "and require both to answer the same names"
        ),
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="also write the downloads to .notes/local_only/diag_dl/",
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

    if args.survey:
        return await survey(args.survey, args.gap)

    if args.sabotage:
        return await sabotage_check(args.gap)

    report = Report()
    print("producing diagnostics against the live router")
    first = await produce("run 1")

    print("\nthe artefact")
    check_shape(first, report)
    check_discovery(first, report)
    check_sanitization(first, report)

    if not args.once:
        # The pass logs out and back in, and the reference hardware refused a
        # request once when one immediately followed another. The wait costs
        # nothing here and removes a source of noise from the diff.
        await asyncio.sleep(5)
        second = await produce("run 2")
        print("\ntwo runs compared")
        check_stability(first, second, report)
        if args.keep:
            print(f"\nsaved -> {_save(second, 'run2', first['entry']['title'])}")

    if args.keep:
        print(f"saved -> {_save(first, 'run1', first['entry']['title'])}")

    total = len(report.checks)
    passed = total - report.failed
    if report.failed:
        print(_red(f"\n✖  Diagnostics check: FAILED  ({passed}/{total} passed)"))
    else:
        print(_green(f"\n✔  Diagnostics check: PASSED  ({passed}/{total})"))
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
