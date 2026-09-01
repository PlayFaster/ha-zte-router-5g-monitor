"""ZTE Router 5G API client."""

import contextlib
import hashlib
import logging
import re
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic
from typing import Any, NamedTuple, cast

import aiohttp

from .const import (
    ABSENT_KEY_PROPORTION_LIMIT,
    APN_PROFILE_SLOTS,
    BATCH_URL_BUDGET,
    DISCOVERY_BUDGET_SECONDS,
    DISCOVERY_CANDIDATES,
    DISCOVERY_CHUNK_SIZE,
    DISCOVERY_CHUNK_TIMEOUT,
    JS_BUNDLES,
    MINED_CHUNK_SIZE,
    SESSION_IDLE_RESET_SECONDS,
)
from .helpers import is_gsm7

_LOGGER = logging.getLogger(__name__)


# The batch poll is split in two because the router's GET is bounded by a URL
# length of roughly 2,048 characters, not by a number of names. A single list
# had grown to within ~160 characters of that ceiling, where the next addition
# would have truncated the response — which presents as missing fields and is
# indistinguishable from firmware contract drift.
#
# The split is by criticality, not alphabetically:
#
#   _CORE_PARAMS      mandatory. Everything feeding an enabled-by-default
#                     entity, the contract keys, and device identity. Its
#                     failure is a whole-integration failure.
#   _EXTENDED_PARAMS  optional. Diagnostics, disabled-by-default entities,
#                     router settings and the thermal keys. Fetched under its
#                     own strike budget, so a failure here degrades those
#                     entities alone and leaves Signal and Data serving real
#                     values.
#
# Keep each comfortably under budget — `test_batch_poll_urls_stay_within_the
# _router_budget` covers both.
_CORE_PARAMS: list[str] = [
    # --- Contract keys (coordinator drift check) ---
    "network_type",
    "signalbar",
    "wa_inner_version",
    "realtime_time",
    "wan_connect_status",
    # --- Signal and radio ---
    "lte_rsrp",
    "lte_rsrq",
    "lte_rssi",
    "lte_snr",
    "lte_pci",
    "Z5g_rsrp",
    "Z5g_rsrq",
    "Z5g_rssi",
    "Z5g_SINR",
    # --- Carrier aggregation and bands ---
    "lte_ca_pcell_band",
    "lte_ca_pcell_bandwidth",
    "wan_lte_ca",
    "wan_active_band",
    "wan_active_channel",
    "nr5g_action_band",
    "nr5g_action_channel",
    "nr5g_pci",
    # --- Cell and network identity ---
    "cell_id",
    "enodeb_id",
    "network_provider",
    "mdm_mcc",
    "mdm_mnc",
    "net_select",
    "net_select_mode",
    # --- Connection and addressing ---
    "wan_ipaddr",
    "lan_ipaddr",
    "ppp_status",
    "wan_apn",
    # --- Throughput and data volume ---
    "realtime_tx_thrpt",
    "realtime_rx_thrpt",
    "realtime_tx_bytes",
    "realtime_rx_bytes",
    "monthly_tx_bytes",
    "monthly_rx_bytes",
    # Billing cycle. Both feed the projection sensor, which is enabled
    # by default, so they belong in the mandatory fetch.
    "traffic_clear_date",
    "wan_auto_clear_flow_data_switch",
    # --- Writable settings ---
    #
    # These are the only router state a *control* is read from that would
    # otherwise sit in the optional batch. A control showing a cached position
    # is worse than a diagnostic showing one: it invites a write against a
    # stale reading, and `DATA_LIMIT_SETTING` echoes four of these fields back
    # in the form it sends, so a degraded read there would build a bad write.
    # They are also the two switches confirmed by targeted read-back after a
    # write, which needs the poll to agree with the confirmation.
    "ODU_led_switch",
    "data_volume_limit_switch",
    "data_volume_alert_percent",
    "data_volume_limit_unit",
    "data_volume_limit_size",
    # --- Device identity ---
    #
    # `imei` stays here despite feeding only a disabled sensor: it is
    # the device-registry identifier prefix, latched into `entry.data`
    # at setup. Sourcing identity from a fetch that is allowed to fail
    # would let a transient error rename every device.
    "model_name",
    "hardware_version",
    "imei",
    # --- SMS counters ---
    "sms_unread_num",
    "sms_nv_rev_total",
    "sms_nv_send_total",
    "sms_nv_draftbox_total",
    "sms_sim_rev_total",
    "sms_sim_send_total",
    "sms_sim_draftbox_total",
    "sms_nv_total",
    "sms_sim_total",
    # --- APN selection ---
    "apn_index",
    "apn_mode",
    # Generated so the request and the APN select cannot disagree
    # about how many slots exist.
    *[f"APN_config{i}" for i in range(APN_PROFILE_SLOTS)],
    # --- Cross-model aliases for the above ---
    #
    # These feed enabled-by-default entities on other members of the
    # goform family, so they ride the mandatory fetch: a Signal sensor
    # on an MC888 must not depend on an endpoint that is allowed to
    # degrade. The MC7010 answers "" for every one.
    "5g_rsrp",
    "nr5g_rsrp",
    "5g_sinr",
    "nr5g_sinr",
    "Z5g_snr",
    "Z5g_CELL_ID",
    "flux_monthly_tx_bytes",
    "flux_monthly_rx_bytes",
    "data_volume_clear_date",
    "data_volume_clear_day",
    # The `flux_` prefix is a whole parallel vocabulary on this API, not a
    # quirk of the monthly counters. `Kajkac/ZTE-MC-Home-assistant-repo`
    # requests both spellings of realtime throughput and of the data-volume
    # settings; this integration aliased the monthly pair and stopped, which
    # left the rest single-spelled. The MC7010 answers "" for all of these.
    #
    # `flux_monthly_time` is deliberately absent: it aliases `monthly_time`,
    # which this integration neither requests nor reads, so it would carry
    # URL budget for nothing.
    "flux_realtime_tx_bytes",
    "flux_realtime_rx_bytes",
    "flux_realtime_tx_thrpt",
    "flux_realtime_rx_thrpt",
    "flux_realtime_time",
    # These three feed `DATA_LIMIT_SETTING`, an all-or-nothing form the router
    # refuses if a field is missing. A wrong spelling here does not blank a
    # sensor, it makes the write impossible.
    "flux_data_volume_limit_size",
    "flux_data_volume_limit_unit",
    "flux_data_volume_alert_percent",
    # Alternate spellings recovered by mining the router's own web UI on
    # 2026-09-01. Each answered the identical value to the key it backs on an
    # MC7010, so each is a fallback rather than a second concept.
    "strBearer",
    "strFullName",
    "strShortName",
    "wan_apn_ui",
    "hardwarenumber",
    # Firmware update state. Two questions, so two keys: whether an update has
    # been found, and whether one is running.
    "current_upgrade_state",
    "new_version_state",
]

_EXTENDED_PARAMS: list[str] = [
    # --- Subscriber identifiers (disabled sensors) ---
    "sim_imsi",
    "sim_iccid",
    # The shorter spellings the rest of the goform family uses. Measured on
    # MC7010 firmware `IRL_H3G_MC7010DV1.0.0B03` on 2026-08-31: `iccid`
    # carries the identical value to `sim_iccid`, and `imsi` is present but
    # empty while `sim_imsi` is populated — the ordinary alias case. Placed in
    # the extended batch because the core batch is the one bounded by URL
    # budget, and neither feeds an enabled-by-default entity.
    "imsi",
    "iccid",
    # --- Diagnostics ---
    "battery_value",
    "rssi",
    "rscp",
    "rmcc",
    "rmnc",
    "lte_band_lock",
    "lte_ca_scell_band",
    "lte_ca_scell_bandwidth",
    "lte_multi_ca_scell_info",
    "opms_wan_mode",
    "opms_wan_auto_mode",
    "apn_interface_version",
    # --- Router settings ---
    "upnpEnabled",
    "alg_sip_enable",
    "web_sleep_switch",
    "web_wake_switch",
    # --- Reboot schedule ---
    "reboot_schedule_enable",
    "reboot_schedule_mode",
    "reboot_dow",
    "reboot_dod",
    "reboot_hour1",
    "reboot_min1",
    "reboot_hour2",
    "reboot_min2",
    # --- Time configuration ---
    "sntp_server0",
    "sntp_server1",
    "sntp_server2",
    "sntp_dst_enable",
    "sntp_timezone",
    # --- Thermal ---
    #
    # No model is confirmed to populate any of these; the MC7010
    # answers "" for all five.
    "pm_sensor_pa1",
    "pm_sensor_ambient",
    "pm_sensor_mdm",
    "pm_modem_5g",
    "pm_sensor_5g",
]


# `result` values a login is accepted on. Shares its members with
# `_is_refusal`, which decides the same question for writes, but is a separate
# constant on purpose: a login carrying no `result` at all has established
# nothing, whereas a write carrying none is normal.
_LOGIN_SUCCESS = frozenset({"success", "0", "ok"})

# Splits `name=value` off the front of a raw `Set-Cookie` header. Needed
# because `SimpleCookie` morsel names are case-sensitive and it drops a header
# it cannot parse without raising, so a cookie can be present in the response
# and absent from `r.cookies`.
_SET_COOKIE_RE = re.compile(r'\s*([^=;,\s]+)\s*=\s*("?[^";,]*"?)')

# `cmd=` literals in the router's own JavaScript. Matches the name that
# follows, in either quoting style the bundles use.
_JS_CMD_RE = re.compile(r"cmd['\"]?\s*[:=]\s*['\"]([A-Za-z_][A-Za-z0-9_,]*)")

# A mined token is only probed when it looks like a `cmd` name. The 2026-07-29
# artefact contains the literal `1`, and both probe paths interpolate names
# straight into a URL — a token carrying `&` or `=` would corrupt the request.
_SAFE_CMD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

# Tokens that survive the filter but are not router fields. `result` is the
# key a `goform` response carries its outcome in, and reads as a `cmd` literal
# in the bundles.
_NOT_ROUTER_FIELDS = frozenset({"result", "cmd", "isTest", "goformId"})

# The fixed part of a batch query, before any `cmd` name. The host is measured
# separately from `self.referer`, because a hostname is longer than an IP and
# the budget is a property of the whole URL.
_BATCH_PATH_PREFIX = (
    "goform/goform_get_cmd_process?multi_data=1&isTest=false"
    "&sms_received_flag_flag=0&cmd="
)


# Appended to every targeted read so an all-empty response still distinguishes
# "these fields are empty" from "the session is gone". See `get_params`.
# Concepts, not names. Each entry is one thing the router reports, with every
# spelling known to carry it. A device that spells a concept differently is
# handled by the same rule as the aliased sensors, and no model is named here.
#
# `wan_connect_status` is blank on an MC888 Pro that reports `ppp_connected`
# under `ppp_status` (issue #56), which is why a single name will not do.
_CONTRACT_CONCEPTS: dict[str, tuple[str, ...]] = {
    "network_type": ("network_type", "strBearer"),
    "signal_bars": ("signalbar",),
    "uptime": ("realtime_time", "flux_realtime_time"),
    "connection_state": ("wan_connect_status", "ppp_status"),
}

# Flattened for membership tests. `test_contract_keys_agree` asserts this
# matches `coordinator.CORE_KEYS`, which is the same mapping flattened the
# same way — `coordinator.py` imports this module, so the dependency runs one
# way only and the two are mirrored rather than shared.
_CONTRACT_KEYS = frozenset(
    key for spellings in _CONTRACT_CONCEPTS.values() for key in spellings
)

# Spellings of the key appended to every targeted read to prove the session is
# alive. **Bounded deliberately.** `_batch_get` passes the requested list into
# `_classify_session`, whose absent-key guard declines to rule once more than
# half of what was asked for came back missing — appending four spellings to a
# one-key read, with three absent, crosses that line and returns `undecidable`,
# which is the exact regression the sentinel exists to prevent.
_SESSION_SENTINELS: tuple[str, ...] = _CONTRACT_CONCEPTS["connection_state"]


# Keys this router answers **without a session**. Measured against an MC7010 on
# firmware V1.0.0B03 (2026-07-31) by replaying an invalidated stok: of the 80
# core keys, exactly these three still carried values, and of the 36 extended
# keys, exactly these two.
#
# This list is load-bearing, and getting it wrong is not a small error. The
# expiry rule used to be "every value in the response is empty", which is a
# property of *what was asked for* rather than of the session. Adding `imei`,
# `model_name` and `wa_inner_version` to the core batch made that rule
# permanently false: the core poll could no longer return an all-empty
# response, so an expired session was scored a clean success and never renewed.
# Every enabled entity published `unknown` while the health sensor stayed
# green — the fault reported after a router reboot. `_EXTENDED_PARAMS` was
# defeated the same way by its two `opms_` keys.
#
# Anything added here must be verified on hardware, never assumed from a name.
# `test_session_detection` asserts each batch still contains keys of *both*
# classes, because a batch of only one kind makes the test below undecidable.
_UNAUTHENTICATED_KEYS = frozenset(
    {
        "imei",
        "model_name",
        "wa_inner_version",
        "opms_wan_auto_mode",
        "opms_wan_mode",
    }
)


class ZTEConnectionError(Exception):
    """Raised when the router cannot be reached."""


class ZTEAuthError(Exception):
    """Raised when the session is not usable."""


class ZTECredentialsError(ZTEAuthError):
    """Raised only when the router rejects the password itself.

    Separated from its parent because the two demand opposite responses. A
    rejected password is the user's to fix, so it earns a reauth prompt. A
    session that has merely lapsed is the integration's to fix, and it already
    does — silently, by logging in again. Before the split, three lapsed
    sessions in a row raised `ConfigEntryAuthFailed` and told the user their
    credentials were wrong when they were not.

    Only `login()` raises this, and only on an explicit rejection.
    """


def _classify_session(
    payload: dict[str, Any],
    requested: list[str] | None = None,
    unauthenticated: frozenset[str] = _UNAUTHENTICATED_KEYS,
) -> str:
    """Say what a `200 OK` response proves about the session.

    This router never reports an expired session as an error. It answers
    ``200 OK`` and echoes every *authenticated* value back as an empty string,
    which at the HTTP layer is indistinguishable from success. The only way to
    tell the two apart is to read the response as two classes of key:

    ``live``
        Something authenticated carried a value, so the session works.
    ``expired``
        Every authenticated key came back blank *while* an unauthenticated key
        carried a value. The router is plainly answering, so blankness cannot
        be a reachability problem — it is the session.
    ``not_ready``
        Everything came back blank, unauthenticated keys included. The router
        is answering but has nothing to report yet, which is what it does for
        a while after a reboot. Logging in again would not help, so this must
        not be mistaken for an expiry.
    ``undecidable``
        The request carried no unauthenticated key, so the second and third
        cases cannot be told apart. The caller falls back to the older, weaker
        rule. This is the normal case for the SMS endpoints, whose responses
        contain no unauthenticated keys at all.

    Deciding from the *relationship* between the two classes is what makes this
    robust. The previous rule asked whether the whole response was blank, which
    silently stopped being a valid test of anything the moment the batch gained
    a key that answers without a session.
    """
    if not payload:
        return "undecidable"

    authenticated_values = [v for k, v in payload.items() if k not in unauthenticated]
    unauthenticated_values = [v for k, v in payload.items() if k in unauthenticated]

    if not authenticated_values:
        return "undecidable"
    if any(value != "" for value in authenticated_values):
        return "live"

    # Every authenticated value is blank. What the unauthenticated ones say
    # decides whether that means "no session" or "nothing to report yet".
    if not unauthenticated_values:
        return "undecidable"
    if all(v == "" for v in unauthenticated_values):
        return "not_ready"

    # Everything points to an expired session — but only if the router
    # actually answered what was asked. A response missing much of its
    # request is a truncated or refused read, or firmware key-name drift,
    # and says nothing about the session.
    #
    # This suppresses `expired` alone. It must not preempt `not_ready`: a
    # router still starting up answers blank, and a device that also omits
    # keys would otherwise be scored as a dead session and re-logged-in
    # pointlessly. `requested` is `None` wherever the caller does not know
    # its own key list — every endpoint but the two batch reads — and the
    # check is skipped, leaving those callers exactly as they were.
    if requested is not None:
        wanted = [k for k in requested if k not in unauthenticated]
        if wanted:
            absent = sum(1 for k in wanted if k not in payload)
            if absent / len(wanted) > ABSENT_KEY_PROPORTION_LIMIT:
                return "undecidable"
    return "expired"


def _cookie_header(cookies: dict[str, str]) -> str:
    """Render cookies as one `Cookie` request header.

    Sorted so the header is stable between calls, which keeps a captured
    request comparable across runs.
    """
    return "; ".join(f"{name}={value}" for name, value in sorted(cookies.items()))


class _LoginAttempt(NamedTuple):
    """Outcome of posting one login form.

    `established` records whether the router accepted the login, and
    `cookies` carries every cookie the response set, by name. The two are
    separate because a login can succeed without setting a cookie this client
    recognises — the condition reported as issue #56, where an MC888 Pro
    answered a successful `LOGIN` with `{"result":"0"}` and a cookie named
    `zsidn`. Testing for one named cookie scored that success as a failure.

    On a failed attempt `established` is false, `cookies` is empty, and
    exactly one of the two errors is set. They carry the outcome rather than
    the caller re-reading client state, so which of the two forms produced it
    stays explicit.
    """

    established: bool
    cookies: dict[str, str]
    auth_error: str | None
    conn_error: str | None


class ZTERouterAPI:
    """Async wrapper for the ZTE Router goform API using aiohttp."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        ip: str,
        username: str | None,
        password: str,
    ) -> None:
        """Initialize the API."""
        # Clean host/IP input: strip protocol prefix and trailing slashes
        clean_ip = ip
        if "://" in clean_ip:
            clean_ip = clean_ip.split("://", 1)[1]
        clean_ip = clean_ip.rstrip("/")

        self.session = session
        self.ip = clean_ip
        self.username = username
        self.password = password
        self.protocol = "http"
        self.referer = f"http://{self.ip}/"
        self.timeout = aiohttp.ClientTimeout(total=15)
        # Two fields, one piece of state. `session_active` is whether the
        # router has authenticated us; `stok` is the cookie it issued, which
        # some firmware does not issue at all (see `_LoginAttempt`). Never
        # assign either directly: `login()` establishes the pair and
        # `_clear_session()` drops it, so no site can move one without the
        # other. A session marked active with no cookie sends no `Cookie`
        # header, which the router answers by echoing the authenticated keys
        # back empty — indistinguishable from an expired session, and
        # published as `unknown` on every entity.
        self.cookies: dict[str, str] = {}
        self.session_active = False
        # Whether the most recent LOGOUT was acknowledged by the router. Only
        # a confirmed logout makes a subsequent read an unauthenticated one.
        self.logout_acknowledged = False
        # Keys this device answers without a session, measured rather than
        # assumed. Empty until a measurement passes validation; the module
        # constant is used until then.
        self.unauthenticated_keys: frozenset[str] = frozenset()
        # Which candidate `cmd` names this device answers. Populated once per
        # setup and published in the diagnostics download; never read by
        # runtime logic.
        self.is_multi = True
        self.last_activity = datetime.fromtimestamp(0, UTC)

        # Evidence for the diagnostics download. `coordinator.data` is `None`
        # until the first successful poll, so an integration that has never
        # succeeded produces an empty `data` block — which is exactly when the
        # download is asked for. These two carry what was rejected and what the
        # login saw, and both are sanitized on the way out.
        self.last_rejection: dict[str, Any] | None = None
        self.login_metadata: dict[str, Any] = {}
        self._cookies_found_in = "none"

    def _record_verdict(
        self, verdict: str, payload: dict[str, Any], requested: list[str] | None
    ) -> None:
        """Hold the response behind a non-live verdict, for diagnostics.

        Names only in the key map, and the payload itself is sanitized by
        `diagnostics.py` on the way out — the same walker that already handles
        `coordinator.data`, so a rejected payload is no more revealing than an
        accepted one. Bounded to the most recent, and cleared by a live
        verdict so a stale rejection cannot outlive the fault.
        """
        if verdict == "live":
            self.last_rejection = None
            return

        asked = list(requested) if requested else list(payload)
        self.last_rejection = {
            "verdict": verdict,
            "keys_populated": sorted(k for k, v in payload.items() if v != ""),
            "keys_empty": sorted(k for k, v in payload.items() if v == ""),
            "keys_absent": sorted(k for k in asked if k not in payload),
            "payload": dict(payload),
        }

    def _record_unparsable(self, status: int, body: str) -> None:
        """Hold a preview of a response that was not JSON at all.

        There is no payload to retain in that case, and the preview is what
        `_request` already computes for its own log line and discards.
        """
        self.last_rejection = {
            "verdict": "unparsable",
            "status": status,
            "body_preview": body.strip()[:300].replace(chr(10), " "),
        }

    def _clear_session(self, *, clear_cookies: bool = False) -> None:
        """Drop the session pair. The only site that ends a session.

        `clear_cookies` also empties the jar, which matters wherever a later
        login could otherwise find a `stok` left by the session just ended and
        mistake it for one the router has just issued.
        """
        self.cookies = {}
        self.session_active = False
        if clear_cookies:
            self.session.cookie_jar.clear(predicate=lambda m: m.key == "stok")

    def _hash(self, val: str | None) -> str:
        if val is None:
            raise ValueError("Input to hash function cannot be None")
        # ZTE challenge-response auth requires SHA256 — not password storage.
        # lgtm[py/weak-cryptographic-algorithm]
        return hashlib.sha256(val.encode()).hexdigest()

    def _hex_decode(self, hex_str: str) -> str:
        """Decode the router's UTF-16BE hex into text.

        **Decode the whole string at once, never code unit by code unit.** The
        previous form built the result with `chr()` per 4 hex digits, which is
        correct only inside the Basic Multilingual Plane. Anything above it —
        every emoji — arrives as a UTF-16 *surrogate pair*, and taking each
        half separately yields two lone surrogates rather than one character.
        The damage is worse than wrong text: a string holding lone surrogates
        **cannot be encoded to UTF-8 at all**, so the recorder, a webhook or a
        file log handler raises `UnicodeEncodeError` on a message the user
        cannot identify. This integration deliberately *sends* emoji
        (`encode_type=UNICODE`, `SMS_MAX_CHARS_UNICODE`) and until now could
        not read one back.

        `bytes.fromhex` also rejects an odd-length string, where the old loop
        silently decoded the remainder and dropped the rest. Reporting that as
        a decode failure is the better answer: a truncated payload is not
        something to half-render.
        """
        if not hex_str:
            return ""
        try:
            return bytes.fromhex(hex_str).decode("utf-16-be")
        except (ValueError, UnicodeDecodeError):
            _LOGGER.debug("Failed to decode hex string '%s'", hex_str)
            return "[Decoding Error]"

    def _require_contract(self, data: Any, key: str, cmd: str) -> None:
        """Fail loudly when a response is missing the key it must carry.

        Second line of defense behind the expiry detection in ``_request``.
        That detection recognizes the router's dead-session shape as observed
        today; this asserts the shape each endpoint actually needs, so a
        response that slips past detection can never be mistaken for "no data".

        Returning ``[]`` here instead would be indistinguishable from an empty
        inbox — which is precisely how an expired session surfaced to users as
        "no SMS" rather than as an error (masked_errors_check Class A/B).
        """
        if not isinstance(data, dict) or key not in data:
            raise ZTEConnectionError(
                f"Response to {cmd} is missing '{key}' — the session is probably "
                f"expired or the firmware changed its API. Got: "
                f"{list(data)[:6] if isinstance(data, dict) else type(data).__name__}"
            )

    def _require_success(self, data: Any, cmd: str) -> None:
        """Fail loudly when the router declines a write command.

        This API never signals a rejected write with an HTTP status: it
        answers ``200 OK`` with ``{"result":"failure"}`` and does nothing
        (see ``docs/zte_how_to_access.md`` — "never treat a 200 as success").
        Without this check a stale ``AD`` token, an expired session or a
        malformed payload all surface to the user as a successful action.

        Only an explicit non-success ``result`` is treated as failure. A
        response with no ``result`` key at all is left alone: not every
        ``goformId`` returns one, and inventing a requirement would turn
        working commands into errors.
        """
        if self._is_refusal(data):
            raise ZTEConnectionError(
                f"Router rejected {cmd}: result={data['result']!r}. The command "
                f"was not carried out — this API answers 200 OK for a refused "
                f"write."
            )

    @staticmethod
    def _is_refusal(data: Any) -> bool:
        """Return whether a response is an explicit non-success ``result``.

        Shared by `_require_success` and the stale-session recovery in
        `_request`, which must agree on what a refusal looks like: one deciding
        a response is a refusal while the other did not would either retry a
        command the router meant to decline, or fail to recover one it never
        authorised.

        A response with no ``result`` key at all is not a refusal. Not every
        ``goformId`` returns one, and inventing a requirement would turn working
        commands into errors.
        """
        if not isinstance(data, dict):
            return False
        result = data.get("result")
        if result is None:
            return False
        return str(result).lower() not in ("success", "0", "ok")

    async def _ensure_session(self, timeout_sec: int | None = None) -> None:
        """Confirm the session before a write derives its ``AD`` token.

        Necessary because of how the two halves of this API fail differently.
        A *read* signals a dead session by echoing every requested key back
        empty, which `_request` detects and recovers from. A *write* answers
        ``{"result":"failure"}`` — indistinguishable from a command the router
        declined on its merits — so nothing recovers it, and a control failed on
        every attempt until some read happened to re-login. That is the reported
        fault: turning the LED on failed repeatedly after the router's web page
        had taken the session, until Refresh Now ran the batch poll.

        It must happen *before* the write, not after it fails. Recovering
        afterwards was tried first and **verified not to work on hardware**: the
        session was renewed and the write replayed, and the router refused it
        again. Why is not established — a first guess that ``RD`` rotates on
        re-login, invalidating the ``AD`` in the replayed payload, was itself
        disproved by `scripts/hardware_check.py`, which observed ``RD``
        surviving a re-login. What *is* established, by repeated hardware runs,
        is that assuring the session first works and recovering afterwards does
        not. The design rests on the measurement, not on the explanation.

        Retrying is also unattractive on its own terms: ``{"result":"failure"}``
        is equally what the router returns for a command it declined on its
        merits, so resending would deliver a `send_sms` twice.

        Costs one short read (~16 ms) on a path where the write itself is
        ~112 ms. `_request` does the recovery: a retrying read re-logs-in on its
        own when the session has gone.
        """
        await self._request(
            "GET",
            "goform/goform_get_cmd_process?multi_data=1&isTest=false"
            "&sms_received_flag_flag=0&cmd=wan_connect_status",
            timeout_sec=timeout_sec,
        )

    def _parse_date(self, date_str: str) -> str | None:
        if not date_str:
            return None
        try:
            parts = date_str.split(",")
            if len(parts) >= 6:
                year = int(f"20{parts[0]}")
                month = int(parts[1])
                day = int(parts[2])
                hour = int(parts[3])
                minute = int(parts[4])
                second = int(parts[5])
                dt = datetime(
                    year,
                    month,
                    day,
                    hour,
                    minute,
                    second,
                    tzinfo=UTC,
                )
                return dt.isoformat()
        except (ValueError, IndexError):
            _LOGGER.debug("Failed to parse date string '%s'", date_str)
        return date_str

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        timeout_sec: int | None = None,
        authenticated: bool = True,
        requested: list[str] | None = None,
        _retry: bool = True,
        _after_relogin: bool = False,
    ) -> Any:
        """Centralized request helper that handles session creation and auto-renewal."""
        tout = aiohttp.ClientTimeout(total=timeout_sec) if timeout_sec else self.timeout

        # Preempt an idle-expired session rather than discovering it on failure.
        now = datetime.now(UTC)
        if (
            authenticated
            and self.session_active
            and (now - self.last_activity).total_seconds() > SESSION_IDLE_RESET_SECONDS
        ):
            _LOGGER.debug("Session likely expired due to inactivity; resetting session")
            self._clear_session()

        if authenticated and not self.session_active:
            await self.login(timeout_sec=timeout_sec)

        url = f"{self.referer}{path}"
        req_headers = {"Referer": f"{self.referer}index.html"}
        if headers:
            req_headers.update(headers)
        # A session with no cookie is normal on firmware that binds the
        # session to the client address; there is simply no header to send.
        if authenticated and self.cookies:
            req_headers["Cookie"] = _cookie_header(self.cookies)

        is_html_page = False
        status = 200
        content_type = ""
        url_str = ""
        body_preview = ""
        resp_json = None

        try:
            async with self.session.request(
                method,
                url,
                params=params,
                data=data,
                headers=req_headers,
                timeout=tout,
                ssl=False,
            ) as r:
                status = r.status
                content_type = r.headers.get("Content-Type", "")
                url_str = str(r.url)

                # Check if redirect or HTML response indicates session expiration
                if "index.html" in url_str:
                    is_html_page = True
                elif "text/html" in content_type:
                    try:
                        text_body = await r.text()
                        stripped_body = text_body.strip()
                        if stripped_body.startswith("<") or "index.html" in text_body:
                            is_html_page = True
                            body_preview = text_body[:300].strip().replace("\n", " ")
                    except (TimeoutError, aiohttp.ClientError):
                        body_preview = "[Unable to read response body]"

                if not is_html_page:
                    with contextlib.suppress(
                        ValueError, TypeError, aiohttp.ContentTypeError
                    ):
                        resp_json = await r.json(content_type=None)
        except (ZTEAuthError, ZTEConnectionError):
            raise
        except (TimeoutError, aiohttp.ClientError, RuntimeError, ValueError) as e:
            # `RuntimeError` covers "Session is closed", which Home Assistant
            # raises when its shared client session is torn down while a
            # request is in flight — a diagnostics download taken during a
            # reload hits exactly that. `ValueError` covers a body that will
            # not decode. Neither is an `aiohttp.ClientError`, so both used to
            # escape as themselves.
            if authenticated:
                self._clear_session()
            raise ZTEConnectionError(f"Request failed: {e}") from e

        # Validate parsed response and handle redirects/HTML
        if is_html_page:
            if authenticated and _retry:
                _LOGGER.debug("Detected HTML redirect/response; renewing session")
                await self.login(timeout_sec=timeout_sec)
                return await self._request(
                    method,
                    path,
                    params=params,
                    data=data,
                    headers=headers,
                    timeout_sec=timeout_sec,
                    authenticated=authenticated,
                    requested=requested,
                    _retry=False,
                    _after_relogin=True,
                )
            self._record_unparsable(status, body_preview)
            _LOGGER.error(
                "Unexpected HTML response from %s (Status: %s, Content-Type: %s): %s",
                url_str,
                status,
                content_type,
                body_preview,
            )
            raise ZTEConnectionError(
                f"Received unexpected HTML response (Status: {status})"
            )

        if resp_json is None:
            if authenticated and _retry:
                _LOGGER.debug("JSON parse failed; renewing session")
                await self.login(timeout_sec=timeout_sec)
                return await self._request(
                    method,
                    path,
                    params=params,
                    data=data,
                    headers=headers,
                    timeout_sec=timeout_sec,
                    authenticated=authenticated,
                    requested=requested,
                    _retry=False,
                    _after_relogin=True,
                )
            self._record_unparsable(status, body_preview)
            raise ZTEConnectionError("Failed to parse JSON response from router")

        # 3. Check JSON structure for session expiry/invalid indicators
        if isinstance(resp_json, dict):
            # A dead session answers HTTP 200 with the *authenticated* keys
            # echoed back empty — never an error, never a redirect. Captured
            # from an MC7010 on firmware V1.0.0B03 (2026-07-27) by replaying an
            # invalidated stok:
            #
            #   batch poll  -> {"network_type":"","signalbar":"","wan_ipaddr":""}
            #   SMS list    -> {"sms_data_total":""}
            #   SMS capacity-> {"sms_capacity_info":""}
            #
            # `_classify_session` reads that shape against the two classes of
            # key rather than against the whole response; see its docstring for
            # why the difference matters. `undecidable` keeps the older rule for
            # the SMS endpoints, which carry no unauthenticated key to compare
            # against — the case that rule was written for and still handles.
            verdict = _classify_session(
                resp_json, requested, self.unauthenticated_key_set()
            )
            self._record_verdict(verdict, resp_json, requested)
            is_status_expired = verdict == "expired" or (
                verdict == "undecidable"
                and bool(resp_json)
                and all(value == "" for value in resp_json.values())
            )
            # Other endpoints might return explicit error indications
            is_auth_error = (
                resp_json.get("result") in ["session expired", "unauth", "fail"]
                or resp_json.get("status") == "fail"
            )

            # Answering, but with nothing to say yet. Logging in again would
            # not help, so this is reported as a reachability problem and picks
            # up the coordinator's hold-last-known-values path instead of
            # burning a re-login and then a reauth prompt.
            if verdict == "not_ready" and authenticated:
                raise ZTEConnectionError(
                    "Router answered but reported no data — it is probably "
                    "still starting up"
                )

            if (is_status_expired or is_auth_error) and authenticated:
                if _retry:
                    _LOGGER.debug("Session expired in JSON response; renewing session")
                    await self.login(timeout_sec=timeout_sec)
                    return await self._request(
                        method,
                        path,
                        params=params,
                        data=data,
                        headers=headers,
                        timeout_sec=timeout_sec,
                        authenticated=authenticated,
                        requested=requested,
                        _retry=False,
                        _after_relogin=True,
                    )
                if _after_relogin and not is_auth_error:
                    # A session established seconds ago cannot itself be
                    # expired. The response was scored from its *shape*, and
                    # a fresh session producing that shape refutes the rule
                    # rather than confirming the verdict. Reported as a
                    # reachability problem so it picks up the coordinator's
                    # hold-last-known-values path, and so a rule that does not
                    # fit this device cannot present as an auth condition.
                    raise ZTEConnectionError(
                        "Router returned an expired-looking response on a "
                        "freshly established session — the session is not the "
                        "problem"
                    )
                # Either the router said so explicitly, or the caller asked for
                # no recovery. `scripts/hardware_check.py` probes an invalidated
                # session with `_retry=False` and asserts this exception; that
                # check is the standing hardware proof that expiry is detectable.
                raise ZTEAuthError("Session expired/unauthorized")

        # Only an authenticated call proves the session is still alive, so only
        # one counts as activity. Unauthenticated endpoints (`LD`, `RD`'s
        # sibling `wa_inner_version`) answer perfectly well with a dead
        # session — letting them stamp this clock told the idle check below
        # that a long-idle session was fresh, so the stale `stok` was never
        # cleared. Every write action calls `get_ad()` -> `get_version()`
        # first, so an action taken after a pause was exactly the case that
        # broke: the unauthenticated version fetch reset the clock immediately
        # before the authenticated call that needed it.
        if authenticated:
            self.last_activity = datetime.now(UTC)
        return resp_json

    async def try_set_protocol(self, timeout_sec: int = 5) -> None:
        """Identify if router is on http or https with a short timeout."""
        protocols = ["http", "https"]
        tout = aiohttp.ClientTimeout(total=timeout_sec)
        for proto in protocols:
            url = f"{proto}://{self.ip}"
            try:
                # SSL verification is disabled as local routers use self-signed certs
                async with self.session.get(url, timeout=tout, ssl=False) as r:
                    if r.status < 400:
                        self.protocol = proto
                        self.referer = f"{self.protocol}://{self.ip}/"
                        return
            except (TimeoutError, aiohttp.ClientError) as e:
                _LOGGER.debug("Failed to connect via %s: %s", proto, e)

        _LOGGER.warning("Could not determine router protocol (http/https)")

    async def get_version(self, timeout_sec: int | None = None) -> str | None:
        """Get the router firmware version."""
        path = "goform/goform_get_cmd_process?isTest=false&cmd=wa_inner_version"
        try:
            data = await self._request(
                "GET", path, timeout_sec=timeout_sec, authenticated=False
            )
            return cast("str | None", data.get("wa_inner_version", ""))
        except (ZTEAuthError, ZTEConnectionError) as e:
            _LOGGER.debug("Failed to get version: %s", e)
            return None

    async def get_ld(self, timeout_sec: int | None = None) -> str:
        """Get the LD parameter for login."""
        path = "goform/goform_get_cmd_process?isTest=false&cmd=LD"
        data = await self._request(
            "GET", path, timeout_sec=timeout_sec, authenticated=False
        )
        return cast(str, data.get("LD", "").upper())

    async def login(self, timeout_sec: int | None = None) -> None:
        """Clean login that resets the internal session state.

        The only site that establishes a session. Callers do not assign the
        result: `self.cookies` and `self.session_active` are set here together,
        which is what stops one from being moved without the other.
        """
        tout = timeout_sec or 15
        # Clearing the jar as well as the pair is what lets `_attempt_login`
        # trust a `stok` it finds there: anything present afterwards was set
        # by the login POST, not left behind by the session just ended.
        self._clear_session(clear_cookies=True)

        ld = await self.get_ld(timeout_sec=tout)
        version = await self.get_version(timeout_sec=tout)

        if not self.password:
            raise ZTECredentialsError("No password provided")
        pass_hash = self._hash(self.password).upper()
        zte_pass = self._hash(pass_hash + ld).upper()

        self.is_multi = True
        if version and any(m in version for m in ["MC801", "MC7010"]):
            self.is_multi = False

        # No username means the multi-user form has no user field to carry, and
        # the router rejects it on that ground alone — which is what produced
        # the `Result: failure` line in issue #56 before the fallback found
        # `LOGIN`. `Kajkac/ZTE-MC-Home-assistant-repo`, the reference
        # implementation for this hardware family, branches on the username
        # alone and sends `LOGIN` here first and only. Matching it removes a
        # login attempt that cannot succeed, and the warning it logged.
        if not self.username:
            primary = "LOGIN"
        else:
            primary = "LOGIN" if not self.is_multi else "LOGIN_MULTI_USER"
        # Derived once and only when a multi-user attempt is actually
        # possible, so the extra unauthenticated read never lands on the
        # single-user path — which is every login on the reference MC7010.
        multi_ad: str | None = None
        if self.username and version:
            multi_ad = await self._login_ad(version, timeout_sec=tout)

        attempt = await self._attempt_login(primary, zte_pass, tout, multi_ad)

        # Best-effort form fallback for models this integration has never seen.
        # Which form a goform router accepts is a per-model quirk and the model
        # list above only covers the ones that have been tested, so an unlisted
        # router can be rejected purely for using the wrong goformId. Only the
        # unclassified failure is worth retrying: a credentials rejection means
        # the password is wrong whichever form carries it, and retrying would
        # just burn a second attempt against routers that lock out.
        if not attempt.established and attempt.auth_error is None:
            fallback = "LOGIN_MULTI_USER" if primary == "LOGIN" else "LOGIN"
            _LOGGER.debug(
                "Login form %s did not yield a session; retrying once with %s",
                primary,
                fallback,
            )
            retry = await self._attempt_login(fallback, zte_pass, tout, multi_ad)
            if retry.established:
                _LOGGER.info(
                    "Login succeeded with fallback form %s (this router does not "
                    "accept %s)",
                    fallback,
                    primary,
                )
            # The alternate form reaching a credentials rejection is the more
            # informative of the two answers, so the retry's verdict replaces
            # the primary's either way.
            attempt = retry

        if attempt.auth_error:
            # The router rejected the password itself. This is the one auth
            # condition the user has to resolve, so it is the one condition
            # allowed to reach a reauth prompt.
            raise ZTECredentialsError(attempt.auth_error)
        if attempt.conn_error:
            raise ZTEConnectionError(attempt.conn_error)

        if not attempt.established:  # pragma: no cover - defensive
            raise ZTEConnectionError("Failed to establish a session at login")

        self.cookies = dict(attempt.cookies)
        self.session_active = True
        self.last_activity = datetime.now(UTC)
        if not attempt.cookies:
            # Kept because a router answering a success `result` with no
            # cookie at all remains a supported outcome, but no device is now
            # known to do it: the MC888 Pro that prompted this path turned out
            # to issue `zsidn` (issue #56), which the old name-matching
            # extractor discarded. Treat a cookieless session as unevidenced
            # rather than as a firmware family.
            _LOGGER.debug(
                "Router accepted the login without setting any cookie; the "
                "session is bound to this client rather than to a cookie"
            )
        else:
            _LOGGER.debug("Login established with cookies: %s", sorted(attempt.cookies))

    async def _attempt_login(
        self, goform_id: str, zte_pass: str, tout: int, ad: str | None = None
    ) -> _LoginAttempt:
        """Post one login form and report what the router made of it.

        Does not touch `self.cookies` or `self.session_active`; `login()` owns
        both. Genuine transport failures raise `ZTEConnectionError` directly
        rather than being reported in the result, because there is no point
        retrying a different form against a router that is not answering at
        all.
        """
        payload = {
            "isTest": "false",
            "goformId": goform_id,
            "password": zte_pass,
        }
        # The two forms take the username under different names, and only the
        # multi-user form carries an `AD` token. Both details follow
        # `Kajkac/ZTE-MC-Home-assistant-repo`, the reference implementation
        # for this hardware family; ZRM's previous shape — `username=` with no
        # token on both forms — is not supported by any device this project
        # can reach, since the MC7010 refuses `LOGIN_MULTI_USER` whatever it
        # carries (measured 2026-08-30, all four combinations).
        #
        # `LOGIN` keeps `username=`. That is measured, not inherited: on
        # MC7010 firmware `IRL_H3G_MC7010DV1.0.0B03` both spellings are
        # accepted and yield a usable session, while omitting the field
        # entirely — Kajkac's shape for this form — makes the router close the
        # connection without answering.
        if self.username:
            if goform_id == "LOGIN_MULTI_USER":
                payload["user"] = self.username
                if ad:
                    payload["AD"] = ad
            else:
                payload["username"] = self.username

        url = f"{self.referer}goform/goform_set_cmd_process"
        login_error = None
        conn_error = None
        try:
            async with self.session.post(
                url,
                data=payload,
                headers={"Referer": self.referer},
                timeout=aiohttp.ClientTimeout(total=tout),
                ssl=False,
            ) as r:
                resp_json: Any = None
                result = None
                with contextlib.suppress(
                    ValueError, TypeError, aiohttp.ContentTypeError
                ):
                    resp_json = await r.json(content_type=None)
                    if isinstance(resp_json, dict):
                        result = resp_json.get("result")

                cookies = self._extract_cookies(r, resp_json=resp_json)
                self._record_login_metadata(r, goform_id, cookies, result)

                # A cookie proves a session — any cookie, under any name.
                # Without one, only an explicit success `result` does. A
                # response carrying neither is not read as success: an absent
                # `result` is normal on a command that returns none, but a
                # *login* that neither set a cookie nor said `0` has not
                # established anything.
                if not cookies and str(result).lower() not in _LOGIN_SUCCESS:
                    if result in (
                        "password_error",
                        "invalid_password",
                        "write_error",
                        "unauth",
                    ):
                        return _LoginAttempt(
                            False,
                            {},
                            f"Login failed due to invalid credentials: {result}",
                            None,
                        )
                    _LOGGER.warning(
                        "Login failed: no session established (Status: %s, "
                        "Result: %s). Treating as connection issue.",
                        r.status,
                        result,
                    )
                    return _LoginAttempt(
                        False,
                        {},
                        None,
                        f"Failed to establish a session at login: {result}",
                    )

                await self._initialize_session(cookies, tout)
        except (TimeoutError, aiohttp.ClientError) as e:
            raise ZTEConnectionError(
                f"Login failed due to connection error: {e}"
            ) from e

        return _LoginAttempt(True, cookies, login_error, conn_error)

    def _record_login_metadata(
        self,
        r: aiohttp.ClientResponse,
        goform_id: str,
        cookies: dict[str, str],
        result: Any,
    ) -> None:
        """Record what the login response looked like, for diagnostics.

        Names and status only. **The cookie value is never recorded** — it is
        a live session credential, and `test_login_metadata_never_carries_a
        _cookie_value` asserts its absence from the whole serialized output.

        `session_cookie_name` is the field that says whether a device issues a
        session cookie under a name `_extract_stok` does not look for, which
        is otherwise answerable only by asking a reporter to capture the login
        response from a browser.
        """
        names = sorted(set(r.headers))
        cookie_names = sorted(r.cookies)
        self.login_metadata = {
            "form_used": goform_id,
            "status": r.status,
            "result": result,
            "header_names": names,
            "cookie_names": cookie_names,
            "session_cookie_issued": bool(cookies),
            "cookies_replayed": sorted(cookies),
            "cookies_found_in": self._cookies_found_in,
        }

    def _extract_cookies(
        self, r: aiohttp.ClientResponse, *, resp_json: Any = None
    ) -> dict[str, str]:
        """Return every cookie the login response set, by name.

        **Does not decide which cookie is the session.** An MC888 Pro on
        `BD_ABPLMC888PROMODV1.0.0B01` names its session cookie `zsidn`, not
        `stok` (issue #56), and the previous form matched the literal name
        `stok` in four places — so the cookie was received, ignored, and every
        subsequent request went out unauthenticated. The router then answered
        as it does to any anonymous client, and every entity published
        `unknown` behind a poll that scored as a success.

        A browser replays whatever the origin set, and so does this. Replaying
        a cookie that is not the session costs nothing; missing the one that
        is costs the whole integration, and no rule for telling them apart
        survives contact with a firmware nobody has seen.

        Three sources, in order. `r.cookies` is a `SimpleCookie`, whose morsel
        names are case-sensitive and which silently drops a header it cannot
        parse, so the raw headers are swept as well. A `stok` in the response
        body is read last, for firmware that answers the token in JSON rather
        than as a cookie.

        The session cookie jar is deliberately **not** consulted. Home
        Assistant's shared client session carries aiohttp's default
        `CookieJar`, which refuses cookies from an IP-address host — the
        normal configuration here — so that branch could never fire for the
        redirect case it was written for.
        """
        cookies: dict[str, str] = {
            name: morsel.value.strip('"') for name, morsel in r.cookies.items()
        }
        if cookies:
            self._cookies_found_in = "response_cookies"

        for header in r.headers.getall("Set-Cookie", []):
            match = _SET_COOKIE_RE.match(header.strip())
            if match:
                name, value = match.group(1), match.group(2).strip('"')
                if name not in cookies and value:
                    cookies[name] = value
                    self._cookies_found_in = "raw_header"

        if not cookies and isinstance(resp_json, dict):
            body_stok = resp_json.get("stok")
            if isinstance(body_stok, str) and body_stok:
                cookies["stok"] = body_stok.strip('"')
                self._cookies_found_in = "response_body"

        return cookies

    async def _initialize_session(self, cookies: dict[str, str], tout: int) -> None:
        """Activate the session with the GET some ZTE routers require.

        Best effort: a failure here is logged and not raised, because the
        login itself already succeeded and the next request retries the same
        ground.
        """
        init_headers = {"Referer": f"{self.referer}index.html"}
        if cookies:
            init_headers["Cookie"] = _cookie_header(cookies)
        try:
            async with self.session.get(
                f"{self.referer}goform/goform_get_cmd_process",
                params={"isTest": "false", "cmd": "wa_inner_version"},
                headers=init_headers,
                timeout=aiohttp.ClientTimeout(total=tout),
                ssl=False,
            ) as init_r:
                await init_r.read()
        except (TimeoutError, aiohttp.ClientError) as init_err:
            _LOGGER.debug("Session initialization GET failed: %s", init_err)

    async def measure_unauthenticated_keys(
        self, timeout_sec: int | None = None
    ) -> frozenset[str]:
        """Ask this device which keys it answers without a session.

        `_UNAUTHENTICATED_KEYS` is five names measured on one MC7010 by
        replaying an invalidated token, and asserted about every device since.
        It is wrong on at least one: an MC888 Pro answers `network_type` and
        `ppp_status` without a session (issue #56), both of which the constant
        classifies as authenticated. On that device a lapsed session would show
        a populated "authenticated" key, `_classify_session` would return
        `live`, and a dead session would score healthy with nothing logged.

        **Call only after a confirmed logout.** A reading taken while the
        session is still live samples an authenticated response and measures
        the whole batch as unauthenticated, which leaves the classifier unable
        to ever return `expired` — a worse failure than the constant it
        replaces. `logout()` records whether the router acknowledged; this
        refuses to run unless it did.

        Returns the measured set, or an empty set where no measurement could
        be trusted. The caller keeps using the constant in that case.
        """
        if self.session_active or not self.logout_acknowledged:
            _LOGGER.debug(
                "Not measuring unauthenticated keys: session_active=%s, "
                "logout_acknowledged=%s",
                self.session_active,
                self.logout_acknowledged,
            )
            return frozenset()

        measured: set[str] = set()
        for params in (_CORE_PARAMS, _EXTENDED_PARAMS):
            # `authenticated=False` is the whole point: `_batch_get` would
            # log back in before sending, sample an authenticated response,
            # and measure the entire batch as unauthenticated.
            path = (
                "goform/goform_get_cmd_process?multi_data=1&isTest=false"
                f"&sms_received_flag_flag=0&cmd={','.join(params)}"
            )
            try:
                payload = await self._request(
                    "GET",
                    path,
                    timeout_sec=timeout_sec,
                    authenticated=False,
                )
            except (ZTEAuthError, ZTEConnectionError) as err:
                _LOGGER.debug("Unauthenticated probe failed: %s", err)
                return frozenset()
            if not isinstance(payload, dict):
                return frozenset()
            measured |= {k for k, v in payload.items() if v not in ("", None)}

        if not self._measurement_is_usable(measured):
            return frozenset()

        _LOGGER.info(
            "Measured %d keys this router answers without a session",
            len(measured),
        )
        return frozenset(measured)

    @staticmethod
    def _measurement_is_usable(measured: set[str]) -> bool:
        """Reject a measurement that cannot safely replace the constant.

        Each rule exists because the failure it prevents is silent. A set that
        swallows a whole batch leaves nothing authenticated to compare
        against, so `_classify_session` returns `undecidable` forever and
        falls back to a rule that `_CORE_PARAMS` made unsatisfiable. A set
        containing the sentinel or a contract key breaks `get_params` and the
        drift check, which both depend on those being authenticated.
        """
        if not measured:
            _LOGGER.debug("Measurement rejected: nothing answered")
            return False

        for params in (_CORE_PARAMS, _EXTENDED_PARAMS):
            if not set(params) - measured:
                _LOGGER.warning(
                    "Measurement rejected: it would leave no authenticated key "
                    "in a batch, so an expired session could never be detected"
                )
                return False

        # Checked **before** the sentinel: the sentinel spellings are
        # themselves contract keys, so testing them first made this branch
        # unreachable — coverage caught it.
        #
        # Reject only a set that claims **every** contract key, not one that
        # claims any. The drift check asks whether *any* of them is present, so
        # it survives losing one — and the MC888 Pro genuinely answers
        # `network_type` without a session (issue #56). Rejecting on a single
        # contract key would refuse that device's own true measurement and
        # leave it on a constant that is wrong for it, which is the failure
        # this whole mechanism exists to prevent.
        if measured >= _CONTRACT_KEYS:
            _LOGGER.warning(
                "Measurement rejected: it would leave no authenticated contract "
                "key, disabling the firmware drift check"
            )
            return False

        if set(_SESSION_SENTINELS) <= measured:
            # `get_params` appends this key to every targeted read precisely to
            # prove the session is alive. A device answering it unauthenticated
            # would make that proof meaningless, and there is no fallback for
            # it — unlike the contract keys, which are a set.
            _LOGGER.warning(
                "Measurement rejected: every spelling of %s answers without "
                "a session, so nothing proves a targeted read is alive",
                sorted(_SESSION_SENTINELS),
            )
            return False

        return True

    def unauthenticated_key_set(self) -> frozenset[str]:
        """The key set in force: measured where trusted, constant otherwise."""
        return self.unauthenticated_keys or _UNAUTHENTICATED_KEYS

    async def mine_candidate_names(
        self, timeout_sec: int | None = None
    ) -> tuple[set[str], list[str]]:
        """Read the router's own web UI for `cmd` names it uses.

        The `goform` API cannot be enumerated: one `cmd` parameter takes a list
        of names and answers those, so a name nobody asks for is invisible
        forever. The router's admin UI is a client of this same API, and its
        JavaScript is the only reliable source for names nobody has written
        down — the 2026-07-29 mining pass recorded in
        `.notes/local_only/router_probe/js_mined_keys.json` recovered 175, of
        which 117 this integration has never requested.

        Several bundles, not one. `docs/zte_how_to_access.md` names
        `js/service.js` alongside `statusBar.js`, `home.js` and the RequireJS
        modules, and that pass crawled all of them to reach 175.

        Returns the names and a list of human-readable notes. Every failure is
        a note rather than an exception: this runs while a diagnostics download
        is being generated, and a download that reports what went wrong is
        useful where one that fails to generate is not.
        """
        names: set[str] = set()
        notes: list[str] = []
        for bundle in JS_BUNDLES:
            try:
                async with self.session.get(
                    f"{self.referer}{bundle}",
                    headers={"Referer": f"{self.referer}index.html"},
                    timeout=aiohttp.ClientTimeout(total=timeout_sec or 10),
                    ssl=False,
                ) as r:
                    if r.status != 200:
                        notes.append(f"{bundle}: HTTP {r.status}")
                        continue
                    body = await r.text(errors="replace")
            except Exception as err:  # noqa: BLE001 - a note, never a failure
                notes.append(f"{bundle}: {type(err).__name__}: {err}")
                continue

            found = {
                part
                for m in _JS_CMD_RE.finditer(body)
                for part in m.group(1).split(",")
            }
            names |= found
            notes.append(f"{bundle}: {len(found)} names")

        return {
            n
            for n in names
            if _SAFE_CMD_RE.fullmatch(n) and n not in _NOT_ROUTER_FIELDS
        }, notes

    async def probe_names(
        self,
        names: list[str],
        *,
        chunk_size: int = DISCOVERY_CHUNK_SIZE,
        deadline: float | None = None,
    ) -> tuple[dict[str, str], list[str]]:
        """Read a list of `cmd` names, tolerating anything that goes wrong.

        Chunked, and every chunk tolerated on its own.
        `docs/zte_how_to_access.md` records a chunk carrying a name outside the
        firmware's dictionary timing out and returning empty defaults for
        *every* name in it — so a genuinely populated key sharing that chunk is
        scored absent with no trace. Per-chunk tolerance saves the other
        chunks; it does nothing for the names inside the failed one, which is
        why a chunk that times out or answers nothing is re-probed one name at
        a time. That converts a timeout into per-name truth.

        `deadline` is wall-clock and checked between chunks. A timed-out chunk
        clears the session, so the next pays a full login; without a ceiling a
        slow firmware could make a diagnostics download take minutes.

        Catches `Exception`, not the two domain types. This runs inside a
        diagnostics download, which must produce a file whatever happens, and
        a `RuntimeError` from a closed session is neither a `ZTEAuthError` nor
        a `ZTEConnectionError`.
        """
        if deadline is None:
            deadline = monotonic() + DISCOVERY_BUDGET_SECONDS
        found: dict[str, str] = {}
        notes: list[str] = []
        retry: list[str] = []

        for start in range(0, len(names), chunk_size):
            if monotonic() > deadline:
                notes.append(
                    f"budget exhausted with {len(names) - start} names unprobed"
                )
                return found, notes
            chunk = names[start : start + chunk_size]
            answered = await self._probe_chunk(chunk)
            if answered is None:
                retry.extend(chunk)
                continue
            found.update(answered)
            if not answered and len(chunk) > 1:
                retry.extend(chunk)

        for name in retry:
            if monotonic() > deadline:
                notes.append("budget exhausted during single-name re-probe")
                break
            answered = await self._probe_chunk([name])
            if answered:
                found.update(answered)
        if retry:
            notes.append(f"{len(retry)} names re-probed singly")

        return found, notes

    async def _probe_chunk(self, chunk: list[str]) -> dict[str, str] | None:
        """Read one chunk. `None` means it failed; `{}` means it answered blank."""
        path = (
            "goform/goform_get_cmd_process?multi_data=1&isTest=false"
            f"&sms_received_flag_flag=0&cmd={','.join(chunk)}"
        )
        try:
            payload = await self._request(
                "GET", path, timeout_sec=DISCOVERY_CHUNK_TIMEOUT
            )
        except Exception as err:  # noqa: BLE001 - a note, never a failure
            _LOGGER.debug("Probe chunk starting %s failed: %s", chunk[0], err)
            return None
        if not isinstance(payload, dict):
            return None
        # `result` is the key a `goform` response carries its outcome in, and
        # a refused chunk echoes it back. It is not a router field, and
        # harvesting it would publish `failure` as though it were telemetry.
        return {
            k: v
            for k, v in payload.items()
            if isinstance(v, str) and v and k not in _NOT_ROUTER_FIELDS
        }

    async def run_discovery(self, timeout_sec: int | None = None) -> dict[str, Any]:
        """Mine, probe and report — the whole discovery pass, for diagnostics.

        Never raises. Every failure becomes a note in the returned mapping,
        because this is called while a diagnostics download is generated and a
        download that reports a failure is useful where one that fails to
        generate is not.
        """
        deadline = monotonic() + DISCOVERY_BUDGET_SECONDS
        result: dict[str, Any] = {"notes": [], "values": {}}
        try:
            # The user pressed Download Diagnostics, which authorises using
            # the router. Logging in evicts whoever holds the single session
            # this hardware permits, and that is acceptable — declining to
            # log in would return less exactly when the download matters most.
            if self.session_active:
                result["session"] = "existing"
            else:
                await self.login(timeout_sec=timeout_sec)
                result["session"] = "fresh login"

            mined, notes = await self.mine_candidate_names(timeout_sec=timeout_sec)
            result["notes"].extend(notes)
            result["mined_count"] = len(mined)

            requested = set(_CORE_PARAMS) | set(_EXTENDED_PARAMS)
            static = [n for n in DISCOVERY_CANDIDATES if n not in requested]
            unknown = sorted(mined - requested - set(static))

            # The static list is not belt-and-braces: 52 of its 62 names do not
            # appear in the mined artefact at all, so the two sources barely
            # overlap and both are needed.
            static_found, static_notes = await self.probe_names(
                static, chunk_size=DISCOVERY_CHUNK_SIZE, deadline=deadline
            )
            mined_found, mined_notes = await self.probe_names(
                unknown, chunk_size=MINED_CHUNK_SIZE, deadline=deadline
            )
            result["notes"].extend(static_notes + mined_notes)
            result["values"] = {**static_found, **mined_found}
            result["mined_names_probed"] = len(unknown)
            result["mined_names_answered"] = len(mined_found)
        except Exception as err:  # noqa: BLE001 - a note, never a failure
            result["notes"].append(f"discovery aborted: {type(err).__name__}: {err}")
        return result

    async def logout(self) -> None:
        """End the router session and drop local session state.

        Best effort by design: this runs on unload, and an unreachable router
        must never block Home Assistant from tearing the entry down. Local
        state is cleared regardless of whether the router acknowledged.

        It matters more here than on most hardware — a ZTE CPE permits only one
        login session at a time, so an abandoned session locks the user out of
        the router's own web UI until it times out (dev_standards Section 10).
        """
        if not self.session_active:
            return

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        try:
            # LOGOUT is a command like any other on this API and needs an AD
            # token. Without it the router answers `{"result":"failure"}` and
            # leaves the session open — verified against MC7010 firmware
            # V1.0.0B03 on 2026-07-27: with AD it returns success and the stok
            # is genuinely invalidated; without it, the stok stays live.
            ad = await self.get_ad()
            resp = await self._request(
                "POST",
                "goform/goform_set_cmd_process",
                data=f"isTest=false&goformId=LOGOUT&AD={ad}",
                headers=headers,
                _retry=False,
            )
            # Recorded because a measurement taken after logout is only an
            # *unauthenticated* sample if the logout actually took effect.
            # This method swallows its own errors by design, and the router
            # answers `{"result":"failure"}` on a bad `AD` — so without this
            # flag a refused logout is indistinguishable from a clean one,
            # and a probe would sample a session that is still live.
            self.logout_acknowledged = isinstance(resp, dict) and not self._is_refusal(
                resp
            )
        except Exception as err:  # noqa: BLE001 - unload must never fail
            _LOGGER.debug("Logout request failed (session dropped anyway): %s", err)
        finally:
            self._clear_session(clear_cookies=True)

    def _split_by_url_budget(self, params: list[str]) -> list[list[str]]:
        """Split a `cmd` list into requests that fit the router's URL limit.

        The limit is a **URL length**, not a name count — see
        `docs/zte_how_to_access.md`. A single list had reached 1,795 characters
        against a ceiling of roughly 2,048 on the reference MC7010, and alias
        expansion for other models keeps adding to it: a device that spells a
        concept differently needs both spellings requested, so the list grows
        with every model supported rather than with every feature added.

        `BATCH_URL_BUDGET` is set below the measured ceiling deliberately. The
        ceiling is one device's, and a firmware with a lower one would
        otherwise truncate — which this API signals by returning the response
        short, not by erroring.

        Splitting never changes what a caller gets: the chunks are merged and
        every one is required. See `_batch_get`.
        """
        # Measured from this entry's own address rather than assumed: a
        # hostname is longer than an IP, and the budget is a property of the
        # whole URL.
        overhead = len(self.referer) + len(_BATCH_PATH_PREFIX)
        chunks: list[list[str]] = [[]]
        length = overhead
        for name in params:
            addition = len(name) + 1
            if chunks[-1] and length + addition > BATCH_URL_BUDGET:
                chunks.append([])
                length = overhead
            chunks[-1].append(name)
            length += addition
        return chunks

    async def _batch_get(
        self, params: list[str], *, timeout_sec: int | None = None
    ) -> dict[str, Any]:
        """Read the given `cmd` names, in as many requests as the URL allows.

        **Every chunk is required.** A mandatory batch that tolerated a failed
        chunk would serve half its entities from a partial response and score
        the poll a success — the silent-failure shape this integration has
        closed twice already. Per-chunk tolerance belongs to discovery, which
        is diagnostics-only; here a failure propagates and fails the poll
        exactly as one oversized request would.

        Each chunk carries its own key list into `_classify_session`, so the
        absent-key guard judges a response against what that request actually
        asked for.
        """
        merged: dict[str, Any] = {}
        for chunk in self._split_by_url_budget(params):
            data = await self._request(
                "GET",
                f"{_BATCH_PATH_PREFIX}{','.join(chunk)}",
                timeout_sec=timeout_sec,
                requested=chunk,
            )
            if isinstance(data, dict):
                merged.update(data)
        return merged

    async def get_params(
        self, params: list[str], *, timeout_sec: int | None = None
    ) -> dict[str, Any]:
        """Read a named handful of keys, for confirming a write.

        A round trip to this router costs about the same whatever the payload —
        16 ms median for one key against 30 ms for the full 75-key core batch —
        so this exists for *precision*, not speed: it answers with the state of
        one setting without disturbing, or being disturbed by, the poll cycle.

        Callers must treat a raised exception as *unverified*, never as a failed
        write. The write may well have landed; only a successful read reporting
        the wrong value proves otherwise.

        A **sentinel key is always appended**, and it is not optional. A dead
        session is detected by every value in the response being empty — a rule
        written when every read was a 75-key poll, where something is always
        populated. A targeted read breaks that assumption: `sms_nv_send_total`
        and `sms_nv_total` are legitimately empty on the reference MC7010, so
        reading just those two produced an all-empty response, a spurious
        re-login, and a `ZTEAuthError` on a perfectly healthy session.

        `wan_connect_status` is populated whenever the session is alive — it is
        one of the contract keys the coordinator checks for firmware drift — so
        its presence distinguishes "these fields are empty" from "this session
        is gone". It is left in the returned dict rather than stripped; callers
        read by key and the extra costs nothing.
        """
        request = list(params)
        # Every spelling the device does not answer without a session. One
        # it *does* answer proves nothing — an MC888 Pro returns `ppp_status`
        # on a dead session (issue #56), so appending it unfiltered would make
        # a dead session look alive, which is the opposite of the point.
        #
        # Capped at two. `_batch_get` passes this list into
        # `_classify_session`, whose absent-key guard declines to rule once
        # more than half the request came back missing; appending four
        # spellings to a one-key read, three of them absent, crosses that line
        # and returns `undecidable`.
        unauthenticated = self.unauthenticated_key_set()
        usable = [k for k in _SESSION_SENTINELS if k not in unauthenticated]
        for sentinel in (usable or list(_SESSION_SENTINELS))[:2]:
            if sentinel not in request:
                request.append(sentinel)
        return await self._batch_get(request, timeout_sec=timeout_sec)

    async def get_all_data(self) -> dict[str, Any]:
        """Fetch the mandatory core payload.

        Failure here is a whole-integration failure and belongs on the global
        strike path — everything an enabled-by-default entity needs is in this
        request, as is the device identity latched into `entry.data`.
        """
        return await self._batch_get(_CORE_PARAMS)

    async def get_extended_data(self) -> dict[str, Any]:
        """Fetch the optional diagnostic payload.

        A second request rather than a longer first one: the router bounds a
        GET at roughly 2,048 characters, and one list carrying everything had
        no room left to grow.

        Called through the coordinator's `_fetch_optional`, so a failure holds
        the last known values for three cycles and then marks only the entities
        fed from here unavailable. It must therefore stay free of anything an
        enabled-by-default entity needs.
        """
        return await self._batch_get(_EXTENDED_PARAMS)

    async def get_sms_capacity(self, timeout_sec: int | None = None) -> dict[str, Any]:
        """Get SMS capacity information."""
        path = "goform/goform_get_cmd_process?isTest=false&cmd=sms_capacity_info"
        try:
            data = await self._request("GET", path, timeout_sec=timeout_sec)
            self._require_contract(data, "sms_nv_total", "sms_capacity_info")
            return cast(dict[str, Any], data)
        except (ZTEAuthError, ZTEConnectionError):
            # Named first so the swallow below is the explicit exception rather
            # than the fallthrough. Under the previous `except Exception` plus
            # an isinstance re-raise, a future domain exception outside this
            # pair would silently become {} — the masked-error class this
            # project has already shipped once.
            raise
        except Exception as e:  # noqa: BLE001 - optional endpoint, degrade quietly
            _LOGGER.debug("Failed to get SMS capacity: %s", e)
            return {}

    async def get_last_sms_content(
        self, timeout_sec: int | None = None
    ) -> dict[str, Any]:
        """Get the content of the last received SMS."""
        path = "goform/goform_get_cmd_process"
        payload = {
            "isTest": "false",
            "cmd": "sms_data_total",
            "page": "0",
            "data_per_page": "1",
            "mem_store": "1",
            "tags": "10",
            "order_by": "order by id desc",
        }
        msg_out = {}
        try:
            resp_json = await self._request(
                "POST", path, data=payload, timeout_sec=timeout_sec
            )
            self._require_contract(resp_json, "messages", "sms_data_total")
            messages = resp_json["messages"]
            if messages:
                msg = messages[0]
                msg["content_decoded"] = self._hex_decode(msg.get("content", ""))
                msg["number_decoded"] = self._hex_decode(msg.get("number", ""))
                msg["date_decoded"] = self._parse_date(msg.get("date", ""))
                msg_out = cast(dict[str, Any], msg)
        except (ZTEAuthError, ZTEConnectionError):
            raise
        except (TimeoutError, aiohttp.ClientError) as e:
            _LOGGER.debug("Failed to get last SMS content: %s", e)
        return msg_out

    async def reboot(self) -> int:
        """Execute a device reboot.

        A connection error still propagates, exactly as before. It is tempting
        to swallow it on the theory that the router acknowledges and then
        drops the link — but that is untested speculation, and it cannot be
        told apart from a router that was simply unreachable. Swallowing it
        would report "rebooted" for a router that never received the command,
        reintroducing the silent-success failure this check exists to remove.
        An intact ``{"result":"failure"}`` is a refusal and is raised.
        """
        ad = await self.get_ad()
        payload = f"isTest=false&goformId=REBOOT_DEVICE&AD={ad}"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        res = await self._request(
            "POST", "goform/goform_set_cmd_process", data=payload, headers=headers
        )
        self._require_success(res, "REBOOT_DEVICE")
        return 200

    async def delete_sms(self, msg_id: str) -> int:
        """Delete SMS."""
        ad = await self.get_ad()
        payload = f"isTest=false&goformId=DELETE_SMS&msg_id={msg_id}&AD=" + ad
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        res = await self._request(
            "POST", "goform/goform_set_cmd_process", data=payload, headers=headers
        )
        self._require_success(res, "DELETE_SMS")
        return 200

    async def delete_all(self) -> int:
        """Delete all SMS."""
        payload = {
            "isTest": "false",
            "cmd": "sms_data_total",
            "page": "0",
            "data_per_page": "500",
            "mem_store": "1",
            "tags": "10",
            "order_by": "order by id desc",
        }
        res_code = 200
        try:
            resp_json = await self._request(
                "POST", "goform/goform_get_cmd_process", data=payload
            )
            self._require_contract(resp_json, "messages", "sms_data_total")
            ids = [m["id"] for m in resp_json["messages"]]

            if ids:
                res_code = await self.delete_sms(";".join(ids))
        except (ZTEAuthError, ZTEConnectionError):
            raise
        except (TimeoutError, aiohttp.ClientError) as e:
            _LOGGER.error("Failed to delete all SMS: %s", e)
            raise ZTEConnectionError(f"Failed to delete all SMS: {e}") from e
        return res_code

    async def send_sms(self, number: str, message: str) -> int:
        """Send an SMS message via the router."""
        ad = await self.get_ad()
        # Convert message to hex utf-16-be. This stays UTF-16BE for both
        # encodings — `encode_type` tells the router which DCS to put on the
        # wire and how to count segments, it does not change the format of
        # `MessageBody`, which this API always takes as UTF-16BE hex.
        hex_msg = message.encode("utf-16-be").hex()

        # A message drawn entirely from the GSM 03.38 alphabet fits 160
        # characters per segment; declaring UNICODE unconditionally capped it
        # at 70 and split plain-text messages needlessly.
        encode_type = "GSM7_default" if is_gsm7(message) else "UNICODE"

        # Build sms_time: yy;mm;dd;HH;MM;SS;+0
        now = datetime.now(UTC)
        sms_time = now.strftime("%y;%m;%d;%H;%M;%S;+0")

        # URL-encoded to match the standard ZTE request exactly, rather than
        # relying on aiohttp's dict-form encoding.
        escaped_number = urllib.parse.quote_plus(number)

        payload = (
            f"isTest=false&goformId=SEND_SMS&notCallback=true&Number={escaped_number}"
            f"&MessageBody={hex_msg}&encode_type={encode_type}"
            f"&ID=-1&sms_time={sms_time}&AD={ad}"
        )
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        res = await self._request(
            "POST", "goform/goform_set_cmd_process", data=payload, headers=headers
        )
        self._require_success(res, "SEND_SMS")
        return 200

    async def get_sms_messages(
        self, mem_store: str = "1", tags: str = "10", timeout_sec: int | None = None
    ) -> list[dict[str, Any]]:
        """Get SMS messages from a specific storage bank."""
        path = "goform/goform_get_cmd_process"
        payload = {
            "isTest": "false",
            "cmd": "sms_data_total",
            "page": "0",
            "data_per_page": "500",
            "mem_store": mem_store,
            "tags": tags,
            "order_by": "order by id desc",
        }
        try:
            resp_json = await self._request(
                "POST", path, data=payload, timeout_sec=timeout_sec
            )
            self._require_contract(resp_json, "messages", "sms_data_total")
            messages = resp_json["messages"]
            for msg in messages:
                msg["content_decoded"] = self._hex_decode(msg.get("content", ""))
                msg["number_decoded"] = self._hex_decode(msg.get("number", ""))
                msg["date_decoded"] = self._parse_date(msg.get("date", ""))
            return cast(list[dict[str, Any]], messages)
        except (ZTEAuthError, ZTEConnectionError):
            raise
        except (TimeoutError, aiohttp.ClientError) as e:
            _LOGGER.debug("Failed to get SMS messages: %s", e)
            return []

    async def get_ad(self, timeout_sec: int | None = None) -> str:
        """Get the AD parameter for commands.

        The single choke point every write passes through, which is why the
        session check lives here rather than in each setter.
        """
        await self._ensure_session(timeout_sec=timeout_sec)
        version = await self.get_version(timeout_sec=timeout_sec)
        if not version:
            # Do not return "" and let the caller send a command with an empty
            # token. The router answers `{"result":"failure"}`, which surfaces
            # as "Router rejected REBOOT_DEVICE" — blaming the device for
            # refusing a command it never received, when the truth is that it
            # could not be reached at all. Raising here keeps the two apart,
            # and matches the dead-session sweep's rule: do the thing, or
            # raise; never report a success-shaped result having done nothing.
            raise ZTEConnectionError(
                "Cannot derive the AD token: the router did not return its "
                "firmware version. The command was not sent."
            )
        hash_func = self._ad_hash_func(version)
        a = hash_func(version)
        rd = await self.get_rd(timeout_sec=timeout_sec)
        if not rd:
            # The other half of the check above, missed when it was added.
            # `get_rd` returns "" when the RD key is absent from an otherwise
            # valid response, and hashing that produces a **well-formed but
            # wrong** token: the write goes out, the router refuses it, and the
            # user is told the device rejected a command it never had a chance
            # to accept. Same failure the version check exists to prevent.
            raise ZTEConnectionError(
                "Cannot derive the AD token: the router did not return RD. "
                "The command was not sent."
            )
        return hash_func(a + rd)

    @staticmethod
    def _ad_hash_func(version: str) -> Callable[[str], str]:
        """Return the digest this firmware family uses for `AD`.

        Shared by `get_ad` and the login-time derivation so the two cannot
        drift: a login carrying an `AD` built with the wrong digest would be
        refused exactly like a wrong password, with no way to tell them apart.
        """
        is_new_gen = any(m in version for m in ["MC888", "MC889"])
        return (
            (lambda s: hashlib.sha256(s.encode()).hexdigest().upper())
            if is_new_gen
            # MD5 hash is required by the legacy ZTE router API authentication protocol
            else (lambda s: hashlib.md5(s.encode()).hexdigest())  # noqa: S324
        )

    async def _login_ad(
        self, version: str, timeout_sec: int | None = None
    ) -> str | None:
        """Derive the `AD` token the multi-user login form carries.

        Cannot reuse `get_ad()`, which asserts the session first and reads
        `RD` through the authenticated path — neither is available before a
        login. `LD`, `wa_inner_version` and `RD` are all served without a
        session, confirmed against MC7010 firmware `IRL_H3G_MC7010DV1.0.0B03`
        on 2026-08-30 by computing this token before any session existed.

        Returns `None` rather than raising when `RD` cannot be read. The
        token is one half of a login shape that is itself a best guess, so a
        missing `RD` should let the attempt proceed without it and fall
        through to the alternate form, not fail the login outright.
        """
        path = "goform/goform_get_cmd_process?isTest=false&cmd=RD"
        try:
            data = await self._request(
                "GET", path, timeout_sec=timeout_sec, authenticated=False
            )
        except (ZTEAuthError, ZTEConnectionError) as err:
            _LOGGER.debug("Could not read RD before login: %s", err)
            return None
        rd = cast(str, data.get("RD", ""))
        if not rd:
            return None
        hash_func = self._ad_hash_func(version)
        return hash_func(hash_func(version) + rd)

    async def get_rd(self, timeout_sec: int | None = None) -> str:
        """Get the RD parameter for AD generation."""
        path = "goform/goform_get_cmd_process?isTest=false&cmd=RD"
        try:
            data = await self._request("GET", path, timeout_sec=timeout_sec)
            return cast(str, data.get("RD", ""))
        except (ZTEAuthError, ZTEConnectionError):
            # Named first so the swallow below is the explicit exception rather
            # than the fallthrough. Under the previous `except Exception` plus
            # an isinstance re-raise, a future domain exception outside this
            # pair would silently become "" — the masked-error class this
            # project has already shipped once.
            raise
        except Exception as e:  # noqa: BLE001 - optional endpoint, degrade quietly
            _LOGGER.debug("Failed to get RD: %s", e)
            return ""

    async def set_apn(self, index: int, pdp_type: str) -> dict[str, Any]:
        """Set the default APN profile index and PDP type."""
        ad = await self.get_ad()
        payload = (
            f"isTest=false&goformId=APN_PROC_EX"
            f"&apn_mode=manual&apn_action=set_default&set_default_flag=1"
            f"&pdp_type={pdp_type}&index={index}&AD={ad}"
        )
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        res = await self._request(
            "POST", "goform/goform_set_cmd_process", data=payload, headers=headers
        )
        self._require_success(res, "APN_PROC_EX")
        return cast(dict[str, Any], res)

    @staticmethod
    def _resolve_apn_profile(current: dict[str, Any]) -> tuple[str, str] | None:
        """Work out which stored profile a manual switch should select.

        **`apn_index` is not authoritative while the router is in auto mode.**
        Observed live (2026-07-31): `apn_mode=auto`, `apn_index=5`
        (`open.internet.public`), while the APN actually carrying traffic was
        `3FWA.ie` — profile 6. `apn_index` there is a leftover manual choice,
        not a description of what the router is doing. Building a manual switch
        from it would silently activate a different APN than the one working,
        which is a worse failure than the refusal this method exists to fix.

        The authoritative value is `wan_apn` (the **Network APN** sensor), so
        the active APN is matched against the profiles' APN field first, case
        insensitively — the router reports `3FWA.ie` for a profile storing
        `3fwa.ie`.

        Returns `None` when no profile can be justified, and the caller then
        refuses rather than guessing. That is the honest outcome: in auto mode
        the router uses the network-provided default, which need not exist in
        the manual list at all. It does on the reference device only because a
        matching profile was added there by hand.
        """
        profiles: dict[str, tuple[str, str]] = {}
        by_index: dict[str, tuple[str, str]] = {}
        for slot in range(APN_PROFILE_SLOTS):
            raw = current.get(f"APN_config{slot}")
            if not raw:
                continue
            parts = str(raw).split("($)")
            apn = parts[1] if len(parts) > 1 else ""
            pdp = parts[7] if len(parts) > 7 and parts[7] else "IP"
            by_index[str(slot)] = (str(slot), pdp)
            if apn:
                profiles[apn.strip().lower()] = (str(slot), pdp)

        active = str(current.get("wan_apn") or "").strip().lower()
        if active and active in profiles:
            return profiles[active]

        # Already manual: `apn_index` *is* the active selection, so it can be
        # trusted here even when `wan_apn` is blank — which is what the router
        # reports for the "Default" profile, whose APN field is empty.
        if str(current.get("apn_mode") or "").strip().lower() == "manual":
            index = str(current.get("apn_index") or "").strip()
            if index in by_index:
                return by_index[index]

        return None

    async def set_apn_mode(
        self, mode: str, current: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Set the APN selection mode, sending the form the router requires.

        `APN_PROC_EX` is another all-or-nothing form, and the two directions do
        not need the same one. Measured on MC7010 firmware `V1.0.0B03`
        (2026-07-31) by replaying payloads against the value already set, so
        acceptance could be tested without changing anything:

        - ``apn_mode=manual`` alone — **refused**
        - ``apn_mode=manual&apn_action=set_default&index=N`` — **refused**
        - ``apn_mode=manual&apn_action=set_default`` — **refused**
        - the complete five-field form (``apn_mode``, ``apn_action``,
          ``set_default_flag``, ``pdp_type``, ``index``) — **accepted**, in
          both directions, and verified to actually apply
        - ``apn_mode=auto`` alone — **accepted**

        So this method sent a payload the router refused **for the manual
        direction in every release** — the `APN Selection Mode` select could
        never switch to manual. Switching to *auto* did work, which is why the
        entity never looked completely dead. Choosing an **APN Profile** also
        worked throughout, because `set_apn()` already sends the complete form,
        and that form carries `apn_mode=manual` — so picking a profile flipped
        the mode as a side effect and masked this.

        The complete form is used for both directions whenever the profile
        index is known: it is the only one verified to actually *apply* (the
        mode changed and `wan_apn` followed). The bare form is kept as the
        fallback for `auto` alone, where it is accepted and where no profile
        index is needed to make sense of the request.
        """
        resolved = self._resolve_apn_profile(current or {})

        if resolved is None:
            if mode != "auto":
                raise ZTEConnectionError(
                    "Cannot switch the APN selection mode to manual: the router "
                    "must be told which stored profile to use, and the active "
                    "APN does not correspond to any of them. Choose an APN "
                    "Profile instead — selecting one switches the mode to "
                    "manual and picks the profile in a single step."
                )
            body = f"apn_mode={mode}"
        else:
            index, pdp_type = resolved
            body = (
                f"apn_mode={mode}&apn_action=set_default&set_default_flag=1"
                f"&pdp_type={pdp_type}&index={index}"
            )

        ad = await self.get_ad()
        payload = f"isTest=false&goformId=APN_PROC_EX&{body}&AD={ad}"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        res = await self._request(
            "POST", "goform/goform_set_cmd_process", data=payload, headers=headers
        )
        self._require_success(res, "APN_PROC_EX")
        return cast(dict[str, Any], res)

    async def set_odu_led_switch(self, status: str) -> dict[str, Any]:
        """Set the ODU LED switch status (1 = On, 0 = Off)."""
        ad = await self.get_ad()
        payload = (
            f"isTest=false&goformId=ODU_LED_SWITCH_SET&ODU_led_switch={status}&AD={ad}"
        )
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        res = await self._request(
            "POST", "goform/goform_set_cmd_process", data=payload, headers=headers
        )
        self._require_success(res, "ODU_LED_SWITCH_SET")
        return cast(dict[str, Any], res)

    # Every field `DATA_LIMIT_SETTING` expects, and the response key each is
    # read back from. The router refuses a payload missing any of them.
    DATA_VOLUME_FIELDS: dict[str, tuple[str, ...]] = {
        "data_volume_limit_switch": ("data_volume_limit_switch",),
        # The `flux_` spellings matter more here than on a sensor. This is an
        # all-or-nothing form: the router refuses it outright when a field is
        # missing, and this method raises rather than guessing, so on a device
        # using those spellings the data-limit controls would not degrade —
        # they would be impossible to write at all.
        "data_volume_limit_unit": (
            "data_volume_limit_unit",
            "flux_data_volume_limit_unit",
        ),
        "data_volume_limit_size": (
            "data_volume_limit_size",
            "flux_data_volume_limit_size",
        ),
        "data_volume_alert_percent": (
            "data_volume_alert_percent",
            "flux_data_volume_alert_percent",
        ),
        "wan_auto_clear_flow_data_switch": ("wan_auto_clear_flow_data_switch",),
        "traffic_clear_date": (
            "traffic_clear_date",
            "data_volume_clear_date",
            "data_volume_clear_day",
        ),
    }

    async def set_data_volume_settings(
        self,
        current: dict[str, Any],
        **changes: str,
    ) -> dict[str, Any]:
        """Write the data-volume form, preserving every field not being changed.

        `DATA_LIMIT_SETTING` is **all-or-nothing**. It carries the limit
        switch, the cap and its unit, the alert percentage, the monthly
        auto-reset switch and the billing reset day, and the router answers
        `{"result":"failure"}` for a payload missing any of them — verified on
        MC7010 firmware `V1.0.0B03` (2026-07-29), which also confirmed that the
        omitted fields are left intact rather than blanked.

        So every write is a read-modify-write: `current` supplies the fields
        that are not changing, normally `coordinator.data` from the last
        successful poll.

        Raises rather than guessing when `current` is missing a field. A data
        cap is not something to invent a value for, and sending a partial form
        would simply be refused.
        """
        payload_fields: dict[str, str] = {}
        missing: list[str] = []

        for field, aliases in self.DATA_VOLUME_FIELDS.items():
            if field in changes:
                payload_fields[field] = str(changes[field])
                continue
            value = next(
                (
                    current[key]
                    for key in aliases
                    if key in current and current[key] not in ("", None)
                ),
                None,
            )
            if value is None:
                missing.append(field)
            else:
                payload_fields[field] = str(value)

        if missing:
            raise ZTEConnectionError(
                "Cannot write the data-volume settings: the last poll did not "
                f"supply {', '.join(missing)}. This command replaces the whole "
                "form, so sending it without those fields would be refused by "
                "the router. Refresh and retry."
            )

        unknown = set(changes) - set(self.DATA_VOLUME_FIELDS)
        if unknown:  # pragma: no cover - guards a programming error, not input
            raise ValueError(f"Unknown data-volume field(s): {sorted(unknown)}")

        ad = await self.get_ad()
        body = "&".join(f"{k}={v}" for k, v in payload_fields.items())
        payload = f"isTest=false&goformId=DATA_LIMIT_SETTING&{body}&AD={ad}"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        res = await self._request(
            "POST", "goform/goform_set_cmd_process", data=payload, headers=headers
        )
        self._require_success(res, "DATA_LIMIT_SETTING")
        return cast(dict[str, Any], res)

    async def set_data_limit_switch(
        self, status: str, current: dict[str, Any]
    ) -> dict[str, Any]:
        """Set the data volume limit switch (1 = On, 0 = Off).

        Routes through `set_data_volume_settings` so there is one write path
        for this form rather than two that can drift apart.
        """
        return await self.set_data_volume_settings(
            current, data_volume_limit_switch=status
        )

    async def set_bearer_preference(self, preference: str) -> dict[str, Any]:
        """Set the network bearer preference (e.g. 4G_AND_5G, Only_5G, Only_LTE)."""
        ad = await self.get_ad()
        payload = (
            f"isTest=false&goformId=SET_BEARER_PREFERENCE"
            f"&BearerPreference={preference}&AD={ad}"
        )
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        res = await self._request(
            "POST", "goform/goform_set_cmd_process", data=payload, headers=headers
        )
        self._require_success(res, "SET_BEARER_PREFERENCE")
        return cast(dict[str, Any], res)
