"""The temporary SMS delete probe.

**Delete this file with `sms_delete_probe.py`.** It exists for issue #56, where
a router accepts a delete, answers success and keeps the message, and four
diagnostics downloads carried no evidence because the failing path raises
before anything is recorded.

What is worth asserting here is not that the probe works — it is that it cannot
stop early, cannot lose a finding, and cannot delete more than the messages it
was given. Each of those is a way the run could quietly waste the one chance we
get to ask this router anything.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.zte_router_5g.api import (
    SMS_STORE_ALL,
    SMS_STORE_DEVICE,
    SMS_STORE_SIM,
)
from custom_components.zte_router_5g.sms_delete_probe import (
    ABSENT_ID,
    BAD_TOKEN,
    run_probe,
)


def _coordinator(ids: list[str] | None = None) -> MagicMock:
    """A coordinator whose router answers everything successfully."""
    held = list(ids if ids is not None else [str(n) for n in range(20, 8, -1)])
    api = MagicMock()
    api.get_rd = AsyncMock(return_value="rd-value")
    api.get_ad = AsyncMock(return_value="ad-value")
    api.login = AsyncMock()
    api.set_data_volume_settings = AsyncMock(return_value={"result": "success"})
    api._request = AsyncMock(return_value={"result": "success"})
    api.get_sms_messages = AsyncMock(
        side_effect=lambda **_kw: [
            {"id": i, "tag": "1", "date_decoded": "2026-09-07T10:00:00+00:00"}
            for i in held
        ]
    )
    api.last_response_status = 200
    api.last_response_preview = ""
    api.last_rejection = {"verdict": "expired", "payload": {"result": ""}}
    api._session_was_fresh = False
    api.login_metadata = {"form": "LOGIN_MULTI_USER"}
    api.delete_all = AsyncMock(return_value=200)
    api.delete_probe = None

    coordinator = MagicMock()
    coordinator.api = api
    coordinator.data = {"flux_data_volume_limit_size": "50_1024"}
    coordinator._async_update_lock = asyncio.Lock()
    return coordinator


def _by_name(report: dict[str, Any], name: str) -> dict[str, Any]:
    """The record for one probe."""
    return next(p for p in report["probes"] if p["probe"] == name)


def _bodies(coordinator: MagicMock) -> list[str]:
    """Every `DELETE_SMS` body the probe sent."""
    return [call.kwargs["data"] for call in coordinator.api._request.call_args_list]


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """The delayed re-list waits five seconds against real hardware."""
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


# ---------------------------------------------------------------------------
# What must always happen
# ---------------------------------------------------------------------------


async def test_every_probe_is_recorded_and_none_is_skipped_for_success() -> None:
    """The run characterises the device; it does not stop at the first answer.

    A router this different from the reference hardware is worth asking every
    question once, properly. Learning that a single-id delete works, and having
    to ask again about the storage bank, is the round trip this exists to end.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator)

    names = [p["probe"] for p in report["probes"]]
    assert names == [
        "1_token_rotation",
        "2_bank_listing",
        "3_absent_id",
        "4_absent_id_bad_token",
        "5_absent_id_not_callback",
        "6a_absent_id_store_device",
        "6b_absent_id_store_all",
        "7_harmless_write",
        "8_single_id",
        "9_single_id_repeat",
        "10_single_id_store_all",
        "11_single_id_not_callback",
        "12_single_id_delayed_relist",
        "13_single_id_fresh_session",
        "14_batch_semicolon",
        "15_integration_delete_all",
    ]
    assert all(p["outcome"] != "skipped" for p in report["probes"])


async def test_the_safe_probes_never_name_a_real_message() -> None:
    """Probes three to six must be incapable of destroying anything.

    They are the half of the run that can be offered without a warning, and the
    pair that matters most — a delete of an absent id, and the same with a
    deliberately wrong token — answers whether writes work at all from two
    requests that risk nothing.
    """
    coordinator = _coordinator(["4", "3"])

    await run_probe(coordinator)

    safe = _bodies(coordinator)[:5]
    assert all(f"msg_id={ABSENT_ID}" in body for body in safe)
    assert not any("msg_id=4" in body or "msg_id=3" in body for body in safe)
    assert f"AD={BAD_TOKEN}" in safe[1]


async def test_the_report_is_stored_for_the_next_download() -> None:
    """The reporter already knows how to produce a diagnostics download."""
    coordinator = _coordinator()

    report = await run_probe(coordinator)

    assert coordinator.api.delete_probe is report
    assert report["started"] and report["finished"]


# ---------------------------------------------------------------------------
# The variants
# ---------------------------------------------------------------------------


async def test_each_variant_sends_the_form_it_names() -> None:
    """The point of the probe is that the form varies; assert that it does."""
    coordinator = _coordinator()

    await run_probe(coordinator)

    bodies = _bodies(coordinator)
    assert "notCallback=true" in bodies[2]
    assert f"mem_store={SMS_STORE_DEVICE}" in bodies[3]
    assert f"mem_store={SMS_STORE_ALL}" in bodies[4]
    # And the plain form carries neither.
    assert "notCallback" not in bodies[0]
    assert "mem_store" not in bodies[0]


async def test_the_bank_listing_asks_all_three_stores() -> None:
    """Where the messages live is a precondition for reading everything else."""
    coordinator = _coordinator(["4"])

    report = await run_probe(coordinator)

    stores = {
        call.kwargs.get("mem_store")
        for call in coordinator.api.get_sms_messages.call_args_list
    }
    assert {SMS_STORE_DEVICE, SMS_STORE_SIM, SMS_STORE_ALL} <= stores
    assert set(_by_name(report, "2_bank_listing")["result"]) == {"device", "sim", "all"}


async def test_the_fresh_session_probe_logs_in_first() -> None:
    """Otherwise it is the same request as probe eight and says nothing new."""
    coordinator = _coordinator()

    await run_probe(coordinator)

    # Once for the token-rotation probe, once before the fresh-session rung.
    assert coordinator.api.login.await_count == 2


async def test_the_delayed_probe_waits_before_re_listing() -> None:
    """A router that deletes lazily would otherwise be recorded as refusing."""
    coordinator = _coordinator()

    report = await run_probe(coordinator)

    assert _by_name(report, "12_single_id_delayed_relist")["waited_seconds"] == 5


# ---------------------------------------------------------------------------
# Running out of messages, and failures
# ---------------------------------------------------------------------------


async def test_probes_with_no_message_left_say_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Five destructive probes need five messages, and he had two.

    Recording the shortfall is the difference between "this variant was not
    tried" and "this variant did nothing", which a reader cannot otherwise
    tell apart.
    """
    coordinator = _coordinator(["4", "3"])

    report = await run_probe(coordinator)

    skipped = [p["probe"] for p in report["probes"] if p["outcome"] == "skipped"]
    assert skipped == [
        "10_single_id_store_all",
        "11_single_id_not_callback",
        "12_single_id_delayed_relist",
        "13_single_id_fresh_session",
        "14_batch_semicolon",
    ]
    assert report["messages_available"] == ["4", "3"]
    # The batch rung needs two and would have been given one; saying so is the
    # difference between "not tried" and "tried and did nothing".
    batch = _by_name(report, "14_batch_semicolon")
    assert batch["reason"] == "needs 2 message(s), not enough left"


async def test_a_raised_probe_is_recorded_and_the_run_continues() -> None:
    """A refusal is the finding. Stopping on it wastes every probe after it."""
    coordinator = _coordinator()
    coordinator.api._request = AsyncMock(side_effect=RuntimeError("router said no"))

    report = await run_probe(coordinator)

    absent = _by_name(report, "3_absent_id")
    assert absent["outcome"] == "raised"
    assert absent["error_type"] == "RuntimeError"
    assert "router said no" in absent["error"]
    # And the probes after it still ran.
    assert _by_name(report, "7_harmless_write")["outcome"] == "returned"


async def test_a_failing_re_list_does_not_lose_the_run() -> None:
    """The delete's own answer is worth keeping even if the check after fails."""
    coordinator = _coordinator()
    calls = {"n": 0}

    async def flaky(**_kw: Any) -> list[dict[str, Any]]:
        calls["n"] += 1
        if calls["n"] > 4:
            raise TimeoutError("listing timed out")
        return [{"id": "4"}, {"id": None}]

    coordinator.api.get_sms_messages = AsyncMock(side_effect=flaky)

    report = await run_probe(coordinator)

    assert report["probes"]
    assert "ids_remaining" not in report


async def test_messages_without_an_id_are_not_counted() -> None:
    """A record the router returned with no id cannot be deleted by any route."""
    coordinator = _coordinator()
    coordinator.api.get_sms_messages = AsyncMock(
        return_value=[{"id": "4"}, {"id": None}, {"id": "3"}]
    )

    report = await run_probe(coordinator)

    assert report["messages_available"] == ["4", "3"]


async def test_the_status_and_body_of_each_answer_are_kept() -> None:
    """Which is what four downloads on issue #56 did not carry."""
    coordinator = _coordinator()
    coordinator.api.last_response_status = 500
    coordinator.api.last_response_preview = "<html>go away</html>"

    report = await run_probe(coordinator)

    assert all(p.get("status") == 500 for p in report["probes"] if "status" in p)
    assert _by_name(report, "3_absent_id")["body_preview"] == "<html>go away</html>"


# ---------------------------------------------------------------------------
# What the first live run showed was missing
# ---------------------------------------------------------------------------


async def test_a_refusal_keeps_what_the_router_said() -> None:
    """The first live run recorded `Request failed:` and nothing behind it.

    The router's own answer is held against the failing verdict and cleared by
    the next successful poll, so it is snapshotted here or lost — on the one
    rung that failed, which is the rung that matters.
    """
    coordinator = _coordinator()
    coordinator.api._request = AsyncMock(side_effect=RuntimeError("no"))

    report = await run_probe(coordinator)

    absent = _by_name(report, "3_absent_id")
    assert absent["rejection"]["payload"] == {"result": ""}


async def test_every_probe_records_what_it_sent_with_the_token_removed() -> None:
    """A variant's name is not the same as the form it sent."""
    coordinator = _coordinator()

    report = await run_probe(coordinator)

    batch = _by_name(report, "14_batch_semicolon")
    assert "msg_id=14;13" in batch["sent"]
    assert "AD=REDACTED" in batch["sent"]
    assert "ad-value" not in batch["sent"]


async def test_the_batch_form_is_the_one_the_button_sends() -> None:
    """Nothing else tests it, and it is where the reported fault appears.

    A router that accepts a single id and refuses a semicolon-joined list would
    pass every other rung while the Delete All button kept failing.
    """
    coordinator = _coordinator()

    await run_probe(coordinator)

    assert any("msg_id=14;13" in body for body in _bodies(coordinator))


async def test_the_integration_s_own_delete_is_exercised() -> None:
    """Everything above it builds its own request and bypasses the real path.

    Without this rung the report can show every variant succeeding while the
    code the user actually runs is never called, which is what left the first
    live run with an empty `write_failures`.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator)

    coordinator.api.delete_all.assert_awaited_once()
    assert _by_name(report, "15_integration_delete_all")["outcome"] == "returned"


async def test_a_repeated_variant_separates_a_fault_from_a_fluke() -> None:
    """One failure of one form says nothing about whether it always fails."""
    coordinator = _coordinator()

    report = await run_probe(coordinator)

    first = _by_name(report, "8_single_id")
    again = _by_name(report, "9_single_id_repeat")
    assert first["id_targeted"] != again["id_targeted"]
    assert first["sent"].replace("msg_id=20", "") == again["sent"].replace(
        "msg_id=19", ""
    )


async def test_each_probe_is_timed_and_carries_its_session_state() -> None:
    """A refusal and a timeout are indistinguishable without a duration."""
    coordinator = _coordinator()

    report = await run_probe(coordinator)

    timed = [p for p in report["probes"] if p["outcome"] != "skipped"]
    assert all(isinstance(p["elapsed_seconds"], float) for p in timed)
    assert all(p["login_form"] == "LOGIN_MULTI_USER" for p in timed)
    assert all(p["session_was_fresh"] is False for p in timed)


async def test_the_message_summary_carries_no_message() -> None:
    """Id, tag and date answer the question; content and sender do not.

    A diagnostics download is written to be attached to a public issue without
    hand-editing, so the probe must not read a field it does not need.
    """
    coordinator = _coordinator(["4", "3"])
    coordinator.api.get_sms_messages = AsyncMock(
        return_value=[
            {
                "id": "4",
                "tag": "0",
                "date_decoded": "2026-09-07T09:00:00+00:00",
                "content_decoded": "a private message",
                "number_decoded": "+353871234567",
            }
        ]
    )

    report = await run_probe(coordinator)

    assert report["messages_before"] == [
        {"id": "4", "tag": "0", "date": "2026-09-07T09:00:00+00:00"}
    ]
    assert "private" not in json.dumps(report)
    assert "353871234567" not in json.dumps(report)


async def test_a_refusal_with_nothing_retained_still_records_the_failure() -> None:
    """The snapshot is best-effort; its absence must not lose the probe.

    `last_rejection` is only set for a verdict the classifier scored, so a
    transport error leaves nothing behind. The record is still the finding.
    """
    coordinator = _coordinator()
    coordinator.api._request = AsyncMock(side_effect=TimeoutError("no answer"))
    coordinator.api.last_rejection = None

    report = await run_probe(coordinator)

    absent = _by_name(report, "3_absent_id")
    assert absent["outcome"] == "raised"
    assert absent["error_type"] == "TimeoutError"
    assert "rejection" not in absent
