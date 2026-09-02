"""Diagnostics sanitization, asserted as properties over the rendered output.

dev_standards Section 20 asks for properties over `json.dumps(result)` rather
than per-key assertions, because a leak is by definition something the key list
did not reach. Every fixture value here is synthetic — a sanitizer seeded with
real identifiers is broken by construction, since it could not work for anyone
else's router and would put PII in the source tree.
"""

import json
from unittest.mock import MagicMock

import pytest

from custom_components.zte_router_5g.diagnostics import (
    async_get_config_entry_diagnostics,
)

# Wholly invented values, chosen to be unmistakable if any of them survives.
FAKE_WAN_IP = "203.0.113.47"
FAKE_LAN_IP = "192.0.2.11"
FAKE_IMEI = "111222333444555"
FAKE_IMSI = "999888777666555"
FAKE_ICCID = "8935411234567890123"
FAKE_MSISDN = "+15550001111"
FAKE_SENDER = "+15550002222"
FAKE_SMS_BODY = "Your verification code is 447711 - do not share it"
# Chosen so no fixture identifier is a substring of any legitimate value below.
# The property test scans the whole serialized document, so a cell id that
# happened to occur inside a byte counter would fail for the wrong reason —
# and "fixing" that by tokenizing the counter would be exactly the
# over-redaction Section 20 calls a defect.
FAKE_CELL_ID = "441207"
FAKE_ENODEB = "44120"
FAKE_APN = "internet.example-carrier.test"
FAKE_PROVIDER = "ExampleCarrier"
FAKE_MAC = "AA:BB:CC:DD:EE:FF"

ROUTER_PAYLOAD = {
    # --- must not survive ---
    "wan_ipaddr": FAKE_WAN_IP,
    "lan_ipaddr": FAKE_LAN_IP,
    "imei": FAKE_IMEI,
    "sim_imsi": FAKE_IMSI,
    "sim_iccid": FAKE_ICCID,
    "msisdn": FAKE_MSISDN,
    "cell_id": FAKE_CELL_ID,
    "enodeb_id": FAKE_ENODEB,
    "lte_pci": "160",
    "wan_apn": FAKE_APN,
    "network_provider": FAKE_PROVIDER,
    "mdm_mcc": "272",
    "mdm_mnc": "02",
    "rmcc": "272",
    "rmnc": "02",
    "APN_config0": (
        "MyProfile($)($)manual($)*99#($)PAP($)apnuser($)apnsecret($)IPv4v6($)auto"
    ),
    "some_unknown_future_key": f"host {FAKE_MAC} at {FAKE_WAN_IP}",
    "last_sms": {
        "id": "7",
        "content": "00590065",
        "content_decoded": FAKE_SMS_BODY,
        "number": "002B0031",
        "number_decoded": FAKE_SENDER,
        "date": "26,07,27,10,15,00",
        "date_decoded": "2026-07-27T10:15:00+00:00",
        "tag": "1",
    },
    # --- must survive: this is the diagnostic substance ---
    "model_name": "MC7010",
    "wa_inner_version": "IRL_H3G_MC7010DV1.0.0B01",
    "hardware_version": "WR_A1",
    "network_type": "ENDC",
    "signalbar": "4",
    "lte_rsrp": "-95.5",
    "Z5g_SINR": "12.3",
    "wan_active_band": "n28",
    "wan_active_channel": "9410",
    "realtime_time": "360512",
    "monthly_rx_bytes": "98765432109",
    "monthly_tx_bytes": "12345678901",
    "sms_unread_num": "3",
}

SECRETS = (
    FAKE_WAN_IP,
    FAKE_LAN_IP,
    FAKE_IMEI,
    FAKE_IMSI,
    FAKE_ICCID,
    FAKE_MSISDN,
    FAKE_SENDER,
    FAKE_SMS_BODY,
    FAKE_CELL_ID,
    FAKE_APN,
    FAKE_PROVIDER,
    FAKE_MAC,
    "apnuser",
    "apnsecret",
    "MyProfile",
    "hunter2",
)

SUBSTANCE = (
    "MC7010",
    "IRL_H3G_MC7010DV1.0.0B01",
    "WR_A1",
    "ENDC",
    "-95.5",
    "12.3",
    "n28",
    "9410",
    "360512",
    "98765432109",
    "12345678901",
)


@pytest.fixture
def diagnostics_entry(mock_config_entry):
    """Return a config entry whose coordinator serves the synthetic payload."""
    coordinator = MagicMock()
    coordinator.data = dict(ROUTER_PAYLOAD)
    coordinator.consecutive_failures = 0
    coordinator.last_update_success = True
    coordinator.last_update_success_time = None
    coordinator.update_interval = None
    coordinator.health_snapshot = {"problem": False, "issues": [], "severity": "ok"}
    # The boot-time latch's own state, published in the download since
    # `[3.3.10-dev1]`. A mock without it serializes a MagicMock.
    coordinator.uptime_state = {"drift_rate_pct": None, "boot_time": None}
    coordinator.uptime_diagnostics = {"drift_rate_pct": None}
    coordinator.endpoint_failures = {}
    mock_config_entry.runtime_data = coordinator

    object.__setattr__(
        mock_config_entry,
        "data",
        {"model": "MC7010", "sw_version": "V1.0.0", "imei": FAKE_IMEI},
    )
    object.__setattr__(
        mock_config_entry,
        "options",
        {"host": FAKE_LAN_IP, "username": "admin", "password": "hunter2"},
    )
    return mock_config_entry


async def _render(entry) -> str:
    result = await async_get_config_entry_diagnostics(None, entry)
    return json.dumps(result, default=str)


# --------------------------------------------------------------------------
# The properties
# --------------------------------------------------------------------------


@pytest.mark.parametrize("secret", SECRETS)
async def test_no_identifier_survives_anywhere_in_the_output(
    diagnostics_entry, secret
) -> None:
    """No sensitive literal may appear anywhere in the rendered file.

    Asserted over the whole serialized document rather than per key, because a
    leak is by definition somewhere the key list did not reach.
    """
    assert secret not in await _render(diagnostics_entry)


@pytest.mark.parametrize("value", SUBSTANCE)
async def test_diagnostic_substance_is_preserved(diagnostics_entry, value) -> None:
    """A sanitizer that guts the file has failed as surely as one that leaks."""
    assert value in await _render(diagnostics_entry)


async def test_byte_counters_are_not_mistaken_for_identifiers(
    diagnostics_entry,
) -> None:
    """Over-redaction is a defect, not caution.

    Byte totals are long digit runs, so a blind digit-shaped rule would tokenize
    them and destroy the usage data the file exists to show.
    """
    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)
    assert result["data"]["monthly_rx_bytes"] == "98765432109"
    assert result["data"]["monthly_tx_bytes"] == "12345678901"


async def test_tokens_are_stable_across_sections(diagnostics_entry) -> None:
    """The same value must carry the same token everywhere it appears.

    The LAN address appears both in the router payload and in the entry
    options; if those tokens differ, the file has lost the fact that they are
    the same host.
    """
    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)
    assert result["data"]["lan_ipaddr"] == result["entry"]["options"]["host"]


async def test_repeated_identifiers_are_not_all_blanked(diagnostics_entry) -> None:
    """Distinct values must get distinct tokens, not one flat REDACTED."""
    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)
    assert result["data"]["wan_ipaddr"] != result["data"]["lan_ipaddr"]
    assert result["data"]["wan_ipaddr"].startswith("ip-")


async def test_unknown_keys_are_swept_structurally(diagnostics_entry) -> None:
    """A key this module never heard of still gets IP/MAC-shaped values pulled.

    Firmware can return anything; matching on shape is what covers the fields
    nobody enumerated.
    """
    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)
    swept = result["data"]["some_unknown_future_key"]
    assert FAKE_MAC not in swept
    assert FAKE_WAN_IP not in swept
    assert "mac-1" in swept


async def test_sms_shape_survives_without_its_content(diagnostics_entry) -> None:
    """Whether decoding worked is diagnostic; what the message said is not."""
    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)
    sms = result["data"]["last_sms"]

    assert str(len(FAKE_SMS_BODY)) in sms["content_decoded"]
    assert sms["number_decoded"].startswith("phone-")
    # The encoded and decoded forms are one sender, so they must share a token.
    # Two tokens would read as two different people — found by inspecting a
    # regenerated download, not by reading the code.
    assert sms["number"] == sms["number_decoded"]
    # Non-identifying metadata is untouched.
    assert sms["id"] == "7"
    assert sms["tag"] == "1"
    assert sms["date_decoded"] == "2026-07-27T10:15:00+00:00"


async def test_non_string_sms_fields_pass_through(diagnostics_entry) -> None:
    """Firmware sometimes returns numbers rather than strings.

    A non-string field must survive untouched rather than being coerced or
    dropped — the sweep only applies to text.
    """
    payload = dict(ROUTER_PAYLOAD)
    payload["last_sms"] = {**payload["last_sms"], "sms_class": 4, "concat_total": None}
    diagnostics_entry.runtime_data.data = payload

    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)
    sms = result["data"]["last_sms"]

    assert sms["sms_class"] == 4
    assert sms["concat_total"] is None


async def test_apn_profile_is_reduced_to_its_shape(diagnostics_entry) -> None:
    """APN profiles can carry credentials; keep only the shape."""
    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)
    summary = result["data"]["APN_config0"]

    assert "pdp=IPv4v6" in summary
    assert "fields" in summary


async def test_live_coordinator_data_is_never_mutated(diagnostics_entry) -> None:
    """Diagnostics is a read path; entities keep serving from this dict."""
    before = json.dumps(
        diagnostics_entry.runtime_data.data, default=str, sort_keys=True
    )

    await async_get_config_entry_diagnostics(None, diagnostics_entry)

    after = json.dumps(diagnostics_entry.runtime_data.data, default=str, sort_keys=True)
    assert before == after


async def test_handles_an_empty_payload(mock_config_entry) -> None:
    """A download taken before the first poll must still render."""
    coordinator = MagicMock()
    coordinator.data = None
    coordinator.consecutive_failures = 4
    coordinator.last_update_success = False
    coordinator.last_update_success_time = None
    coordinator.update_interval = None
    coordinator.health_snapshot = {"problem": True, "issues": ["no data"]}
    # The boot-time latch's own state, published in the download since
    # `[3.3.10-dev1]`. A mock without it serializes a MagicMock.
    coordinator.uptime_state = {"drift_rate_pct": None, "boot_time": None}
    coordinator.uptime_diagnostics = {"drift_rate_pct": None}
    coordinator.endpoint_failures = {}
    mock_config_entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(None, mock_config_entry)

    assert result["data"] == {}
    assert result["coordinator"]["health"]["problem"] is True


async def test_an_sms_with_no_sender_is_not_given_a_phone_token(
    diagnostics_entry,
) -> None:
    """A message carrying no number must not mint a pseudonym for one.

    The distinction is between "sender withheld" and "sender redacted". A
    network-originated message (a carrier notice, a cell broadcast) has no
    number at all, and emitting `phone-1` there invents a correspondent the
    payload never contained — the over-redaction §20 names as a defect in its
    own right, and misleading in the one direction a maintainer cannot check.
    """
    payload = dict(ROUTER_PAYLOAD)
    stripped = {
        key: value
        for key, value in payload["last_sms"].items()
        if key not in ("number", "number_decoded")
    }
    payload["last_sms"] = stripped
    diagnostics_entry.runtime_data.data = payload

    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)
    sms = result["data"]["last_sms"]

    assert "number" not in sms
    assert "number_decoded" not in sms
    assert "phone-" not in json.dumps(result)
    # The rest of the block still sanitizes, so the absent token above is the
    # missing sender rather than the whole path having been skipped.
    assert str(len(FAKE_SMS_BODY)) in sms["content_decoded"]


async def test_two_different_identifiers_get_two_different_tokens(
    diagnostics_entry,
) -> None:
    """A pseudonym identifies an entity; collapsing two into one destroys that.

    §20 asks for **stable** tokens precisely so a reader can follow one entity
    through the file. A tokenizer fed a constant instead of the value
    satisfies every "no raw identifier survives" property while merging every
    distinct entity into `cell-1` — the file looks correctly sanitized and
    reads as though the router only ever saw one cell.

    Asserted on the cell identifiers because they are the pair that genuinely
    co-occurs in one payload. The sender is a single value per SMS block, so
    two phone tokens cannot arise from any response this router produces.
    """
    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)
    rendered = json.dumps(result)
    data = result["data"]

    assert FAKE_CELL_ID not in rendered
    assert FAKE_ENODEB not in rendered
    assert data["cell_id"].startswith("cell-")
    assert data["enodeb_id"].startswith("cell-")
    assert data["cell_id"] != data["enodeb_id"], (
        "two distinct identifiers collapsed into one pseudonym"
    )


async def test_a_sender_known_only_by_its_decoded_form_still_gets_a_token(
    diagnostics_entry,
) -> None:
    """`number_decoded or number` — either alone is enough to mint a token.

    Separates `or` from `and`. With `and`, a block carrying only the decoded
    form yields no token at all and the sender is blanked instead of
    pseudonymized: safe, but the cross-reference §20 exists to preserve is
    gone, and the loss is invisible against a "nothing leaked" assertion.
    """
    payload = dict(ROUTER_PAYLOAD)
    payload["last_sms"] = {
        k: v for k, v in payload["last_sms"].items() if k != "number"
    }
    payload["last_sms"]["number_decoded"] = FAKE_SENDER
    diagnostics_entry.runtime_data.data = payload

    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)

    assert FAKE_SENDER not in json.dumps(result)
    assert result["data"]["last_sms"]["number_decoded"].startswith("phone-")


async def test_only_the_sms_block_is_sanitized_as_an_sms(diagnostics_entry) -> None:
    """`key == "last_sms" and isinstance(value, dict)` — both halves required.

    With `or`, every dict-valued key in the payload is run through the SMS
    sanitizer, which replaces text fields with `<key: N chars>` summaries. The
    diagnostic substance §20 requires to survive would be destroyed wholesale,
    and no "nothing leaked" property can see it — over-redaction passes every
    leak test by construction.
    """
    payload = dict(ROUTER_PAYLOAD)
    payload["some_nested_block"] = {"content": "a plain diagnostic value", "n": 4}
    diagnostics_entry.runtime_data.data = payload

    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)
    nested = result["data"]["some_nested_block"]

    assert nested["content"] == "a plain diagnostic value"
    assert nested["n"] == 4


async def test_two_macs_in_one_value_get_two_tokens(diagnostics_entry) -> None:
    """The structural sweep pseudonymizes each MAC, not "a MAC".

    Same failure as the cell-token case, one layer down: `_MAC_RE.sub` fed a
    constant instead of the matched text rewrites every address to `mac-1`.
    Nothing leaks, so the existing single-MAC assertion still passes — but a
    maintainer reading the file sees one device where the router reported two,
    which is the cross-reference §20 keeps tokens for in the first place.
    """
    payload = dict(ROUTER_PAYLOAD)
    payload["some_unknown_future_key"] = (
        f"peer {FAKE_MAC} talking to aa:bb:cc:dd:ee:ff on {FAKE_WAN_IP}"
    )
    diagnostics_entry.runtime_data.data = payload

    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)
    swept = result["data"]["some_unknown_future_key"]

    assert FAKE_MAC not in swept
    assert "aa:bb:cc:dd:ee:ff" not in swept
    assert "mac-1" in swept and "mac-2" in swept
