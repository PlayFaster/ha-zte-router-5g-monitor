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

from .const import DISCOVERY_VALUE_SAFE
from .coordinator import ZTERouterDataUpdateCoordinator

# Values with no cross-reference worth preserving — blanked outright.
TO_REDACT = {
    "password",
    "username",
    "imei",
    "sim_imsi",
    "sim_iccid",
    # The shorter spellings the goform family also answers on. Added with the
    # aliases that put them in the request list: this module matches on exact
    # key name, and `_sweep` catches only IP- and MAC-shaped strings, so a
    # bare-digit IMSI would have travelled to a public issue in clear text.
    # `test_subscriber_aliases_are_redacted` fails if an alias of a redacted
    # concept is requested without being classified here.
    "imsi",
    "iccid",
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
    # Alternate spellings of the two above. A concept classified here must
    # cover every spelling requested, or one is redacted and the other is not
    # — `test_every_classified_concept_covers_all_its_aliases` enforces it.
    "strFullName",
    "strShortName",
    "wan_apn_ui",
}

# Identifiers that DO carry cross-reference value, so they are tokenized rather
# than blanked: seeing that two fields hold the same cell is diagnostic.
IP_KEYS = {"wan_ipaddr", "lan_ipaddr", "ipv6_wan_ipaddr"}
# `Z5g_CELL_ID` is the other spelling of `nr5g_pci` — see
# `sensor._ALIAS_5G_PCI`. It was requested and published untokenized while its
# sibling was pseudonymized, which `test_every_classified_concept_covers_all
# _its_aliases` now prevents: an alias of a classified concept is invisible to
# a set that enumerates by exact name.
CELL_KEYS = {"cell_id", "enodeb_id", "lte_pci", "nr5g_pci", "Z5g_CELL_ID"}

# The SMS block is the highest-sensitivity content in the payload: it is data
# about a *third party* who never consented to appear in a bug report.
SMS_TEXT_KEYS = {"content", "content_decoded"}
SMS_NUMBER_KEYS = {"number", "number_decoded"}

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
# Identifier-shaped digit runs: IMSI is 15 digits, ICCID 19-20. See `_sweep`.
_LONG_DIGITS_RE = re.compile(r"\b\d{15,}\b")
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
    """Replace anything IP-, MAC- or identifier-shaped anywhere in a string.

    A structural backstop for keys this module does not enumerate. Matched on
    shape only — never against a list of real values, which would put PII in
    the source tree and would not work for anybody else's router.

    The digit threshold is 15, not lower. An IMSI is 15 digits and an ICCID
    19 or 20, so 15 catches both; a byte counter is not an identifier, and
    `test_byte_counters_are_not_mistaken_for_identifiers` pins an 11-digit
    one, so anything below 12 would mask ordinary telemetry.
    """
    value = _IP_RE.sub(lambda m: tokenizer.token("ip", m.group(0)), value)
    value = _MAC_RE.sub(lambda m: tokenizer.token("mac", m.group(0)), value)
    return _LONG_DIGITS_RE.sub(lambda m: tokenizer.token("id", m.group(0)), value)


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


def _scalar(value: Any) -> Any:
    """Return a value only when it is a JSON scalar, else `None`.

    The download is serialized after every section has succeeded, so a value
    that cannot be encoded fails the whole file at the last moment and past
    every guard. Anything read off a collaborator — which may be a stand-in
    under test, or a future object here — passes through this first.
    """
    return value if isinstance(value, (str, int, float, bool)) else None


async def _async_guarded(section: str, coro: Any, errors: list[str]) -> Any:
    """Await one section, recording a failure rather than raising."""
    try:
        return await coro
    except Exception as err:  # noqa: BLE001 - recorded, never raised
        errors.append(f"{section}: {type(err).__name__}: {err}")
        return None


def _guarded(section: str, build: Any, errors: list[str]) -> Any:
    """Run one section of the download, recording a failure rather than raising.

    Home Assistant does not wrap `config_entry_diagnostics`
    (`homeassistant/components/diagnostics/__init__.py`), so an exception
    escaping here is an HTTP 500 and no file at all. A download that reports
    what went wrong is useful; one that fails to generate is not.
    """
    try:
        return build()
    except Exception as err:  # noqa: BLE001 - recorded, never raised
        errors.append(f"{section}: {type(err).__name__}: {err}")
        return None


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return sanitized diagnostics for a config entry.

    Every section is built independently and every failure is recorded in the
    file. This function must not raise: see `_guarded`.
    """
    coordinator: ZTERouterDataUpdateCoordinator = entry.runtime_data

    tokenizer = _Tokenizer()
    errors: list[str] = []

    # deepcopy first — diagnostics is a read path and must never mutate the
    # live coordinator payload the entities are serving from.
    raw = deepcopy(coordinator.data) if coordinator.data else {}
    payload = _guarded("data", lambda: _sanitize_payload(raw, tokenizer), errors) or {}

    entry_data = (
        _guarded(
            "entry.data",
            lambda: _sanitize_payload(deepcopy(dict(entry.data)), tokenizer),
            errors,
        )
        or {}
    )
    entry_options = (
        _guarded(
            "entry.options",
            lambda: _sanitize_payload(deepcopy(dict(entry.options)), tokenizer),
            errors,
        )
        or {}
    )

    # The router is touched here, not at setup: the mined names have no
    # runtime consumer, so the work is done when the user asks for it and not
    # speculatively for everyone. `run_discovery` never raises — it returns
    # its failures as notes — and the guard is the second line of defence.
    discovery_raw = await _async_guarded(
        "discovery", coordinator.async_run_discovery(), errors
    )
    discovery = (
        _guarded(
            "discovery.sanitize",
            lambda: _sanitize_discovery(discovery_raw, tokenizer),
            errors,
        )
        or {}
    )

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
            "endpoint_failures": coordinator.endpoint_failures,
        },
        "data": payload,
        # Counted here so a vocabulary mismatch is visible without diffing two
        # downloads: a device spelling concepts differently answers most of
        # the request empty.
        "data_populated": sum(
            1 for value in payload.values() if value not in ("", None, {})
        ),
        "data_empty": sum(1 for value in payload.values() if value in ("", None)),
        # `data` is empty until the first successful poll, which is exactly
        # the case this file is usually requested for. These two carry the
        # evidence that would otherwise be reachable only from raw logs.
        #
        # The rejected payload goes through the same walker as `data`, so it
        # is no more revealing than an accepted one. `login` carries names and
        # status only and never a cookie value — see
        # `api.ZTERouterAPI._record_login_metadata`.
        "last_rejection": _sanitize_rejection(
            coordinator.api.last_rejection, tokenizer
        ),
        # Measured rather than assumed: which keys this device answers
        # without a session. Names only. Empty means no measurement passed
        # validation and the module constant is in force.
        "setup_completed": _scalar(getattr(coordinator.api, "setup_completed", None)),
        "measurement_note": _scalar(getattr(coordinator.api, "measurement_note", None)),
        "logout_acknowledged": _scalar(
            getattr(coordinator.api, "logout_acknowledged", None)
        ),
        "unauthenticated_keys": sorted(coordinator.api.unauthenticated_keys)
        if isinstance(coordinator.api.unauthenticated_keys, (set, frozenset))
        else [],
        # Which candidate names this device answered. Values only for the
        # names classified safe in `const.DISCOVERY_VALUE_SAFE`; everything
        # else reports shape and length, because `_sanitize_payload` matches
        # on exact key name and a name it does not know would otherwise be
        # published intact.
        "discovery": discovery,
        "errors": errors,
        "login": (
            deepcopy(coordinator.api.login_metadata)
            if isinstance(coordinator.api.login_metadata, dict)
            else {}
        ),
    }


def _describe(value: str) -> str:
    """Reduce a value to its shape, for a name not classified safe."""
    if value.isdigit():
        kind = "digits"
    elif all(c.isalnum() or c in "-_." for c in value):
        kind = "alphanumeric"
    else:
        kind = "mixed"
    return f"<{kind}, {len(value)} chars>"


# Names whose value is never published, matched case-insensitively anywhere in
# the key. Mined names are discovered rather than chosen, and the 2026-07-29
# artefact contains `pppoe_password`, `tr069_ServerPassword`,
# `tr069_ConnectionRequestPassword`, `wifi_chip1_ssid1_password_encode`,
# `wifi_wds_WPAPSK1`, `gps_lat`, `gps_lon`, `msisdn` and `loginfo` — none of
# which `_sweep` would catch.
_DENY_NAME_RE = re.compile(
    r"(?i)(pass|pwd|psk|secret|token|cred|key_|_key|imsi|iccid|msisdn"
    r"|gps|_lat$|_lon$|latitude|longitude|ssid|apn|loginfo|serial|sn$"
    # Carrier identity. `network_provider` and `wan_apn` are already in
    # `CARRIER_KEYS`, so publishing their discovery equivalents was
    # inconsistent as well as revealing: an MC7010 answered `profile_name_ui`
    # and `m_profile_name` with the operator's own APN profile name, and
    # `rplmn_num` carries MCC and MNC in one value.
    r"|profile_name|provider|spn|plmn|fullname|shortname)"
)

# Decimal degrees, as a pair or alone: a coordinate is location whatever the
# key is called.
_GEO_RE = re.compile(r"^-?\d{1,3}\.\d{4,}$")

# Above this a value is a blob rather than a reading, and is reported as one.
_BLOB_CHARS = 200

# Published values are capped. A long value is still identifiable from its
# first line; an uncapped one bloats a file that is attached to an issue.
_VALUE_CAP = 120


def _gate_discovery_value(
    key: str, value: str, tokenizer: _Tokenizer
) -> tuple[Any, str]:
    """Decide what a discovered value publishes as, and say why.

    **Publish by default.** A value is what identifies an element — a name
    alone does not distinguish a counter from a timestamp from free text — and
    the whole purpose of discovery is to learn what a device reports. Denying
    by default would produce a file listing names and answering nothing.

    Safety comes from layers rather than from an allow-list, because a mined
    name has no allow-list entry by construction:

    1. `DISCOVERY_VALUE_SAFE` bypasses the rest for names already vetted.
    2. The name is matched against `_DENY_NAME_RE` — credentials, subscriber
       identifiers, location, SSIDs and APNs never publish.
    3. The existing walker runs: addresses, MACs and long digit runs are
       tokenized exactly as they are in the payload block.
    4. Shape rules catch what the name did not: coordinates, and anything long
       enough to be a blob.
    5. What survives is truncated.

    Returns the published value and a one-word verdict, so a reader can tell a
    key that answered nothing from one that was withheld.
    """
    if key in DISCOVERY_VALUE_SAFE:
        return _sweep(value, tokenizer), "vetted"

    if _DENY_NAME_RE.search(key):
        return _describe(value), "denied-name"

    swept = _sweep(value, tokenizer)
    if swept != value:
        return swept, "tokenized"

    if _GEO_RE.match(value.strip()):
        return tokenizer.token("geo", value), "denied-shape"

    if len(value) > _BLOB_CHARS:
        return _describe(value), "blob"

    return value[:_VALUE_CAP], "published"


def _sanitize_discovery(discovery: Any, tokenizer: _Tokenizer) -> dict[str, Any]:
    """Publish discovery results, values only where the name was classified.

    Values publish by default and are withheld by the layered gate in
    `_gate_discovery_value`, because a mined name has no allow-list entry by
    construction — denying by default would list names and answer nothing,
    which is the opposite of what discovery is for. The verdict for each key
    is published alongside, so a key that answered nothing and a key that was
    withheld stop looking alike.
    """
    if not isinstance(discovery, dict):
        return {}

    values = discovery.get("values") if "values" in discovery else discovery
    if not isinstance(values, dict):
        values = {}

    published: dict[str, Any] = {}
    verdicts: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(value, str):
            published[key] = value
            verdicts[key] = "published"
            continue
        published[key], verdicts[key] = _gate_discovery_value(key, value, tokenizer)

    out: dict[str, Any] = {"values": published, "verdicts": verdicts}
    for field in (
        "notes",
        "mined_count",
        "mined_names_probed",
        "mined_names_answered",
        "probed_no_answer",
        "mined_names",
        "session",
    ):
        if field in discovery:
            out[field] = discovery[field]
    return out


def _sanitize_rejection(
    rejection: dict[str, Any] | None, tokenizer: _Tokenizer
) -> dict[str, Any] | None:
    """Sanitize a retained rejection, payload included.

    The key maps are names only and pass through untouched; the payload is
    walked exactly as `coordinator.data` is. A response that was never JSON
    carries a body preview instead of a payload, and that is swept for
    address-shaped strings by the same walker.
    """
    # `isinstance`, not truthiness: diagnostics must survive a coordinator
    # whose api is a stand-in, and must never put a non-serializable object
    # into a file the user is about to attach to an issue.
    if not isinstance(rejection, dict):
        return None
    out = deepcopy(rejection)
    if "payload" in out:
        out["payload"] = _sanitize_payload(out["payload"], tokenizer)
    if "body_preview" in out:
        out["body_preview"] = _sweep(out["body_preview"], tokenizer)
    return out
