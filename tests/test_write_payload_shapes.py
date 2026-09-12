"""Lock the field set every write command sends.

This is a **change detector, not a correctness check**, and the distinction is
the whole point. It cannot tell you a payload is right — it locks in whatever is
there. What it does is make any change to a payload *visible and deliberate*,
which is precisely the gap left by the writes a script may not exercise.

Four of the eleven commands can never be automated against hardware: `reboot`
takes the device down, and `send_sms` / `delete_sms` / `delete_all` cost money,
reach third parties, or destroy data irreversibly (see
`scripts/write_classification.py`). Their correctness today rests on real-world
use. Nothing guards them against a future edit — and the failure mode is
established: `DATA_LIMIT_SETTING` and `APN_PROC_EX` each shipped for months
sending a partial form the router silently refused, and in both cases the unit
tests were green because they asserted one field rather than the set.

So the guarantee here is narrow and worth stating plainly: **if someone changes
what a command sends, a test fails and they must say so in the diff.** Whether
the new shape is correct is a question only hardware can answer — for the seven
commands that can be exercised, `scripts/hardware_check.py` answers it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from custom_components.zte_router_5g.api import ZTERouterAPI

from .conftest import MockResponse

# Fields present on every write, carried by the transport rather than chosen by
# the command. Excluded so the expectations below describe intent, not boilerplate.
_TRANSPORT = frozenset({"isTest", "goformId", "AD"})

_FULL_DATA_VOLUME = {
    "data_volume_limit_switch": "1",
    "data_volume_limit_unit": "data",
    "data_volume_limit_size": "2_1048576",
    "data_volume_alert_percent": "80",
    "wan_auto_clear_flow_data_switch": "on",
    "traffic_clear_date": "1",
}

_APN_STATE = {
    "apn_mode": "manual",
    "apn_index": "1",
    "wan_apn": "3broadband.ie",
    "APN_config1": "3broadband.ie($)3broadband.ie($)manual($)*99#($)none($)($)($)IP",
}

# The locked shapes. Each entry is (call, expected goformId, expected fields).
#
# Changing one of these is a deliberate act: update the expectation in the same
# commit as the payload, and say why. A shape that has been verified on hardware
# is marked; the rest are validated only by real-world use.
_WRITES: list[tuple[str, object, str, set[str]]] = [
    (
        "set_odu_led_switch",  # hardware-verified
        lambda api: api.set_odu_led_switch("1"),
        "ODU_LED_SWITCH_SET",
        {"ODU_led_switch"},
    ),
    (
        "set_bearer_preference",  # hardware-verified
        lambda api: api.set_bearer_preference("Only_LTE"),
        "SET_BEARER_PREFERENCE",
        {"BearerPreference"},
    ),
    (
        "set_data_volume_settings",  # hardware-verified; all six or refused
        lambda api: api.set_data_volume_settings(_FULL_DATA_VOLUME),
        "DATA_LIMIT_SETTING",
        set(_FULL_DATA_VOLUME),
    ),
    (
        "set_data_limit_switch",  # hardware-verified; delegates to the above
        lambda api: api.set_data_limit_switch("0", _FULL_DATA_VOLUME),
        "DATA_LIMIT_SETTING",
        set(_FULL_DATA_VOLUME),
    ),
    (
        "set_apn",  # hardware-verified; the reference for the APN form
        lambda api: api.set_apn(1, "IP"),
        "APN_PROC_EX",
        {"apn_mode", "apn_action", "set_default_flag", "pdp_type", "index"},
    ),
    (
        "set_apn_mode (manual)",  # hardware-verified; four fields are refused
        lambda api: api.set_apn_mode("manual", _APN_STATE),
        "APN_PROC_EX",
        {"apn_mode", "apn_action", "set_default_flag", "pdp_type", "index"},
    ),
    (
        "set_apn_mode (auto, no profile)",  # hardware-verified; bare form accepted
        lambda api: api.set_apn_mode("auto", {}),
        "APN_PROC_EX",
        {"apn_mode"},
    ),
    (
        "logout",  # hardware-verified; needs AD despite carrying no fields
        lambda api: api.logout(),
        "LOGOUT",
        set(),
    ),
    (
        "reboot",  # NOT hardware-verified by script — validated by use
        lambda api: api.reboot(),
        "REBOOT_DEVICE",
        set(),
    ),
    (
        "send_sms",  # NOT hardware-verified by script — costs money
        lambda api: api.send_sms("+353871234567", "hello"),
        "SEND_SMS",
        {"Number", "MessageBody", "ID", "encode_type", "sms_time", "notCallback"},
    ),
    (
        "delete_sms",  # NOT hardware-verified by script — destroys data
        lambda api: api.delete_sms("1"),
        "DELETE_SMS",
        {"msg_id", "notCallback"},
    ),
]


def _fields(payload: str) -> set[str]:
    """Return the field names in a pre-built form body."""
    return {pair.split("=", 1)[0] for pair in payload.split("&") if "=" in pair}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "call", "goform_id", "expected"),
    _WRITES,
    ids=[w[0] for w in _WRITES],
)
async def test_write_payload_shape_is_unchanged(
    mock_aiohttp_client, label, call, goform_id, expected
):
    """A command must send exactly the fields recorded for it.

    Asserting the *set* rather than a membership check is deliberate: every
    defect of this class so far has been a **missing** field, which `in` cannot
    see. An unexpected extra field is equally worth stopping on, since it means
    the payload changed without the expectation following.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "success"}
    )

    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
        patch.object(api, "_ensure_session"),
    ):
        await call(api)

    payload = mock_aiohttp_client.post.call_args[1]["data"]
    assert isinstance(payload, str), f"{label}: payload is no longer a form string"

    sent = _fields(payload)
    assert f"goformId={goform_id}" in payload, f"{label}: goformId changed"
    assert "AD=" in payload, f"{label}: the AD token is missing"

    assert sent - _TRANSPORT == expected, (
        f"{label}: payload shape changed.\n"
        f"  expected: {sorted(expected)}\n"
        f"  actual:   {sorted(sent - _TRANSPORT)}\n"
        "If this change is intended, update the expectation in _WRITES in the "
        "same commit and say why. A *missing* field is the failure mode that "
        "shipped twice already — the router answers 200 OK and does nothing."
    )


@pytest.mark.asyncio
async def test_delete_all_reuses_the_delete_payload(mock_aiohttp_client):
    """`delete_all` builds no payload of its own; it batches ids into `delete_sms`.

    Worth locking separately because the batching is the part that could drift:
    the router takes semicolon-separated ids, and a change to that separator
    would be invisible until someone tried to clear a full inbox.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.post.side_effect = [
        MockResponse(json_data={"messages": [{"id": "1"}, {"id": "2"}]}),
        MockResponse(json_data={"result": "success"}),
        # `delete_all` re-lists to verify, so the write is no longer the last
        # call — the assertions below name it explicitly.
        MockResponse(json_data={"messages": []}),
    ]

    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
        patch.object(api, "_ensure_session"),
    ):
        await api.delete_all()

    payload = mock_aiohttp_client.post.call_args_list[1][1]["data"]
    assert "goformId=DELETE_SMS" in payload
    assert re.search(r"msg_id=1;2;(&|$)", payload), (
        f"ids are no longer semicolon-terminated: {payload}"
    )


def test_every_write_command_has_a_locked_shape():
    """Guard the guard: a new command must be added here, not just classified.

    `test_write_classification.py` forces a *decision* about every write;
    this forces a *recorded payload* for it. Without this check the lock would
    quietly cover ten of eleven commands and look complete.
    """
    from scripts.write_classification import ATTENDED, NEVER_AUTOMATED, SAFE

    covered = {label.split(" ")[0] for label, _, _, _ in _WRITES}
    covered.add("delete_all")  # locked by its own test above
    classified = set(SAFE) | set(ATTENDED) | set(NEVER_AUTOMATED)

    missing = sorted(classified - covered)
    assert not missing, (
        f"classified writes with no locked payload shape: {missing}. "
        "Add an entry to _WRITES so a future change to what it sends cannot "
        "pass unnoticed."
    )


@pytest.mark.asyncio
async def test_delete_payload_matches_the_captured_browser_request(
    mock_aiohttp_client,
):
    """The delete form, field for field, as the router's own page sends it.

    Captured from the MC888 Pro of issue #56 on 2026-09-11, deleting message
    16 successfully: `isTest=false&goformId=DELETE_SMS&msg_id=16%3B` —
    a semicolon-*terminated* id — `&notCallback=true&AD=...`. Both of those
    were missing here, and that device refuses every write it is sent.

    Locked as an ordered comparison rather than a field set, because the set
    check above cannot see a `16` that should be `16;`.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "success"}
    )

    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
        patch.object(api, "_ensure_session"),
    ):
        await api.delete_sms("16")

    payload = mock_aiohttp_client.post.call_args[1]["data"]
    assert payload == (
        "isTest=false&goformId=DELETE_SMS&msg_id=16;&notCallback=true&AD=test_ad"
    )


@pytest.mark.asyncio
async def test_delete_does_not_double_the_terminator(mock_aiohttp_client):
    """A caller that already terminated its ids gets them back unchanged.

    `delete_all` joins ids here, and a service call may pass either form.
    `16;;` is not what the device was captured accepting.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "success"}
    )

    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
        patch.object(api, "_ensure_session"),
    ):
        await api.delete_sms("1;2;")

    payload = mock_aiohttp_client.post.call_args[1]["data"]
    assert "msg_id=1;2;&" in payload
    assert ";;" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "call", "goform_id", "expected"),
    _WRITES,
    ids=[w[0] for w in _WRITES],
)
async def test_every_write_sends_the_headers_the_router_expects(
    mock_aiohttp_client, label, call, goform_id, expected
):
    """Nine write sites, one header set.

    The router's own page sends a charset on the content type, an `Accept`,
    an `X-Requested-With` and an `Origin`. Every site here sent `Content-Type`
    alone. Parametrized over the same table as the payload shapes so a new
    command cannot be added with a header dict of its own.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "test"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "success"}
    )

    with (
        patch.object(api, "get_ad", return_value="test_ad"),
        patch.object(api, "login"),
        patch.object(api, "_ensure_session"),
    ):
        await call(api)

    sent = mock_aiohttp_client.post.call_args[1]["headers"]
    assert sent["Content-Type"] == (
        "application/x-www-form-urlencoded; charset=UTF-8"
    ), f"{label}: the charset is missing from the content type"
    assert sent["X-Requested-With"] == "XMLHttpRequest", f"{label}"
    assert sent["Accept"].startswith("application/json"), f"{label}"
    assert sent["Origin"] == "http://192.168.0.1", f"{label}: origin is wrong"
    assert sent["Referer"] == "http://192.168.0.1/index.html", f"{label}"


def test_origin_follows_the_discovered_protocol():
    """`Origin` is derived, not stored — the referer is rewritten on discovery."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    api.referer = "https://192.168.0.1/"
    assert api.write_headers()["Origin"] == "https://192.168.0.1"
