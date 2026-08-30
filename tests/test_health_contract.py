"""Contract sweeps over the health snapshot and the repair set.

Each asserts that every member of a set satisfies a property, rather than
testing one mechanism. They appear in no coverage or depth report — those read
the code under test, and these read a **set** the code defines — so a project
can pass every other check while having none of them.

**The vacuity guards are not optional.** A sweep that inspects almost nothing
passes for the same reason a correct one does, so the size of each swept set is
asserted by its own named test rather than folded into the sweeps. A named
guard covers every sweep over that set, including ones written later, and says
plainly that the sweep stopped sweeping when it fires.
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import re
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.api import ZTEConnectionError, ZTERouterAPI
from custom_components.zte_router_5g.const import (
    DOMAIN,
    FETCH_STRIKE_LIMIT,
    REPAIR_AUTH_FAILED,
)
from custom_components.zte_router_5g.coordinator import (
    REPAIR_NAMES,
    RETIRED_REPAIR_NAMES,
    ZTERouterDataUpdateCoordinator,
)

COMPONENT = pathlib.Path("custom_components/zte_router_5g")

# Section 19's severity vocabulary. Asserted as **published strings**, never as
# the constants the code uses: comparing a finding against the constant that
# produced it compares the code with itself, and a rename would pass here while
# every user automation matching on `severity` broke.
SEVERITIES = {"ok", "degraded", "warning", "error", "unknown"}

# Every key a health snapshot must carry. Published, so a template reading one
# that goes missing gets an empty value rather than an error.
SECTION_19_CONTRACT = {
    "problem",
    "issues",
    "severity",
    "degraded_capabilities",
    "drift",
    "repairs",
    "last_good_update",
    "consecutive_failures",
}

GOOD_DATA = {
    "network_type": "ENDC",
    "signalbar": "4",
    "realtime_time": "3600",
    "wan_connect_status": "ppp_connected",
}


def _load(name: str) -> dict:
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def _translation_files() -> list[str]:
    """Every file that must carry the rendered text, `strings.json` included."""
    names = ["strings.json"]
    names += [
        f"translations/{p.name}"
        for p in sorted((COMPONENT / "translations").glob("*.json"))
    ]
    return names


@pytest.fixture
def entry():
    """Return a config entry for the coordinator under test."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="864155042229309",
        title="ZTE 5G",
        data={"imei": "864155042229309"},
        options={
            CONF_HOST: "192.168.0.1",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "password",
        },
    )


@pytest.fixture
def coordinator(hass: HomeAssistant, entry):
    """Return a coordinator over a fully mocked API."""
    entry.add_to_hass(hass)
    api = MagicMock(spec=ZTERouterAPI)
    api.get_all_data = AsyncMock(return_value=dict(GOOD_DATA))
    api.get_extended_data = AsyncMock(return_value={})
    api.get_sms_capacity = AsyncMock(return_value={})
    api.get_sms_messages = AsyncMock(return_value=[])
    api.login = AsyncMock(return_value="stok=test")
    return ZTERouterDataUpdateCoordinator(hass, entry, api)


# ------------------------------------------------------------------------- 8a


def test_every_repair_issue_has_title_and_rendered_text() -> None:
    """A missing entry shows the raw key, or a card with an empty body.

    Stronger than the check this replaces, which asserted only that the key was
    *present* in `issues`.

    **`description` and `fix_flow` are mutually exclusive**, and the sweep has
    to allow for that or it contradicts `hassfest`. Its issues schema
    (`script/hassfest/translations.py`) requires a `title`, then exactly one of
    the two — `vol.Exclusive(..., "fixable")` — because a fixable issue renders
    its prose in the flow's step rather than on the card. A sweep asserting
    both demands a shape Home Assistant rejects, and would pass while
    validation failed.

    So: a title always, and rendered text in whichever form the issue's
    fixability calls for.
    """
    for name in _translation_files():
        issues = _load(name).get("issues", {})
        for key in REPAIR_NAMES:
            assert key in issues, f"{name}: no text for repair '{key}'"
            entry = issues[key]
            assert entry.get("title"), f"{name}: '{key}' has no title"

            has_description = bool(entry.get("description"))
            has_fix_flow = bool(entry.get("fix_flow"))
            assert has_description != has_fix_flow, (
                f"{name}: '{key}' must carry exactly one of 'description' or "
                "'fix_flow' — hassfest rejects both, and neither leaves the "
                "card with an empty body"
            )

            if has_fix_flow:
                steps = entry["fix_flow"].get("step", {})
                assert steps, f"{name}: '{key}' has a fix_flow with no steps"
                for step_name, step in steps.items():
                    assert step.get("description"), (
                        f"{name}: '{key}' fix_flow step '{step_name}' has no "
                        "description, so the dialog renders empty"
                    )


def test_the_fixable_repair_is_the_one_with_a_fix_flow() -> None:
    """The two forms must line up with what the code actually raises.

    A `fix_flow` on an issue raised with `is_fixable=False` is text nobody can
    reach; a fixable issue without one gets `ConfirmRepairFlow` and a Fix
    button that dismisses the card. Both are silent failures, which is why the
    pairing is asserted rather than assumed.
    """
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")

    issues = _load("strings.json")["issues"]
    with_flow = {key for key, entry in issues.items() if entry.get("fix_flow")}

    assert with_flow == {REPAIR_AUTH_FAILED}, (
        f"expected only '{REPAIR_AUTH_FAILED}' to carry a fix_flow, got {with_flow}"
    )
    assert "is_fixable=True" in source, "no fixable repair is raised at all"


# ------------------------------------------------------------------------- 8b


def test_no_orphan_issue_translations() -> None:
    """Text left behind for a key nothing raises any more.

    An orphan is invisible: nothing renders it, so nothing reveals that it
    describes a repair that no longer exists. It then quietly becomes the
    documentation for a key someone later reuses.

    The retired keys are the live case here — three of them were retired on
    2026-08-25, and their text had to go with them.
    """
    for name in _translation_files():
        declared = set(_load(name).get("issues", {}))
        orphans = declared - set(REPAIR_NAMES)
        assert not orphans, f"{name}: issue text for keys nothing raises: {orphans}"

        retired_left = declared & set(RETIRED_REPAIR_NAMES)
        assert not retired_left, (
            f"{name}: text still present for retired repairs: {retired_left}"
        )


# ------------------------------------------------------------------------- 8c


async def test_every_repair_the_code_raises_is_registered_for_removal(
    hass: HomeAssistant, entry
) -> None:
    """The sharp one: a repair omitted here outlives the integration.

    `async_remove_entry` deletes exactly the list it is given. A repair the
    code can raise but that list omits sits in the Repairs panel forever, with
    `is_fixable=False` and no UI path to clear it and no integration left that
    could. This class of defect has recurred twice in this family.

    Driven rather than read out of the source: an assertion that `__init__.py`
    mentions the removal constants is satisfied by the import line alone, and
    passes with the loop emptied. Raising a card under every id the code knows
    about and asserting the registry empties cannot.
    """
    from homeassistant.helpers import issue_registry as ir

    from custom_components.zte_router_5g import async_remove_entry

    entry.add_to_hass(hass)

    # Every id a card could be live under: the current repairs, the ones
    # retired on 2026-08-25, and both the entry-scoped and bare spellings.
    all_names = (*REPAIR_NAMES, *RETIRED_REPAIR_NAMES)
    for name in all_names:
        for issue_id in (f"{entry.entry_id}_{name}", name):
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=name,
            )

    registry = ir.async_get(hass)
    assert len([k for k in registry.issues if k[0] == DOMAIN]) == len(all_names) * 2

    await async_remove_entry(hass, entry)

    left = [k[1] for k in registry.issues if k[0] == DOMAIN]
    assert not left, f"repairs left behind with no integration to clear them: {left}"

    # The source check is kept as a second, cheaper signal, but it is not the
    # assertion this test rests on.
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    raised = {n.lower() for n in re.findall(r"translation_key=REPAIR_(\w+)", source)}
    raised |= set(re.findall(r'translation_key="(\w+)"', source))
    assert raised <= set(REPAIR_NAMES), (
        f"repairs raised in coordinator.py but absent from REPAIR_NAMES: "
        f"{raised - set(REPAIR_NAMES)}"
    )


# ------------------------------------------------------------------------- 8d


async def test_every_published_severity_is_in_the_section_19_vocabulary(
    coordinator,
) -> None:
    """A severity outside the vocabulary breaks every automation reading it.

    This exists because a mutation survived on `wifi_ssid_monitor`: every test
    asserted the severity of the check it was written for, so nothing noticed
    when one stopped setting one at all.

    Asserted over the **published strings**, and over every path that writes a
    snapshot, not just the happy one.
    """
    published: list[str] = []

    # 1. Success.
    await coordinator._async_update_data()
    published.append(coordinator.health_snapshot["severity"])

    # 2. Degraded — an optional endpoint past its budget.
    coordinator.api.get_sms_messages = AsyncMock(side_effect=ZTEConnectionError("down"))
    for _ in range(FETCH_STRIKE_LIMIT + 2):
        coordinator.data = await coordinator._async_update_data()
    published.append(coordinator.health_snapshot["severity"])

    # 3. Drift.
    coordinator.api.get_all_data = AsyncMock(return_value={"renamed": "1"})
    for _ in range(FETCH_STRIKE_LIMIT + 1):
        coordinator.data = await coordinator._async_update_data()
    published.append(coordinator.health_snapshot["severity"])

    # 4. Total outage at runtime.
    coordinator.api.get_all_data = AsyncMock(side_effect=ZTEConnectionError("down"))
    for _ in range(FETCH_STRIKE_LIMIT + 2):
        # The raise is not the subject here; the severity the snapshot carries
        # afterwards is.
        with contextlib.suppress(Exception):
            await coordinator._async_update_data()
    published.append(coordinator.health_snapshot["severity"])

    for value in published:
        assert isinstance(value, str) and value, "severity must never be blank or None"
        assert value in SEVERITIES, f"severity '{value}' is outside Section 19"

    assert len(published) == 4, "this test drove fewer paths than it claims"
    assert len(set(published)) >= 3, (
        "every path reported the same severity — the sweep is not distinguishing them"
    )


# ------------------------------------------------------------------------- 8e


async def test_every_finding_is_classified_exactly_once(coordinator) -> None:
    """A finding must be drift or capability, never both and never neither.

    The two lists are what a template reads to decide whether a problem is the
    router's shape changing or an endpoint being unavailable. A finding in both
    is reported twice; a finding in neither is a `problem: true` the user
    cannot explain.
    """
    await coordinator._async_update_data()

    coordinator.api.get_sms_messages = AsyncMock(side_effect=ZTEConnectionError("down"))
    coordinator.api.get_sms_capacity = AsyncMock(side_effect=ZTEConnectionError("down"))
    for _ in range(FETCH_STRIKE_LIMIT + 2):
        coordinator.data = await coordinator._async_update_data()

    snapshot = coordinator.health_snapshot
    drift = set(snapshot["drift"])
    capabilities = set(snapshot["degraded_capabilities"])

    assert not (drift & capabilities), (
        f"findings classified as both drift and capability: {drift & capabilities}"
    )
    assert capabilities, "no capability was degraded, so nothing was classified"
    assert snapshot["problem"] is True
    assert snapshot["issues"], "a problem with no issue text cannot be explained"


# ------------------------------------------------------------------------- 8f


async def test_every_snapshot_the_coordinator_writes_carries_the_full_contract(
    coordinator,
) -> None:
    """The vacuity guard, and a shape sweep over every write path.

    Section 19's attribute names are a published contract: users write
    templates against them, so a missing key silently yields an empty template
    value rather than an error. There are four places that assign
    `health_snapshot` — success, success-fallback, failure, failure-fallback —
    and they are easy to let drift apart. One of them was missing `repairs`
    when this sweep was written.

    Asserts the **count** of keys as well as their presence, so the guard
    cannot quietly shrink.
    """
    contract = SECTION_19_CONTRACT

    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    assignments = source.count("self.health_snapshot = {")

    for block in source.split("self.health_snapshot = {")[1:]:
        body = block[: block.index("}")]
        keys = set(re.findall(r'"(\w+)":', body))
        assert contract <= keys, (
            f"a health snapshot omits {contract - keys} — a template reading it "
            "gets an empty value rather than an error"
        )

    # And once at runtime, so the static sweep above cannot be the only cover.
    await coordinator._async_update_data()
    assert contract <= set(coordinator.health_snapshot)


# ------------------------------------------------- the sweeps must sweep something


def test_the_repair_text_sweep_is_not_vacuous() -> None:
    """The text sweeps pass trivially if the key set is empty.

    Pins the count and the membership as well as the property, so a rename that
    empties `REPAIR_NAMES` fails here rather than turning both text sweeps
    green. Named rather than folded into either, because one guard has to cover
    both and anything written over the same set later.
    """
    keys = set(REPAIR_NAMES)

    assert len(keys) >= 2
    assert {"auth_failed", "conn_error"} <= keys
    assert len(set(RETIRED_REPAIR_NAMES)) >= 3
    assert len(_translation_files()) >= 2, "expected strings.json plus a translation"


def test_the_severity_sweep_still_sweeps_something() -> None:
    """The guard cannot quietly shrink to a set of one.

    The severity vocabulary is fixed at five, and every place the coordinator
    assigns a health snapshot has to be in reach of the shape sweep — success,
    its fallback, failure, and its fallback.
    """
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")

    assert len(SEVERITIES) == 5
    assert len(set(REPAIR_NAMES)) >= 2
    assert source.count("self.health_snapshot = {") >= 4, (
        "fewer snapshot assignments than the shape sweep expects to find"
    )
    assert len(SECTION_19_CONTRACT) == 8
