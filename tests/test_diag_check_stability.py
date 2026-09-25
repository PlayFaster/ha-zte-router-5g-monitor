"""The two-run comparison in `scripts/diag_check.py`.

`check_stability` compares two consecutive diagnostics downloads and reports
any difference the device itself cannot explain. Two of its inputs are not
comparable across files and were being compared anyway, so a pass that lost
and re-established its session failed both halves of the check while doing
exactly what it was supposed to do.

Reproducing that needs a session loss, which is an environmental event nobody
can schedule. These tests drive the comparison directly with the two shapes
that caused it instead.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.diag_check import Report, check_stability, unanswered_files, unasked_count


def _artefact(
    notes: list[str],
    values: dict[str, Any],
    *,
    session: str = "fresh login",
) -> dict[str, Any]:
    """Build the part of a download that `check_stability` reads."""
    return {
        "discovery": {
            "notes": notes,
            "values": values,
            "session": session,
            "mined_names_answered": 99,
            "mined_names_probed": 612,
            "names_from_union_only": 104,
            "refused": ["tr069_ServerURL"],
            "probed_no_answer": ["a", "b"],
            "not_reprobed": [],
        },
        "data_populated": 108,
    }


def _outcome(report: Report, name: str) -> bool:
    """Return whether the named check passed."""
    return next(ok for ok, label, _ in report.checks if name in label)


# ---------------------------------------------------------------------------
# What must be tolerated
# ---------------------------------------------------------------------------


def test_a_pass_that_emits_extra_notes_is_not_a_difference() -> None:
    """Re-establishing a session adds notes a clean pass never writes.

    The notes are a free-text list compared by position, so a longer list
    reads as extra fields unless it is excluded. It carries no assertion of
    its own — the counts inside it are checked directly elsewhere.
    """
    values = {"lan_netmask": "ip-1"}
    first = _artefact(["mined 612 names"], values)
    second = _artefact(
        ["mined 612 names", "session re-established", "8 names re-probed"],
        values,
    )
    report = Report()

    check_stability(first, second, report)

    assert _outcome(report, "same set of fields")


def test_notes_differing_in_text_are_not_a_structural_difference() -> None:
    """Two passes re-probe singly over a different number of rounds.

    Measured 2026-09-25 on 3.4.4-dev1: one pass wrote "758 names re-probed
    singly over 3 rounds, resolving 2" and the other "over 2 rounds, resolving
    1". Compared as a set, the notes list is one leaf, and the structural check
    reported it although the field-set check already excluded it.
    """
    values = {"lan_netmask": "ip-1"}
    first = _artefact(["758 names re-probed singly over 3 rounds, resolving 2"], values)
    second = _artefact(
        ["758 names re-probed singly over 2 rounds, resolving 1"], values
    )
    report = Report()

    check_stability(first, second, report)

    assert _outcome(report, "no structural difference")


def test_renumbered_pseudonyms_are_not_a_difference() -> None:
    """Tokens are allocated in first-seen order and only within one download.

    A pass that reads its keys in a different order renumbers every token
    after the first divergence, so three unchanged values come back as a
    permutation. This is the exact set observed failing.
    """
    first = _artefact(
        [],
        {
            "lan_netmask": "ip-5",
            "prefer_dns_auto": "ip-6",
            "standby_dns_auto": "ip-7",
        },
    )
    second = _artefact(
        [],
        {
            "lan_netmask": "ip-7",
            "prefer_dns_auto": "ip-5",
            "standby_dns_auto": "ip-6",
        },
    )
    report = Report()

    check_stability(first, second, report)

    assert _outcome(report, "no structural difference")


@pytest.mark.parametrize("kind", ["ip", "cell", "mac", "phone"])
def test_every_token_kind_is_renumbering_tolerant(kind: str) -> None:
    """All four pseudonym prefixes are allocated the same way."""
    first = _artefact([], {"key": f"{kind}-1"})
    second = _artefact([], {"key": f"{kind}-4"})
    report = Report()

    check_stability(first, second, report)

    assert _outcome(report, "no structural difference")


# ---------------------------------------------------------------------------
# What must still fail
# ---------------------------------------------------------------------------


def test_a_token_changing_kind_is_a_difference() -> None:
    """Only the number is unstable across files. The kind is not.

    Without this the tolerance would swallow a sanitizer routing a value
    through the wrong classifier, which is the fault the token scheme exists
    to make visible.
    """
    first = _artefact([], {"key": "ip-1"})
    second = _artefact([], {"key": "cell-1"})
    report = Report()

    check_stability(first, second, report)

    assert not _outcome(report, "no structural difference")


def test_a_field_present_in_one_run_only_is_a_difference() -> None:
    """The field-set check still does its job outside the notes list."""
    first = _artefact([], {"lan_netmask": "ip-1"})
    second = _artefact([], {"lan_netmask": "ip-1", "surprise": "value"})
    report = Report()

    check_stability(first, second, report)

    assert not _outcome(report, "same set of fields")


def test_the_derived_usage_figures_are_allowed_to_move() -> None:
    """They are the byte counters and their clocks under another name.

    Two passes twenty seconds apart differ in every one of them, which is the
    device living its life rather than the download changing shape.
    """
    first = _artefact([], {})
    first["data_usage"] = {
        "spelling_used": {"monthly_rx_bytes": "flux_monthly_rx_bytes"},
        "values": {"monthly_rx_bytes": "100"},
        "monthly": {"total_bytes": 100.0, "total_bytes_per_second": 1.0},
        "monthly_rate_over_session_rate": 1.0,
        "uptime_seconds": 10.0,
    }
    second = _artefact([], {})
    second["data_usage"] = {
        "spelling_used": {"monthly_rx_bytes": "flux_monthly_rx_bytes"},
        "values": {"monthly_rx_bytes": "160"},
        "monthly": {"total_bytes": 160.0, "total_bytes_per_second": 1.6},
        "monthly_rate_over_session_rate": 1.6,
        "uptime_seconds": 30.0,
    }
    report = Report()

    check_stability(first, second, report)

    assert _outcome(report, "no structural difference")


def test_a_device_resolving_a_different_spelling_is_a_difference() -> None:
    """Which vocabulary a device answers on is a property of the device.

    A pass that resolved it differently from the one before it has either lost
    a session partway or read a truncated response — the instability this
    check exists to catch, and the reason `spelling_used` is not excluded
    along with the figures beside it.

    Stated on `limit_unit` rather than on one of the byte concepts: a path
    such as `/data_usage/spelling_used/monthly_rx_bytes` already matches the
    `monthly_` and `_rx_` alternatives that predate this section, so those
    concepts are tolerated whatever this rule says.
    """
    first = _artefact([], {})
    first["data_usage"] = {"spelling_used": {"limit_unit": "data_volume_limit_unit"}}
    second = _artefact([], {})
    second["data_usage"] = {
        "spelling_used": {"limit_unit": "flux_data_volume_limit_unit"}
    }
    report = Report()

    check_stability(first, second, report)

    assert not _outcome(report, "no structural difference")


def test_an_unpseudonymized_value_change_is_a_difference() -> None:
    """A real value changing under a non-volatile path is what this catches."""
    first = _artefact([], {"session": "fresh login"})
    second = _artefact([], {"session": "reused"})
    report = Report()

    check_stability(first, second, report)

    assert not _outcome(report, "no structural difference")


# ---------------------------------------------------------------------------
# Whether a pass finished probing
# ---------------------------------------------------------------------------


def test_a_pass_that_asked_everything_reports_none_unasked() -> None:
    """`not_reprobed` empty is the definition of a complete pass."""
    assert unasked_count(_artefact([], {})) == 0


def test_unasked_names_are_counted() -> None:
    """Names that could not be asked are counted.

    A name lands here when its own request kept failing, which is what another
    client logging into the router does to this one.

    The count decides whether the pass is re-taken, so it reads the field
    rather than inferring incompleteness from the differences it causes.
    """
    artefact = _artefact([], {})
    artefact["discovery"]["not_reprobed"] = ["a", "b", "c"]
    assert unasked_count(artefact) == 3


def test_a_download_without_a_discovery_block_counts_as_complete() -> None:
    """`--once` against an older artefact must not crash the retry decision."""
    assert unasked_count({}) == 0


# ---------------------------------------------------------------------------
# One missing name is one difference
# ---------------------------------------------------------------------------


def test_a_name_missing_from_one_pass_is_reported_as_that_name() -> None:
    """Compared by position, one missing name shifted every later entry.

    On 2026-09-24 one unanswered web file removed three mined names from one
    pass, and the check reported the shift at positions 375, 321, 901 and 531
    instead of the three names.
    """
    first = _artefact([], {})
    second = _artefact([], {})
    first["discovery"]["probed_no_answer"] = ["a", "b", "c", "d"]
    second["discovery"]["probed_no_answer"] = ["a", "c", "d"]

    report = Report()
    check_stability(first, second, report)

    detail = next(d for _, label, d in report.checks if "structural" in label)
    assert "only in first ['b']" in detail
    assert "/probed_no_answer/" not in detail


def test_the_same_names_in_another_order_are_not_a_difference() -> None:
    """The order a pass records names in is incidental."""
    first = _artefact([], {})
    second = _artefact([], {})
    first["discovery"]["probed_no_answer"] = ["a", "b"]
    second["discovery"]["probed_no_answer"] = ["b", "a"]

    report = Report()
    check_stability(first, second, report)

    assert _outcome(report, "no structural difference")


def test_a_web_file_with_no_answer_marks_the_pass_incomplete() -> None:
    """A refused file is a property of the device; an unanswered one is not."""
    artefact = {
        "web_sources": {
            "files": {
                "js/a.js": {"status": 200},
                "js/b.js": {"status": 404},
                "js/c.js": {"status": None},
            }
        }
    }

    assert unanswered_files(artefact) == ["js/c.js"]
    assert unanswered_files({}) == []
