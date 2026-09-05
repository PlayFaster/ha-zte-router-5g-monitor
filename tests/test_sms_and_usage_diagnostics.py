"""The two diagnostics sections added for issue #56.

Both exist because a value alone did not settle either fault. The SMS section
answers "how many messages will this router actually hand over", which is what
`delete_all` operates on; the usage section answers "do this device's own byte
counters agree with its own clocks", which is what four downloads of hand
arithmetic established that an MC888 Pro's did not.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.zte_router_5g.api import ZTEConnectionError, ZTERouterAPI
from custom_components.zte_router_5g.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import MockResponse

# A message as the router serves it: hex content, hex sender, comma date.
_MESSAGE = {
    "id": "3",
    "content": "0041",
    "number": "002b0031",
    "tag": "0",
    "date": "26,08,09,21,24,52,0",
    "content_decoded": "A",
    "number_decoded": "+1",
    "date_decoded": "2026-08-09T21:24:52+00:00",
}


def _coordinator(mock_coordinator, *, messages: list[dict] | None) -> MagicMock:
    """A coordinator whose SMS snapshot returns `messages`."""
    mock_coordinator.async_fetch_sms_snapshot = AsyncMock(return_value=messages)
    mock_coordinator.last_sms_timestamp = "2026-08-09T21:24:52+00:00"
    mock_coordinator.fired_sms_hashes = {"3_2026-08-09T21:24:52+00:00"}
    mock_coordinator.api.last_delete = None
    return mock_coordinator


async def test_the_sms_section_reports_what_the_router_will_hand_over(
    mock_coordinator, mock_config_entry
):
    """The count, the ids, and the router's own totals, side by side.

    The comparison is the point: `sms_nv_rev_total` is what the router claims
    it holds and `message_count` is what it will serve. `delete_all` can only
    delete the second, so the two disagreeing and the two agreeing are
    opposite faults with opposite fixes.
    """
    mock_coordinator.data = {"sms_nv_rev_total": "2", "sms_nv_total": "100"}
    mock_config_entry.runtime_data = _coordinator(mock_coordinator, messages=[_MESSAGE])

    sms = (await async_get_config_entry_diagnostics(None, mock_config_entry))["sms"]

    assert sms["fetched"] is True
    assert sms["message_count"] == 1
    assert sms["ids"] == ["3"]
    assert sms["capacity_counters"] == {"sms_nv_rev_total": "2", "sms_nv_total": "100"}
    assert sms["event_tracker"]["fired_hashes"] == 1


async def test_no_message_body_or_sender_reaches_the_sms_section(
    mock_coordinator, mock_config_entry
):
    """Third-party content, in a file attached to a public issue.

    The section publishes a whole list where `last_sms` published one message,
    so the sanitizer has to run over every entry. Both encodings of the sender
    must resolve to one pseudonym, or the file reads as two different people.
    """
    mock_coordinator.data = {}
    mock_config_entry.runtime_data = _coordinator(mock_coordinator, messages=[_MESSAGE])

    result = await async_get_config_entry_diagnostics(None, mock_config_entry)
    published = result["sms"]["messages"][0]

    assert "A" not in str(published["content_decoded"])
    assert published["content"] == "<content: 4 chars>"
    assert published["number"] == published["number_decoded"]
    assert published["number"].startswith("phone-")
    assert "+1" not in str(result["sms"])
    # The metadata that makes a message diagnosable is kept.
    assert published["id"] == "3"
    assert published["tag"] == "0"


async def test_a_message_with_no_parsable_date_is_counted(
    mock_coordinator, mock_config_entry
):
    """`_check_new_sms` drops those before sorting and says nothing.

    A message the event tracker cannot see is invisible everywhere else too,
    so the count is the only trace it leaves.
    """
    mock_coordinator.data = {}
    undated = dict(_MESSAGE, id="4", date_decoded="")
    mock_config_entry.runtime_data = _coordinator(
        mock_coordinator, messages=[_MESSAGE, undated]
    )

    sms = (await async_get_config_entry_diagnostics(None, mock_config_entry))["sms"]

    assert sms["message_count"] == 2
    assert sms["undated_messages"] == 1


async def test_a_failed_sms_fetch_is_recorded_not_raised(
    mock_coordinator, mock_config_entry
):
    """Home Assistant does not guard `config_entry_diagnostics`.

    An exception escaping is an HTTP 500 and no file at all — and a router
    that refuses the message list is exactly the device a download is being
    requested for.
    """
    mock_coordinator.data = {}
    mock_coordinator.last_sms_timestamp = None
    mock_coordinator.fired_sms_hashes = set()
    mock_coordinator.api.last_delete = None
    mock_coordinator.async_fetch_sms_snapshot = AsyncMock(
        side_effect=ZTEConnectionError("refused")
    )
    mock_config_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(None, mock_config_entry)

    assert result["sms"]["fetched"] is False
    assert result["sms"]["message_count"] == 0
    assert any("sms" in note for note in result["errors"])


async def test_the_delete_record_reaches_the_download(
    mock_coordinator, mock_config_entry
):
    """The only evidence a refused delete leaves.

    This API answers `{"result": "success"}` for a message id it does not
    hold, so the result alone proves nothing — what was asked for, beside what
    survived, is the whole finding.
    """
    mock_coordinator.data = {}
    mock_config_entry.runtime_data = _coordinator(mock_coordinator, messages=[])
    mock_coordinator.api.last_delete = {
        "ids_requested": ["2", "3"],
        "result": {"result": "success"},
        "ids_surviving": ["2", "3"],
    }

    sms = (await async_get_config_entry_diagnostics(None, mock_config_entry))["sms"]

    assert sms["last_delete"]["ids_requested"] == ["2", "3"]
    assert sms["last_delete"]["ids_surviving"] == ["2", "3"]


# --- the usage section ------------------------------------------------------


_BARE_USAGE = {
    "monthly_rx_bytes": "800",
    "monthly_tx_bytes": "200",
    "monthly_time": "100",
    "realtime_rx_bytes": "80",
    "realtime_tx_bytes": "20",
    "realtime_time": "10",
    "boot_time": "2026-09-05T00:00:00+00:00",
}

_FLUX_USAGE = {
    "flux_monthly_rx_bytes": "800",
    "flux_monthly_tx_bytes": "200",
    "flux_monthly_time": "100",
    "flux_realtime_rx_bytes": "80",
    "flux_realtime_tx_bytes": "20",
    "flux_realtime_time": "10",
}


@pytest.mark.parametrize(
    ("payload", "expected_spelling"),
    [
        (_BARE_USAGE, "monthly_rx_bytes"),
        (_FLUX_USAGE, "flux_monthly_rx_bytes"),
    ],
)
async def test_the_usage_section_records_which_spelling_answered(
    mock_coordinator, mock_config_entry, payload, expected_spelling
):
    """Two vocabularies, one section.

    The MC7010 answers the bare names and the MC888 Pro the `flux_` ones, and
    which of the two a device speaks is a fact about the device rather than
    something to infer from a page of blanks.
    """
    mock_coordinator.data = dict(payload)
    mock_config_entry.runtime_data = _coordinator(mock_coordinator, messages=[])

    usage = (await async_get_config_entry_diagnostics(None, mock_config_entry))[
        "data_usage"
    ]

    assert usage["spelling_used"]["monthly_rx_bytes"] == expected_spelling
    assert usage["monthly"]["total_bytes"] == 1000
    assert usage["monthly"]["total_bytes_per_second"] == 10
    assert usage["session"]["total_bytes_per_second"] == 10
    # Both counters describing the same traffic sit at 1.
    assert usage["monthly_rate_over_session_rate"] == 1


async def test_the_rate_ratio_states_a_disagreement(
    mock_coordinator, mock_config_entry
):
    """The number that would have made issue #56 visible in one file.

    A month accumulating far faster than the session it contains is the shape
    of the fault. Nothing here judges it — the ratio is reported, never
    flagged, because which counter is wrong is not decidable from the device.
    """
    mock_coordinator.data = dict(_FLUX_USAGE, flux_realtime_rx_bytes="8")
    mock_config_entry.runtime_data = _coordinator(mock_coordinator, messages=[])

    usage = (await async_get_config_entry_diagnostics(None, mock_config_entry))[
        "data_usage"
    ]

    assert usage["session"]["total_bytes_per_second"] == 2.8
    assert usage["monthly_rate_over_session_rate"] == pytest.approx(3.571, abs=0.001)


@pytest.mark.parametrize("elapsed", ["0", "", None])
async def test_a_zero_or_absent_clock_yields_no_rate(
    mock_coordinator, mock_config_entry, elapsed
):
    """A router polled in the first second of a cycle reports zero elapsed.

    That is the ordinary case, not an error, and it must not divide.
    """
    payload = dict(_FLUX_USAGE)
    if elapsed is None:
        del payload["flux_monthly_time"]
    else:
        payload["flux_monthly_time"] = elapsed
    mock_coordinator.data = payload
    mock_config_entry.runtime_data = _coordinator(mock_coordinator, messages=[])

    usage = (await async_get_config_entry_diagnostics(None, mock_config_entry))[
        "data_usage"
    ]

    assert usage["monthly"]["total_bytes_per_second"] is None
    assert usage["monthly_rate_over_session_rate"] is None
    # The totals still stand; only the rate is undecidable.
    assert usage["monthly"]["total_bytes"] == 1000


async def test_a_device_answering_neither_spelling_still_produces_the_section(
    mock_coordinator, mock_config_entry
):
    """The section must not depend on the device supporting any of it."""
    mock_coordinator.data = {"network_type": "5G"}
    mock_config_entry.runtime_data = _coordinator(mock_coordinator, messages=[])

    usage = (await async_get_config_entry_diagnostics(None, mock_config_entry))[
        "data_usage"
    ]

    assert set(usage["spelling_used"].values()) == {None}
    assert usage["monthly"]["total_bytes"] is None
    assert usage["monthly_rate_over_session_rate"] is None


@pytest.mark.parametrize(
    "boot_time",
    [
        # The live shape. `coordinator.py:617` assigns `self._boot_time`, a
        # `datetime`, and it only reads as a string once a JSON encoder has
        # been over it — which is after this section is built. Accepting only
        # the string form published `uptime_seconds: null` from an MC7010
        # whose every other figure in the section was correct.
        datetime(2026, 9, 5, 0, 0, 0, tzinfo=UTC),
        "2026-09-05T00:00:00+00:00",
    ],
)
async def test_the_session_is_measured_against_the_boot_instant(
    mock_coordinator, mock_config_entry, boot_time
):
    """Both models measured report the session as time since reboot.

    Stating it beside the counter saves the next reader deriving it from two
    timestamps, which is how it was established the first time.
    """
    mock_coordinator.data = dict(_BARE_USAGE, boot_time=boot_time)
    mock_coordinator.last_update_success_time = MagicMock()
    mock_coordinator.last_update_success_time.isoformat.return_value = (
        "2026-09-05T00:00:10+00:00"
    )
    mock_config_entry.runtime_data = _coordinator(mock_coordinator, messages=[])

    usage = (await async_get_config_entry_diagnostics(None, mock_config_entry))[
        "data_usage"
    ]

    assert usage["uptime_seconds"] == 10
    assert usage["session"]["elapsed_seconds"] == 10


@pytest.mark.parametrize(
    "boot_time",
    [
        "up 3 days",  # not a timestamp at all
        123,  # not a timestamp and not a string
        datetime(2026, 9, 5, 0, 0, 0),  # naive: subtracting raises TypeError
    ],
)
async def test_a_boot_time_that_is_not_usable_yields_no_uptime(
    mock_coordinator, mock_config_entry, boot_time
):
    """`boot_time` is the router's, by way of the payload sanitizer.

    A firmware that answers it in some other format, a sweep that rewrites it,
    or a naive instant that cannot be subtracted from an aware one must cost
    the section its uptime figure and nothing else — the whole download is
    serialized at the end, so an exception here is an HTTP 500 and no file at
    all. A naive value must not silently produce a wrong figure either.
    """
    mock_coordinator.data = dict(_BARE_USAGE, boot_time=boot_time)
    mock_coordinator.last_update_success_time = MagicMock()
    mock_coordinator.last_update_success_time.isoformat.return_value = (
        "2026-09-05T00:00:10+00:00"
    )
    mock_config_entry.runtime_data = _coordinator(mock_coordinator, messages=[])

    usage = (await async_get_config_entry_diagnostics(None, mock_config_entry))[
        "data_usage"
    ]

    assert usage["uptime_seconds"] is None
    assert usage["session"]["elapsed_seconds"] == 10


# --- the coordinator method and the delete verification ---------------------


async def test_the_sms_snapshot_is_taken_under_the_update_lock(mock_coordinator):
    """The router permits one session, and this shares the poll's API client.

    An unsynchronized read can re-login underneath a poll and invalidate the
    cookie it is using — the reason `async_run_discovery` takes the same lock.
    """
    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    coordinator = MagicMock(spec=ZTERouterDataUpdateCoordinator)
    coordinator._async_update_lock = asyncio.Lock()
    coordinator.api = MagicMock()
    held: list[bool] = []

    async def _listing(**_kwargs):
        held.append(coordinator._async_update_lock.locked())
        return [{"id": "1"}]

    coordinator.api.get_sms_messages = AsyncMock(side_effect=_listing)

    result = await ZTERouterDataUpdateCoordinator.async_fetch_sms_snapshot(coordinator)

    assert result == [{"id": "1"}]
    assert held == [True], "the bank was read without holding the update lock"
    assert not coordinator._async_update_lock.locked(), "the lock was not released"


async def test_delete_all_raises_when_the_router_keeps_a_message(mock_aiohttp_client):
    """A delete this API reports as successful, having done nothing.

    Measured on an MC7010 on 2026-09-05: `DELETE_SMS` answers
    `{"result": "success"}` for an id the router does not hold, so
    `_require_success` cannot distinguish a refusal. Issue #56 is that shape
    on an MC888 Pro, and without this check the button reports done.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    mock_aiohttp_client.post.side_effect = [
        MockResponse(json_data={"messages": [{"id": "1"}, {"id": "2"}]}),
        MockResponse(json_data={"result": "success"}),
        MockResponse(json_data={"messages": [{"id": "2"}]}),
    ]

    with (
        patch.object(api, "login"),
        patch.object(api, "get_ad", return_value="ad"),
        pytest.raises(ZTEConnectionError, match="kept 1 of 2"),
    ):
        await api.delete_all()

    assert api.last_delete["ids_requested"] == ["1", "2"]
    assert api.last_delete["ids_surviving"] == ["2"]


async def test_a_message_arriving_during_the_delete_is_not_a_failure(
    mock_aiohttp_client,
):
    """The check is against the ids this call asked for, not against emptiness.

    An inbox that is non-empty afterwards because something arrived in the
    meantime has not failed to delete anything.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    mock_aiohttp_client.post.side_effect = [
        MockResponse(json_data={"messages": [{"id": "1"}]}),
        MockResponse(json_data={"result": "success"}),
        MockResponse(json_data={"messages": [{"id": "9"}]}),
    ]

    with patch.object(api, "login"), patch.object(api, "get_ad", return_value="ad"):
        assert await api.delete_all() == 200

    assert api.last_delete["ids_surviving"] == []


async def test_survivors_recorded_against_no_attempt_are_dropped(
    mock_aiohttp_client,
):
    """The guard on held state, exercised rather than assumed away.

    `_record_delete` always runs first through `delete_all`, so this branch is
    unreachable by that route today. It is held state and not a local, which
    is exactly where the "impossible" shape turns up once something upstream
    changes — and the cost of being wrong is an exception thrown while a
    diagnostics download is being built.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    api._record_delete_survivors(["1"])

    assert api.last_delete is None


async def test_an_empty_bank_deletes_nothing_and_verifies_nothing(
    mock_aiohttp_client,
):
    """Nothing to remove is a success, and must cost no extra request."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    mock_aiohttp_client.post.return_value = MockResponse(json_data={"messages": []})

    with patch.object(api, "login"):
        assert await api.delete_all() == 200

    assert api.last_delete is None
    assert mock_aiohttp_client.post.call_count == 1
