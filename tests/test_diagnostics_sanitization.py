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
    coordinator._endpoint_failures = {}
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
    coordinator._endpoint_failures = {}
    mock_config_entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(None, mock_config_entry)

    assert result["data"] == {}
    assert result["coordinator"]["health"]["problem"] is True
