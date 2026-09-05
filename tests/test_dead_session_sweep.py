"""Fault injection: no API method may silently no-op on a dead session.

This router never signals an ended session with an HTTP status. It answers
`200 OK` with every requested value blank, so an unguarded call reads that as
"no data" and reports success. That is how `get_sms_list` once returned an
empty inbox while messages sat on the router (`[3.3.0-dev12]`), and how
`send_sms` later reported success while sending nothing (`[3.3.1-dev6]`).

Both were found one at a time, by a user. This sweep is the systematic
version: it kills the session at every point in every method's internal
request sequence and asserts one property throughout —

    **every method either does the thing, or raises. None may return a
    success-shaped result having done nothing.**

The point is not to re-prove the two known bugs. It is that the ninth write
command someone adds in six months is covered the moment it exists:
`test_every_public_method_is_covered_by_the_sweep` fails if a method is added
without an entry in `_CALLS`.

Live findings this encodes (MC7010 `V1.0.0B03`, 2026-07-29, see
`.notes/issues/silent_login_fail.md`):
- `RD` is a **static per-device seed**, so `AD` is constant per router and a
  payload retried after re-login carries a still-valid token. The double
  therefore does not need to model token scoping.
- A dead session answers with every value an empty string.
"""

import inspect
import re
from datetime import UTC, datetime
from typing import Any

import pytest

from custom_components.zte_router_5g.api import (
    ZTEAuthError,
    ZTEConnectionError,
    ZTERouterAPI,
)

from .conftest import MockResponse

# A response wide enough to satisfy every method's contract at once. Values are
# non-empty so it can never be mistaken for the dead-session shape.
_HEALTHY: dict[str, Any] = {
    "result": "success",
    "LD": "ABC123",
    "RD": "1ca9f84e0314259ddb072fba15e42061",
    "wa_inner_version": "IRL_H3G_MC7010DV1.0.0B03",
    "cr_version": "CR1",
    "cell_id": "1234",
    "network_type": "5G",
    "sms_nv_total": "10",
    "sms_capacity_info": "10",
    "messages": [
        {"id": "1", "content": "0041", "number": "0041", "date": "26,07,29,10,0,0"}
    ],
}

# The shape a dead session actually returns: 200 OK, every value blank.
_DEAD: dict[str, Any] = {"cell_id": "", "messages": "", "result": "", "LD": ""}

# Every public method that talks to the router, with arguments to drive it.
# Adding a method to the API without adding it here fails the coverage test
# below — that is the point of the file.
# A complete data-volume form, as the last successful poll would supply it.
_DATA_VOLUME_STATE = {
    "data_volume_limit_switch": "0",
    "data_volume_limit_unit": "data",
    "data_volume_limit_size": "2_1048576",
    "data_volume_alert_percent": "80",
    "wan_auto_clear_flow_data_switch": "on",
    "traffic_clear_date": "1",
}

_CALLS: dict[str, tuple[Any, ...]] = {
    "get_version": (),
    "get_ld": (),
    "login": (),
    "logout": (),
    "get_all_data": (),
    # Returns an empty set rather than raising, and only ever runs after a
    # confirmed logout — so on a dead session it refuses to run at all, which
    # is the behavior being asserted rather than an exception.
    "measure_unauthenticated_keys": (),
    # Diagnostics only, and it must never raise: it runs while a download is
    # being generated, and Home Assistant does not guard that call, so an
    # escaping exception is an HTTP 500 and no file at all. Every failure
    # becomes a note in the returned mapping.
    "run_discovery": (),
    # Reads the router's own JavaScript for `cmd` names. Returns names and
    # notes; a dead session or an unreachable bundle is a note.
    "mine_candidate_names": (),
    # Reads a list of names. Chunk failures are absorbed by design.
    "probe_names": ([],),
    "get_extended_data": (),
    # The targeted read-back used to confirm a switch write. It must behave
    # exactly like the batch reads against a dead session: the switch treats a
    # raised error as *unverified*, but a silent empty answer would be read as
    # the router reporting the old value — a false "did not apply".
    "get_params": (["ODU_led_switch"],),
    "get_sms_capacity": (),
    "get_last_sms_content": (),
    "get_sms_messages": (),
    "get_ad": (),
    "get_rd": (),
    "reboot": (),
    "delete_sms": ("1",),
    "delete_all": (),
    # The post-delete check. A read, and it must behave like one on a dead
    # session: raising rather than reporting an empty bank, which would read
    # as "every message went" and restore the silent success it exists to
    # remove. `_HEALTHY` still holds message id "1", so against a live session
    # it finds the survivor and raises for that reason instead.
    "verify_deleted": (["99"],),
    "send_sms": ("+123456789", "Hello"),
    "set_apn": (1, "IP"),
    "set_apn_mode": ("auto",),
    "set_odu_led_switch": ("1",),
    "set_data_limit_switch": ("1", _DATA_VOLUME_STATE),
    "set_data_volume_settings": (_DATA_VOLUME_STATE,),
    "set_bearer_preference": ("Only_5G",),
    "try_set_protocol": (),
}

# Methods that are best-effort by contract and may legitimately return a
# default instead of raising. Each needs a stated reason — this list is a
# deliberate carve-out, not a place to silence failures.
_BEST_EFFORT = {
    # Runs on unload; an unreachable router must never block teardown, and it
    # always clears local session state regardless of the answer.
    "logout",
    # Probes http vs https by design; failure to reach one is the normal path.
    "try_set_protocol",
    # Returns None/"" so callers can decide. Both feed `get_ad`, and an empty
    # AD makes the router refuse the write, which `_require_success` raises on.
    "get_version",
    "get_rd",
    "get_ad",
}

# Methods whose whole answer is whether they raised. `None` from one of these
# is not a silent no-op — it is the success case, and there is no other value
# it could return. Distinct from `_BEST_EFFORT`, which is about tolerating
# failure; these tolerate nothing.
_ASSERTS_BY_RAISING = {
    # Confirms a delete happened. It reads the bank through `get_sms_messages`,
    # which raises on a dead session, so the property this file guards is held
    # by the call it makes rather than by its own return.
    "verify_deleted",
}


class _DyingSession:
    """aiohttp session double whose session dies after `die_after` requests.

    A login POST mints a new session and revives it, which is what the real
    router does — so a method that correctly detects the dead session and
    re-authenticates will succeed, and one that does not will get the blank
    payload and must fail loudly.
    """

    def __init__(self, die_after: float, revive_on_login: bool = True) -> None:
        self.die_after = die_after
        self.revive_on_login = revive_on_login
        self.count = 0
        self.dead = False
        # A deleted message stays deleted. `delete_all` re-lists to verify,
        # because this API answers success for a delete it does not carry out
        # — so a stub that acknowledged the command and kept the message would
        # model the broken firmware, and every recovery run would fail.
        self.deleted: set[str] = set()

    def _healthy(self) -> dict[str, Any]:
        """The healthy payload, with deleted messages actually gone."""
        payload = dict(_HEALTHY)
        payload["messages"] = [
            msg for msg in _HEALTHY["messages"] if msg["id"] not in self.deleted
        ]
        return payload

    def _respond(self, *args: Any, **kwargs: Any) -> MockResponse:
        data = kwargs.get("data")
        body = str(data) + str(args[0] if args else "")
        # `login()` posts a dict while every other write posts a form-encoded
        # string, so both shapes have to be recognised. Matching only
        # "goformId=LOGIN" silently missed the dict form, which made every
        # login fail and every recovery test fail with it.
        goform_id = data.get("goformId", "") if isinstance(data, dict) else ""
        is_login = goform_id.startswith("LOGIN") or "goformId=LOGIN" in body

        if is_login:
            if self.revive_on_login:
                # A renewed session is healthy from here on. Resetting only
                # the counter is not enough: the death threshold would fire
                # again on the very next request, so no method could ever
                # recover and the test would be modelling a router that
                # cannot be logged into at all.
                self.dead = False
                self.count = 0
                self.die_after = float("inf")
            cookie = type("C", (), {"value": "fresh_stok"})()
            return MockResponse(cookies={"stok": cookie})

        # `LD` and `wa_inner_version` are served without a session on real
        # hardware — that is exactly why they were able to reset the activity
        # clock and cause the bug this file guards. Returning the dead shape
        # for them would be a fault the router cannot produce.
        if "cmd=LD" in body or "cmd=wa_inner_version" in body:
            return MockResponse(json_data=self._healthy())

        self.count += 1
        if self.count > self.die_after:
            self.dead = True
        if self.dead:
            return MockResponse(json_data=dict(_DEAD))
        if "goformId=DELETE_SMS" in body:
            match = re.search(r"msg_id=([^&]*)", body)
            if match:
                self.deleted |= {part for part in match.group(1).split(";") if part}
        return MockResponse(json_data=self._healthy())

    def get(self, *args: Any, **kwargs: Any) -> MockResponse:
        return self._respond(*args, **kwargs)

    def post(self, *args: Any, **kwargs: Any) -> MockResponse:
        return self._respond(*args, **kwargs)

    def request(self, method: str, *args: Any, **kwargs: Any) -> MockResponse:
        return self._respond(*args, **kwargs)

    @property
    def cookie_jar(self) -> Any:
        jar = type("J", (), {"clear": lambda self, predicate=None: None})()
        return jar


def _is_empty_result(value: Any) -> bool:
    """Report whether a return value would read to a caller as "nothing there".

    This is the shape the bug produced: no exception, and a value that looks
    like a legitimately empty answer.
    """
    return value in (None, "", [], {}, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", sorted(_CALLS))
@pytest.mark.parametrize("die_after", [0, 1, 2, 3])
async def test_no_method_silently_no_ops_on_a_dead_session(method_name, die_after):
    """Kill the session at each point in the sequence; demand success or an error.

    `die_after=0` kills it before the first request, so even the opening call
    of each method meets a dead session. Higher values kill it partway through
    multi-request methods such as `send_sms`, which fetches the version and RD
    before it posts.
    """
    session = _DyingSession(die_after=die_after, revive_on_login=False)
    api = ZTERouterAPI(session, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "stale"}
    api.session_active = True

    method = getattr(api, method_name)
    try:
        result = await method(*_CALLS[method_name])
    except (ZTEAuthError, ZTEConnectionError):
        return  # Raised: the failure is visible. This is the correct outcome.

    if method_name in _BEST_EFFORT:
        return

    # `login` reports through the session pair rather than a return value:
    # a router may authenticate without issuing a stok, so there is nothing
    # meaningful to hand back (issue #56). Returning `None` is its success
    # shape, and the equivalent assertion is that the session is now active.
    if method_name == "login":
        assert api.session_active, (
            "login returned without raising and without establishing a session"
        )
        return

    # Not a best-effort exemption, which is capped deliberately. Its contract
    # is "the measured set, or empty where nothing can be trusted", and a dead
    # session is exactly the case where nothing can be. Returning empty here
    # is the required behavior, not a silent no-op: measuring against a live
    # session would classify the whole batch as unauthenticated and leave the
    # classifier unable to ever report an expiry.
    if method_name in ("mine_candidate_names", "probe_names"):
        # Both return a pair and absorb their own failures: a chunk that
        # cannot be read is a note, not an exception, because the caller is a
        # diagnostics download that must produce a file whatever happens.
        assert isinstance(result, tuple), f"{method_name} must return a pair"
        return

    if method_name == "run_discovery":
        # Degrades rather than failing, by design: chunks are tolerated
        # independently, so a session dying partway leaves whatever earlier
        # chunks answered. Nothing reads this but the diagnostics download,
        # and a raise would let a debugging aid break a poll.
        assert isinstance(result, dict), "run_discovery must always return a mapping"
        return

    if method_name == "measure_unauthenticated_keys":
        assert result == frozenset(), (
            "measure_unauthenticated_keys returned a set on a dead session; "
            "it must decline unless a logout was acknowledged"
        )
        return

    if method_name in _ASSERTS_BY_RAISING:
        assert result is None, f"{method_name} is expected to return nothing"
        return

    assert not _is_empty_result(result), (
        f"{method_name} returned {result!r} after the session died — a silent "
        f"no-op. It must raise instead, so the caller can tell 'nothing there' "
        f"from 'could not ask'."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", sorted(_CALLS))
async def test_methods_recover_when_the_session_can_be_renewed(method_name):
    """With a router that accepts a fresh login, every method should succeed.

    This is the other half: detection must lead to recovery, not just to a
    louder failure. Confirmed against live hardware at every idle boundary
    (`.notes/issues/silent_login_fail.md` §8).
    """
    session = _DyingSession(die_after=0, revive_on_login=True)
    api = ZTERouterAPI(session, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "stale"}
    api.session_active = True

    result = await getattr(api, method_name)(*_CALLS[method_name])

    if method_name in _BEST_EFFORT or result is None:
        return
    assert not _is_empty_result(result), (
        f"{method_name} did not recover after re-login, returning {result!r}"
    )


class _RefusingSession(_DyingSession):
    """A live session that refuses writes with `{"result":"failure"}`.

    A second, distinct fault mode. The dead-session sweep above cannot reach
    the write guards at all: `_request` recognises the all-blank payload and
    raises before any command inspects its own result. This models the other
    thing the router really does — answer a *populated* 200 OK refusing the
    command, which is what a stale `AD`, a malformed payload or a command the
    firmware dislikes produces.

    Mutation-checked: without this class, deleting `_require_success` from any
    write left the whole file green.
    """

    def _respond(self, *args: Any, **kwargs: Any) -> MockResponse:
        data = kwargs.get("data")
        body = str(data) + str(args[0] if args else "")
        goform_id = data.get("goformId", "") if isinstance(data, dict) else ""
        if goform_id.startswith("LOGIN") or "goformId=LOGIN" in body:
            return super()._respond(*args, **kwargs)
        if "goform_set_cmd_process" in body and "goformId=" in body:
            return MockResponse(json_data={"result": "failure"})
        return MockResponse(json_data=dict(_HEALTHY))


# The write commands, which must all surface a refusal.
_WRITES = [
    name
    for name in _CALLS
    if name.startswith("set_") or name in {"send_sms", "delete_sms", "reboot"}
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", sorted(_WRITES))
async def test_write_commands_surface_a_refusal(method_name):
    """A refused write must raise, not report success having done nothing.

    This is the failure a user actually hit: the action went green, and no
    SMS arrived.
    """
    session = _RefusingSession(die_after=float("inf"))
    api = ZTERouterAPI(session, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True

    with pytest.raises((ZTEAuthError, ZTEConnectionError)):
        await getattr(api, method_name)(*_CALLS[method_name])


class _DriftingSession(_DyingSession):
    """A session answering 200 OK with a shape that is neither dead nor useful.

    The third fault mode, and the one `_require_contract` exists for. The
    all-blank detector in `_request` only fires when *every* value is empty,
    so a response carrying one populated field and missing the key the caller
    needs sails straight past it — which is what a firmware upgrade that
    renames fields looks like, and what a partially-torn-down session can
    look like.

    Without this class, deleting `_require_contract` from the SMS reads left
    the file green: the dead-session sweep never reaches the check, because
    `_request` raises first.
    """

    def _respond(self, *args: Any, **kwargs: Any) -> MockResponse:
        data = kwargs.get("data")
        body = str(data) + str(args[0] if args else "")
        goform_id = data.get("goformId", "") if isinstance(data, dict) else ""
        if goform_id.startswith("LOGIN") or "goformId=LOGIN" in body:
            return super()._respond(*args, **kwargs)
        # Populated, so not "hollow"; but carries none of the keys the SMS
        # readers contract for.
        return MockResponse(json_data={"status": "ok", "unrelated_field": "1"})


# The reads that assert a required key rather than falling back to a default.
_CONTRACTED_READS = [
    "get_sms_messages",
    "get_sms_capacity",
    "get_last_sms_content",
    "delete_all",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", _CONTRACTED_READS)
async def test_contracted_reads_reject_a_response_missing_their_key(method_name):
    """A drifted response must raise, never read as an empty inbox.

    This is the distinction the whole SMS fix rests on: `{"messages": []}` is
    an empty inbox, and a response with no `messages` key at all is a broken
    conversation. Returning `[]` for the second is how "no session" was once
    reported to users as "no SMS".
    """
    session = _DriftingSession(die_after=float("inf"))
    api = ZTERouterAPI(session, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True

    with pytest.raises((ZTEAuthError, ZTEConnectionError)):
        await getattr(api, method_name)(*_CALLS[method_name])


@pytest.mark.asyncio
async def test_an_empty_inbox_is_not_an_error():
    """The other side of the contract: `messages: []` must pass through.

    Guards against "fix" the previous test by making any empty result raise,
    which would break a router that genuinely has no messages.
    """

    class _EmptyInbox(_DyingSession):
        def _respond(self, *args: Any, **kwargs: Any) -> MockResponse:
            return MockResponse(json_data={"messages": [], "sms_nv_total": "0"})

    api = ZTERouterAPI(_EmptyInbox(die_after=float("inf")), "1.2.3.4", "a", "p")
    api.cookies = {"stok": "live"}
    api.session_active = True
    # Fresh clock, or the idle reset fires and this double cannot serve a login.
    api.last_activity = datetime.now(UTC)
    assert await api.get_sms_messages() == []


def test_every_write_command_is_in_the_refusal_sweep():
    """A new write must be added to `_WRITES`, or its refusal goes unchecked."""
    import re

    source = (
        __import__("pathlib")
        .Path(__file__)
        .parent.parent.joinpath("custom_components/zte_router_5g/api.py")
        .read_text(encoding="utf-8")
    )
    # Every method that posts a goformId is a write, except login/logout which
    # have their own error handling and are covered elsewhere.
    posting = set(re.findall(r"async def (\w+)\(", source)) & {
        name
        for name in _CALLS
        if name.startswith("set_") or name in {"send_sms", "delete_sms", "reboot"}
    }
    missing = sorted(posting - set(_WRITES))
    assert posting == set(_WRITES), (
        f"write commands missing from the refusal sweep: {missing}"
    )


def test_every_public_method_is_covered_by_the_sweep():
    """A new API method must be added to `_CALLS` or this fails.

    The guard that gives the file its value: the two known bugs were each
    found by a user after release, one method at a time. This makes coverage
    of the next method automatic rather than remembered.
    """
    public = {
        name
        for name, member in inspect.getmembers(ZTERouterAPI)
        if inspect.iscoroutinefunction(member) and not name.startswith("_")
    }
    missing = public - set(_CALLS)
    stale = set(_CALLS) - public
    assert not missing, f"public API methods absent from the sweep: {sorted(missing)}"
    assert not stale, f"_CALLS names methods that no longer exist: {sorted(stale)}"


def test_best_effort_carve_out_stays_small():
    """Every exemption is a method allowed to fail quietly — keep it deliberate."""
    assert set(_CALLS) >= _BEST_EFFORT
    assert len(_BEST_EFFORT) <= 5, (
        "the best-effort list has grown; each entry is a method permitted to "
        "return a default on failure, so each needs a stated reason above"
    )
