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

from custom_components.zte_router_5g import api as api_module
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


def _coordinator(
    mock_coordinator, *, messages: list[dict] | None, sim: list[dict] | None = None
) -> MagicMock:
    """A coordinator whose SMS snapshot returns `messages`."""
    snapshot = None if messages is None else {"all": messages, "sim": sim or []}
    mock_coordinator.async_fetch_sms_snapshot = AsyncMock(return_value=snapshot)
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
        # Naive: subtracting it from an aware instant raises TypeError. Built
        # by parsing rather than by constructor, which `DTZ001` rejects for
        # exactly the reason this case exists.
        datetime.fromisoformat("2026-09-05T00:00:00"),
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

    async def _listing(*, mem_store, **_kwargs):
        held.append(coordinator._async_update_lock.locked())
        return [{"id": "1"}] if mem_store == "2" else []

    coordinator.api.get_sms_messages = AsyncMock(side_effect=_listing)

    result = await ZTERouterDataUpdateCoordinator.async_fetch_sms_snapshot(coordinator)

    assert result == {"all": [{"id": "1"}], "sim": []}
    assert held == [True, True], "a bank was read without holding the update lock"
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

    # One pass, so this still asserts what it was written to assert: that a
    # surviving id is reported. The retry window added in `[3.3.23-dev1]` is
    # exercised by its own tests; widening it here would only make this test
    # slow, and the property under test is the verdict, not the timing.
    with (
        patch.object(api, "login"),
        patch.object(api, "get_ad", return_value="ad"),
        patch.object(api_module, "SMS_DELETE_VERIFY_SECONDS", 0),
        pytest.raises(ZTEConnectionError, match="kept 1 of 2"),
    ):
        await api.delete_all()

    assert api.last_delete["ids_requested"] == ["1", "2"]
    assert api.last_delete["ids_surviving"] == ["2"]
    assert api.last_delete["verify_settled"] is False


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


async def test_a_parameter_recorded_against_no_attempt_is_dropped(
    mock_aiohttp_client,
):
    """The same guard as below, on the same held state.

    `note_delete_parameter` runs after a delete today, so the record always
    exists by then. It is stored state rather than a local, and the cost of
    being wrong is an exception raised while a download is being built.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")

    api.note_delete_parameter(3)

    assert api.last_delete is None


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

    api._record_delete_survivors(["1"], [{"after_ms": 0, "remaining": ["1"]}])

    assert api.last_delete is None


async def test_the_sim_bank_is_reported_separately(mock_coordinator, mock_config_entry):
    """The only route to knowing whether `mem_store="2"` is really the union.

    The reference device has an empty SIM, so the question cannot be settled
    here. A reporter holding a SIM message settles it: the same count in both
    places means the union is real, and a SIM message absent from the combined
    list means `delete_all` is still missing messages.
    """
    mock_coordinator.data = {}
    on_sim = dict(_MESSAGE, id="9")
    mock_config_entry.runtime_data = _coordinator(
        mock_coordinator, messages=[_MESSAGE, on_sim], sim=[on_sim]
    )

    sms = (await async_get_config_entry_diagnostics(None, mock_config_entry))["sms"]

    assert sms["message_count"] == 2
    assert sms["sim_message_count"] == 1
    assert sms["sim_ids"] == ["9"]


async def test_the_delete_record_carries_the_keep_last_that_chose_the_targets(
    mock_aiohttp_client,
):
    """`keep_last` decides the target set and cannot be recovered afterwards.

    The ids say what was aimed at; reconstructing the parameter would need the
    bank contents at that moment, and a download reports them later.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    mock_aiohttp_client.post.side_effect = [
        MockResponse(json_data={"result": "success"}),
        MockResponse(json_data={"messages": []}),
    ]

    with patch.object(api, "login"), patch.object(api, "get_ad", return_value="ad"):
        await api.delete_sms("2;1")
        api.note_delete_parameter(3)
        await api.verify_deleted(["2", "1"])

    assert api.last_delete["keep_last"] == 3
    assert api.last_delete["ids_surviving"] == []


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


@pytest.mark.asyncio
async def test_a_slow_delete_is_not_reported_as_a_failure(mock_aiohttp_client):
    """The fault this release exists to remove.

    `{"result":"success"}` means the command was accepted, not carried out. On
    the MC888 Pro of issue #56 nine of ten requested ids were still listed at
    an immediate re-list and gone later, so the button reported a failure for a
    delete that worked. The check now re-lists until the window closes.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    mock_aiohttp_client.post.side_effect = [
        MockResponse(json_data={"messages": [{"id": "1"}, {"id": "2"}]}),
        MockResponse(json_data={"result": "success"}),
        # Two passes still show them, the third is clean.
        MockResponse(json_data={"messages": [{"id": "1"}, {"id": "2"}]}),
        MockResponse(json_data={"messages": [{"id": "2"}]}),
        MockResponse(json_data={"messages": []}),
    ]

    with (
        patch.object(api, "login"),
        patch.object(api, "get_ad", return_value="ad"),
        patch.object(api_module, "SMS_DELETE_VERIFY_INTERVAL", 0),
        patch.object(api, "_record_delete_command_status"),
    ):
        assert await api.delete_all() == 200

    assert api.last_delete["ids_surviving"] == []
    assert api.last_delete["verify_settled"] is True
    attempts = api.last_delete["verify_attempts"]
    assert [a["remaining"] for a in attempts] == [["1", "2"], ["2"], []], (
        "the series must record every pass, not just the last"
    )


@pytest.mark.asyncio
async def test_the_verification_window_is_bounded(mock_aiohttp_client):
    """A message that never goes is still a failure, reported as before.

    The window defers the verdict; it does not remove it. Without this the
    settle would turn the silent-success detection into a delay.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    listing = MockResponse(json_data={"messages": [{"id": "1"}]})
    mock_aiohttp_client.post.side_effect = [
        MockResponse(json_data={"messages": [{"id": "1"}]}),
        MockResponse(json_data={"result": "success"}),
        *[MockResponse(json_data={"messages": [{"id": "1"}]}) for _ in range(8)],
    ]
    assert listing is not None

    with (
        patch.object(api, "login"),
        patch.object(api, "get_ad", return_value="ad"),
        patch.object(api_module, "SMS_DELETE_VERIFY_INTERVAL", 0),
        patch.object(api_module, "SMS_DELETE_VERIFY_SECONDS", 0.0001),
        patch.object(api, "_record_delete_command_status"),
        pytest.raises(ZTEConnectionError, match="kept 1 of 1"),
    ):
        await api.delete_all()

    assert api.last_delete["verify_settled"] is False


@pytest.mark.asyncio
async def test_the_command_status_is_recorded_as_shape_not_content(
    mock_aiohttp_client,
):
    """`last_delete` reaches the download unsanitized, so only shape may go in.

    `sms_cmd_status_info` returns a `messages` list whose entries have never
    been observed on any device. Recording the payload could put message text
    into a file a reporter attaches to a public issue.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_delete = {}

    entry = {"id": "7", "content": "00480069", "state": "2"}
    with patch.object(
        api, "_request", new=AsyncMock(return_value={"messages": [entry]})
    ):
        await api._record_delete_command_status()

    status = api.last_delete["cmd_status"]
    assert status == {"entries": 1, "keys": ["content", "id", "state"]}
    assert "00480069" not in str(status), "a message body reached the record"


@pytest.mark.asyncio
async def test_an_unreadable_command_status_is_not_fatal(mock_aiohttp_client):
    """It runs after the router has already answered, so it may fail alone."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.last_delete = {}

    with patch.object(
        api, "_request", new=AsyncMock(side_effect=ZTEConnectionError("gone"))
    ):
        await api._record_delete_command_status()

    assert api.last_delete["cmd_status"] == {"unreadable": "ZTEConnectionError"}


@pytest.mark.asyncio
async def test_a_command_status_that_is_not_a_list_records_its_shape(
    mock_aiohttp_client,
):
    """No device has been seen answering this, so the other shape is covered."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.last_delete = {}

    with patch.object(api, "_request", new=AsyncMock(return_value={"state": "idle"})):
        await api._record_delete_command_status()

    assert api.last_delete["cmd_status"] == {"shape": "dict", "keys": ["state"]}


@pytest.mark.asyncio
async def test_the_status_record_is_skipped_with_no_delete_to_attach_it_to(
    mock_aiohttp_client,
):
    """Nothing to annotate means no read is taken."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.last_delete = None

    with patch.object(api, "_request", new=AsyncMock()) as request:
        await api._record_delete_command_status()

    assert not request.called
