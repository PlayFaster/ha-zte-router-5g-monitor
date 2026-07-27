"""Recorder hygiene, value rounding and icon coverage.

These cover dev_standards Sections 6, 12, 14 and 18 — the parts that are easy
to regress silently, because nothing fails at runtime when an attribute starts
being recorded or a sensor starts storing twelve decimal places.
"""

import json
import pathlib
import re

from custom_components.zte_router_5g.binary_sensor import ZTEIntegrationHealthSensor
from custom_components.zte_router_5g.sensor import (
    SENSOR_TYPES,
    ZTERouterSensor,
    _safe_float,
)

COMPONENT = pathlib.Path("custom_components/zte_router_5g")


# --------------------------------------------------------------------------
# Section 6 — rounding at parse time
# --------------------------------------------------------------------------


def test_safe_float_rounds_at_parse_time() -> None:
    """Controller noise must not reach the recorder verbatim."""
    assert _safe_float("99.930600002408") == 99.931
    assert _safe_float(-85.7777777) == -85.778


def test_safe_float_still_tolerates_bad_input() -> None:
    """Rounding must not weaken the None/empty/garbage guards."""
    assert _safe_float(None) is None
    assert _safe_float("") is None
    assert _safe_float("not-a-number") is None
    assert _safe_float("-85") == -85.0


# --------------------------------------------------------------------------
# Section 14 — unrecorded attributes
# --------------------------------------------------------------------------


def test_sms_sender_number_is_never_recorded() -> None:
    """The SMS sender's number is third-party personal data.

    Recording it would write someone else's phone number into the user's
    database on every poll.
    """
    assert "number" in ZTERouterSensor._unrecorded_attributes


def test_every_attribute_the_sensor_emits_was_evaluated() -> None:
    """No attribute may be added without a recorded/unrecorded decision.

    `sntp_server1` and `sntp_dst_enable` are the deliberate exceptions: static
    configuration, cheap to store, and worth seeing in history.
    """
    emitted = {
        "id",
        "number",
        "date",
        "sms_nv_total",
        "sms_sim_total",
        "sms_nv_rev_total",
        "sms_nv_send_total",
        "sms_nv_draftbox_total",
        "sms_sim_rev_total",
        "sms_sim_send_total",
        "sms_sim_draftbox_total",
        "sntp_server1",
        "sntp_dst_enable",
    }
    deliberately_recorded = {"sntp_server1", "sntp_dst_enable"}
    assert emitted - deliberately_recorded == set(
        ZTERouterSensor._unrecorded_attributes
    )


def test_health_detail_is_unrecorded() -> None:
    """The health sensor's detail churns with every failure."""
    assert "issues" in ZTEIntegrationHealthSensor._unrecorded_attributes


# --------------------------------------------------------------------------
# Section 12 — icons resolve for everything that needs one
# --------------------------------------------------------------------------


def _load(name: str) -> dict:
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def test_every_entity_without_a_device_class_has_an_icon() -> None:
    """An entity with no device_class falls back to a generic icon."""
    icons = _load("icons.json")["entity"]
    have = {key for platform in icons.values() for key in platform}

    missing = [
        d.translation_key
        for d in SENSOR_TYPES
        if d.device_class is None and d.translation_key not in have
    ]
    assert not missing, f"sensors with neither device_class nor icon: {missing}"


def test_refresh_button_has_an_icon() -> None:
    """Refresh Now has no device_class to derive one from."""
    assert "system_refresh" in _load("icons.json")["entity"]["button"]


def test_services_have_icons() -> None:
    """Section 12 requires icons.json to cover services, not just entities."""
    declared = set(_load("icons.json").get("services", {}))
    expected = {"send_sms", "delete_sms", "delete_all_sms", "get_sms_list"}
    assert expected <= declared


def test_registered_services_match_the_icon_entries() -> None:
    """Guards against an icon entry drifting from the real service name."""
    source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    registered = set(
        re.findall(r'hass\.services\.async_register\(\s*DOMAIN,\s*"(\w+)"', source)
    )
    assert registered == set(_load("icons.json")["services"])


def test_translation_keys_resolve_in_both_files() -> None:
    """Every translation_key used in code must resolve in both files.

    Compared against the code, not file-to-file: a healthy entry count in one
    file conceals both stale entries and live entities with no entry at all.
    """
    source = "".join(p.read_text(encoding="utf-8") for p in COMPONENT.glob("*.py"))
    keys = set(re.findall(r'translation_key="([^"]+)"', source))

    for name in ("strings.json", "translations/en.json"):
        data = _load(name)
        resolved = {k for platform in data["entity"].values() for k in platform}
        resolved |= set(data.get("issues", {}))
        assert not keys - resolved, f"{name} missing: {sorted(keys - resolved)}"


def test_every_repair_issue_has_translated_text() -> None:
    """A missing issues entry shows the raw key on the Repairs card."""
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    raised = set(re.findall(r'translation_key="(\w+)"', source))

    for name in ("strings.json", "translations/en.json"):
        issues = set(_load(name).get("issues", {}))
        assert raised <= issues, f"{name} missing issue text for {raised - issues}"
