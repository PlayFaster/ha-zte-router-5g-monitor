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
    ACTION_CAPTURE,
    ACTION_CONFIRM,
    ACTION_FULL,
    BAD_TOKEN,
    _captures,
    _resolve,
    run_probe,
)

# A miniature of what a ZTE web UI serves: an index that names its scripts
# through a module loader, and a bundle carrying the payload builders the probe
# reads. Small, but the same shape the reference MC7010 answers with.
_FAKE_INDEX = (
    "<html><head>"
    '<script src="js/lib/require/require-jquery.js?v=1" data-main="js/main">'
    "</script></head><body></body></html>"
)
_FAKE_MAIN = (
    'require.config({paths:{service:"service",home:"home",md5:"lib/md5"}});'
    # A shim list, which is how the reference device reaches bootstrap.
    'require.config({shim:{md5:["app"]}});'
    # Named in a dependency array and nowhere else, which is how the reference
    # MC7010 reaches nine of the thirty-one files it loads.
    'define(["app"],function(){});'
)
# `service` again, so a name already queued is not fetched twice.
# `md5` is an alias, not a path: resolving it literally invents js/md5.js.
_FAKE_APP = 'define(["language","md5","service"],function(){});'
# The assignment six probe runs never saw, because the file was never fetched.
_FAKE_LANGUAGE = (
    "function o(){var o=this,u=c();rd0=u.rd_params0,rd1=u.rd_params1;return o}"
    'var CFG={DEVICE:"cpe/MF253V"};'
)
_FAKE_MD5 = "function hex_md5(s){return s}"
_FAKE_SERVICE = (
    'function zteDelete(){function e(e,t){var n=e.ids.join(";")+";";'
    'return{isTest:Dn,goformId:"DELETE_SMS",msg_id:n,notCallback:!0}}}'
    'function zteDeleteAll(){return{isTest:Dn,goformId:"ALL_DELETE_SMS",notCallback:!0,'
    "which_cgi:e.location}}"
    'var loc={all:"2",device:"1"};which_cgi="2";'
    'function zteDataLimit(){var _={isTest:Dn,goformId:"DATA_LIMIT_SETTING"};'
    "_.data_volume_limit_size=e.limitDataMonth;"
    "_.traffic_clear_date=e.traffic_clear_date;"
    "_.data_volume_limit_switch=e.x;return _}"
    'if(n.ACCESSIBLE_ID_SUPPORT&&"LOGIN"!=e.goformId){'
    'var o=hex_md5(rd0+rd1),u=Bt({nv:"RD"}).RD,c=hex_md5(o+u);e.AD=c}'
    't.ajax({url:"/goform/goform_set_cmd_process"});'
)


class _FakeGet:
    """One `session.get`, answering with the miniature web UI above."""

    def __init__(self, url: str) -> None:
        self._url = url

    async def __aenter__(self) -> MagicMock:
        body = ""
        if self._url.endswith(("/", "index.html")):
            body = _FAKE_INDEX
        elif self._url.endswith("main.js"):
            body = _FAKE_MAIN
        elif self._url.endswith("service.js"):
            body = _FAKE_SERVICE
        elif self._url.endswith("app.js"):
            body = _FAKE_APP
        elif self._url.endswith("language.js"):
            body = _FAKE_LANGUAGE
        elif self._url.endswith("md5.js"):
            body = _FAKE_MD5
        elif self._url.endswith("cpe/MF253V/config.js"):
            body = "var deviceConfig={};"
        response = MagicMock()
        response.status = 200 if body else 404
        response.headers = {"Content-Type": "text/html"}
        response.text = AsyncMock(return_value=body)
        return response

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakePost:
    """One login request, answering whatever the api stand-in is set to say."""

    def __init__(self, api: MagicMock) -> None:
        self._api = api

    async def __aenter__(self) -> MagicMock:
        response = MagicMock()
        answer = self._api._request.return_value
        # A string passes through, so a router answering a login with
        # something that is not an object can be exercised.
        if not isinstance(answer, (dict, str)):
            answer = {"result": "0"}
        response.json = AsyncMock(return_value=answer)
        return response

    async def __aexit__(self, *_exc: object) -> None:
        return None


# The reporter's own strings. Rules are exercised against these rather than a
# stand-in, because two rules that differ in the abstract can produce the same
# digest on a given device — which is how v3 reported twelve candidates where
# the router received nine.
_MC888_VALUES = {
    "wa": "xx_xxxxMC888PROMODV1.0.0B01 [Oct 16 2025 21:15:14]",
    "wav": "xx_xxxxMC888PROMODV1.0.1B03",
    "cr": "CR_xxxxMC888PROV1.0.1B04",
    "hw": "MC888 Pro_HWV1.0",
    "model": "MC888 Pro",
    "ld": "L" * 64,
    "rd": "a1b2" * 16,
}


def _coordinator(ids: list[str] | None = None) -> MagicMock:
    """A coordinator whose router answers everything successfully."""
    held = list(ids if ids is not None else [str(n) for n in range(20, 8, -1)])
    api = MagicMock()
    switch = {"value": "1"}
    api.get_rd = AsyncMock(return_value="rd-value")
    api.get_ad = AsyncMock(return_value="ad-value")
    api.login = AsyncMock()
    api.set_data_volume_settings = AsyncMock(return_value={"result": "success"})

    async def _request(method="POST", path="", **kwargs):
        # A router that actually applies the write, so the read-back the probe
        # now insists on has something to confirm. Without this the stand-in
        # claims success and never changes, and the probe is right to refuse
        # to believe it.
        body = str(kwargs.get("data") or path)
        for field in ("data_volume_limit_switch", "led_night_mode_switch"):
            marker = f"{field}="
            if marker in body:
                switch["value"] = body.split(marker, 1)[1].split("&", 1)[0]
        return {"result": "success"}

    api._request = AsyncMock(side_effect=_request)
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

    async def _params(names, **_kw):
        answer = {
            "signalbar": "4",
            "cr_version": "CR_TEST_V1.0",
            "wa_version": "TEST_VERSION_V1.1",
            "hardware_version": "TESTMODEL_HWV1.0",
            "model_name": "TESTMODEL",
            "data_volume_limit_switch": switch["value"],
            "led_night_mode_switch": switch["value"],
        }
        picked = {name: answer.get(name, "") for name in names}
        picked["wan_connect_status"] = "up"
        return picked

    api.get_params = AsyncMock(side_effect=_params)
    api.get_ld = AsyncMock(return_value="LD-VALUE")
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
    # The login stage posts its own form and reads the cookies back, so the
    # stand-in needs the pieces of the API that path touches.
    api.username = "configured-name"
    api.password = "secret"
    api.referer = "http://router/"
    api.get_ld = AsyncMock(return_value="LD-VALUE")
    api._hash = MagicMock(side_effect=lambda v: "h(" + str(v)[:8] + ")")
    api._clear_session = MagicMock()
    api._extract_cookies = MagicMock(return_value={"zsidn": "cookie-value"})
    api.session_active = True
    api.cookies = {"zsidn": "cookie-value"}
    api.session = MagicMock()
    # `_try_login` posts, or sends a query string for the GET variant, through
    # the same call.
    api.session.get = MagicMock(side_effect=lambda url, **_kw: _FakeGet(url))
    api.session.request = MagicMock(return_value=_FakePost(api))

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
    # `data=None` is a real call: the query-string variant carries its payload
    # in the path instead, and collecting it here would put a `None` among the
    # bodies every other assertion iterates over.
    return [
        call.kwargs["data"]
        for call in coordinator.api._request.call_args_list
        if call.kwargs.get("data") is not None
    ]


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """The delayed re-list waits five seconds against real hardware."""
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


@pytest.fixture(autouse=True)
def _smaller_space(monkeypatch: pytest.MonkeyPatch) -> None:
    """Four operands and two `RD` forms rather than the full product.

    The generated space is 1,548 rules on the reporter's firmware, and a suite
    that ran every one of them through several tests took longer than the
    probe does against real hardware. The four kept are the ones every
    assertion here reasons about, `wa_version + cr_version` first, so the
    shape being tested is the shape that ships.
    """
    monkeypatch.setattr(sms_delete_probe, "_OPERANDS", sms_delete_probe._OPERANDS[:4])
    monkeypatch.setattr(sms_delete_probe, "_RD_FORMS", sms_delete_probe._RD_FORMS[:2])


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

    report = await run_probe(coordinator, ACTION_FULL)

    names = [p["probe"] for p in report["probes"]]
    # The capture runs first, before anything that can be refused or locked
    # out. The login stage follows it and precedes everything that assumes a
    # session which may write.
    assert names[0].startswith("24a_")
    assert names.index("24a_source_crawl") < min(
        i for i, n in enumerate(names) if n.startswith("0a_")
    )
    ladder = [
        n for n in names if not n.startswith(("0a_", "0b_", "0y_", "0z_", "22", "24"))
    ]
    assert ladder[:8] == [
        "1_token_rotation",
        "1b_liveness_keys",
        "1c_session_check",
        "1d_version",
        "1e_rd",
        "1f_token",
        "1g_login_baseline",
        "2_bank_listing",
    ]
    # The generated token space, screened once each.
    assert "7a_token_inputs" in names
    inputs = _by_name(report, "7a_token_inputs")["result"]
    assert len(report["candidates"]) == inputs["distinct_tokens"]
    assert report["screened"] == inputs["distinct_tokens"]
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

    await run_probe(coordinator, ACTION_FULL)

    bodies = _bodies(coordinator)
    absent = [b for b in bodies if f"msg_id={ABSENT_ID}" in b]
    # Six now: the trailing-semicolon form joined the safe set.
    assert len(absent) == 6
    assert any(f"msg_id={ABSENT_ID};" in b for b in absent)
    assert not any("msg_id=4&" in b or "msg_id=3&" in b for b in absent)
    assert any(f"AD={BAD_TOKEN}" in b for b in absent)


async def test_the_report_is_stored_for_the_next_download() -> None:
    """The reporter already knows how to produce a diagnostics download."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    assert coordinator.api.delete_probe is report
    assert report["started"] and report["finished"]


# ---------------------------------------------------------------------------
# The variants
# ---------------------------------------------------------------------------


async def test_each_variant_sends_the_form_it_names() -> None:
    """The point of the probe is that the form varies; assert that it does."""
    coordinator = _coordinator()

    await run_probe(coordinator, ACTION_FULL)

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

    report = await run_probe(coordinator, ACTION_FULL)

    stores = {
        call.kwargs.get("mem_store")
        for call in coordinator.api.get_sms_messages.call_args_list
    }
    assert {SMS_STORE_DEVICE, SMS_STORE_SIM, SMS_STORE_ALL} <= stores
    assert set(_by_name(report, "2_bank_listing")["result"]) == {"device", "sim", "all"}


async def test_the_fresh_session_probe_logs_in_first() -> None:
    """Otherwise it is the same request as probe eight and says nothing new."""
    coordinator = _coordinator()

    await run_probe(coordinator, ACTION_FULL)

    # Token rotation, the fresh-session rung, and the after-login variant's
    # three attempts.
    assert coordinator.api.login.await_count >= 2


async def test_the_delayed_probe_waits_before_re_listing() -> None:
    """A router that deletes lazily would otherwise be recorded as refusing."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

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

    report = await run_probe(coordinator, ACTION_FULL)

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

    report = await run_probe(coordinator, ACTION_FULL)

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

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["probes"]
    assert "ids_remaining" not in report


async def test_messages_without_an_id_are_not_counted() -> None:
    """A record the router returned with no id cannot be deleted by any route."""
    coordinator = _coordinator()
    coordinator.api.get_sms_messages = AsyncMock(
        return_value=[{"id": "4"}, {"id": None}, {"id": "3"}]
    )

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["messages_available"] == ["4", "3"]


async def test_the_status_and_body_of_each_answer_are_kept() -> None:
    """Which is what four downloads on issue #56 did not carry."""
    coordinator = _coordinator()
    coordinator.api.last_response_status = 500
    coordinator.api.last_response_preview = "<html>go away</html>"

    report = await run_probe(coordinator, ACTION_FULL)

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

    report = await run_probe(coordinator, ACTION_FULL)

    absent = _by_name(report, "3_absent_id")
    assert absent["rejection"]["payload"] == {"result": ""}


async def test_every_probe_records_what_it_sent_with_the_token_removed() -> None:
    """A variant's name is not the same as the form it sent."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

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

    await run_probe(coordinator, ACTION_FULL)

    assert any(";" in b and "msg_id=" in b for b in _bodies(coordinator))


async def test_the_integration_s_own_delete_is_exercised() -> None:
    """Everything above it builds its own request and bypasses the real path.

    Without this rung the report can show every variant succeeding while the
    code the user actually runs is never called, which is what left the first
    live run with an empty `write_failures`.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    coordinator.api.delete_all.assert_awaited_once()
    assert _by_name(report, "15_integration_delete_all")["outcome"] == "returned"


async def test_a_repeated_variant_separates_a_fault_from_a_fluke() -> None:
    """One failure of one form says nothing about whether it always fails."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    first = _by_name(report, "8_single_id")
    again = _by_name(report, "9_single_id_repeat")
    assert first["id_targeted"] != again["id_targeted"]


async def test_each_probe_is_timed_and_carries_its_session_state() -> None:
    """A refusal and a timeout are indistinguishable without a duration."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

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

    report = await run_probe(coordinator, ACTION_FULL)

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

    report = await run_probe(coordinator, ACTION_FULL)

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

    report = await run_probe(coordinator, ACTION_FULL)

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

    report = await run_probe(coordinator, ACTION_FULL)

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

    report = await run_probe(coordinator, ACTION_FULL)

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

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["working_variant"] is None


async def test_the_confirmed_variant_deletes_three_messages_and_a_batch() -> None:
    """Three separate messages, so one success cannot pass for a working delete."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

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

    report = await run_probe(coordinator, ACTION_FULL)

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
        report = await run_probe(coordinator, ACTION_FULL)

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

    report = await run_probe(coordinator, ACTION_FULL)

    attempts = [
        p for p in report["probes"] if p["probe"].startswith("7b_a_control_current")
    ]
    assert all(p["outcome"] == "raised" for p in attempts)


# ---------------------------------------------------------------------------
# Probe 3 - the hash candidates, and judging them on what the router said
# ---------------------------------------------------------------------------


async def test_a_response_carrying_no_result_is_not_counted_as_success() -> None:
    """Silence is not consent.

    Treating a missing field as success is the same mistake as treating a
    `200` as success, in a quieter form.
    """
    coordinator = _coordinator()
    coordinator.api._request = AsyncMock(return_value={"nothing": "useful"})

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["working_variant"] is None


async def test_the_token_inputs_rung_records_lengths_and_not_values() -> None:
    """A length identifies the digest without publishing a session value.

    Sixty-four characters is SHA-256 and thirty-two is MD5, which is the whole
    of what the formulas need to be read against.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    result = _by_name(report, "7a_token_inputs")["result"]
    assert set(result) >= {
        "wa_inner_version_length",
        "cr_version_length",
        "rd_length",
        "cr_version_answered",
    }
    assert not any(isinstance(v, str) and len(v) > 20 for v in result.values())


async def test_the_login_baseline_records_names_and_not_values() -> None:
    """Groundwork for a session check drawn from the device rather than a list.

    Names only: the inventory is what a future profile is built from, and the
    values behind it are the reporter's. The identity pair is the exception,
    and it identifies a firmware rather than anything of his.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

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

    report = await run_probe(coordinator, ACTION_FULL)

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

    report = await run_probe(coordinator, ACTION_FULL)

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
    await run_probe(coordinator, ACTION_FULL)

    healthy = _coordinator()
    report = await run_probe(healthy, ACTION_FULL)

    assert "cr_version_note" not in _by_name(report, "7a_token_inputs")["result"]


async def test_a_reply_that_is_not_a_mapping_is_not_counted_as_success() -> None:
    """Firmware answering with something other than an object says nothing.

    It is not evidence the write happened, and counting it would be the same
    error as counting a `200` as success.
    """
    coordinator = _coordinator()
    coordinator.api._request = AsyncMock(return_value="OK")

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["working_variant"] is None


async def test_the_control_asks_the_integration_for_its_token() -> None:
    """Reproducing the shipped formula here is how the control stopped being one.

    Version 3 hardcoded SHA-256 and ran against an MD5 router: the control
    failed three times out of three while the integration's own write in the
    same run succeeded. Asking `get_ad` makes the control right by
    construction.
    """
    coordinator = _coordinator()

    await run_probe(coordinator, ACTION_FULL)

    coordinator.api.get_ad.assert_awaited()


# ---------------------------------------------------------------------------
# Probe 4 - the login stage, and the space that replaced the list
# ---------------------------------------------------------------------------


async def test_the_login_stage_runs_before_anything_that_assumes_a_session() -> None:
    """It is the one step every other rung depends on.

    Three downloads measured the same refusal because the login was never
    varied.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    names = [p["probe"] for p in report["probes"]]
    # Only the read-only capture precedes it.
    assert names.index("24a_source_crawl") < min(
        i for i, n in enumerate(names) if n.startswith("0a_")
    )
    assert min(i for i, n in enumerate(names) if n.startswith("0a_")) < names.index(
        "1_token_rotation"
    )
    assert set(report["login_variants"])


async def test_every_login_variant_records_the_cookies_it_drew() -> None:
    """The reporter's device only ever issues `zsidn`.

    A variant drawing a differently named cookie, or a second one, is a finding
    no amount of guessing at cookie names could produce - so every name the
    router sets is recorded whether or not the variant went on to write.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    logins = [p for p in report["probes"] if p["probe"].startswith("0a_")]
    assert logins
    for record in logins:
        assert "cookie_names" in record["result"]


async def test_a_correct_login_is_forced_after_three_failed_ones() -> None:
    """Neither device exposes a failed-attempt count, so the probe counts its own.

    Five attempts are allowed before a five-minute lockout; three leaves a
    margin against a limit that is itself only inferred.
    """
    coordinator = _coordinator()
    # No cookie means no session, which is what the budget counts.
    coordinator.api._extract_cookies = MagicMock(return_value={})

    report = await run_probe(coordinator, ACTION_FULL)

    resets = [p for p in report["probes"] if p["probe"].startswith("0z_reset")]
    assert resets, "no correct login was made despite a run of failures"


async def test_a_failed_login_is_recognized_by_the_routers_own_code() -> None:
    """`result: "3"` is the only marker of a spent attempt.

    Measured on the reference MC7010 on 2026-09-09: a wrong password and a
    wrong username with the right one both answer with it.
    """
    coordinator = _coordinator()
    coordinator.api._request = AsyncMock(
        return_value={"result": sms_delete_probe.FAILED_LOGIN_RESULT}
    )

    report = await run_probe(coordinator, ACTION_FULL)

    logins = [p for p in report["probes"] if p["probe"].startswith("0a_")]
    assert all(p["result"]["spent_an_attempt"] for p in logins)


async def test_the_stage_stops_when_a_known_good_login_fails() -> None:
    """A correct login that fails is what a lockout looks like from here.

    Carrying on would spend the remaining variants against a router that is
    refusing everything, and report them as findings.
    """
    coordinator = _coordinator()
    coordinator.api._extract_cookies = MagicMock(return_value={})
    coordinator.api.login = AsyncMock(side_effect=TimeoutError("locked out"))

    report = await run_probe(coordinator, ACTION_FULL)

    assert "login_stage_stopped" in report


async def test_the_token_space_is_deduplicated_for_this_devices_own_strings() -> None:
    """Two rules that differ in the abstract can produce the same digest here.

    Version 3 checked distinctness against a stand-in firmware string and
    reported twelve candidates where the MC888 Pro received nine, because an
    uppercasing digest makes an `.upper()` variant a duplicate of its base.
    """
    space = sms_delete_probe._token_space(_MC888_VALUES)

    tokens = [rule(_MC888_VALUES) for _name, rule in space]
    assert len(set(tokens)) == len(tokens)


async def test_the_space_shrinks_where_cr_version_is_not_answered() -> None:
    """The MC7010 lists `cr_version` under `probed_no_answer`.

    Every operand built from it collapses onto one built without it, and the
    count reported must be the count actually sent.
    """
    with_cr = sms_delete_probe._token_space(_MC888_VALUES)
    without_cr = sms_delete_probe._token_space({**_MC888_VALUES, "cr": "", "wav": ""})

    assert len(without_cr) < len(with_cr)


async def test_the_space_carries_both_digests_and_both_cases() -> None:
    """Version 3 could explore structure and never case.

    `_ad_hash_func` returns an uppercasing digest on an MC888, every candidate
    inherited it, and no lowercase token was ever sent to the reporter's
    router.
    """
    space = sms_delete_probe._token_space(_MC888_VALUES)

    names = [name for name, _token in space]
    assert any("_sha_" in n for n in names)
    assert any("_md5_" in n for n in names)
    assert any(n.endswith("rdupper") for n in names)
    assert any("rdfirst" in n for n in names)
    assert any("3round" in n for n in names)
    tokens = [rule(_MC888_VALUES) for _n, rule in space]
    assert any(t.islower() for t in tokens)
    assert any(t.isupper() for t in tokens)


async def test_a_screened_token_is_confirmed_before_a_message_is_spent() -> None:
    """One success is not a method. Screening only decides what to confirm."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["candidates_passed"]
    assert report["working_variant"] in report["candidates_passed"]
    confirms = [p for p in report["probes"] if p["probe"].startswith("7h_")]
    assert len(confirms) >= sms_delete_probe.WRITE_ATTEMPTS


async def test_a_refused_screening_pass_spends_no_message() -> None:
    """This API answers `200 OK` for a refused write, so returning proves nothing."""
    coordinator = _coordinator()
    coordinator.api._request = AsyncMock(return_value={"result": "failure"})

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["working_variant"] is None
    assert all(v == "screened: refused" for v in report["candidates"].values())
    skipped = _by_name(report, "16_confirmed_variant_deletes")
    assert skipped["outcome"] == "skipped"


async def test_no_token_can_be_built_without_a_firmware_string_or_rd() -> None:
    """A skipped stage with a reason beats one that silently ran nothing.

    A stage reporting zero candidates and no explanation reads as a device
    that refused everything.
    """
    coordinator = _coordinator()
    coordinator.api.get_rd = AsyncMock(return_value="")

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["candidates"] == {}
    skipped = _by_name(report, "7b_token_space")
    assert skipped["outcome"] == "skipped"


async def test_the_same_write_is_tried_with_other_transports() -> None:
    """Each is something another implementation does and this one does not.

    None is attested as necessary, so they are tried rather than adopted.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    names = [p["probe"] for p in report["probes"]]
    for expected in (
        "20a_referer_root",
        "20b_browser_headers",
        "20c_no_content_type",
        "20d_write_after_fresh_login",
        "20e_red_crypto_present",
    ):
        assert expected in names


async def test_whether_a_read_proves_a_session_is_measured_not_assumed() -> None:
    """Reads working proves nothing if those reads need no session.

    The session is discarded rather than logged out, because the reporter's
    router does not acknowledge a logout.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    result = _by_name(report, "20f_reads_without_a_session")["result"]
    assert set(result) == {
        "populated_with_a_session",
        "populated_without_one",
        "served_without_a_session",
    }


async def test_the_session_is_restored_after_the_sessionless_read() -> None:
    """Every rung below would otherwise measure a session this one threw away.

    Discarding it is how the rung works; not putting it back would make every
    later finding an artefact of this one.
    """
    coordinator = _coordinator()

    await run_probe(coordinator, ACTION_FULL)

    assert coordinator.api.session_active is not False or coordinator.api.cookies


async def test_a_login_that_answers_no_json_is_still_recorded() -> None:
    """A router answering a login with something other than JSON has answered.

    What it set is still the finding, and the variant is still recorded.
    """
    coordinator = _coordinator()
    coordinator.api.session.request = MagicMock(return_value=_FakePost(coordinator.api))
    coordinator.api._request = AsyncMock(return_value="not json")
    coordinator.api._extract_cookies = MagicMock(return_value={})

    report = await run_probe(coordinator, ACTION_FULL)

    logins = [p for p in report["probes"] if p["probe"].startswith("0a_")]
    assert logins
    assert all(p["result"]["cookie_names"] == [] for p in logins)
    assert all(v == "no session" for v in report["login_variants"].values())


def test_the_username_sent_is_described_without_repeating_his_own() -> None:
    """The literal defaults are ours to publish; a configured username is his."""
    kind = sms_delete_probe._value_kind

    assert kind({"field": None, "value": None}) == "field absent"
    assert kind({"field": "user", "value": ""}) == "empty"
    assert kind({"field": "user", "value": "user"}) == "user"
    assert kind({"field": "user", "value": "admin"}) == "admin"
    assert kind({"field": "user", "value": "his-own"}) == "the configured username"


def test_every_rule_in_the_space_has_its_own_name() -> None:
    """The report is keyed by name, so two rules sharing one lose a finding.

    Four single-round rules once shared a label because the outer case was left
    out of it, and the candidate table silently reported fewer entries than
    were sent.
    """
    space = sms_delete_probe._token_space(_MC888_VALUES)

    names = [name for name, _rule in space]
    assert len(set(names)) == len(names)


def test_a_rule_is_a_function_of_the_values_read_at_the_time() -> None:
    """A token is single-use on this hardware, so the space cannot hold tokens.

    Measured on the reference MC7010: the first write carrying a given token
    succeeds and every later write carrying the same one is refused, at any
    delay, while `RD` is unchanged. Re-reading re-arms it.
    """
    space = sms_delete_probe._token_space(_MC888_VALUES)

    _name, rule = space[0]
    assert rule(_MC888_VALUES) != rule({**_MC888_VALUES, "rd": "c" * 32})


async def test_whether_an_intervening_read_spends_the_token_is_measured() -> None:
    """The token is single-use, and what spends it is not fully established.

    `get_ad` makes three calls of its own before the write follows. If a read
    between deriving and posting invalidates the token, every write on a device
    that orders things differently fails for a reason no token variant can
    reach.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    names = [p["probe"] for p in report["probes"]]
    assert "20g_derive_then_post" in names
    assert "20h_derive_read_then_post" in names


async def test_the_write_is_also_tried_as_a_query_string() -> None:
    """`nicjac` logs in by GET against this same endpoint.

    So the firmware reads parameters from the query string on at least one
    command, and whether it does so for a write is untested.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    assert "20i_write_as_query" in [p["probe"] for p in report["probes"]]


async def test_the_write_is_tried_without_a_cookie_and_under_another_name() -> None:
    """`Kajkac` sends no cookie at all to a device issuing `zsidn`.

    Whether replaying it helps, is ignored, or names a session the firmware
    considers closed has never been tested.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    names = [p["probe"] for p in report["probes"]]
    assert "20j_no_cookie" in names
    assert "20k_cookie_named_stok" in names


async def test_the_held_cookies_are_put_back_after_the_cookie_variants() -> None:
    """Every rung below would otherwise run without a session this one removed."""
    coordinator = _coordinator()

    await run_probe(coordinator, ACTION_FULL)

    # Whatever the login stage ended up holding, the cookie rungs put it back.
    assert coordinator.api.cookies
    assert "zsidn" in coordinator.api.cookies


async def test_a_token_captured_before_a_relogin_is_tried_once() -> None:
    """The two reference implementations disagree about token lifetime.

    `Kajkac` reuses a token captured at authentication; `nicjac` derives fresh,
    as this integration does. Neither is attested on an MC888, so one rung
    settles it for this device.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    assert "20l_token_captured_at_login" in [p["probe"] for p in report["probes"]]


async def test_bundles_that_could_not_be_read_are_mined_again() -> None:
    """The reporter's pass recorded `js/statusBar.js: HTTP 404`.

    A name appearing only in a bundle nobody read is invisible to every other
    rung.
    """
    coordinator = _coordinator()
    coordinator.api.mine_candidate_names = AsyncMock(
        return_value=({"a", "b"}, ["js/statusBar.js: HTTP 404"])
    )

    report = await run_probe(coordinator, ACTION_FULL)

    result = _by_name(report, "20m_remine_bundles")["result"]
    assert result["mined"] == 2
    assert result["notes"] == ["js/statusBar.js: HTTP 404"]


async def test_the_login_that_wrote_is_adopted_for_the_rest_of_the_run() -> None:
    """Answering the hardest question and not using the answer costs a round trip.

    Every rung below the login stage asks something that only means anything on
    a session that can write, and this pass already had the router in front of
    it.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["login_variant_that_wrote"]
    assert report["session_in_use"] == report["login_variant_that_wrote"]
    adopted = [p for p in report["probes"] if p["probe"].startswith("0y_adopt_")]
    assert len(adopted) == 1


async def test_a_winner_that_will_not_come_back_falls_back_to_the_shipped_login() -> (
    None
):
    """A session that cannot be re-established is not one to run a pass on.

    Saying which session the findings were taken under is the difference
    between a report that can be read and one that cannot.
    """
    coordinator = _coordinator()
    calls = {"n": 0}

    def cookies_then_none(*_args: object, **_kwargs: object) -> dict[str, str]:
        calls["n"] += 1
        # The first variant establishes a session and writes; the adoption
        # attempt that follows every other rung draws nothing.
        return {} if calls["n"] > 1 else {"zsidn": "cookie-value"}

    coordinator.api._extract_cookies = MagicMock(side_effect=cookies_then_none)

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["session_in_use"].startswith("shipped login")


async def test_a_run_with_no_winner_says_which_session_it_used() -> None:
    """A report that does not name its session cannot be compared with another."""
    coordinator = _coordinator()
    coordinator.api._extract_cookies = MagicMock(return_value={})

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["login_variant_that_wrote"] is None
    assert report["session_in_use"] == "shipped login"


async def test_a_transport_that_works_is_held_for_the_rest_of_the_run() -> None:
    """A value discovered and then not used is the defect two audits found.

    Every write below inherits the carrier that was proven, without being told.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["transport_in_use"] != "shipped transport"
    assert report["transport_variants"]


async def test_the_adopted_transport_does_not_outlive_its_run() -> None:
    """It is module state, and it must not cross a run boundary.

    An adopted carrier silently changes how every write below it is sent.
    """
    coordinator = _coordinator()
    await run_probe(coordinator, ACTION_FULL)

    coordinator.api._request = AsyncMock(return_value={"result": "failure"})
    report = await run_probe(coordinator, ACTION_FULL)

    assert report["transport_in_use"] == "shipped transport"


async def test_a_delete_is_carried_the_way_a_write_was_proven() -> None:
    """A delete must inherit the carrier the run has already proven.

    Sending one through a transport the device refuses fails for a reason this
    run has already solved.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    # The deletes ran, and they ran after a transport was adopted.
    names = [p["probe"] for p in report["probes"]]
    assert "16_confirmed_single" in names
    assert names.index("20a_referer_root") < names.index("16_confirmed_single")


async def test_the_documented_derivations_are_tried_first() -> None:
    """The screening pass runs to the cap, so a run cut short loses its tail.

    `wa + cr` is what miononno documents for the MC888 Pro; it should not sit
    behind operands nobody has cited.
    """
    space = sms_delete_probe._token_space(_MC888_VALUES)

    names = [name for name, _rule in space]
    # `wa_version + cr_version` is the internally consistent pair on the
    # reporter's firmware — both `1.0.1` — and leads for that reason.
    assert names[0].startswith("wavcr_")


async def test_a_writes_response_header_names_are_recorded() -> None:
    """A refused write that sets a cookie is otherwise invisible."""
    coordinator = _coordinator()
    coordinator.api.last_response_header_names = ["Content-Type", "Set-Cookie"]

    report = await run_probe(coordinator, ACTION_FULL)

    record = _by_name(report, "20a_referer_root")
    assert record["response_header_names"] == ["Content-Type", "Set-Cookie"]


async def test_not_callback_is_tried_on_a_write_that_is_not_a_delete() -> None:
    """`Kajkac` carries it on its writes.

    This integration sends it only on a delete, so it has never been tried on
    anything else.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    assert "20n_not_callback" in [p["probe"] for p in report["probes"]]


async def test_a_run_that_saw_no_headers_records_none() -> None:
    """Absent is a fact; an empty list read as a fact would be a wrong one."""
    coordinator = _coordinator()
    coordinator.api.last_response_header_names = []

    report = await run_probe(coordinator, ACTION_FULL)

    assert "response_header_names" not in _by_name(report, "20a_referer_root")


async def test_every_screened_attempt_is_kept_not_only_the_ones_that_worked() -> None:
    """Collapsing a refusal to one word discards the evidence.

    A token refused differently from its neighbours — another `result` string,
    another status, a much slower answer — would have been invisible, on the
    part of the run most likely to hold the finding.
    """
    coordinator = _coordinator()
    coordinator.api._request = AsyncMock(return_value={"result": "failure"})

    report = await run_probe(coordinator, ACTION_FULL)

    screened = [p for p in report["probes"] if p["probe"].startswith("7b_")]
    # One record per rule, plus a verified re-run for any that claimed success.
    assert len(screened) >= len(report["candidates"])
    named = {p["probe"].removeprefix("7b_").removesuffix("_verified") for p in screened}
    assert named == set(report["candidates"])
    assert all("status" in p and "elapsed_seconds" in p for p in screened)


async def test_an_attempt_records_what_it_carried() -> None:
    """An attempt must say what it sent.

    A variant that silently failed to carry its override is otherwise
    indistinguishable from one the router refused.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    carried = _by_name(report, "20b_browser_headers")["carried"]
    assert carried["method"] == "POST"
    assert "Origin" in carried["header_names"]
    assert carried["command"] == "DATA_LIMIT_SETTING"


async def test_the_token_is_described_and_never_published() -> None:
    """Its length and case identify the digest, which is all a reader needs."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    carried = _by_name(report, "20a_referer_root")["carried"]
    assert set(carried) >= {"token_length", "token_case"}
    assert carried["token_case"] in ("upper", "lower", "mixed", "no letters")
    assert not any(isinstance(v, str) and len(v) > 24 for v in carried.values())


def test_the_case_of_a_digest_is_reported_without_the_digest() -> None:
    """Three states, and a fourth for a value that has no letters at all."""
    case_of = sms_delete_probe._case_of

    assert case_of("ABCDEF") == "upper"
    assert case_of("abcdef") == "lower"
    assert case_of("AbCdEf") == "mixed"
    assert case_of("123456") == "no letters"


async def test_the_login_is_also_tried_as_a_query_string() -> None:
    """`nicjac` logs in by GET against this same endpoint.

    It is the only login form in either reference implementation this
    integration has never sent.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    record = _by_name(report, "0a_L10_get_query")
    assert record["result"]["method"] == "GET"


async def test_the_axes_are_crossed_under_every_session_that_can_be_had() -> None:
    """Two axes at once is a fault a one-at-a-time run cannot see.

    A fix needing a particular login and a particular carrier together passes
    unseen through every rung that holds the others at their shipped value.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["logins_with_a_session"]
    assert report["combinations"]
    names = [p["probe"] for p in report["probes"]]
    assert any(n.startswith("21b_") for n in names)
    assert any(n.startswith("21c_") for n in names)


async def test_no_session_means_no_combinations_and_a_stated_reason() -> None:
    """A skipped pass with a reason beats one that silently ran nothing."""
    coordinator = _coordinator()
    coordinator.api._extract_cookies = MagicMock(return_value={})

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["logins_with_a_session"] == []
    skipped = _by_name(report, "21_combinations")
    assert skipped["outcome"] == "skipped"


def test_every_cited_rule_names_a_source_this_project_has_read() -> None:
    """What the combination pass crosses must be what a source documents.

    It cannot cross the whole space, so the six it does carry are the ones with
    a citation behind them rather than a preference.
    """
    names = [name for name, _rule in sms_delete_probe._CITED_RULES]

    assert names == [
        "wacr_sha_ll",
        "wacr_sha_uu",
        "wacr_md5_ll",
        "wa_sha_uu",
        "wa_md5_ll",
        "crwa_md5_lu",
        "wavcr_sha_uu",
        "wavcr_sha_ll",
    ]


async def test_the_carrier_is_found_before_the_token_space_is_screened() -> None:
    """Seven writes settle the carrier; a hundred and fifty screen the rules.

    Run the other way round, every rule is screened through a carrier that may
    itself be what the router is refusing, and the run reports a hundred and
    fifty refusals for a reason it solves two rungs later.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    names = [p["probe"] for p in report["probes"]]
    assert names.index("20a_referer_root") < names.index("7a_token_inputs")
    assert names.index("20a_referer_root") < min(
        i for i, n in enumerate(names) if n.startswith("7b_")
    )


async def test_a_screened_rule_carries_the_transport_that_was_proven() -> None:
    """The adopted carrier has to reach the sweep, not merely precede it."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    screened = next(p for p in report["probes"] if p["probe"].startswith("7b_"))
    assert "Referer" in screened["carried"]["header_names"]


async def test_the_confirmation_gate_reads_the_value_back() -> None:
    """This is the gate that decides whether real messages are spent.

    It is the last place to take the router's word for its own write, on an
    API this project's own code documents as answering `200 OK` to a refusal.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    confirmations = [p for p in report["probes"] if p["probe"].startswith("7h_")]
    assert confirmations
    assert all(p["verified"] is True for p in confirmations)


async def test_a_router_that_claims_success_and_changes_nothing_is_not_believed() -> (
    None
):
    """A read-back that shows the old value beats a `result` of success."""
    coordinator = _coordinator()
    coordinator.api._request = AsyncMock(return_value={"result": "success"})

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["working_variant"] is None
    skipped = _by_name(report, "16_confirmed_variant_deletes")
    assert skipped["outcome"] == "skipped"


async def test_a_switch_is_read_under_whichever_spelling_answers() -> None:
    """Devices differ on whether the field carries a `flux_` prefix.

    A toggle read under the wrong spelling reads as absent, and an absent
    toggle cannot be verified.
    """
    api = MagicMock()
    api.get_params = AsyncMock(
        return_value={
            "data_volume_limit_switch": "",
            "flux_data_volume_limit_switch": "1",
        }
    )

    alias, value = await sms_delete_probe._read_switch(
        api, ("data_volume_limit_switch", "flux_data_volume_limit_switch")
    )

    assert alias == "flux_data_volume_limit_switch"
    assert value == "1"


async def test_a_switch_no_spelling_answers_is_reported_absent() -> None:
    """A toggle nobody can read is a toggle nobody can verify.

    That is a finding rather than an error, so it is reported and not raised.
    """
    api = MagicMock()
    api.get_params = AsyncMock(return_value={})

    alias, value = await sms_delete_probe._read_switch(api, ("a", "b"))

    assert alias == "a"
    assert value is None


async def test_only_the_first_of_several_passing_rules_is_adopted() -> None:
    """Several may pass; the run spends messages through one of them.

    The rest are still recorded, because a device accepting more than one
    derivation says something different about its firmware than one accepting
    exactly one.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    assert len(report["candidates_passed"]) >= 1
    assert report["working_variant"] == report["candidates_passed"][0]


async def test_a_second_passing_rule_does_not_displace_the_first() -> None:
    """Both are recorded; the run spends its messages through one of them."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    passed = report["candidates_passed"]
    assert passed
    assert report["working_variant"] == passed[0]
    assert set(passed) <= set(report["candidates"])


async def test_two_rules_that_both_confirm_are_both_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All of them are kept, not only the one the run goes on to use.

    A device accepting several derivations says something different about its
    firmware than one accepting exactly one.
    """
    coordinator = _coordinator()
    # The space is narrowed by its own inputs rather than by replacing the
    # function that builds it: a mock there would sit exactly where a defect
    # would.
    monkeypatch.setattr(sms_delete_probe, "_OPERANDS", sms_delete_probe._OPERANDS[:1])
    monkeypatch.setattr(sms_delete_probe, "_RD_FORMS", sms_delete_probe._RD_FORMS[:1])
    monkeypatch.setattr(sms_delete_probe, "_CASES", sms_delete_probe._CASES[:1])

    report = await run_probe(coordinator, ACTION_FULL)

    assert len(report["candidates_passed"]) > 1
    assert report["working_variant"] == report["candidates_passed"][0]


async def test_a_rule_that_screens_and_then_stops_working_is_not_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One success is not a method, which is why screening only nominates.

    A rule that writes during screening and then fails its confirmations must
    not take the run on to spend real messages, and the rule after it must
    still be tried rather than the pass ending there.
    """
    coordinator = _coordinator()
    # Both cases kept, so the space holds several distinct rules and the pass
    # has a rule after the failing one to try.
    monkeypatch.setattr(sms_delete_probe, "_OPERANDS", sms_delete_probe._OPERANDS[:1])
    monkeypatch.setattr(sms_delete_probe, "_RD_FORMS", sms_delete_probe._RD_FORMS[:1])

    seen: dict[str, int] = {}
    original = coordinator.api._request.side_effect

    async def applies_each_token_once(*args, **kwargs):
        # The router — not the probe — is what changes here. A token works the
        # first time it is presented and never again, so every rule screens and
        # none of them survives its confirmations.
        body = str(kwargs.get("data") or (args[1] if len(args) > 1 else ""))
        if "goformId=DATA_LIMIT_SETTING" in body and "AD=" in body:
            token = body.split("AD=", 1)[1].split("&", 1)[0]
            seen[token] = seen.get(token, 0) + 1
            if seen[token] > 1:
                return {"result": "success"}
        return await original(*args, **kwargs)

    coordinator.api._request = AsyncMock(side_effect=applies_each_token_once)

    report = await run_probe(coordinator, ACTION_FULL)

    assert report["candidates_passed"] == []
    assert report["working_variant"] is None
    confirmed = {
        p["probe"].rsplit("_", 1)[0]
        for p in report["probes"]
        if p["probe"].startswith("7h_")
    }
    assert len(confirmed) > 1, "the rule after the failing one was not tried"


async def test_the_router_s_own_client_is_read_and_recorded() -> None:
    """Five probe versions decided what to send from constants written here.

    The router serves a working client of its own API; what that client sends
    is a measurement rather than a guess.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    index = _by_name(report, "22a_index")["result"]
    assert index["data_main"] == ["js/main"]
    assert index["script_src"]
    modules = _by_name(report, "22b_module_list")["result"]
    assert modules["declared"] == {
        "service": "service",
        "home": "home",
        "md5": "lib/md5",
    }
    bundles = _by_name(report, "22c_bundles")["result"]
    assert bundles["read"] >= 2


async def test_the_write_path_source_is_captured_from_the_router() -> None:
    """The code that builds a write says what the browser sends.

    It is the router's own script, served to anyone who opens its address, and
    carries nothing belonging to the reporter.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    captures = _by_name(report, "22d_write_path_source")["result"]["captures"]
    assert "goform_set_cmd_process" in captures
    assert any("hex_md5" in text for text in captures.get("rd0", []))
    assert "ACCESSIBLE_ID_SUPPORT" in captures


async def test_the_fields_the_router_sends_are_compared_with_ours() -> None:
    """A constant the device contradicts is the finding.

    It should be stated in the report rather than hunted for across a
    thousand records.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    diff = report["command_field_differences"]
    assert diff["DELETE_SMS"]["router_sends"]
    assert "notCallback" in diff["DELETE_SMS"]["router_sends"]
    assert "which_cgi" in diff["ALL_DELETE_SMS"]["router_sends"]
    assert set(diff) == {
        "DATA_LIMIT_SETTING",
        "NIGHT_MODE_INFO_SETTINGS",
        "DELETE_SMS",
        "ALL_DELETE_SMS",
    }


async def test_a_write_is_also_sent_carrying_no_token_at_all() -> None:
    """The router attaches `AD` only when its own flag is set.

    A firmware with that flag unset expects no token, and every request this
    project has ever sent carried one.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    record = _by_name(report, "23b_write_without_a_token")
    assert record["carried"]["token_sent"] is False


async def test_a_delete_is_sent_in_the_form_the_browser_uses() -> None:
    """The browser sends both the trailing semicolon and `notCallback`.

    This project has sent each separately and never the two together, which is
    not the same request.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    record = _by_name(report, "23c_delete_browser_form")
    assert record["sent"].count(";") >= 1
    assert "notCallback=true" in record["sent"]


async def test_a_page_that_cannot_be_read_is_a_finding_not_a_failure() -> None:
    """A router that answers nothing must still produce a report."""
    coordinator = _coordinator()
    coordinator.api.session.get = MagicMock(side_effect=OSError("no route"))

    report = await run_probe(coordinator, ACTION_FULL)

    index = _by_name(report, "22a_index")["result"]
    assert index["status"] is None
    assert "OSError" in index["head"] or index["bytes"] > 0


async def test_an_index_naming_no_entry_point_says_so() -> None:
    """Four downloads reported exactly that, and the run must not stop there."""
    coordinator = _coordinator()
    coordinator.api.session.get = MagicMock(
        side_effect=lambda url, **_kw: _FakeGet("http://router/nothing")
    )

    report = await run_probe(coordinator, ACTION_FULL)

    modules = _by_name(report, "22b_module_list")["result"]
    assert modules["note"] == "the index named no entry point"


async def test_the_router_form_write_is_skipped_when_nothing_was_extracted() -> None:
    """A fallback to our own constants would test this module, not the router.

    The result would read as a finding about his firmware when it is a finding
    about ours.
    """
    coordinator = _coordinator()
    coordinator.api.session.get = MagicMock(
        side_effect=lambda url, **_kw: _FakeGet("http://router/nothing")
    )

    report = await run_probe(coordinator, ACTION_FULL)

    skipped = _by_name(report, "23a_data_limit_router_form")
    assert skipped["outcome"] == "skipped"
    assert "field list" in skipped["reason"]


async def test_the_browser_form_delete_is_skipped_with_no_message_left() -> None:
    """A rung that needs a message says so rather than reporting a refusal."""
    coordinator = _coordinator([])

    report = await run_probe(coordinator, ACTION_FULL)

    skipped = _by_name(report, "23c_delete_browser_form")
    assert skipped["outcome"] == "skipped"


def test_the_source_capture_is_bounded_per_marker() -> None:
    """A minified bundle can mention a name hundreds of times.

    Capturing every one would put a megabyte of the same script into a
    download that is already several.
    """
    text = "goform_set_cmd_process " * 50

    captures = sms_delete_probe._captures(text, "goform_set_cmd_process")

    assert len(captures) == 4
    assert all(len(c) <= 2 * sms_delete_probe._CAPTURE_WINDOW for c in captures)


def test_the_field_reader_handles_malformed_and_nested_source() -> None:
    """Three readings of this were wrong before one was right.

    A window scan reported a neighbouring reader's fields as the command's own;
    a literal-only scan found none, because the data-limit form is assembled by
    assignment after the literal. These are the edges that produced each.
    """
    fields_for = sms_delete_probe._fields_for

    # No literal at all before the marker.
    assert fields_for('goformId:"X"', "X") == []
    # A literal that never closes inside the scan window.
    assert fields_for('{a:1,goformId:"X"' + " " * 5000, "X") == []
    # Keys of a nested object are not fields of this command.
    assert fields_for('{goformId:"X",a:1,b:{hidden:2}}', "X") == ["a", "b"]
    # Fields assigned to the literal afterwards are.
    assert fields_for('var _={goformId:"X"};_.later=1;', "X") == ["later"]
    # A quoted key is read; a computed one is not.
    assert fields_for('{goformId:"X","quoted":1,[k]:2}', "X") == ["quoted"]


async def test_a_caller_supplied_form_still_flips_and_is_verified() -> None:
    """Computing the flip only for forms this module builds made `23a` blind.

    It compared its read-back against `None` and could not report success
    whatever the router did — a false negative of the kind that rung exists to
    detect.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    record = _by_name(report, "23a_data_limit_router_form")
    assert record["result"]["flipped_from"] is not None
    assert record["result"]["flipped_to"] is not None
    assert record["verified"] is True


async def test_the_router_form_fills_a_field_the_poll_does_not_carry() -> None:
    """Dropping it sends our form under the router's name.

    The first run reported six fields where the router's code assembles seven,
    and the missing one is the whole reason the rung exists.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    record = _by_name(report, "23a_data_limit_router_form")
    assert "fields_the_device_would_not_answer" in record


async def test_which_cgi_is_read_from_the_script_not_assumed() -> None:
    """A guess reported as a measurement is worse than no rung at all."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    names = [p["probe"] for p in report["probes"]]
    tried = [n for n in names if n.startswith("23d_all_delete_which_cgi_")]
    assert tried
    assert all(
        _by_name(report, n)["which_cgi_from"] == "the router's own script"
        for n in tried
    )


async def test_no_which_cgi_value_means_the_rung_is_skipped() -> None:
    """Sending a guess would report our assumption as the router's behaviour."""
    coordinator = _coordinator()
    coordinator.api.session.get = MagicMock(
        side_effect=lambda url, **_kw: _FakeGet("http://router/nothing")
    )

    report = await run_probe(coordinator, ACTION_FULL)

    skipped = _by_name(report, "23d_all_delete_which_cgi")
    assert skipped["outcome"] == "skipped"
    assert "guess" in skipped["reason"]


async def test_a_form_the_poll_already_carries_needs_no_extra_read() -> None:
    """The fill is for the gap, not a second read of what is already known."""
    coordinator = _coordinator()
    # Every field the fixture's script names is in the poll payload, so there
    # is nothing left to fetch.
    coordinator.data = {
        **coordinator.data,
        "data_volume_limit_size": "50_1024",
        "traffic_clear_date": "1",
        "notify_deviceui_enable": "1",
        "data_volume_limit_switch": "1",
    }

    report = await run_probe(coordinator, ACTION_FULL)

    record = _by_name(report, "23a_data_limit_router_form")
    assert record["fields_the_device_would_not_answer"] == []


async def test_the_crawl_reaches_a_file_only_a_dependency_array_names() -> None:
    """The module map is not the loader's whole answer.

    On the reference MC7010 the index names three scripts and the `paths` map a
    dozen more, while the browser loads thirty-one. The assignment that
    resolves the write token was in one of the files that difference accounts
    for, and six probe runs never fetched it because the probe read only what
    was declared.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_CAPTURE)

    sources = report["source_capture"]["sources"]
    assert "js/app.js" in sources
    assert "js/language.js" in sources


async def test_a_library_is_followed_but_not_returned() -> None:
    """Its dependencies matter; its megabyte of source does not."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_CAPTURE)

    capture = report["source_capture"]
    assert "js/lib/md5.js" in capture["files"]
    assert "js/lib/md5.js" not in capture["sources"]


async def test_every_captured_file_carries_a_size_and_a_digest() -> None:
    """So two devices can be compared without diffing a megabyte."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_CAPTURE)

    records = report["source_capture"]["files"]
    answered = [r for r in records.values() if r["status"] == 200]
    assert answered
    assert all("sha256" in r and "bytes" in r for r in answered)


async def test_a_listed_file_that_is_not_served_is_reported() -> None:
    """A 404 used to be a silent skip, which is how four downloads said nothing."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_CAPTURE)

    assert _by_name(report, "24a_source_crawl")["result"]["missing"]


async def test_the_rd_assignment_site_is_extracted_with_its_surroundings() -> None:
    """Naming the file is not enough; the line is what settles the derivation."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_CAPTURE)

    result = _by_name(report, "24b_rd_assignment")["result"]
    assert "js/language.js" in result["files_with_an_assignment"]
    assert "rd_params0" in result["sites"]["js/language.js"][0]


async def test_whether_the_device_answers_cr_version_is_reported() -> None:
    """It decides whether the shipped derivation matches this firmware at all.

    `get_ad` uses `wa_inner_version` alone, which equals the firmware's
    `rd0 + rd1` only where `cr_version` is unanswered.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_CAPTURE)

    result = _by_name(report, "24c_token_operands")["result"]
    assert "cr_version_answered" in result
    assert "operands_differ_from_shipped" in result


async def test_capture_writes_nothing() -> None:
    """The default action is read-only, so it cannot lock an account out."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_CAPTURE)

    assert report["action"] == ACTION_CAPTURE
    assert report["completed"] is True
    names = [p["probe"] for p in report["probes"]]
    assert not [n for n in names if n.startswith(("0a_", "20", "23", "8_", "15_"))]
    coordinator.api.session.post.assert_not_called()


async def test_capture_is_recorded_before_any_write_is_attempted() -> None:
    """A lockout or a timeout in a later stage must not cost the capture.

    The probe persists its report as it goes, so the sequencing is what
    protects the one stage expected to return something new.
    """
    coordinator = _coordinator()
    seen: list[int] = []
    original = coordinator.persist_delete_probe

    def _record() -> None:
        report = coordinator.api.delete_probe or {}
        seen.append(len(report.get("probes", [])))
        original()

    coordinator.persist_delete_probe = _record

    await run_probe(coordinator, ACTION_FULL)

    report = coordinator.api.delete_probe
    # A persist happened once the crawl had been recorded and before the first
    # login variant was tried.
    assert "source_capture" in report
    assert any(count >= 1 for count in seen)


async def test_confirm_writes_but_does_not_sweep() -> None:
    """About twenty writes, each read back; not fifteen hundred derivations."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_CONFIRM)

    names = [p["probe"] for p in report["probes"]]
    assert report["action"] == ACTION_CONFIRM
    assert report["completed"] is True
    assert "24a_source_crawl" in names
    assert [n for n in names if n.startswith("20")]
    # The token sweep, the crossed axes and the real-message ladder are the
    # stages that cost a fifteen-minute run, and they are kept for `full`.
    assert not [n for n in names if n.startswith(("7a_", "7b_", "21", "8_", "15_"))]


async def test_full_still_runs_every_rung_the_probe_has_ever_carried() -> None:
    """Nothing is deleted from the module, only switched off by default."""
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_FULL)

    names = [p["probe"] for p in report["probes"]]
    assert report["action"] == ACTION_FULL
    for prefix in ("24a_", "0a_", "20a_", "7a_", "22a_", "23a_"):
        assert [n for n in names if n.startswith(prefix)], prefix


async def test_a_module_reference_resolves_the_way_the_loader_resolves_it() -> None:
    """Extensionless, relative, and text-plugin names all name a real path."""
    assert _resolve("service") == "js/service.js"
    assert _resolve("./home") == "js/home.js"
    assert _resolve("text!tmpl/login.html") == "tmpl/login.html"
    assert _resolve("js/config/config.js") == "js/config/config.js"
    assert _resolve("/js/util.js") == "js/util.js"
    assert _resolve("http://example.invalid/x.js") is None
    assert _resolve("") is None


async def test_a_truncated_file_is_reported_as_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A body cut to the cap must not look like the whole file."""
    monkeypatch.setattr(sms_delete_probe, "_MAX_RETURN_BYTES", 20)
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_CAPTURE)

    result = _by_name(report, "24a_source_crawl")["result"]
    assert result["truncated"]
    assert report["source_capture"]["files"]["js/service.js"]["returned_bytes"] == 20


def test_a_reference_that_names_nothing_fetchable_is_dropped() -> None:
    """A plugin prefix with no resource, and a path that escapes the root."""
    assert _resolve("text!") is None
    assert _resolve("js/../../etc/passwd") is None
    assert _resolve("js/a/../b") == "js/b.js"


async def test_an_alias_is_resolved_through_the_loaders_path_map() -> None:
    """A dependency array asks for `md5`; only the `paths` map says where it is.

    Resolving the alias literally invents `js/md5.js`, which the router does
    not serve. The first rehearsal fabricated eighteen names that way and
    reported every one as a file the device had failed to serve.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_CAPTURE)

    files = report["source_capture"]["files"]
    assert "js/lib/md5.js" in files
    assert "js/md5.js" not in files


async def test_the_model_specific_directory_is_fetched() -> None:
    """Nothing refers to it by name: the loader composes the path at runtime.

    It holds the config that overrides the general one, so a build whose write
    path differs could differ there and nowhere else.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_CAPTURE)

    assert "js/config/cpe/MF253V/config.js" in report["source_capture"]["sources"]


def test_a_reference_with_no_name_left_is_dropped() -> None:
    """`js/config/` names a directory, and `.js` is not a file."""
    assert _resolve("js/config/") is None


async def test_the_token_operand_read_survives_a_device_that_answers_one_key() -> None:
    """Three of the four version keys are unanswered on the reference device.

    Without `requested=`, the session classifier sees a mostly-empty reply,
    judges the session expired and the rung raises — reporting nothing about
    the one question it exists to answer.
    """
    coordinator = _coordinator()

    report = await run_probe(coordinator, ACTION_CAPTURE)

    record = _by_name(report, "24c_token_operands")
    assert record["outcome"] == "returned"
    assert "cr_version_answered" in record["result"]


async def test_the_crawl_is_seeded_from_the_static_list_too() -> None:
    """An index that names no scripts is the fault this probe exists for.

    Four downloads from the device of issue #56 reported exactly that, so a
    crawl starting only from what the index declares starts there from nothing.
    """
    coordinator = _coordinator()
    coordinator.api.session.get = lambda url, **_kw: _FakeGet(
        url.replace("index.html", "empty.html")
    )

    report = await run_probe(coordinator, ACTION_CAPTURE)

    assert "js/service.js" in report["source_capture"]["sources"]


def test_a_marker_captured_fewer_than_four_times_ends_the_scan() -> None:
    """The bound exists for a marker that occurs throughout a bundle."""
    assert _captures("no matches here", "X") == []
    assert len(_captures("a X b X c", "X")) == 2
    assert len(_captures("X" * 10, "X")) == 4
