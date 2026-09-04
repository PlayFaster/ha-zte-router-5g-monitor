"""The `reset_entities` administrative action.

Its job is to change many registry entries at once, so almost every test here
is about it changing the *right* ones — and about the several ways it must
refuse rather than guess.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.zte_router_5g.reset_entities import (
    _entity_key,
    async_reset_entities,
)

UNIQUE = "imei_with_underscores"


def _call(**overrides: Any) -> dict[str, Any]:
    """Service data with every parameter at its schema default."""
    data: dict[str, Any] = {
        "dry_run": True,
        "reset_to_default": True,
        "enable_populated": False,
        "disable_unavailable": False,
        "disable_unknown": False,
        "include_ever_populated": False,
        "preserve_user_customized": False,
        "exclude_entities": [],
        "save_snapshot": False,
        "restore_snapshot": False,
    }
    data.update(overrides)
    return data


def _entry(key: str, *, disabled_by: er.RegistryEntryDisabler | None = None):
    """A registry entry for one of this integration's entities."""
    return MagicMock(
        entity_id=f"sensor.zte_5g_{key}",
        unique_id=f"{UNIQUE}_{key}",
        disabled_by=disabled_by,
        name=None,
        original_name=key,
    )


@pytest.fixture
def coordinator():
    """A coordinator with a healthy poll and an empty observation record.

    The config entry is a stand-in rather than a real `ConfigEntry`: the real
    one refuses a direct `unique_id` assignment, and nothing here needs its
    behaviour beyond an id and a unique id.
    """
    made = MagicMock()
    made.entry = MagicMock(entry_id="entry-1", unique_id=UNIQUE, title="ZTE 5G")
    made.last_update_success = True
    made.model = "MC7010"
    made.data = {"lte_rsrp": "-97"}
    made.observations = MagicMock(
        snapshot=MagicMock(return_value={}),
        ever_populated=MagicMock(return_value=frozenset()),
        populated_history=MagicMock(
            return_value={"entities_known_populated": 0, "recording_since": None}
        ),
        async_save_snapshot=AsyncMock(),
    )
    return made


@pytest.fixture
def registry(hass, monkeypatch):
    """A registry whose entries this test controls."""
    made = MagicMock(async_update_entity=MagicMock())
    entries: list[Any] = []
    monkeypatch.setattr(
        "custom_components.zte_router_5g.reset_entities.er.async_get",
        lambda _hass: made,
    )
    monkeypatch.setattr(
        "custom_components.zte_router_5g.reset_entities.er"
        ".async_entries_for_config_entry",
        lambda _registry, _entry_id: entries,
    )
    made.entries = entries
    return made


# ---------------------------------------------------------------------------
# Reading a registry entry
# ---------------------------------------------------------------------------


def test_the_entity_key_survives_underscores_in_the_unique_id() -> None:
    """The key survives underscores in the prefix.

    The prefix is the router IMEI or its host address, both of which can
    contain underscores, so the key cannot be found by splitting on the first
    separator.
    """
    entry = _entry("lte_rsrp")

    assert _entity_key(entry, UNIQUE) == "lte_rsrp"


def test_an_entry_from_another_prefix_yields_no_key() -> None:
    """A registry entry that does not belong to this entry is left alone."""
    entry = MagicMock(unique_id="someone_else_lte_rsrp")

    assert _entity_key(entry, UNIQUE) == ""


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


async def test_two_baselines_are_refused(hass, coordinator, registry) -> None:
    """Preferring one silently would make the same call mean two things."""
    with pytest.raises(HomeAssistantError):
        await async_reset_entities(
            hass, coordinator, _call(restore_snapshot=True, reset_to_default=True)
        )


async def test_saving_a_snapshot_beside_a_change_is_refused(
    hass, coordinator, registry
) -> None:
    """A capture cannot be combined with a change.

    A snapshot records what the user has curated, not what a call is about to
    make of it.
    """
    with pytest.raises(HomeAssistantError):
        await async_reset_entities(
            hass, coordinator, _call(save_snapshot=True, reset_to_default=True)
        )


async def test_restoring_with_nothing_saved_is_refused(
    hass, coordinator, registry
) -> None:
    """Naming the reason beats reporting a run that changed nothing."""
    with pytest.raises(HomeAssistantError):
        await async_reset_entities(
            hass, coordinator, _call(restore_snapshot=True, reset_to_default=False)
        )


async def test_an_unreachable_router_is_refused(hass, coordinator, registry) -> None:
    """Every state-driven operation reads what entities report right now.

    During an outage that is nothing at all, so a run would disable almost
    everything — and the dry run that preceded it would have looked the same.
    """
    coordinator.last_update_success = False

    with pytest.raises(HomeAssistantError):
        await async_reset_entities(hass, coordinator, _call())


# ---------------------------------------------------------------------------
# reset_to_default
# ---------------------------------------------------------------------------


async def test_reset_enables_what_the_resolver_says_should_be_on(
    hass, coordinator, registry
) -> None:
    """`lte_rsrp` ships enabled, so a disabled one is put back."""
    registry.entries.append(
        _entry("lte_rsrp", disabled_by=er.RegistryEntryDisabler.INTEGRATION)
    )

    result = await async_reset_entities(hass, coordinator, _call())

    assert [row["entity_id"] for row in result["changes"]["to_enable"]] == [
        "sensor.zte_5g_lte_rsrp"
    ]
    assert result["summary"]["to_disable"] == 0


async def test_reset_disables_what_the_resolver_says_should_be_off(
    hass, coordinator, registry
) -> None:
    """`imei` ships disabled, so one the user enabled goes back off."""
    registry.entries.append(_entry("imei"))

    result = await async_reset_entities(hass, coordinator, _call())

    assert [row["entity_id"] for row in result["changes"]["to_disable"]] == [
        "sensor.zte_5g_imei"
    ]


async def test_reset_follows_the_model_overlay_not_the_description(
    hass, coordinator, registry
) -> None:
    """The action shares the resolver platform setup uses.

    If it read the description flag instead, a reset on an MC888 would
    re-enable the six sensors that firmware leaves blank — undoing the overlay
    every time it ran.
    """
    coordinator.model = "MC888 Pro"
    registry.entries.append(_entry("lte_rsrq"))

    result = await async_reset_entities(hass, coordinator, _call())

    assert [row["entity_id"] for row in result["changes"]["to_disable"]] == [
        "sensor.zte_5g_lte_rsrq"
    ]


async def test_an_entity_already_in_its_default_state_is_unchanged(
    hass, coordinator, registry
) -> None:
    """Only differences are reported, so the summary means something."""
    registry.entries.append(_entry("lte_rsrp"))

    result = await async_reset_entities(hass, coordinator, _call())

    assert result["summary"] == {
        "total_evaluated": 1,
        "to_enable": 0,
        "to_disable": 0,
        "unchanged": 1,
    }


async def test_an_entity_with_no_description_is_left_alone(
    hass, coordinator, registry
) -> None:
    """A registry entry can outlive the entity that created it."""
    registry.entries.append(_entry("removed_in_some_earlier_release"))

    result = await async_reset_entities(hass, coordinator, _call())

    assert result["summary"]["unchanged"] == 1


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


async def test_excluded_entities_are_untouched(hass, coordinator, registry) -> None:
    """The dry run lists what would change; this carries the keepers through."""
    registry.entries.append(_entry("imei"))

    result = await async_reset_entities(
        hass, coordinator, _call(exclude_entities=["sensor.zte_5g_imei"])
    )

    assert result["changes"]["to_disable"] == []


async def test_an_entity_the_user_disabled_can_be_preserved(
    hass, coordinator, registry
) -> None:
    """`disabled_by == USER` is the one customization the registry records."""
    registry.entries.append(
        _entry("lte_rsrp", disabled_by=er.RegistryEntryDisabler.USER)
    )

    result = await async_reset_entities(
        hass, coordinator, _call(preserve_user_customized=True)
    )

    assert result["changes"]["to_enable"] == []


async def test_an_entity_the_integration_disabled_is_not_preserved(
    hass, coordinator, registry
) -> None:
    """A stale registration is not user customization.

    An entity registered before its default changed differs from the resolver
    without anyone having touched it, and resetting it is the point — this is
    the path by which a model overlay reaches an existing installation.
    """
    registry.entries.append(
        _entry("lte_rsrp", disabled_by=er.RegistryEntryDisabler.INTEGRATION)
    )

    result = await async_reset_entities(
        hass, coordinator, _call(preserve_user_customized=True)
    )

    assert len(result["changes"]["to_enable"]) == 1


# ---------------------------------------------------------------------------
# The state-driven operations
# ---------------------------------------------------------------------------


async def test_enable_populated_turns_on_what_the_router_reports(
    hass, coordinator, registry
) -> None:
    """A disabled entity has no state, so this is evaluated from the payload."""
    registry.entries.append(
        _entry("lte_rsrp", disabled_by=er.RegistryEntryDisabler.USER)
    )

    result = await async_reset_entities(
        hass, coordinator, _call(reset_to_default=False, enable_populated=True)
    )

    assert len(result["changes"]["to_enable"]) == 1


async def test_disable_unavailable_leaves_a_previously_populated_entity_alone(
    hass, coordinator, registry
) -> None:
    """The point of the ever-populated record.

    A 5G sensor is unavailable while the router is on LTE. Disabling it then
    is almost never what the user meant, and nothing re-enables it later.
    """
    registry.entries.append(_entry("z5g_rsrp"))
    hass.states.async_set("sensor.zte_5g_z5g_rsrp", "unavailable")
    coordinator.observations.ever_populated.return_value = frozenset({"z5g_rsrp"})

    result = await async_reset_entities(
        hass,
        coordinator,
        _call(reset_to_default=False, disable_unavailable=True),
    )

    assert result["changes"]["to_disable"] == []


async def test_include_ever_populated_disables_it_anyway(
    hass, coordinator, registry
) -> None:
    """The escape hatch, for a user who has genuinely stopped using 5G."""
    registry.entries.append(_entry("z5g_rsrp"))
    hass.states.async_set("sensor.zte_5g_z5g_rsrp", "unavailable")
    coordinator.observations.ever_populated.return_value = frozenset({"z5g_rsrp"})

    result = await async_reset_entities(
        hass,
        coordinator,
        _call(
            reset_to_default=False,
            disable_unavailable=True,
            include_ever_populated=True,
        ),
    )

    assert len(result["changes"]["to_disable"]) == 1


async def test_disable_unknown_acts_on_an_entity_never_populated(
    hass, coordinator, registry
) -> None:
    """Nothing protects an entity that has never reported anything."""
    registry.entries.append(_entry("z5g_rsrp"))
    hass.states.async_set("sensor.zte_5g_z5g_rsrp", "unknown")

    result = await async_reset_entities(
        hass, coordinator, _call(reset_to_default=False, disable_unknown=True)
    )

    assert len(result["changes"]["to_disable"]) == 1


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


async def test_saving_a_snapshot_records_every_entity_state(
    hass, coordinator, registry
) -> None:
    """Reported back so a snapshot taken mid-exploration is visible as one."""
    registry.entries.append(_entry("lte_rsrp"))
    registry.entries.append(
        _entry("imei", disabled_by=er.RegistryEntryDisabler.INTEGRATION)
    )

    result = await async_reset_entities(
        hass,
        coordinator,
        _call(save_snapshot=True, reset_to_default=False, dry_run=False),
    )

    coordinator.observations.async_save_snapshot.assert_awaited_once_with(
        {"lte_rsrp": True, "imei": False}
    )
    assert result["snapshot"] == {"entities": 2, "enabled": 1}


async def test_a_dry_run_snapshot_writes_nothing(hass, coordinator, registry) -> None:
    """`dry_run` governs this operation like every other."""
    registry.entries.append(_entry("lte_rsrp"))

    result = await async_reset_entities(
        hass, coordinator, _call(save_snapshot=True, reset_to_default=False)
    )

    coordinator.observations.async_save_snapshot.assert_not_awaited()
    assert result["snapshot"]["entities"] == 1


async def test_restoring_a_snapshot_returns_to_the_saved_state(
    hass, coordinator, registry
) -> None:
    """The scenario this exists for: keep my set, not the shipped one."""
    coordinator.observations.snapshot.return_value = {"imei": True, "lte_rsrp": False}
    registry.entries.append(
        _entry("imei", disabled_by=er.RegistryEntryDisabler.INTEGRATION)
    )
    registry.entries.append(_entry("lte_rsrp"))

    result = await async_reset_entities(
        hass, coordinator, _call(reset_to_default=False, restore_snapshot=True)
    )

    assert [row["entity_id"] for row in result["changes"]["to_enable"]] == [
        "sensor.zte_5g_imei"
    ]
    assert [row["entity_id"] for row in result["changes"]["to_disable"]] == [
        "sensor.zte_5g_lte_rsrp"
    ]


async def test_an_entity_added_after_the_snapshot_falls_through(
    hass, coordinator, registry
) -> None:
    """An upgrade still delivers new entities to a user holding a snapshot."""
    coordinator.observations.snapshot.return_value = {"imei": True}
    registry.entries.append(_entry("sinr"))

    result = await async_reset_entities(
        hass, coordinator, _call(reset_to_default=False, restore_snapshot=True)
    )

    assert result["summary"]["unchanged"] == 1


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


async def test_a_dry_run_changes_nothing(hass, coordinator, registry) -> None:
    """The default, and the whole safety model."""
    registry.entries.append(_entry("imei"))

    result = await async_reset_entities(hass, coordinator, _call())

    assert result["dry_run"] is True
    assert len(result["changes"]["to_disable"]) == 1
    registry.async_update_entity.assert_not_called()


async def test_applying_writes_the_registry_and_reloads(
    hass, coordinator, registry
) -> None:
    """A reload is what makes newly enabled entities appear."""
    registry.entries.append(_entry("imei"))
    hass.config_entries.async_reload = AsyncMock()

    await async_reset_entities(hass, coordinator, _call(dry_run=False))

    registry.async_update_entity.assert_called_once_with(
        "sensor.zte_5g_imei", disabled_by=er.RegistryEntryDisabler.USER
    )
    hass.config_entries.async_reload.assert_awaited_once()


async def test_applying_an_enable_clears_the_disabled_flag(
    hass, coordinator, registry
) -> None:
    """Enabling is `disabled_by=None`, not a separate flag."""
    registry.entries.append(
        _entry("lte_rsrp", disabled_by=er.RegistryEntryDisabler.INTEGRATION)
    )
    hass.config_entries.async_reload = AsyncMock()

    await async_reset_entities(hass, coordinator, _call(dry_run=False))

    registry.async_update_entity.assert_called_once_with(
        "sensor.zte_5g_lte_rsrp", disabled_by=None
    )


async def test_a_run_with_nothing_to_do_does_not_reload(
    hass, coordinator, registry
) -> None:
    """Reloading an entry is disruptive and pointless when nothing changed."""
    registry.entries.append(_entry("lte_rsrp"))
    hass.config_entries.async_reload = AsyncMock()

    await async_reset_entities(hass, coordinator, _call(dry_run=False))

    hass.config_entries.async_reload.assert_not_awaited()


async def test_the_response_reports_how_much_history_backs_the_filter(
    hass, coordinator, registry
) -> None:
    """An empty record makes the safe default a no-op, silently.

    Without this the dry run looks identical whether the ever-populated filter
    protected twenty entities or none.
    """
    result = await async_reset_entities(hass, coordinator, _call())

    assert result["populated_history"] == {
        "entities_known_populated": 0,
        "recording_since": None,
    }
