"""Every command this integration can send, and whether a script may send it.

The register exists because of how the Data Limit Switch failed: it had never
worked, in any release, and nobody noticed for weeks — not because testing was
hard, but because **nobody used that entity**. A control the owner does not
personally use is exercised only by accident. The same was true of the ODU LED.

So the guarantee this file provides is not "these are tested". It is *"no write
can be added without someone deciding, in writing, whether it can be tested"*.
`tests/test_write_classification.py` fails on an unclassified write, and fails
again if something classified SAFE is not actually exercised by
`scripts/hardware_check.py`.

The three tiers:

``SAFE``
    Automatable unattended. Must be reversible **in-process**, must not
    interrupt service, cost money, or touch anyone else's property — and,
    because a crash can strand it, **either resting state must be harmless**.
    That last clause is why the data-volume *alert percentage* is SAFE while the
    data-limit *switch* is not: a stranded percentage is a cosmetic threshold, a
    stranded cap can stop the router passing traffic.

``ATTENDED``
    Exercised only with a human confirming each step individually, and never in
    an unattended run. Everything that re-establishes the connection lives here:
    it is recoverable, but a script cannot judge whether it recovered.

``NEVER``
    Not scriptable at any tier. Costs money, reaches a third party, or destroys
    user data. No flag enables these.
"""

from __future__ import annotations

# --- Automatable unattended -------------------------------------------------
SAFE: dict[str, str] = {
    "set_odu_led_switch": (
        "Cosmetic. Applies in ~128 ms, both states harmless, no service impact. "
        "This is the write whose failure prompted the whole exercise."
    ),
    "set_data_volume_settings": (
        "Exercised by nudging `data_volume_alert_percent` only, and restoring "
        "it. That covers the all-or-nothing six-field form — the part that was "
        "broken in every release — without touching the cap or the limit "
        "switch. A stranded alert percentage warns at a slightly wrong point; "
        "nothing stops working."
    ),
    "logout": (
        "Ends a session the script immediately re-establishes. Worth covering "
        "because it carries a non-obvious requirement: `goformId=LOGOUT` needs "
        "an `AD` token, and a router that quietly ignores the call leaves the "
        "user locked out of their own web UI with no error anywhere."
    ),
}

# --- Human present, one step at a time --------------------------------------
ATTENDED: dict[str, str] = {
    "set_apn_mode": (
        "Re-establishes the connection. Recoverable, and the round trip "
        "auto -> manual -> auto is short, but the router answers with blank "
        "values while reconnecting and a script cannot tell that from a dead "
        "session."
    ),
    "set_apn": (
        "As `set_apn_mode`, and worse: a wrong profile means no data at all "
        "until it is put back. Restoring needs the original index, which is "
        "only knowable while the connection works."
    ),
    "set_bearer_preference": (
        "Radio re-registration. `Only_5G` where 5G is marginal may not come "
        "back on its own, so this must never run unattended."
    ),
    "set_data_limit_switch": (
        "Turning the cap ON can stop the router passing traffic — the router "
        "enforces the limit, it does not merely warn. Whether that is safe "
        "depends on the configured cap against current usage, which is a "
        "judgement, not a check."
    ),
    "reboot": (
        "Minutes of downtime, and verification means waiting for the device to "
        "come back. Classified rather than scripted: there is no way to make "
        "this quick or quiet."
    ),
}

# --- Not scriptable at any tier ---------------------------------------------
NEVER: dict[str, str] = {
    "send_sms": (
        "Costs money and delivers to a third party. There is no test recipient "
        "that makes this acceptable, and a retry loop would send twice."
    ),
    "delete_sms": (
        "Irreversibly destroys the user's messages. A round trip is impossible "
        "— nothing can put a deleted message back."
    ),
    "delete_all": (
        "As `delete_sms`, across the whole inbox. The most destructive command "
        "this integration can issue."
    ),
}

# Writes the hardware script is expected to exercise. Kept separate from `SAFE`
# so the test can tell "classified safe" from "actually covered" — the gap that
# let the Data Limit Switch ship broken. Adding a SAFE write without covering it
# fails the test.
EXERCISED_BY_HARDWARE_CHECK: frozenset[str] = frozenset(
    {"set_odu_led_switch", "set_data_volume_settings", "logout"}
)

# ATTENDED writes the script offers under `--attended`. The rest of the
# ATTENDED tier is classified but deliberately unscripted: `reboot` cannot be
# made quick or quiet, and `set_data_limit_switch` turns on a cap that stops
# traffic, which is a judgement about the user's plan rather than a check.
OFFERED_WHEN_ATTENDED: frozenset[str] = frozenset(
    {
        "set_apn_mode",
        "set_apn",
        "set_bearer_preference",
        "set_data_limit_switch",
    }
)


def classification(name: str) -> str | None:
    """Return the tier a write belongs to, or None when unclassified."""
    for tier, register in (("SAFE", SAFE), ("ATTENDED", ATTENDED), ("NEVER", NEVER)):
        if name in register:
            return tier
    return None
