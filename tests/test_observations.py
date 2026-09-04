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
    TRACKED,
    ObservationRecorder,
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
    valueless = MagicMock(key="valueless", value_fn=None)
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
    broken = MagicMock(key="broken", value_fn=MagicMock(side_effect=ValueError))
    with patch(
        "custom_components.zte_router_5g.sensor.SENSOR_TYPES",
        (broken,),
    ):
        assert recorder.observe(_poll(), DEVICE) is True

    assert "broken" not in recorder.ever_populated()


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
