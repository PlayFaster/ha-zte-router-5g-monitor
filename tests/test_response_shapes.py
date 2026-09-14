"""What each guard does with each shape this router actually produces.

Item 97. The shapes are not imagined: they are the ones enumerated on the
reference MC7010 on 2026-09-14 and recorded in `device_behaviour_reference.md`
section 3.1. That distinction is the point of the file. 1,671 tests at 100%
line and branch coverage did not catch a fault that blocked every write on the
reference device, because every one of them handed the classifier a payload
somebody had imagined.

One shape in that list turned out not to exist, and it is asserted here as
such: **a key absent from its own response does not occur.** This firmware
echoes every name it is asked and answers an unimplemented one as an empty
string, so "absent" and "unpopulated" cannot be told apart from a response
alone — which is why `keys_absent` is `None` rather than `[]` when nothing was
asked for explicitly.
"""

from unittest.mock import MagicMock

import pytest

from custom_components.zte_router_5g.api import (
    _UNAUTHENTICATED_KEYS,
    ZTEConnectionError,
    ZTERouterAPI,
    _classify_session,
)

# Each shape, as the router produces it, with the keys that were asked for.
# `network_type` and `signalbar` require a session; `wa_inner_version` does
# not, which is what makes a verdict possible at all.
_ASKED = ["network_type", "signalbar", "wa_inner_version"]

SHAPES: list[tuple[str, dict[str, str], str]] = [
    (
        "a live session answers its authenticated keys",
        {"network_type": "LTE", "signalbar": "4", "wa_inner_version": "MC7010"},
        "live",
    ),
    (
        "a dead session blanks the authenticated keys and keeps the rest",
        {"network_type": "", "signalbar": "", "wa_inner_version": "MC7010"},
        "expired",
    ),
    (
        "a wholly blank answer is a router with nothing to say, not an expiry",
        {"network_type": "", "signalbar": "", "wa_inner_version": ""},
        "not_ready",
    ),
    (
        "one populated authenticated key is enough to prove the session",
        {"network_type": "", "signalbar": "4", "wa_inner_version": "MC7010"},
        "live",
    ),
]


@pytest.mark.parametrize(("why", "payload", "verdict"), SHAPES)
def test_each_shape_is_classified_the_way_the_device_produces_it(
    why: str, payload: dict[str, str], verdict: str
) -> None:
    """Every shape the reference device answers with, and the verdict for it."""
    assert _classify_session(payload, _ASKED, _UNAUTHENTICATED_KEYS) == verdict, why


def test_an_answer_of_only_unauthenticated_keys_cannot_rule() -> None:
    """No authenticated key was asked, so nothing in the answer can witness.

    Ruling `live` here is how a dead session read as a clean success in
    `[3.3.2]`: the batch carried `imei`, `model_name` and `wa_inner_version`,
    which a dead session answers perfectly well.
    """
    payload = {"wa_inner_version": "MC7010", "imei": "0"}
    assert (
        _classify_session(payload, list(payload), _UNAUTHENTICATED_KEYS)
        == "undecidable"
    )


@pytest.mark.parametrize(
    ("result", "refused"),
    [
        ("success", False),
        ("0", False),
        ("ok", False),
        ("failure", True),
        ("fail", True),
        ("manual_fail", True),
        ("3", True),
        ("", True),
    ],
)
def test_the_write_vocabulary_is_fail_closed(result: str, refused: bool) -> None:
    """A `result` this integration does not recognise is a refusal.

    The literals here are the ones the reference device's own scripts compare
    against — including `fail` and `manual_fail`, which is why the vocabulary
    published in a download is evidence and not a licence to widen this set.
    A write reported as carried out when the router declined it is the fault
    the whole of issue #56 is about.
    """
    assert ZTERouterAPI._is_refusal({"result": result}) is refused


def test_a_response_with_no_result_at_all_is_not_a_refusal() -> None:
    """A response with no `result` key is not a refusal.

    Not every `goformId` answers one, and inventing the requirement would turn
    working commands into errors.
    """
    assert ZTERouterAPI._is_refusal({"messages": []}) is False
    assert ZTERouterAPI._is_refusal([]) is False


def test_an_empty_list_is_an_empty_inbox_and_not_a_missing_contract() -> None:
    """`{"messages": []}` is a real answer: the device holds no messages."""
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")

    # Returns None rather than raising. Asserted explicitly so the test states
    # its expectation instead of resting on the absence of an exception.
    assert api._require_contract({"messages": []}, "messages", "GET_SMS") is None


def test_a_contract_key_is_met_by_any_spelling_of_its_concept() -> None:
    """Any spelling of a concept satisfies the contract.

    The MC888 Pro reports under `ppp_status` what this device calls
    `wan_connect_status`, and a check keyed on one spelling calls that a
    connection error.
    """
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    api._require_contract({"ppp_status": "ppp_connected"}, "wan_connect_status", "POLL")

    with pytest.raises(ZTEConnectionError, match="missing"):
        api._require_contract({"something_else": "1"}, "wan_connect_status", "POLL")


def test_a_key_absent_from_its_own_response_does_not_occur() -> None:
    """Asserted because the plan listed it as a shape to handle.

    Measured on the reference MC7010: the router echoes every name it is asked,
    implemented or not, and answers an unimplemented one as an empty string. So
    a response never omits a key it was asked for, and an unpopulated witness
    cannot be told from an unsupported one.
    """
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    payload = {"network_type": "", "signalbar": "", "wa_inner_version": "MC7010"}

    api._record_verdict("expired", payload, list(payload))

    assert api.last_rejection["keys_absent"] == []


def test_keys_absent_is_unknown_rather_than_empty_when_nothing_was_asked() -> None:
    """The two look alike in a download and mean opposite things.

    `[]` says the router answered everything it was asked. `None` says nobody
    knows, because no list of what was asked reached this point. It used to
    report the first while meaning the second, on every device, because the set
    was computed against the payload's own keys.
    """
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")

    api._record_verdict("expired", {"network_type": ""}, None)

    assert api.last_rejection["keys_absent"] is None


def test_a_live_verdict_clears_the_live_field_and_not_the_history() -> None:
    """A stale rejection must not read as current, and must still be readable.

    Producing a diagnostics download reads the router, and those reads return
    live verdicts — which used to wipe the very record the file exists to
    carry.
    """
    api = ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")
    api._record_verdict("expired", {"network_type": ""}, ["network_type"])

    api._record_verdict("live", {"network_type": "LTE"}, ["network_type"])

    assert api.last_rejection is None
    assert api.last_rejection_seen["verdict"] == "expired"
