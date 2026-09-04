"""Per-model entity defaults.

`entity_registry_enabled_default` is one flag per description, so the same
defaults ship to every device. `default_enabled` overlays a per-model opinion
on top of it, and is the single resolver both platform setup and the
`reset_entities` action must consult — two readers of different sources would
disagree, and a reset would undo the overlay every time it ran.
"""

from __future__ import annotations

import pytest

from custom_components.zte_router_5g.binary_sensor import BINARY_SENSORS
from custom_components.zte_router_5g.entity_defaults import (
    MODEL_OVERLAY,
    default_enabled,
)
from custom_components.zte_router_5g.select import SELECT_TYPES
from custom_components.zte_router_5g.sensor import SENSOR_TYPES
from custom_components.zte_router_5g.switch import SWITCH_TYPES

MC888 = "MC888 Pro"
MC7010 = "MC7010"


def _description(key: str):
    """Return the entity description with this key, from any platform."""
    for types in (SENSOR_TYPES, BINARY_SENSORS, SWITCH_TYPES, SELECT_TYPES):
        for description in types:
            if description.key == key:
                return description
    raise AssertionError(f"no description with key {key!r}")


# ---------------------------------------------------------------------------
# The fallback
# ---------------------------------------------------------------------------


def test_an_unrecognised_model_keeps_every_description_default() -> None:
    """The overlay is an addition, not a replacement.

    A device nobody has measured gets the curated defaults the integration was
    built around, which is the only honest answer for hardware we have never
    seen.
    """
    for description in SENSOR_TYPES:
        assert default_enabled(description, "MF286D") == (
            description.entity_registry_enabled_default
        )


def test_no_model_at_all_keeps_the_description_default() -> None:
    """`coordinator.model` is `None` before the first poll identifies it."""
    description = _description("lte_rsrq")

    assert default_enabled(description, None) is (
        description.entity_registry_enabled_default
    )


def test_a_matched_model_keeps_defaults_it_says_nothing_about() -> None:
    """An overlay entry names exceptions, not a whole entity list."""
    description = _description("lte_rsrp")
    assert "lte_rsrp" not in MODEL_OVERLAY["MC888"]

    assert default_enabled(description, MC888) is (
        description.entity_registry_enabled_default
    )


# ---------------------------------------------------------------------------
# The MC888 overlay
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    ["lte_rsrq", "lte_rssi", "lte_snr", "z5g_rssi", "wan_connect_status"],
)
def test_the_mc888_disables_what_it_cannot_populate(key: str) -> None:
    """Six enabled sensors are blank on that firmware.

    Measured on the 2026-09-02 download: no spelling of any of these is
    populated there, and its own web pages request three of them and get
    blanks back.
    """
    description = _description(key)
    assert description.entity_registry_enabled_default is True

    assert default_enabled(description, MC888) is False
    assert default_enabled(description, MC7010) is True


@pytest.mark.parametrize("key", ["rssi", "sinr", "wifi_clients", "wifi_enabled"])
def test_the_mc888_enables_what_only_it_reports(key: str) -> None:
    """The overlay is a curated suite, not a filter over blanks.

    RSSI and SINR are the only signal-quality figures that firmware reports,
    and the two Wi-Fi aggregates are answered there and by no MC7010. All four
    are off by default because they are blank on the reference device.
    """
    description = _description(key)
    assert description.entity_registry_enabled_default is False

    assert default_enabled(description, MC888) is True
    assert default_enabled(description, MC7010) is False


def test_the_enodeb_sensor_is_not_disabled_on_the_mc888() -> None:
    """It is derived there, not read, so it does populate.

    The overlay disabled it when it was written, from a download taken before
    the derivation existed. Left in place the entry would suppress a sensor
    that works, which is the failure mode of seeding an overlay from a
    measurement and then changing what the code does with it.
    """
    description = _description("enodeb_id")

    assert default_enabled(description, MC888) is True


def test_the_overlay_matches_the_family_not_the_variant() -> None:
    """Evidence is one MC888 Pro; the entry covers the MC888 family.

    The `network_` vocabulary and the `zsidn` cookie are firmware-family
    behaviours, and `api._hash` already selects its algorithm on `MC888`
    appearing anywhere in the version string.
    """
    description = _description("lte_rsrq")

    for model in ("MC888", "MC888 Pro", "MC888A", "MC888 Ultra"):
        assert default_enabled(description, model) is False


def test_a_longer_entry_wins_over_a_shorter_one() -> None:
    """Order is by key length, so a variant can override its family.

    Nothing needs this yet. It is here so that a later download contradicting
    the family entry is a new dict key rather than a rewrite of the lookup.
    """
    description = _description("lte_rsrq")
    MODEL_OVERLAY["MC888 Ultra"] = {"lte_rsrq": True}
    try:
        assert default_enabled(description, "MC888 Ultra") is True
        assert default_enabled(description, "MC888 Pro") is False
    finally:
        del MODEL_OVERLAY["MC888 Ultra"]


# ---------------------------------------------------------------------------
# The overlay itself
# ---------------------------------------------------------------------------


def test_every_overlay_key_names_a_real_entity() -> None:
    """A typo would be silent: the lookup misses and the default stands."""
    known = {
        d.key
        for types in (SENSOR_TYPES, BINARY_SENSORS, SWITCH_TYPES, SELECT_TYPES)
        for d in types
    }

    for model, entries in MODEL_OVERLAY.items():
        unknown = sorted(set(entries) - known)
        assert not unknown, f"{model} names entities that do not exist: {unknown}"


def test_no_overlay_entry_repeats_the_description_default() -> None:
    """An entry that agrees with the description states nothing.

    Left in place it reads as a measured decision about that model, and it
    would survive a later change to the description that was meant to move it.
    """
    for model, entries in MODEL_OVERLAY.items():
        for key, enabled in entries.items():
            description = _description(key)
            assert enabled is not description.entity_registry_enabled_default, (
                f"{model}/{key} repeats the description default"
            )
