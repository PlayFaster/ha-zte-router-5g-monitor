"""Every write must be classified, and every SAFE write must be exercised.

This file guards a gap that is not a coding error at all. The Data Limit Switch
shipped broken in every release for weeks; the ODU LED switch was erratic for
just as long. Neither was a subtle bug — both failed on the first attempt. They
survived because **nobody used those entities**, so nobody tried.

No behavioral test catches that, because the missing thing is not an assertion,
it is the decision to look. What this file enforces instead is a decision:
adding a command to `api.py` without recording whether a script may exercise it
fails the suite.

Deliberately not a behavioral test — it never touches a router, and it proves
nothing about whether any write works. It proves only that none was added in
silence.
"""

from __future__ import annotations

import ast
import pathlib

from scripts.write_classification import (
    ATTENDED,
    EXERCISED_BY_HARDWARE_CHECK,
    NEVER_AUTOMATED,
    SAFE,
    classification,
)

_API = pathlib.Path("custom_components/zte_router_5g/api.py")
_HARDWARE_CHECK = pathlib.Path("scripts/hardware_check.py")

# `login` is excluded: it is the precondition for every other command, so it is
# exercised by literally every check rather than needing one of its own. Nothing
# else is excluded — see `test_the_write_detector_sees_the_delegating_writes`
# for why the detector cannot simply look for `goformId`.
_NOT_A_USER_FACING_WRITE = frozenset({"login"})

_WRITE_PREFIXES = ("set_", "send_", "delete_")
_WRITE_NAMES = frozenset({"reboot", "logout"})


def _public_writes() -> set[str]:
    """Return every public API method that commands the router."""
    source = _API.read_text(encoding="utf-8")
    tree = ast.parse(source)
    api = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ZTERouterAPI"
    )
    found = {
        node.name
        for node in api.body
        if isinstance(node, ast.AsyncFunctionDef)
        and not node.name.startswith("_")
        and (node.name.startswith(_WRITE_PREFIXES) or node.name in _WRITE_NAMES)
    }
    return found - _NOT_A_USER_FACING_WRITE


def test_every_write_is_classified() -> None:
    """A new command must be placed in SAFE, ATTENDED or NEVER.

    The failure this prevents is a write shipping with nobody having asked
    whether it could be exercised — which is exactly how two broken controls
    reached users.
    """
    unclassified = sorted(n for n in _public_writes() if classification(n) is None)
    assert not unclassified, (
        "writes with no entry in scripts/write_classification.py:\n  "
        + "\n  ".join(unclassified)
        + "\n\nDecide the tier and record the reason. SAFE means reversible "
        "in-process with both resting states harmless; ATTENDED means a human "
        "confirms each step; NEVER_AUTOMATED means no confirmation could make "
        "it acceptable."
    )


def test_no_write_is_classified_twice() -> None:
    """Overlapping tiers would make the strictest one unenforceable."""
    overlaps = (
        (SAFE.keys() & ATTENDED.keys())
        | (SAFE.keys() & NEVER_AUTOMATED.keys())
        | (ATTENDED.keys() & NEVER_AUTOMATED.keys())
    )
    assert not overlaps, f"writes in more than one tier: {sorted(overlaps)}"


def test_the_register_does_not_name_writes_that_no_longer_exist() -> None:
    """A renamed or deleted command must not leave a stale entry behind.

    A stale entry is worse than a missing one: it reads as coverage.
    """
    known = _public_writes()
    stale = sorted((SAFE.keys() | ATTENDED.keys() | NEVER_AUTOMATED.keys()) - known)
    assert not stale, (
        f"classified but no longer present in api.py: {stale}. "
        "Remove the entry, or fix the name if the method was renamed."
    )


def test_every_safe_write_is_exercised_by_the_hardware_check() -> None:
    """Classifying a write SAFE is a promise that something actually runs it.

    Without this, the register would happily record "safe" for a command no
    script has ever sent — restating the original failure in a tidier form.
    """
    unexercised = sorted(SAFE.keys() - EXERCISED_BY_HARDWARE_CHECK)
    assert not unexercised, (
        f"classified SAFE but not exercised: {unexercised}. Either add a check "
        "to scripts/hardware_check.py and list it in "
        "EXERCISED_BY_HARDWARE_CHECK, or reclassify it as ATTENDED."
    )


def test_the_hardware_check_really_calls_what_it_claims() -> None:
    """`EXERCISED_BY_HARDWARE_CHECK` must not drift from the script.

    The list is hand-maintained, so it can claim coverage that was renamed away.
    This reads the script and confirms each name genuinely appears.
    """
    script = _HARDWARE_CHECK.read_text(encoding="utf-8")
    missing = sorted(name for name in EXERCISED_BY_HARDWARE_CHECK if name not in script)
    assert not missing, (
        f"claimed as exercised but absent from {_HARDWARE_CHECK}: {missing}"
    )


def test_the_write_detector_sees_the_delegating_writes() -> None:
    """Guard the guard: the detector must not go blind.

    Detecting writes by searching for `goformId` looks obvious and is wrong —
    `delete_all` and `set_data_limit_switch` send commands by delegating to
    another method, so neither contains the string. A detector that missed them
    would let two real writes escape classification while the suite stayed
    green, which is the precise failure mode this file exists to prevent.
    """
    writes = _public_writes()
    for delegating in ("delete_all", "set_data_limit_switch"):
        assert delegating in writes, (
            f"{delegating} is no longer detected as a write — the detector has "
            "regressed to something that only sees direct goformId posts."
        )
    # A plain read must never be swept in; that would make the register noise.
    assert "get_params" not in writes
    assert "get_all_data" not in writes


def test_every_classification_carries_a_reason() -> None:
    """A tier without a stated reason cannot be reviewed, only trusted."""
    thin = sorted(
        name
        for register in (SAFE, ATTENDED, NEVER_AUTOMATED)
        for name, reason in register.items()
        if len(reason.strip()) < 40
    )
    assert not thin, f"classified with no meaningful justification: {thin}"


def test_attended_writes_offered_by_the_script_are_classified_attended() -> None:
    """The `--attended` menu must not quietly include a NEVER or a SAFE write."""
    from scripts.write_classification import OFFERED_WHEN_ATTENDED

    misfiled = sorted(n for n in OFFERED_WHEN_ATTENDED if n not in ATTENDED)
    assert not misfiled, (
        f"offered under --attended but not classified ATTENDED: {misfiled}"
    )


def test_offered_attended_writes_really_appear_in_the_script() -> None:
    """Same drift guard as the SAFE list, for the attended tier."""
    from scripts.write_classification import OFFERED_WHEN_ATTENDED

    script = _HARDWARE_CHECK.read_text(encoding="utf-8")
    missing = sorted(n for n in OFFERED_WHEN_ATTENDED if n not in script)
    assert not missing, (
        f"offered under --attended but absent from the script: {missing}"
    )
