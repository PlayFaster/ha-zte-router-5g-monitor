"""Ordering messages by the moment they carry, rather than by their text.

Two changes meet here. A message's timestamp now carries its router's own
offset instead of a fabricated `UTC`, and a message the router dates
unreadably has to be placed somewhere. Both are ordering questions, and both
decide what a destructive command does.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.zte_router_5g import _messages_beyond_the_newest
from custom_components.zte_router_5g.const import DOMAIN
from custom_components.zte_router_5g.coordinator import ZTERouterDataUpdateCoordinator


def _msg(msg_id: str, date: str | None) -> dict[str, str]:
    """A message carrying an id and, usually, a decoded date."""
    entry = {"id": msg_id, "number_decoded": "+10", "content_decoded": "hi"}
    if date is not None:
        entry["date_decoded"] = date
    return entry


# --- what `keep_last` keeps -------------------------------------------------


def test_the_newest_dated_messages_are_the_ones_kept() -> None:
    """Ids are per-bank, so they cannot order a list drawn from both.

    The router's `mem_store="2"` returns one list with no field naming which
    bank a message came from, and id `3` on the SIM is not id `3` in device
    memory. Only the moment each message carries orders them.
    """
    messages = [
        _msg("1", "2026-09-05T12:00:00+00:00"),
        _msg("9", "2026-09-01T08:00:00+00:00"),
        _msg("4", "2026-09-04T23:00:00+00:00"),
    ]

    to_delete = _messages_beyond_the_newest(messages, 2, "router")

    assert [msg["id"] for msg in to_delete] == ["9"]


def test_an_undated_message_is_deleted_before_a_dated_one() -> None:
    """It is not known to be recent, so it is not one of the newest."""
    messages = [
        _msg("1", None),
        _msg("2", "2026-09-01T08:00:00+00:00"),
        _msg("3", "2026-09-05T12:00:00+00:00"),
    ]

    to_delete = _messages_beyond_the_newest(messages, 2, "router")

    assert [msg["id"] for msg in to_delete] == ["1"]


def test_keep_two_of_four_keeps_two_even_when_none_can_be_dated() -> None:
    """The count is honoured against every message, not the dated subset.

    Counting only dated messages would let `keep_last: 2` delete all four,
    which is not a partial answer to the request — it is the opposite of it.
    """
    messages = [_msg(str(i), None) for i in (4, 3, 2, 1)]

    to_delete = _messages_beyond_the_newest(messages, 2, "router")

    assert [msg["id"] for msg in to_delete] == ["2", "1"]


def test_undated_messages_are_reported(caplog) -> None:
    """Silence would make an id-ordered delete look date-ordered."""
    messages = [_msg("1", None), _msg("2", "2026-09-05T12:00:00+00:00")]

    with caplog.at_level(logging.WARNING):
        _messages_beyond_the_newest(messages, 1, "router")

    assert "no readable date" in caplog.text


def test_keeping_more_than_are_there_deletes_nothing() -> None:
    """`keep_last: 10` against three messages is not a request to delete."""
    messages = [_msg("1", "2026-09-05T12:00:00+00:00"), _msg("2", None)]

    assert _messages_beyond_the_newest(messages, 10, "router") == []


# --- what counts as a new message -------------------------------------------


def _coordinator(hass) -> ZTERouterDataUpdateCoordinator:
    """A coordinator with no router behind it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"imei": "1"},
        options={
            CONF_HOST: "192.168.0.1",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "password",
        },
    )
    entry.add_to_hass(hass)
    return ZTERouterDataUpdateCoordinator(hass, entry, AsyncMock())


async def test_the_baseline_is_the_latest_instant_not_the_latest_text(hass) -> None:
    """Text order and time order part company at a daylight-saving change.

    Both messages below are the same evening. The first sorts later as text
    because `02:30` beats `02:00`, and earlier in time because its offset is
    an hour further ahead. While every timestamp carried a fabricated `+00:00`
    the two orders agreed and the string comparison was harmless; carrying the
    router's real offset, it is not.
    """
    coordinator = _coordinator(hass)

    earlier_but_later_text = _msg("1", "2026-10-25T02:30:00+02:00")
    later_but_earlier_text = _msg("2", "2026-10-25T02:00:00+01:00")

    fired = async_capture_events(hass, "zte_router_5g_sms_received")
    coordinator._check_new_sms([earlier_but_later_text, later_but_earlier_text])
    await hass.async_block_till_done()

    assert coordinator.last_sms_timestamp == "2026-10-25T02:00:00+01:00"
    assert coordinator.fired_sms_hashes == {"2_2026-10-25T02:00:00+01:00"}
    assert fired == []


async def test_a_message_dated_unreadably_fires_nothing(hass) -> None:
    """`_parse_date` returns the router's string unchanged when it cannot read it.

    Such a message cannot be placed against the baseline at all, so it is
    treated as undated — the same outcome the empty-date filter has always
    produced, reached by the same rule.
    """
    coordinator = _coordinator(hass)
    coordinator.last_sms_timestamp = "2026-09-01T00:00:00+00:00"

    fired = async_capture_events(hass, "zte_router_5g_sms_received")
    coordinator._check_new_sms([_msg("1", "26,09,05,12,18,07,+4")])
    await hass.async_block_till_done()

    assert fired == []
    assert coordinator.last_sms_timestamp == "2026-09-01T00:00:00+00:00"


async def test_a_genuinely_newer_message_still_fires(hass) -> None:
    """The guard against fixing the above by never firing at all."""
    coordinator = _coordinator(hass)
    coordinator.last_sms_timestamp = "2026-09-01T00:00:00+00:00"

    fired = async_capture_events(hass, "zte_router_5g_sms_received")
    coordinator._check_new_sms([_msg("7", "2026-09-05T12:00:00+01:00")])
    await hass.async_block_till_done()

    assert len(fired) == 1
    assert fired[0].data["index"] == 7
    assert coordinator.last_sms_timestamp == "2026-09-05T12:00:00+01:00"


# --- the delete record outliving a restart ----------------------------------
#
# The record lives on the API object, so a Home Assistant restart erased it.
# Issue #56 turned on exactly that: the reporter pressed Delete All, restarted,
# downloaded diagnostics, and the section read `null` — the router's answer to
# the delete was gone, which was the one thing the download was wanted for.


def _entry_with(hass, **data):
    """A config entry carrying whatever extra keys a test needs."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"imei": "1", **data},
        options={
            CONF_HOST: "192.168.0.1",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "password",
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_a_stored_delete_record_is_restored_onto_the_api(hass) -> None:
    """Setting up again after a restart brings the last attempt back."""
    stored = {"ids_requested": ["4"], "ids_surviving": ["4"], "result": None}
    api = AsyncMock()
    api.last_delete = None

    ZTERouterDataUpdateCoordinator(hass, _entry_with(hass, last_delete=stored), api)

    assert api.last_delete == stored


async def test_a_stored_record_of_the_wrong_shape_is_ignored(hass) -> None:
    """Hand-edited or older entry data must not break setup."""
    api = AsyncMock()
    api.last_delete = None

    ZTERouterDataUpdateCoordinator(hass, _entry_with(hass, last_delete="rubbish"), api)

    assert api.last_delete is None


async def test_the_delete_record_is_written_into_the_entry(hass) -> None:
    """What the delete routes call, so the record survives the next restart."""
    entry = _entry_with(hass)
    api = AsyncMock()
    api.last_delete = {"ids_requested": ["2"], "ids_surviving": ["2"]}
    coordinator = ZTERouterDataUpdateCoordinator(hass, entry, api)

    coordinator.persist_last_delete()
    await hass.async_block_till_done()

    assert entry.data["last_delete"] == {"ids_requested": ["2"], "ids_surviving": ["2"]}
    assert entry.data["imei"] == "1"


async def test_no_attempt_writes_nothing(hass) -> None:
    """Called on a route that never reached the router; there is nothing to keep."""
    entry = _entry_with(hass)
    api = AsyncMock()
    api.last_delete = None
    coordinator = ZTERouterDataUpdateCoordinator(hass, entry, api)

    coordinator.persist_last_delete()
    await hass.async_block_till_done()

    assert "last_delete" not in entry.data
