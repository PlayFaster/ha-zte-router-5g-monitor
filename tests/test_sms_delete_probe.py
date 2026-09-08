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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.zte_router_5g import sms_delete_probe
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
    api.delete_all = AsyncMock(return_value=200)
    api.get_version = AsyncMock(return_value="TEST_VERSION_V1.0")
    api.get_params = AsyncMock(
        return_value={"signalbar": "4", "cr_version": "CR_TEST_V1.0"}
    )
    api._ensure_session = AsyncMock()
    api._ad_hash_func = MagicMock(return_value=lambda value: "digest-" + value[:6])
    api.unauthenticated_key_set = MagicMock(
        return_value=frozenset({"modem_main_state"})
    )
    api._batch_get = AsyncMock(
        return_value={
            "model_name": "TESTMODEL",
            "wa_inner_version": "TEST_VERSION_V1.0",
            "wan_connect_status": "pdp_connected",
            "ppp_status": "",
        }
    )
    api.DATA_VOLUME_FIELDS = {
        "data_volume_limit_switch": ("flux_data_volume_limit_switch",),
        "traffic_clear_date": ("flux_clear_date",),
    }
    api.delete_probe = None

    coordinator = MagicMock()
    coordinator.api = api
    coordinator.data = {
        "flux_data_volume_limit_size": "50_1024",
        "flux_data_volume_limit_switch": "1",
        "flux_clear_date": "1",
    }
    coordinator._async_update_lock = asyncio.Lock()
    return coordinator


def _by_name(report: dict[str, Any], name: str) -> dict[str, Any]:
    """The record for one probe."""
    return next(p for p in report["probes"] if p["probe"] == name)


def _bodies(coordinator: MagicMock) -> list[str]:
    """Every `DELETE_SMS` body the probe sent."""
    return [
        call.kwargs["data"]
        for call in coordinator.api._request.call_args_list
        if "data" in call.kwargs
    ]


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
    # The diagnostic rungs, which isolate which step of deriving a token fails.
    assert names[:8] == [
        "1_token_rotation",
        "1b_liveness_keys",
        "1c_session_check",
        "1d_version",
        "1e_rd",
        "1f_token",
        "1g_login_baseline",
        "2_bank_listing",
    ]
    # Twelve hash candidates, three attempts each, then three confirmations.
    assert "7a_token_inputs" in names
    assert (
        len([n for n in names if n.startswith("7b_")])
        == len(sms_delete_probe._CANDIDATES) * sms_delete_probe.WRITE_ATTEMPTS
    )
    assert sum(1 for n in names if n.startswith("7h_confirm")) == 3
    # The original ladder is still there, unchanged.
    assert "14_batch_semicolon" in names
    assert "15_integration_delete_all" in names


async def test_the_safe_probes_never_name_a_real_message() -> None:
    """Probes three to six must be incapable of destroying anything.

    They are the half of the run that can be offered without a warning, and the
    pair that matters most — a delete of an absent id, and the same with a
    deliberately wrong token — answers whether writes work at all from two
    requests that risk nothing.
    """
    coordinator = _coordinator(["4", "3"])

    await run_probe(coordinator)

    bodies = _bodies(coordinator)
    absent = [b for b in bodies if f"msg_id={ABSENT_ID}" in b]
    assert len(absent) == 5
    assert not any("msg_id=4&" in b or "msg_id=3&" in b for b in absent)
    assert any(f"AD={BAD_TOKEN}" in b for b in absent)


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

    absent = [b for b in _bodies(coordinator) if f"msg_id={ABSENT_ID}" in b]
    assert any("notCallback=true" in b for b in absent)
    assert any(f"mem_store={SMS_STORE_DEVICE}" in b for b in absent)
    assert any(f"mem_store={SMS_STORE_ALL}" in b for b in absent)
    # The plain form carries neither.
    plain = [b for b in absent if "notCallback" not in b and "mem_store" not in b]
    assert plain


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

    # Token rotation, the fresh-session rung, and the after-login variant's
    # three attempts.
    assert coordinator.api.login.await_count >= 2


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
    assert "14_batch_semicolon" in skipped
    assert "13_single_id_fresh_session" in skipped
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
    assert ";" in batch["sent"].split("msg_id=")[1].split("&")[0]
    assert "AD=REDACTED" in batch["sent"]
    assert "ad-value" not in batch["sent"]


async def test_the_batch_form_is_the_one_the_button_sends() -> None:
    """Nothing else tests it, and it is where the reported fault appears.

    A router that accepts a single id and refuses a semicolon-joined list would
    pass every other rung while the Delete All button kept failing.
    """
    coordinator = _coordinator()

    await run_probe(coordinator)

    assert any(";" in b and "msg_id=" in b for b in _bodies(coordinator))


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


async def test_each_probe_is_timed_and_carries_its_session_state() -> None:
    """A refusal and a timeout are indistinguishable without a duration."""
    coordinator = _coordinator()

    report = await run_probe(coordinator)

    timed = [p for p in report["probes"] if p["outcome"] != "skipped"]
    assert all(isinstance(p["elapsed_seconds"], float) for p in timed)
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


async def test_an_unexpected_failure_still_leaves_the_report_behind() -> None:
    """The one device where a failure is expected is the one running this.

    The report used to be stored on the last line, so anything raising
    anywhere discarded every finding above it. It is stored before the first
    rung now, and an abort is written into it rather than only raised.
    """
    coordinator = _coordinator()
    coordinator._async_update_lock = MagicMock()
    coordinator._async_update_lock.__aenter__ = AsyncMock(
        side_effect=RuntimeError("lock is gone")
    )

    report = await run_probe(coordinator)

    assert report["completed"] is False
    assert report["aborted"]["error_type"] == "RuntimeError"
    assert coordinator.api.delete_probe is report
    coordinator.persist_delete_probe.assert_called()


# ---------------------------------------------------------------------------
# Probe 2 — isolating which step fails, and proving a fix before spending a
# message
# ---------------------------------------------------------------------------


async def test_each_step_of_deriving_a_token_is_probed_separately() -> None:
    """The fault is inside the token derivation, which makes three calls.

    Every rung that derived a token failed and the one that supplied its own
    succeeded. Separating the three is the difference between "the token could not be built"
    and knowing which of the three is refusing.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator)

    for name in ("1c_session_check", "1d_version", "1e_rd", "1f_token"):
        assert _by_name(report, name)["outcome"] == "returned"
    coordinator.api._ensure_session.assert_awaited()
    coordinator.api.get_version.assert_awaited()


async def test_the_liveness_keys_are_read_together_and_scored() -> None:
    """One key cannot separate a dead session from a router still starting up.

    That is why the current single-key check falls back to a weaker rule, and
    why a key that is permanently blank on one model reads as an expiry.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator)

    result = _by_name(report, "1b_liveness_keys")["result"]
    assert set(result) == {"answer", "verdict", "unauthenticated_keys"}


async def test_a_variant_must_work_every_time_to_count() -> None:
    """One success is not a working method, and one failure is not a broken one."""
    coordinator = _coordinator()
    calls = {"n": 0}

    async def flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] % 2:
            raise TimeoutError("intermittent")
        return {"result": "success"}

    coordinator.api._request = AsyncMock(side_effect=flaky)

    report = await run_probe(coordinator)

    assert report["working_variant"] is None


async def test_a_working_variant_is_confirmed_before_a_message_is_spent() -> None:
    """A variant that works three times and fails the next three is not a fix.

    Finding that out costs nothing at the harmless write and a message later.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator)

    assert report["working_variant"] == "a_control_current"
    assert report["working_variant_confirmed"] == "a_control_current"
    assert [p["probe"] for p in report["probes"] if p["probe"].startswith("7h_")] == [
        "7h_confirm_1",
        "7h_confirm_2",
        "7h_confirm_3",
    ]


async def test_the_confirmed_variant_deletes_three_messages_and_a_batch() -> None:
    """Three separate messages, so one success cannot pass for a working delete."""
    coordinator = _coordinator()

    report = await run_probe(coordinator)

    names = [p["probe"] for p in report["probes"]]
    for expected in (
        "16_confirmed_single",
        "17_confirmed_single_again",
        "18_confirmed_single_third",
        "19_confirmed_batch",
    ):
        assert expected in names


async def test_no_working_variant_means_no_messages_are_spent() -> None:
    """If nothing writes reliably, deleting proves nothing and costs a message."""
    coordinator = _coordinator()
    coordinator.api._request = AsyncMock(side_effect=TimeoutError("no answer"))

    report = await run_probe(coordinator)

    assert report["working_variant"] is None
    skipped = _by_name(report, "16_confirmed_variant_deletes")
    assert skipped["outcome"] == "skipped"
    assert "reliably" in skipped["reason"]


async def test_the_run_is_capped_and_keeps_what_it_collected() -> None:
    """A run with no limit is one the user restarts, and a restart loses it."""
    coordinator = _coordinator()

    async def forever(*_a, **_k):
        await asyncio.Event().wait()

    coordinator.api.get_rd = AsyncMock(side_effect=forever)

    with patch.object(sms_delete_probe, "PROBE_TIMEOUT", 0.05):
        report = await run_probe(coordinator)

    assert report["timed_out"] == 0.05
    assert report["completed"] is False
    assert coordinator.api.delete_probe is report


async def test_the_harmless_write_refuses_a_form_it_cannot_fill() -> None:
    """This command replaces the whole form; a partial one would be refused.

    Raising here rather than sending is what stops the probe altering a data
    limit the user relies on.
    """
    coordinator = _coordinator()
    coordinator.data = {"flux_clear_date": "1"}

    report = await run_probe(coordinator)

    attempts = [
        p for p in report["probes"] if p["probe"].startswith("7b_a_control_current")
    ]
    assert all(p["outcome"] == "raised" for p in attempts)
    assert report["working_variant"] is None


async def test_a_variant_that_stops_working_is_not_confirmed() -> None:
    """Three successes then three failures is not a method.

    The deletes must not run on the strength of the first three.
    """
    coordinator = _coordinator()
    calls = {"n": 0}

    async def works_then_stops(*_a, **_k):
        calls["n"] += 1
        if calls["n"] > 12:
            raise TimeoutError("stopped working")
        return {"result": "success"}

    coordinator.api._request = AsyncMock(side_effect=works_then_stops)

    report = await run_probe(coordinator)

    assert report["working_variant"] is not None
    assert report["working_variant_confirmed"] is None
    assert _by_name(report, "16_confirmed_variant_deletes")["outcome"] == "skipped"


# ---------------------------------------------------------------------------
# Probe 3 - the hash candidates, and judging them on what the router said
# ---------------------------------------------------------------------------


async def test_a_candidate_is_judged_on_the_routers_result_not_on_returning() -> None:
    """This API answers `200 OK` for a refused write, so returning proves nothing.

    Version 2 counted any call that did not raise, and reported a variant
    confirmed while all six of its writes came back `{"result": "failure"}`.
    """
    coordinator = _coordinator()
    coordinator.api._request = AsyncMock(return_value={"result": "failure"})

    report = await run_probe(coordinator)

    assert report["working_variant"] is None
    assert all(count == "0/3" for count in report["candidates"].values())


async def test_a_response_carrying_no_result_is_not_counted_as_success() -> None:
    """Silence is not consent.

    Treating a missing field as success is the same mistake as treating a
    `200` as success, in a quieter form.
    """
    coordinator = _coordinator()
    coordinator.api._request = AsyncMock(return_value={"nothing": "useful"})

    report = await run_probe(coordinator)

    assert report["working_variant"] is None


async def test_every_candidate_runs_even_after_one_succeeds() -> None:
    """Stopping at the first success leaves eleven formulas unknown.

    That is another round trip with the reporter for a fact this run already
    had the router in front of it to establish.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator)

    tried = {name for name, *_rest in sms_delete_probe._CANDIDATES}
    assert set(report["candidates"]) == tried
    assert report["candidates_passed"], "the control should pass against a stand-in"


async def test_candidates_needing_cr_version_are_named_when_it_is_absent() -> None:
    """A candidate never tried and one that failed are different findings.

    `cr_version` answers this device through the discovery pass. Whether it
    answers a plain read is not established, so the run records what it got.
    """
    coordinator = _coordinator()
    coordinator.api.get_params = AsyncMock(return_value={"signalbar": "4"})

    report = await run_probe(coordinator)

    needs_cr = [n for n, cr, _alt, _b in sms_delete_probe._CANDIDATES if cr]
    for name in needs_cr:
        assert report["candidates"][name] == "skipped: no cr_version"
    inputs = _by_name(report, "7a_token_inputs")
    assert inputs["result"]["cr_version_answered"] is False


async def test_the_token_inputs_rung_records_lengths_and_not_values() -> None:
    """A length identifies the digest without publishing a session value.

    Sixty-four characters is SHA-256 and thirty-two is MD5, which is the whole
    of what the formulas need to be read against.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator)

    result = _by_name(report, "7a_token_inputs")["result"]
    assert set(result) >= {
        "wa_inner_version_length",
        "cr_version_length",
        "rd_length",
        "cr_version_answered",
    }
    assert not any(isinstance(v, str) and len(v) > 20 for v in result.values())


async def test_every_candidate_formula_is_distinct() -> None:
    """Two entries computing the same token report one finding twice.

    It would also make a passing formula look more corroborated than it is.
    The control is excluded: it asks the integration for its token rather than
    computing one, which is the whole point of it.
    """
    # The reporter's own shape, timestamp included. One candidate strips that
    # timestamp, so a stand-in without one would make two formulas identical
    # and the test would report a collision the device never sees.
    # The digest is part of a candidate's identity, so each is built with the
    # one it would actually be given — SHA-256 on an MC888, MD5 for the entry
    # that exists to try the other one. Building them all with the same digest
    # would report a collision the device never sees.
    tokens = {
        name: builder(
            sms_delete_probe._md5 if alternate else sms_delete_probe._sha,
            "BD_ABPLMC888PROMODV1.0.0B01 [Oct 16 2025 21:15:14]",
            "CR_ABPLMC888PROV1.0.1B04",
            "0123456789abcdef",
        )
        for name, _needs_cr, alternate, builder in sms_delete_probe._CANDIDATES
        if builder is not None
    }

    assert len(set(tokens.values())) == len(tokens)


async def test_the_login_baseline_records_names_and_not_values() -> None:
    """Groundwork for a session check drawn from the device rather than a list.

    Names only: the inventory is what a future profile is built from, and the
    values behind it are the reporter's. The identity pair is the exception,
    and it identifies a firmware rather than anything of his.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator)

    result = _by_name(report, "1g_login_baseline")["result"]
    assert result["populated_keys"] == [
        "model_name",
        "wa_inner_version",
        "wan_connect_status",
    ]
    assert result["populated_count"] == 3
    # `ppp_status` is blank in the stand-in, so it is absent here — which is
    # the MC888 Pro's shape for `wan_connect_status`, inverted.
    assert result["session_check_keys_populated"] == [
        "wan_connect_status",
        "model_name",
    ]
    assert result["identity"]["model_name"] == "TESTMODEL"


async def test_the_login_baseline_survives_a_batch_read_that_fails() -> None:
    """One poll failing still leaves the other's keys.

    No baseline at all is a finding rather than a reason to lose the rest of
    the run.
    """
    coordinator = _coordinator()
    coordinator.api._batch_get = AsyncMock(side_effect=TimeoutError("no answer"))

    report = await run_probe(coordinator)

    result = _by_name(report, "1g_login_baseline")["result"]
    assert result["populated_keys"] == []
    assert result["read"] == 0


async def test_an_unanswered_cr_version_read_is_recorded_with_its_reason() -> None:
    """A read that raised and a read that returned nothing look the same later.

    The candidates depending on `cr_version` are skipped either way, and
    without the reason the next run repeats the same guess.
    """
    coordinator = _coordinator()
    coordinator.api.get_params = AsyncMock(side_effect=TimeoutError("no answer"))

    report = await run_probe(coordinator)

    inputs = _by_name(report, "7a_token_inputs")["result"]
    assert inputs["cr_version_answered"] is False
    assert "TimeoutError" in inputs["cr_version_note"]


async def test_the_recorded_reason_does_not_outlive_its_run() -> None:
    """It is module state, so it has to be cleared per run.

    A note from an earlier run would be reported against this one and read as
    a fresh failure.
    """
    coordinator = _coordinator()
    coordinator.api.get_params = AsyncMock(side_effect=TimeoutError("no answer"))
    await run_probe(coordinator)

    healthy = _coordinator()
    report = await run_probe(healthy)

    assert "cr_version_note" not in _by_name(report, "7a_token_inputs")["result"]


async def test_a_reply_that_is_not_a_mapping_is_not_counted_as_success() -> None:
    """Firmware answering with something other than an object says nothing.

    It is not evidence the write happened, and counting it would be the same
    error as counting a `200` as success.
    """
    coordinator = _coordinator()
    coordinator.api._request = AsyncMock(return_value="OK")

    report = await run_probe(coordinator)

    assert report["working_variant"] is None


async def test_the_control_asks_the_integration_for_its_token() -> None:
    """Reproducing the shipped formula here is how the control stopped being one.

    Version 3 hardcoded SHA-256 and ran against an MD5 router: the control
    failed three times out of three while the integration's own write in the
    same run succeeded. Asking `get_ad` makes the control right by
    construction.
    """
    coordinator = _coordinator()

    await run_probe(coordinator)

    coordinator.api.get_ad.assert_awaited()


async def test_a_candidate_is_built_with_the_digest_this_device_uses() -> None:
    """`_ad_hash_func` reads the firmware string and picks MD5 or SHA-256.

    Asking it, rather than choosing here, is what stops a candidate disagreeing
    with what the integration itself would send.
    """
    coordinator = _coordinator()

    await run_probe(coordinator)

    coordinator.api._ad_hash_func.assert_called()


def test_the_other_digest_is_the_one_this_device_does_not_use() -> None:
    """The alternative must be the alternative on either kind of device.

    One candidate exists to try it, and a device-independent choice here would
    make that candidate a duplicate on one of the two.
    """
    api = MagicMock()

    api._ad_hash_func = MagicMock(return_value=sms_delete_probe._sha)
    native, other = sms_delete_probe._digests(api, "any")
    assert (native, other) == (sms_delete_probe._sha, sms_delete_probe._md5)

    api._ad_hash_func = MagicMock(return_value=sms_delete_probe._md5)
    native, other = sms_delete_probe._digests(api, "any")
    assert (native, other) == (sms_delete_probe._md5, sms_delete_probe._sha)


async def test_exactly_one_candidate_carries_the_other_digest() -> None:
    """The alternative digest is a thin hypothesis, worth exactly one candidate.

    `RD` is 64 characters on the MC888 Pro, which points firmly at SHA-256.
    """
    alternates = [
        name for name, _cr, alternate, _b in sms_delete_probe._CANDIDATES if alternate
    ]

    assert len(alternates) == 1
