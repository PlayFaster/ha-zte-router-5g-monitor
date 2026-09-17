"""The post-poll observation records.

`ObservationRecorder` folds each successful poll into two persisted records:
the transitions of six tracked text values, and the set of entities that have
ever reported a value on this device. Both exist because Home Assistant's
recorder forgets — the first because a text entity produces no long-term
statistics, the second so that `reset_entities` can avoid disabling an entity
that was populated yesterday and is merely absent today.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.zte_router_5g.observations import (
    HISTORY_CAP,
    META_KEY,
    TRACKED,
    ObservationRecorder,
    entity_keys_with_values,
)

DEVICE = "imei-1"


@pytest.fixture
def recorder(hass, mock_config_entry) -> ObservationRecorder:
    """A recorder with both stores replaced, so nothing touches the disk."""
    made = ObservationRecorder(hass, mock_config_entry)
    made._history_store = MagicMock(
        async_load=AsyncMock(return_value=None),
        async_save=AsyncMock(),
        async_remove=AsyncMock(),
    )
    made._observed_store = MagicMock(
        async_load=AsyncMock(return_value=None),
        async_save=AsyncMock(),
        async_remove=AsyncMock(),
    )
    return made


def _poll(**overrides: Any) -> dict[str, Any]:
    """A payload carrying every tracked value."""
    data = {
        "wa_inner_version": "V1.0.0B01",
        "wan_ipaddr": "10.0.0.1",
        "wan_apn": "internet",
        "cell_id": "c8751",
        "network_provider": "Operator",
        "opms_wan_mode": "LTE_BRIDGE",
        "realtime_time": "76194",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def test_the_first_reading_starts_the_series_without_counting_as_a_change(
    recorder: ObservationRecorder,
) -> None:
    """Otherwise every fresh install reports one change of everything."""
    assert recorder.observe(_poll(), DEVICE) is True

    entries = recorder.history("wa_inner_version")
    assert len(entries) == 1
    assert entries[0]["from"] is None
    assert entries[0]["to"] == "V1.0.0B01"
    assert recorder.change_count("wa_inner_version") == 0


def test_an_unchanged_value_records_nothing(recorder: ObservationRecorder) -> None:
    """Almost every poll changes nothing, and must not write."""
    recorder.observe(_poll(), DEVICE)

    assert recorder.observe(_poll(), DEVICE) is False
    assert len(recorder.history("wa_inner_version")) == 1


def test_a_change_is_recorded_with_what_it_came_from(
    recorder: ObservationRecorder,
) -> None:
    """The point of the feature: the previous value survives the recorder."""
    recorder.observe(_poll(), DEVICE)

    assert recorder.observe(_poll(wa_inner_version="V1.0.0B03"), DEVICE) is True

    entries = recorder.history("wa_inner_version")
    assert entries[-1]["from"] == "V1.0.0B01"
    assert entries[-1]["to"] == "V1.0.0B03"
    assert recorder.change_count("wa_inner_version") == 1


def test_an_empty_value_is_not_a_change(recorder: ObservationRecorder) -> None:
    """A key the router answered blank has not changed to nothing.

    Present-but-empty is absent everywhere else in this integration, and a
    transition to `""` would record an outage as a firmware downgrade.
    """
    recorder.observe(_poll(), DEVICE)

    assert recorder.observe(_poll(wa_inner_version=""), DEVICE) is False
    assert len(recorder.history("wa_inner_version")) == 1


def test_a_tracked_value_is_read_through_its_aliases(
    recorder: ObservationRecorder,
) -> None:
    """The MC888 answers `network_cell_id` and leaves `cell_id` empty."""
    data = _poll(cell_id="")
    data["network_cell_id"] = "16512357"

    recorder.observe(data, DEVICE)

    assert recorder.history("cell_id")[-1]["to"] == "16512357"


def test_the_uptime_counter_is_recorded_beside_the_change(
    recorder: ObservationRecorder,
) -> None:
    """Placing a change against a restart is the field's only purpose."""
    recorder.observe(_poll(), DEVICE)

    assert recorder.history("wa_inner_version")[-1]["uptime_at_change"] == 76194


def test_a_missing_uptime_records_none_rather_than_zero(
    recorder: ObservationRecorder,
) -> None:
    """Zero would read as "just rebooted", the one wrong answer available."""
    data = _poll()
    del data["realtime_time"]

    recorder.observe(data, DEVICE)

    assert recorder.history("wa_inner_version")[-1]["uptime_at_change"] is None


def test_the_history_is_capped_and_the_count_keeps_rising(
    recorder: ObservationRecorder,
) -> None:
    """The count is stored separately because the list is capped.

    Deriving the count from the list would make it stop at the cap, which is
    exactly when the long-term view starts being the only record left.
    """
    for n in range(HISTORY_CAP + 5):
        recorder.observe(_poll(wa_inner_version=f"V{n}"), DEVICE)

    entries = recorder.history("wa_inner_version")
    assert len(entries) == HISTORY_CAP
    assert entries[-1]["to"] == f"V{HISTORY_CAP + 4}"
    assert recorder.change_count("wa_inner_version") == HISTORY_CAP + 4


def test_each_device_keeps_its_own_record(recorder: ObservationRecorder) -> None:
    """One entry fronts one router here, but the shape is shared."""
    recorder.observe(_poll(), "imei-1")
    recorder.observe(_poll(wa_inner_version="OTHER"), "imei-2")

    assert recorder.history("wa_inner_version")[-1]["to"] == "OTHER"
    recorder.device_id = "imei-1"
    assert recorder.history("wa_inner_version")[-1]["to"] == "V1.0.0B01"


def test_a_key_never_answered_has_no_history(recorder: ObservationRecorder) -> None:
    """Reading a tracked key the device does not serve returns nothing."""
    data = _poll()
    del data["opms_wan_mode"]

    recorder.observe(data, DEVICE)

    assert recorder.history("opms_wan_mode") == []
    assert recorder.change_count("opms_wan_mode") == 0


def test_every_tracked_key_names_a_sensor() -> None:
    """A tracked key with no entity records history nothing can display."""
    from custom_components.zte_router_5g.sensor import SENSOR_TYPES

    keys = {d.key for d in SENSOR_TYPES}
    assert not set(TRACKED) - keys


# ---------------------------------------------------------------------------
# The populated set
# ---------------------------------------------------------------------------


def test_entities_reporting_a_value_enter_the_populated_set(
    recorder: ObservationRecorder,
) -> None:
    """Recorded by entity key, so aliases and derived values are covered."""
    recorder.observe(_poll(), DEVICE)

    populated = recorder.ever_populated()
    assert "wa_inner_version" in populated
    assert "cell_id" in populated
    # Derived rather than read: the eNodeB falls out of the cell identity.
    assert "enodeb_id" in populated


def test_a_boolean_entity_needs_its_key_to_count_as_populated(
    recorder: ObservationRecorder,
) -> None:
    """A boolean value function answers `False` for any input.

    Calling it proves nothing about the router: nine entities entered this set
    on the first poll of a device that had said nothing at all, which would
    have made `enable_populated` turn on every switch and binary sensor
    regardless of the hardware. They are judged by whether a key they read is
    present, the same rule the switch platform uses for availability.
    """
    from custom_components.zte_router_5g.binary_sensor import BINARY_SENSORS
    from custom_components.zte_router_5g.switch import SWITCH_TYPES

    booleans = {d.key for types in (BINARY_SENSORS, SWITCH_TYPES) for d in types}

    assert not entity_keys_with_values({}) & booleans


def test_a_boolean_entity_with_its_key_present_does_count(
    recorder: ObservationRecorder,
) -> None:
    """The guard must not lock the boolean platforms out altogether."""
    found = entity_keys_with_values({"upnpEnabled": "0"})

    assert "upnp_enabled" in found


def test_the_populated_set_only_ever_grows(recorder: ObservationRecorder) -> None:
    """A degraded poll must not erase what protects an entity from a reset."""
    recorder.observe(_poll(), DEVICE)
    before = recorder.ever_populated()

    assert recorder.observe({"wa_inner_version": "V1.0.0B01"}, DEVICE) is False
    assert recorder.ever_populated() == before


def test_the_populated_history_reports_how_much_it_knows(
    recorder: ObservationRecorder,
) -> None:
    """An empty record silently disables the reset action's safe default.

    The caller has to be able to say the filter filtered nothing rather than
    present a list that looks protected.
    """
    assert recorder.populated_history() == {
        "entities_known_populated": 0,
        "recording_since": None,
    }

    recorder.observe(_poll(), DEVICE)

    reported = recorder.populated_history()
    assert reported["entities_known_populated"] > 0
    assert reported["recording_since"] is not None


def test_a_description_with_no_value_function_is_skipped(
    recorder: ObservationRecorder,
) -> None:
    """`value_fn` is optional on a switch description.

    Nothing in the shipped catalogue leaves it unset, but the type allows it,
    and calling `None` here would raise inside the broad catch below and hide
    a real programming error behind a swallowed exception.
    """
    valueless = MagicMock(key="valueless", value_fn=None, state_keys=())
    with patch(
        "custom_components.zte_router_5g.switch.SWITCH_TYPES",
        (valueless,),
    ):
        recorder.observe(_poll(), DEVICE)

    assert "valueless" not in recorder.ever_populated()


def test_a_description_that_raises_does_not_stop_the_poll(
    recorder: ObservationRecorder,
) -> None:
    """This runs on every poll purely to note what reported something.

    An entity whose `value_fn` cannot cope with an odd payload is that
    entity's own problem and is surfaced where it lives; letting it escape
    here would mean one bad description stopped every record being kept.
    """
    # `state_keys` is set explicitly: a bare MagicMock iterates as empty,
    # so the boolean guard above would skip this description before its
    # value function was ever called, and the test would prove nothing.
    broken = MagicMock(
        key="broken", value_fn=MagicMock(side_effect=ValueError), state_keys=()
    )
    with patch(
        "custom_components.zte_router_5g.sensor.SENSOR_TYPES",
        (broken,),
    ):
        assert recorder.observe(_poll(), DEVICE) is True

    assert "broken" not in recorder.ever_populated()


# ---------------------------------------------------------------------------
# The saved snapshot
# ---------------------------------------------------------------------------


def test_no_snapshot_reads_as_an_empty_baseline(
    recorder: ObservationRecorder,
) -> None:
    """Empty is what `reset_entities` turns into an error, not a silent no-op."""
    assert recorder.snapshot() == {}


async def test_a_saved_snapshot_comes_back(recorder: ObservationRecorder) -> None:
    """The user's own baseline, kept beside the populated record."""
    recorder.observe(_poll(), DEVICE)

    await recorder.async_save_snapshot({"lte_rsrp": True, "imei": False})

    assert recorder.snapshot() == {"lte_rsrp": True, "imei": False}
    recorder._observed_store.async_save.assert_awaited()


async def test_a_snapshot_belongs_to_one_device(
    recorder: ObservationRecorder,
) -> None:
    """Same shape as the other records, and the same reason."""
    recorder.observe(_poll(), "imei-1")
    await recorder.async_save_snapshot({"lte_rsrp": True})

    recorder.device_id = "imei-2"
    assert recorder.snapshot() == {}


async def test_a_corrupt_snapshot_reads_as_absent(
    recorder: ObservationRecorder,
) -> None:
    """A hand-edited store must not become a crash on the next reset."""
    recorder._observed_store.async_load.return_value = {
        DEVICE: {"snapshot": "not a mapping"}
    }
    await recorder.async_load()
    recorder.device_id = DEVICE

    assert recorder.snapshot() == {}


# ---------------------------------------------------------------------------
# What a loaded record does on the next poll
# ---------------------------------------------------------------------------

def _stored_history() -> dict[str, Any]:
    """A history record as the store holds one, freshly built each time.

    A function rather than a literal: the recorder appends into the record
    it loaded, so a shared dict carries one test's transitions into the
    next.
    """
    return {
        DEVICE: {
            "wan_ipaddr": [
                {
                    "timestamp": "2026-09-06T02:11:04+00:00",
                    "from": None,
                    "to": "10.52.24.68",
                },
                {
                    "timestamp": "2026-09-09T04:22:51+00:00",
                    "from": "10.52.24.68",
                    "to": "10.48.27.76",
                },
            ]
        }
    }


async def test_a_loaded_history_survives_a_poll_that_changes_nothing(
    recorder: ObservationRecorder,
) -> None:
    """This is "history survives a restart", and it was unasserted.

    A recorder that re-seeded on load would append a third entry here, with
    `from: None`, and the series would restart at every Home Assistant
    restart while still looking well-formed in the file.
    """
    recorder._history_store.async_load.return_value = _stored_history()
    await recorder.async_load()

    assert recorder.observe(_poll(wan_ipaddr="10.48.27.76"), DEVICE) is True

    entries = recorder.history("wan_ipaddr")
    assert len(entries) == 2
    assert entries[-1]["to"] == "10.48.27.76"


async def test_a_transition_after_a_load_chains_onto_the_stored_value(
    recorder: ObservationRecorder,
) -> None:
    """The new entry's `from` is what the store held, not `None`.

    An unbroken chain across a restart is the property the production store
    demonstrated over four transitions between 2026-09-06 and 2026-09-14.
    """
    recorder._history_store.async_load.return_value = _stored_history()
    await recorder.async_load()

    recorder.observe(_poll(wan_ipaddr="10.52.32.15"), DEVICE)

    entries = recorder.history("wan_ipaddr")
    assert len(entries) == 3
    assert entries[-1]["from"] == "10.48.27.76"
    assert entries[-1]["to"] == "10.52.32.15"


async def test_a_failed_load_re_seeds_every_tracked_key(
    recorder: ObservationRecorder,
) -> None:
    """The consequence of a lost record, which stops at setup elsewhere.

    `test_an_unreadable_store_resolves_to_nothing_learned` asserts the entry
    survives and the history reads empty. This is what the next poll then
    writes: a fresh series for every tracked key, with nothing to say a series
    ever preceded it.
    """
    recorder._history_store.async_load.side_effect = OSError("disk gone")
    await recorder.async_load()

    recorder.observe(_poll(), DEVICE)

    for key in TRACKED:
        entries = recorder.history(key)
        assert len(entries) == 1
        assert entries[0]["from"] is None


# ---------------------------------------------------------------------------
# Saying so afterwards
# ---------------------------------------------------------------------------


async def test_a_read_fault_is_counted_and_carried_across_restarts(
    recorder: ObservationRecorder,
) -> None:
    """A lost record and a record that could not be read look alike.

    They mean opposite things, and the count is what separates them. It is
    written back into the observed store so a fault survives the restart it
    caused.
    """
    recorder._history_store.async_load.side_effect = OSError("disk gone")
    await recorder.async_load()
    recorder.observe(_poll(), DEVICE)
    await recorder.async_save()

    assert recorder.report()["load_faults"] == 1
    saved = recorder._observed_store.async_save.await_args.args[0]
    assert saved[META_KEY] == {"load_faults": 1}


async def test_a_carried_count_is_added_to_this_run_s_faults(
    recorder: ObservationRecorder,
) -> None:
    """Two faults across two runs read as two, not as one."""
    recorder._observed_store.async_load.return_value = {META_KEY: {"load_faults": 1}}
    recorder._history_store.async_load.side_effect = OSError("disk gone")

    await recorder.async_load()

    assert recorder.report()["load_faults"] == 2


async def test_a_hand_edited_meta_record_reads_as_no_faults(
    recorder: ObservationRecorder,
) -> None:
    """The store is a file on disk; a bad shape must not become a crash."""
    recorder._observed_store.async_load.return_value = {META_KEY: "not a mapping"}

    await recorder.async_load()

    assert recorder.report()["load_faults"] == 0


async def test_the_report_describes_each_series_without_its_values(
    recorder: ObservationRecorder,
) -> None:
    """A reset store shows as recent entries against an older start date.

    Values are excluded deliberately: the tracked keys are addresses and
    identifiers, and this section is published in a file written to be
    attached to a public issue.
    """
    recorder._history_store.async_load.return_value = _stored_history()
    await recorder.async_load()
    recorder.observe(_poll(wan_ipaddr="10.52.32.15"), DEVICE)

    report = recorder.report()

    assert report["series"]["wan_ipaddr"]["entries"] == 3
    assert report["series"]["wan_ipaddr"]["oldest"] == "2026-09-06T02:11:04+00:00"
    assert report["series"]["wan_ipaddr"]["newest"] > "2026-09-06T02:11:04+00:00"
    assert report["change_counts"]["wan_ipaddr"] == 1
    assert report["recording_since"] is not None
    assert "10.52.32.15" not in str(report)


async def test_a_series_with_no_entries_reports_no_dates(
    recorder: ObservationRecorder,
) -> None:
    """An empty list is a series that exists and has recorded nothing."""
    recorder._history_store.async_load.return_value = {DEVICE: {"wan_apn": []}}
    await recorder.async_load()
    recorder.device_id = DEVICE

    series = recorder.report()["series"]["wan_apn"]

    assert series == {"entries": 0, "oldest": None, "newest": None}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


async def test_an_unreadable_store_resolves_to_nothing_learned(
    recorder: ObservationRecorder,
) -> None:
    """No storage fault may fail entry setup.

    The same contract the uptime store holds: everything here is advisory, and
    a coordinator works perfectly well with no history at all.
    """
    recorder._history_store.async_load.side_effect = OSError("disk gone")

    await recorder.async_load()

    assert recorder.history("wa_inner_version") == []
    assert recorder.ever_populated() == frozenset()


async def test_a_store_holding_something_other_than_a_dict_is_ignored(
    recorder: ObservationRecorder,
) -> None:
    """A truncated or hand-edited file must not become a crash."""
    recorder._history_store.async_load.return_value = ["not", "a", "dict"]

    await recorder.async_load()

    assert recorder.history("wa_inner_version") == []


async def test_one_unwritable_store_does_not_skip_the_other(
    recorder: ObservationRecorder,
) -> None:
    """A failed save loses a record, not a poll — and not the other record.

    The two stores are written in one pass, so a fault in the first must not
    stop the second from reaching disk.
    """
    recorder._history_store.async_save.side_effect = OSError("read-only")
    recorder.observe(_poll(), DEVICE)

    await recorder.async_save()

    recorder._history_store.async_save.assert_awaited_once()
    recorder._observed_store.async_save.assert_awaited_once()


async def test_both_files_are_removed_with_the_entry(
    recorder: ObservationRecorder,
) -> None:
    """Neither store is cleaned up by Home Assistant when the entry goes."""
    await recorder.async_remove()

    recorder._history_store.async_remove.assert_awaited_once()
    recorder._observed_store.async_remove.assert_awaited_once()


async def test_one_unremovable_store_does_not_skip_the_other(
    recorder: ObservationRecorder,
) -> None:
    """Entry removal must complete even if a file cannot be unlinked.

    Leaving one file behind is untidy; leaving both because the first threw
    is the failure worth testing.
    """
    recorder._history_store.async_remove.side_effect = OSError("locked")

    await recorder.async_remove()

    recorder._observed_store.async_remove.assert_awaited_once()


async def test_session_lifetimes_round_trip(hass, mock_config_entry) -> None:
    """What this device's sessions lasted, kept across a restart.

    Re-learning after every restart costs one expiry per restart — a failed
    request, a login and a retry — for a value the device has already taught us.
    """
    recorder = ObservationRecorder(hass, mock_config_entry)
    await recorder.async_load()

    assert recorder.session_lifetimes() == []

    await recorder.async_save_session_lifetimes([120.0, 95.5])

    assert recorder.session_lifetimes() == [120.0, 95.5]


async def test_an_unreadable_lifetime_record_is_nothing_learned(
    hass, mock_config_entry
) -> None:
    """Advisory, like every other record here.

    A corrupt entry must route the pre-write reset back to the idle constant it
    has always used, not fail setup and not produce a threshold from nonsense.
    """
    recorder = ObservationRecorder(hass, mock_config_entry)
    await recorder.async_load()
    recorder._observed.setdefault(recorder.device_id, {})["session_lifetimes"] = (
        "not a list"
    )

    assert recorder.session_lifetimes() == []
