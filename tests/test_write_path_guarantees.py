"""Four properties of the write path that were true without being asserted.

Items 42, 43 and 46. Each of these held when it was checked in v3.3.25-dev9 and
none of them was pinned by a test, so each was one edit away from being lost
silently — which is the shape of every fault this project has shipped and later
found by hand.

They are gathered in one file because they are the same kind of claim: what a
write sends, and what a failed write may not do.
"""

import asyncio
import urllib.parse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.zte_router_5g.api import (
    _CONTRACT_CONCEPTS,
    _TOKEN_READS,
    ZTERouterAPI,
    _first_spelling,
)

# ---------------------------------------------------------------------------
# Item 42 — every alias map writes the spelling the device answered
# ---------------------------------------------------------------------------


def _api() -> ZTERouterAPI:
    return ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "aliases"),
    sorted(ZTERouterAPI.DATA_VOLUME_FIELDS.items()),
)
async def test_the_spelling_a_device_answers_is_the_spelling_written(
    field: str, aliases: tuple[str, ...]
) -> None:
    """Parametrised over the map, so a new entry is covered without being remembered.

    `DATA_LIMIT_SETTING` replaces the whole form and the router refuses a
    payload whose field names it does not recognise. The MC888 Pro of issue #56
    answers the `flux_` spellings and leaves the unprefixed names empty, so a
    device on those spellings was being sent a form it could never accept,
    however correct the token.
    """
    api = _api()
    # A device that answers only the last alias, whatever that is.
    answered = aliases[-1]
    current = dict.fromkeys(aliases, "")
    current[answered] = "1"
    for other, spellings in ZTERouterAPI.DATA_VOLUME_FIELDS.items():
        if other != field:
            current[spellings[0]] = "1"

    sent: list[str] = []

    async def capture(_method, _path, **kwargs):
        sent.append(str(kwargs.get("data")))
        return {"result": "success"}

    with (
        patch.object(api, "get_ad", new=AsyncMock(return_value="token")),
        patch.object(api, "_request", side_effect=capture),
    ):
        await api.set_data_volume_settings(current)

    assert f"{answered}=" in sent[0], "the canonical name was written instead"
    if answered != field:
        assert f"&{field}=" not in sent[0], "both spellings were sent"


def test_a_read_resolves_to_the_first_spelling_the_device_populates() -> None:
    """The other alias map: the two names a write's token is derived from.

    The alias resolves the read and never the operand — the token hashes the
    *value*, and a spelling that silently became the operand would produce a
    well-formed wrong token, which is a write refused with nothing to say why.
    """
    for spellings in _TOKEN_READS.values():
        first, second = spellings[0], spellings[1]
        assert _first_spelling({second: "value"}, spellings) == "value"
        assert _first_spelling({first: "wins", second: "loses"}, spellings) == "wins"
        assert _first_spelling({first: ""}, spellings) == ""


def test_a_contract_concept_is_met_by_any_of_its_spellings() -> None:
    """Any spelling of a known concept satisfies the contract check.

    A device reporting `ppp_status` where this one reports `wan_connect_status`
    is not a connection error.
    """
    api = _api()
    for concept, spellings in _CONTRACT_CONCEPTS.items():
        for spelling in spellings:
            assert (
                api._require_contract({spelling: "x"}, spellings[0], concept) is None
            ), f"{spelling} was not accepted for {concept}"


# ---------------------------------------------------------------------------
# Item 46 — a payload value is encoded exactly once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_id_list_carrying_a_separator_is_encoded_once() -> None:
    """`;` terminates the id list and must survive one pass, not two.

    Encoded twice, `%3B` becomes `%253B`, the router reads a literal `%3B`, and
    the delete targets nothing. The body is built here and sent as a string, so
    nothing downstream re-encodes it — this asserts that nobody adds a second
    pass later.
    """
    api = _api()
    sent: list[str] = []

    async def capture(_method, _path, **kwargs):
        sent.append(str(kwargs.get("data")))
        return {"result": "success"}

    with (
        patch.object(api, "get_ad", new=AsyncMock(return_value="token")),
        patch.object(api, "_request", side_effect=capture),
        patch.object(api, "get_sms_messages", new=AsyncMock(return_value=[])),
    ):
        await api.delete_sms("11;12")

    body = sent[0]
    assert "msg_id=" + urllib.parse.quote("11;12;", safe="") in body
    assert "%253B" not in body, "the separator was encoded twice"


@pytest.mark.asyncio
async def test_a_number_carrying_a_plus_is_encoded_once() -> None:
    """An international number is the everyday case for this.

    `+` is a space in a form body, so an unencoded `+353…` reaches the router as
    ` 353…`; encoded twice it reaches it as a literal `%2B`. Both send the
    message to the wrong place, and the API answers `success` either way.
    """
    api = _api()
    sent: list[str] = []

    async def capture(_method, _path, **kwargs):
        sent.append(str(kwargs.get("data")))
        return {"result": "success"}

    with (
        patch.object(api, "get_ad", new=AsyncMock(return_value="token")),
        patch.object(api, "_request", side_effect=capture),
        patch.object(api, "_send_counters", new=AsyncMock(return_value={})),
        patch.object(api, "_classify_send", new=AsyncMock(return_value=None)),
    ):
        await api.send_sms("+353871234567", "hello")

    body = sent[0]
    assert "Number=%2B353871234567" in body
    assert "%252B" not in body, "the plus was encoded twice"


# ---------------------------------------------------------------------------
# Item 43 — the implemented fallbacks, on their failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_recovery_path_ever_re_sends_a_write() -> None:
    """Item 75's rule, asserted rather than inferred from where the code sits.

    A resent `SEND_SMS` delivers the message twice and the response cannot say
    whether it did. `_request` recovers a read by logging in and putting it
    again; a write that looks like an expiry must raise instead.
    """
    api = _api()
    api.session_active = True
    api.cookies = {"stok": "s"}
    posts: list[str] = []

    async def transport(call):
        if call.method == "POST":
            posts.append(str(call.data))
        # The shape of a dead session on this API: 200 OK, and the values the
        # caller asked for echoed back empty.
        return {"result": ""}

    with (
        patch.object(api, "login", new=AsyncMock()),
        patch.object(api, "_perform", side_effect=transport),
    ):
        await api._request("POST", "goform/goform_set_cmd_process", data="x=1")

    assert len(posts) == 1, "a write was put a second time"


@pytest.mark.asyncio
async def test_a_write_is_not_replayed_even_when_retry_is_asked_for() -> None:
    """The exclusion is on the method and path, not on the caller's intent."""
    api = _api()

    assert api._is_write_request("POST", "goform/goform_set_cmd_process") is True
    assert api._is_write_request("GET", "goform/goform_set_cmd_process") is False
    assert api._is_write_request("POST", "goform/goform_get_cmd_process") is False


# ---------------------------------------------------------------------------
# Item 71 — a write and a poll take turns, and a write never waits for long
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_write_waits_for_a_poll_that_is_in_flight() -> None:
    """The one session this router grants is used by one of them at a time.

    A poll that judges the session expired re-logs in, and the new login
    invalidates the cookie a write in flight is carrying.
    """
    api = _api()
    # A live session, so `_perform` goes straight to the lock rather than
    # logging in first — the login is not what this asserts.
    api.session_active = True
    api.cookies = {"stok": "s"}
    order: list[str] = []
    poll_started = asyncio.Event()
    release = asyncio.Event()

    async def slow_poll(*_args, **_kwargs):
        order.append("poll started")
        poll_started.set()
        await release.wait()
        order.append("poll finished")
        return {}

    async def write(_call, _answer, **_kwargs):
        order.append("write ran")
        return {"result": "success"}

    with (
        patch.object(api, "_batch_get", side_effect=slow_poll),
        patch.object(api, "login", new=AsyncMock()),
        patch.object(api, "_send", new=AsyncMock()),
        patch.object(api, "_dispose", side_effect=write),
    ):
        poll_task = asyncio.create_task(api.get_all_data())
        await poll_started.wait()
        write_task = asyncio.create_task(
            api._request("POST", "goform/goform_set_cmd_process", data="x=1")
        )
        for _ in range(10):
            await asyncio.sleep(0)

        assert "write ran" not in order, "the write did not wait for the poll"
        release.set()
        await asyncio.gather(poll_task, write_task)

    assert order == ["poll started", "poll finished", "write ran"]


@pytest.mark.asyncio
async def test_a_write_proceeds_when_the_wait_runs_out() -> None:
    """Failing to acquire is not an error.

    The worst case is an unserialised write, which is what every release before
    this one did. A lock that could refuse would be another way to block writes
    on routers nobody can test.
    """
    api = _api()
    api.session_active = True
    api.cookies = {"stok": "s"}
    await api._write_lock.acquire()

    with (
        patch("custom_components.zte_router_5g.api.WRITE_LOCK_WAIT_SECONDS", 0.01),
        patch.object(api, "login", new=AsyncMock()),
        patch.object(api, "_send", new=AsyncMock()),
        patch.object(
            api, "_dispose", new=AsyncMock(return_value={"result": "success"})
        ),
    ):
        result = await api._request("POST", "goform/goform_set_cmd_process", data="x=1")

    assert result == {"result": "success"}
    assert api.write_lock_timeouts == 1, "the give-up was not counted"
    api._write_lock.release()


@pytest.mark.asyncio
async def test_a_read_back_after_a_write_does_not_deadlock() -> None:
    """The nesting that would hang if the lock sat on every request.

    A switch reads its value straight back after writing it, through
    `get_params`. If that took the same lock the write still held, the write
    would wait on itself for ever. `get_params` deliberately does not take it —
    only the two poll entry points do.
    """
    api = _api()

    async def transport(call):
        if call.method == "POST":
            # Read back from inside the write, which is what a switch does
            # immediately afterwards and what a re-entrant lock would hang on.
            await api.get_params(["ODU_led_switch"])
        return {"result": "success", "ODU_led_switch": "1"}

    with patch.object(api, "_perform", side_effect=transport):
        result = await asyncio.wait_for(
            api._request("POST", "goform/goform_set_cmd_process", data="x=1"),
            timeout=5,
        )

    assert result["result"] == "success"


# ---------------------------------------------------------------------------
# Item 35 — every write asks one place whether it carries a token
# ---------------------------------------------------------------------------


def test_every_write_payload_takes_its_token_from_ad_suffix() -> None:
    """Asserted over the source, because the fault is a method that opts out.

    `ad_suffix` is the single place that reads the firmware's gate flag and
    its exempt list. A writer that calls `get_ad` directly bypasses both and
    sends a token to a device that wants none, or sends one on a command its
    own client exempts — and it does so silently, because a router that
    ignores an unwanted `AD` accepts the write anyway.

    Enumerating the methods here would only pin the ones that exist today.
    Finding them by the payload they build is what covers the ninth write
    command somebody adds later.
    """
    import ast
    import pathlib

    source = pathlib.Path("custom_components/zte_router_5g/api.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    offenders: list[str] = []
    writers: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        body = ast.get_source_segment(source, node) or ""
        if "goformId=" not in body:
            continue
        writers.append(node.name)
        if "self.ad_suffix(" not in body:
            offenders.append(f"{node.name}: builds a payload without ad_suffix")
        if "self.get_ad(" in body:
            offenders.append(f"{node.name}: calls get_ad directly")

    assert not offenders, "\n".join(offenders)
    # A guard against the sweep silently finding nothing — a rename of
    # `goformId` in the payload builders would make this test vacuous.
    assert len(writers) >= 8, f"only {len(writers)} write payloads found: {writers}"
