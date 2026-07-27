"""Diagnostics support for ZTE Router 5G Monitor.

A diagnostics download must be safe to attach to a public issue **without the
user hand-editing it** (dev_standards Section 20). Key-name redaction alone is
not enough here: `coordinator.data` is the router's `goform` payload stored
verbatim, so it carries whatever the firmware chose to return — including the
subscriber's cell tower, their carrier, and the body and sender of the most
recent SMS.

The approach is therefore layered:

* **Blank** values with no referential role — credentials, subscriber
  identifiers, carrier identity.
* **Pseudonymize** values that are worth cross-referencing across the file —
  IP addresses and cell identifiers become stable tokens (`ip-1`, `cell-1`), so
  a maintainer can still see "these two fields refer to the same thing".
* **Summarize** structured vendor blobs — an APN profile is reduced to its
  shape, which is the part that helps diagnose.
* **Sweep** what remains for anything IP- or MAC-shaped, in case the firmware
  returns one under a key this module does not know about.

Everything diagnostically useful is deliberately preserved: model, firmware,
hardware version, every signal metric, band and channel, byte counters, uptime,
health state and failure counts.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import ZTERouterDataUpdateCoordinator

# Values with no cross-reference worth preserving — blanked outright.
TO_REDACT = {
    "password",
    "username",
    "imei",
    "sim_imsi",
    "sim_iccid",
    "msisdn",
}

# Carrier and network-operator identity. MCC+MNC name the operator and country,
# and together with a cell id they place the subscriber geographically. None of
# it helps diagnose an integration fault.
CARRIER_KEYS = {
    "mdm_mcc",
    "mdm_mnc",
    "rmcc",
    "rmnc",
    "network_provider",
    "wan_apn",
}

# Identifiers that DO carry cross-reference value, so they are tokenized rather
# than blanked: seeing that two fields hold the same cell is diagnostic.
IP_KEYS = {"wan_ipaddr", "lan_ipaddr", "ipv6_wan_ipaddr"}
CELL_KEYS = {"cell_id", "enodeb_id", "lte_pci", "nr5g_pci"}

# The SMS block is the highest-sensitivity content in the payload: it is data
# about a *third party* who never consented to appear in a bug report.
SMS_TEXT_KEYS = {"content", "content_decoded"}
SMS_NUMBER_KEYS = {"number", "number_decoded"}

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
_PDP_RE = re.compile(r"\b(IPv4v6|IPv6|IPv4|PPP|IP)\b")

REDACTED = "**REDACTED**"


class _Tokenizer:
    """Assigns stable pseudonyms to identifier values.

    Section 20: twenty identical `**REDACTED**` strings destroy the file's
    usefulness, twenty stable tokens preserve it. The same input always yields
    the same token *within one download*, and tokens are allocated in first-seen
    order, so nothing about the real value survives.
    """

    def __init__(self) -> None:
        """Initialize an empty token map."""
        self._tokens: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}

    def token(self, prefix: str, value: str) -> str:
        """Return a stable token for this value under this prefix."""
        key = (prefix, value)
        if key not in self._tokens:
            self._counts[prefix] = self._counts.get(prefix, 0) + 1
            self._tokens[key] = f"{prefix}-{self._counts[prefix]}"
        return self._tokens[key]


def _summarize_apn(value: str, tokenizer: _Tokenizer) -> str:
    """Reduce a `($)`-delimited APN profile to its shape.

    The raw string can carry the profile name and, on some firmware, the APN
    username and password. What actually helps diagnose is that a profile
    exists, how many fields it has, and its PDP type — so keep exactly that.
    """
    fields = value.split("($)")
    populated = sum(1 for f in fields if f.strip())
    pdp = _PDP_RE.search(value)
    pdp_type = pdp.group(1) if pdp else "unknown"
    return f"<apn profile: {len(fields)} fields, {populated} set, pdp={pdp_type}>"


def _sweep(value: str, tokenizer: _Tokenizer) -> str:
    """Replace anything IP- or MAC-shaped anywhere in a string.

    A structural backstop for keys this module does not enumerate. Matched on
    shape only — never against a list of real values, which would put PII in
    the source tree and would not work for anybody else's router.
    """
    value = _IP_RE.sub(lambda m: tokenizer.token("ip", m.group(0)), value)
    return _MAC_RE.sub(lambda m: tokenizer.token("mac", m.group(0)), value)


def _sanitize_sms(block: dict[str, Any], tokenizer: _Tokenizer) -> dict[str, Any]:
    """Strip an SMS down to its diagnostic shape.

    The message body and the sender's number are removed entirely. What is kept
    is whether decoding worked and how much text there was — which is what an
    SMS-handling bug actually turns on — plus the non-identifying metadata.
    """
    # `number` and `number_decoded` are the hex-encoded and human-readable
    # forms of the *same* sender, so both must resolve to one token. Tokenizing
    # each literal separately yields `phone-1` and `phone-2`, which reads as two
    # different people — the opposite of what a stable pseudonym is for.
    sender_token = ""
    decoded = block.get("number_decoded") or block.get("number")
    if decoded:
        sender_token = tokenizer.token("phone", str(decoded))

    clean: dict[str, Any] = {}
    for key, value in block.items():
        if key in SMS_TEXT_KEYS:
            length = len(value) if isinstance(value, str) else 0
            clean[key] = f"<{key}: {length} chars>"
        elif key in SMS_NUMBER_KEYS:
            clean[key] = sender_token if value else ""
        elif isinstance(value, str):
            clean[key] = _sweep(value, tokenizer)
        else:
            clean[key] = value
    return clean


def _sanitize_payload(data: dict[str, Any], tokenizer: _Tokenizer) -> dict[str, Any]:
    """Sanitize the router payload in place on a copy."""
    clean: dict[str, Any] = {}

    for key, value in data.items():
        if key in TO_REDACT or key in CARRIER_KEYS:
            clean[key] = REDACTED if value not in (None, "") else value
            continue

        if key == "last_sms" and isinstance(value, dict):
            clean[key] = _sanitize_sms(value, tokenizer)
            continue

        if not isinstance(value, str) or not value:
            clean[key] = value
            continue

        if key in IP_KEYS:
            clean[key] = tokenizer.token("ip", value)
        elif key in CELL_KEYS:
            clean[key] = tokenizer.token("cell", value)
        elif key.startswith("APN_config"):
            clean[key] = _summarize_apn(value, tokenizer)
        else:
            clean[key] = _sweep(value, tokenizer)

    return clean


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return sanitized diagnostics for a config entry."""
    coordinator: ZTERouterDataUpdateCoordinator = entry.runtime_data

    tokenizer = _Tokenizer()

    # deepcopy first — diagnostics is a read path and must never mutate the
    # live coordinator payload the entities are serving from.
    raw = deepcopy(coordinator.data) if coordinator.data else {}
    payload = _sanitize_payload(raw, tokenizer)

    entry_data = _sanitize_payload(deepcopy(dict(entry.data)), tokenizer)
    entry_options = _sanitize_payload(deepcopy(dict(entry.options)), tokenizer)

    return {
        "entry": {
            "title": entry.title,
            # async_redact_data as a second pass: cheap, and it catches a key
            # added to TO_REDACT that the payload walker did not reach.
            "data": async_redact_data(entry_data, TO_REDACT),
            # `host` is deliberately NOT blanked: it is the LAN address, which
            # the sweep has already tokenized, and keeping the token preserves
            # the fact that it is the same host as `lan_ipaddr` in the payload.
            "options": async_redact_data(entry_options, TO_REDACT),
        },
        "coordinator": {
            "consecutive_failures": coordinator.consecutive_failures,
            "last_update_success": coordinator.last_update_success,
            "last_update_success_time": (
                coordinator.last_update_success_time.isoformat()
                if coordinator.last_update_success_time
                else None
            ),
            "data_available": coordinator.data is not None,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            # Section 19 state: the most useful thing in the file when the
            # complaint is "it stopped working and I don't know why".
            "health": deepcopy(coordinator.health_snapshot),
            "endpoint_failures": dict(coordinator._endpoint_failures),
        },
        "data": payload,
    }
