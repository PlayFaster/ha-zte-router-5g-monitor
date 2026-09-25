"""Which names each poll asks for: `poll_plan.PollPlan` (3.4.4-dev2)."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from custom_components.zte_router_5g import api
from custom_components.zte_router_5g.poll_plan import (
    ALWAYS_POLLED,
    FULL_POLL_EVERY,
    ROTATION,
    PollPlan,
    RecordingDict,
    is_5g_mode,
    is_5g_name,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)

# Two entities: one reading a value under two spellings, one reading a name
# that never answers. Plus an internal name and one no entity reads.
UNIVERSE = ["lte_rsrp", "network_lte_rsrp", "never_answers", "network_type", "orphan"]


def _rsrp(data: Any) -> Any:
    return data.get("lte_rsrp") or data.get("network_lte_rsrp") or None


def _never(data: Any) -> Any:
    return data.get("never_answers") or None


READERS = [("e_rsrp", (_rsrp,)), ("e_never", (_never,))]
DATA = {
    "lte_rsrp": "-97",
    "network_lte_rsrp": "",
    "never_answers": "",
    "network_type": "ENDC",
}


def _learned() -> PollPlan:
    """A plan after its first, full, poll."""
    plan = PollPlan(UNIVERSE)
    names, full = plan.names(NOW)
    assert names is not None
    assert full
    plan.learn_readers(READERS, DATA)
    plan.learn_answers(READERS, DATA)
    plan.after_poll(DATA, full=True, fresh=True, now=NOW)
    return plan


def test_the_first_poll_with_nothing_learned_is_full() -> None:
    """Everything answering at setup resolves at once."""
    names, full = PollPlan(UNIVERSE).names(NOW)
    assert full
    assert names == frozenset(UNIVERSE)


def test_a_narrowed_poll_drops_the_unanswered_spelling_of_a_resolved_value() -> None:
    """`network_lte_rsrp` never answered and `lte_rsrp` did."""
    names, full = _learned().names(NOW)
    assert not full
    assert names is not None
    assert "lte_rsrp" in names
    assert "network_lte_rsrp" not in names


def test_internal_and_unowned_names_are_always_asked() -> None:
    """`network_type` is read by the session checks; `orphan` by no entity seen."""
    names, _ = _learned().names(NOW)
    assert names is not None
    assert {"network_type", "orphan"} <= names


def test_an_unresolved_name_is_asked_one_poll_in_five() -> None:
    """Rotation bounds the cost of names that never answer."""
    plan = _learned()
    asked = 0
    for _ in range(ROTATION):
        names, full = plan.names(NOW)
        assert not full
        assert names is not None
        asked += "never_answers" in names
        plan.after_poll(DATA, full=False, fresh=True, now=NOW)
    assert asked == 1


def test_a_name_only_disabled_entities_read_is_not_asked_even_on_a_full_poll() -> None:
    """Enabling the entity reloads the entry, which rebuilds the plan."""
    plan = _learned()
    plan.disabled = {"e_rsrp"}
    plan.request_full("test")
    names, full = plan.names(NOW)
    assert full
    assert names is not None
    assert "lte_rsrp" not in names


def test_every_thirtieth_poll_is_full() -> None:
    """The full poll that heals a wrong resolution."""
    plan = _learned()
    kinds = []
    for _ in range(FULL_POLL_EVERY):
        _, full = plan.names(NOW)
        kinds.append(full)
        plan.after_poll(DATA, full=full, fresh=True, now=NOW)
    assert kinds.count(True) == 1
    assert kinds[-1]


def test_a_day_without_a_full_poll_owes_one() -> None:
    """At least daily, whatever the interval."""
    plan = _learned()
    _, full = plan.names(NOW + timedelta(hours=25))
    assert full


def test_an_owed_full_poll_stays_owed_until_one_succeeds_fresh() -> None:
    """A full poll served from the cache, or one that failed, does not count."""
    plan = _learned()
    plan.request_full("refresh now")
    plan.after_poll(DATA, full=True, fresh=False, now=NOW)
    assert plan.names(NOW)[1]
    plan.after_poll(DATA, full=True, fresh=True, now=NOW)
    assert not plan.names(NOW)[1]


def test_a_placeholder_its_entity_rejects_does_not_resolve() -> None:
    """A value the entity reads as nothing is not an answer."""

    def rejects(data: Any) -> Any:
        data.get("never_answers")
        return None

    plan = PollPlan(UNIVERSE)
    plan.learn_readers([("e_never", (rejects,))], {})
    plan.learn_answers([("e_never", (rejects,))], {"never_answers": "--"})
    assert "never_answers" not in plan.answered


def test_stored_names_make_the_first_poll_after_a_restart_narrowed() -> None:
    """The store holds what answered and the firmware it answered on."""
    plan = _learned()
    stored = plan.to_store("FW1")
    restarted = PollPlan(UNIVERSE)
    assert restarted.load(stored) == "FW1"
    restarted.learn_readers(READERS, {})
    names, full = restarted.names(NOW)
    assert not full
    assert names is not None
    assert "network_lte_rsrp" not in names


def test_a_malformed_store_is_ignored() -> None:
    """Nothing loaded, and the first poll stays full."""
    plan = PollPlan(UNIVERSE)
    assert plan.load({"answered": "x"}) == ""
    assert plan.names(NOW)[1]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ENDC", True),
        ("EN-DC", True),
        ("LTE-NSA", False),
        ("LTE", False),
        ("", False),
        ("SA", True),
    ],
)
def test_the_5g_canary_reads_network_type(value: str, expected: bool) -> None:
    """`LTE-NSA` is LTE although its name carries NSA; an unseen value may be 5G."""
    assert is_5g_mode(value) is expected


def test_an_lte_to_5g_change_asks_every_unresolved_5g_name_next_poll() -> None:
    """No rotation delay for 5G values when 5G attaches."""
    universe = ["Z5g_rsrp", "network_type"]
    readers = [("e5g", (lambda d: d.get("Z5g_rsrp") or None,))]
    plan = PollPlan(universe)
    lte = {"network_type": "LTE-NSA", "Z5g_rsrp": ""}
    plan.learn_readers(readers, lte)
    plan.learn_answers(readers, lte)
    plan.after_poll(lte, full=True, fresh=True, now=NOW)
    plan.after_poll({"network_type": "ENDC"}, full=False, fresh=True, now=NOW)
    names, _ = plan.names(NOW)
    assert names is not None
    assert "Z5g_rsrp" in names
    assert is_5g_name("network_Z5g_rsrp")
    assert not is_5g_name("lte_rsrp")


def test_a_recording_dict_records_every_read() -> None:
    """`get`, indexing and membership are all reads."""
    payload = RecordingDict({"a": 1})
    payload.get("b")
    _ = payload["a"]
    assert "c" not in payload
    assert payload.reads == {"a", "b", "c"}


def test_a_reader_that_raises_still_records_its_reads() -> None:
    """A read before the fault is still a read."""

    def broken(data: Any) -> Any:
        data.get("lte_rsrp")
        raise ValueError

    plan = PollPlan(UNIVERSE)
    plan.learn_readers([("e", (broken,))], {})
    plan.learn_answers([("e", (broken,))], DATA)
    assert plan.consumers["lte_rsrp"] == {"e"}
    assert "lte_rsrp" not in plan.answered


def test_the_summary_counts_what_the_plan_holds() -> None:
    """Published in the diagnostics download."""
    plan = _learned()
    plan.disabled = {"e_never"}
    summary = plan.summary()
    assert summary["answered"] == 2
    assert summary["skipped_disabled"] == 1
    assert summary["last_kind"] == "full"


# ---------------------------------------------------------------------------
# Widened aliases
# ---------------------------------------------------------------------------


def test_widening_keeps_the_known_spellings_first() -> None:
    """A router answering a known spelling reads exactly as before."""
    widened = api.widen_aliases(("Z5g_rsrp", "5g_rsrp", "nr5g_rsrp"))
    assert widened[:3] == ("Z5g_rsrp", "5g_rsrp", "nr5g_rsrp")
    assert "Nr_rsrp" in widened
    assert api.widen_aliases(("imei",)) == ("imei",)


@pytest.mark.parametrize(
    ("name", "family"),
    [
        ("Z5g_rsrp", "5g:rsrp"),
        ("nr5g_SINR", "5g:sinr"),
        ("network_Z5g_rsrp", "5g:rsrp"),
        ("network_lte_rsrp", "lte_rsrp"),
        ("flux_total_time", "total_time"),
    ],
)
def test_the_spelling_family_ignores_the_prefix(name: str, family: str) -> None:
    """One value, whatever the prefix."""
    assert api.spelling_family(name) == family


def test_every_widened_name_is_in_the_poll_universe() -> None:
    """A spelling in a tuple that no poll asks for can never answer."""
    assert set(api._WIDENED_PARAMS) <= set(api.POLL_UNIVERSE)


# ---------------------------------------------------------------------------
# Internal reads
# ---------------------------------------------------------------------------

_INTERNAL_MODULES = (
    "coordinator.py",
    "observations.py",
    "__init__.py",
    "helpers.py",
    "api.py",
    "const.py",
    "binary_sensor.py",
)


def test_every_internal_read_is_always_polled() -> None:
    """A name read outside a description must never be dropped from a poll.

    Scans the modules that read the payload directly for string constants that
    are poll names, outside the poll lists themselves.
    """
    package = Path(api.__file__).parent
    universe = set(api.POLL_UNIVERSE)
    missing: dict[str, list[str]] = {}
    for module in _INTERNAL_MODULES:
        tree = ast.parse((package / module).read_text(encoding="utf-8"))
        skip: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign | ast.AnnAssign):
                target = (
                    node.targets[0] if isinstance(node, ast.Assign) else node.target
                )
                if isinstance(target, ast.Name) and target.id in (
                    "_CORE_PARAMS",
                    "_EXTENDED_PARAMS",
                ):
                    skip |= {id(child) for child in ast.walk(node)}
        names = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in universe
            and id(node) not in skip
        }
        gap = sorted(names - ALWAYS_POLLED)
        if gap:
            missing[module] = gap
    assert not missing, missing


def test_the_sensor_attribute_reads_are_always_polled() -> None:
    """Sensor attributes read the SMS counters outside `value_fn`."""
    source = (Path(api.__file__).parent / "sensor.py").read_text(encoding="utf-8")
    start = source.index("def extra_state_attributes")
    names = {n for n in api.POLL_UNIVERSE if f'"{n}"' in source[start : start + 6000]}
    assert names <= ALWAYS_POLLED, sorted(names - ALWAYS_POLLED)


def test_a_membership_test_on_a_non_string_is_not_a_read() -> None:
    """Only names are recorded."""
    payload = RecordingDict()
    assert 1 not in payload
    assert payload.reads == set()


async def test_an_extended_batch_with_nothing_asked_sends_nothing() -> None:
    """A narrowed poll can leave the extended half empty."""
    from unittest.mock import AsyncMock, MagicMock

    client = MagicMock(spec=api.ZTERouterAPI)
    client._write_lock = __import__("asyncio").Lock()
    client._batch_get = AsyncMock()
    result = await api.ZTERouterAPI.get_extended_data(
        client, frozenset({"not_extended"})
    )
    assert result == {}
    client._batch_get.assert_not_awaited()
