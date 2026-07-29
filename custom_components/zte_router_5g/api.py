"""ZTE Router 5G API client."""

import contextlib
import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, NamedTuple, cast

import aiohttp

from .const import SESSION_IDLE_RESET_SECONDS
from .helpers import is_gsm7

_LOGGER = logging.getLogger(__name__)


class ZTEConnectionError(Exception):
    """Raised when the router cannot be reached."""


class ZTEAuthError(Exception):
    """Raised when login credentials are rejected."""


class _LoginAttempt(NamedTuple):
    """Outcome of posting one login form.

    Exactly one of the three is set. `stok` carries the session rather than
    the caller re-reading `self.stok`, so which attempt produced it stays
    explicit when two forms are tried.
    """

    stok: str | None
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
        self.stok: str | None = None
        self.is_multi = True
        self.last_activity = datetime.fromtimestamp(0, UTC)

    def _hash(self, val: str | None) -> str:
        if val is None:
            raise ValueError("Input to hash function cannot be None")
        # ZTE challenge-response auth requires SHA256 — not password storage.
        # lgtm[py/weak-cryptographic-algorithm]
        return hashlib.sha256(val.encode()).hexdigest()

    def _hex_decode(self, hex_str: str) -> str:
        if not hex_str:
            return ""
        decoded = ""
        try:
            for i in range(0, len(hex_str), 4):
                decoded += chr(int(hex_str[i : i + 4], 16))
        except (ValueError, IndexError):
            _LOGGER.debug("Failed to decode hex string '%s'", hex_str)
            return "[Decoding Error]"
        return decoded

    def _require_contract(self, data: Any, key: str, cmd: str) -> None:
        """Fail loudly when a response is missing the key it must carry.

        Second line of defence behind the expiry detection in ``_request``.
        That detection recognises the router's dead-session shape as observed
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
        if not isinstance(data, dict):
            return
        result = data.get("result")
        if result is None:
            return
        if str(result).lower() not in ("success", "0", "ok"):
            raise ZTEConnectionError(
                f"Router rejected {cmd}: result={result!r}. The command was not "
                f"carried out — this API answers 200 OK for a refused write."
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
        params: dict[str, Any] | None = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        timeout_sec: int | None = None,
        authenticated: bool = True,
        _retry: bool = True,
    ) -> Any:
        """Centralized request helper that handles session creation and auto-renewal."""
        tout = aiohttp.ClientTimeout(total=timeout_sec) if timeout_sec else self.timeout

        # Preempt an idle-expired session rather than discovering it on failure.
        now = datetime.now(UTC)
        if (
            authenticated
            and self.stok
            and (now - self.last_activity).total_seconds() > SESSION_IDLE_RESET_SECONDS
        ):
            _LOGGER.debug("Session likely expired due to inactivity; resetting stok")
            self.stok = None

        if authenticated and not self.stok:
            self.stok = await self.login(timeout_sec=timeout_sec)

        url = f"{self.referer}{path}"
        req_headers = {"Referer": f"{self.referer}index.html"}
        if headers:
            req_headers.update(headers)
        if authenticated and self.stok:
            req_headers["Cookie"] = self.stok

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
        except (TimeoutError, aiohttp.ClientError) as e:
            if authenticated:
                self.stok = None
            raise ZTEConnectionError(f"Request failed: {e}") from e

        # Validate parsed response and handle redirects/HTML
        if is_html_page:
            if authenticated and _retry:
                _LOGGER.debug("Detected HTML redirect/response; renewing session")
                self.stok = await self.login(timeout_sec=timeout_sec)
                return await self._request(
                    method,
                    path,
                    params,
                    data,
                    headers,
                    timeout_sec,
                    authenticated,
                    _retry=False,
                )
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
                self.stok = await self.login(timeout_sec=timeout_sec)
                return await self._request(
                    method,
                    path,
                    params,
                    data,
                    headers,
                    timeout_sec,
                    authenticated,
                    _retry=False,
                )
            raise ZTEConnectionError("Failed to parse JSON response from router")

        # 3. Check JSON structure for session expiry/invalid indicators
        if isinstance(resp_json, dict):
            # A dead session answers HTTP 200 with the *requested keys echoed
            # back empty* — never an error, never a redirect. Captured from an
            # MC7010 on firmware V1.0.0B03 (2026-07-27) by replaying an
            # invalidated stok:
            #
            #   batch poll  -> {"network_type":"","signalbar":"","wan_ipaddr":""}
            #   SMS list    -> {"sms_data_total":""}
            #   SMS capacity-> {"sms_capacity_info":""}
            #
            # The rule is "every value is an empty string", not "these two named
            # keys are empty". The old form only knew the batch-poll keys, so it
            # could never fire on an SMS response: `.get("network_type")` is
            # None there, and `None == ""` is False. The SMS action therefore
            # returned an empty list on an expired session while Refresh Now
            # (which runs the batch poll) recovered it — the exact asymmetry
            # reported. Do not narrow this back to named keys.
            is_status_expired = bool(resp_json) and all(
                value == "" for value in resp_json.values()
            )
            # Other endpoints might return explicit error indications
            is_auth_error = (
                resp_json.get("result") in ["session expired", "unauth", "fail"]
                or resp_json.get("status") == "fail"
            )

            if (is_status_expired or is_auth_error) and authenticated:
                if _retry:
                    _LOGGER.debug("Session expired in JSON response; renewing session")
                    self.stok = await self.login(timeout_sec=timeout_sec)
                    return await self._request(
                        method,
                        path,
                        params,
                        data,
                        headers,
                        timeout_sec,
                        authenticated,
                        _retry=False,
                    )
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

    async def login(self, timeout_sec: int | None = None) -> str:
        """Clean login that resets the internal session state."""
        tout = timeout_sec or 15
        self.stok = None
        self.session.cookie_jar.clear(predicate=lambda m: m.key == "stok")

        ld = await self.get_ld(timeout_sec=tout)
        version = await self.get_version(timeout_sec=tout)

        if not self.password:
            raise ZTEAuthError("No password provided")
        pass_hash = self._hash(self.password).upper()
        zte_pass = self._hash(pass_hash + ld).upper()

        self.is_multi = True
        if version and any(m in version for m in ["MC801", "MC7010"]):
            self.is_multi = False

        primary = (
            "LOGIN" if (self.username and not self.is_multi) else "LOGIN_MULTI_USER"
        )
        attempt = await self._attempt_login(primary, zte_pass, tout)

        # Best-effort form fallback for models this integration has never seen.
        # Which form a goform router accepts is a per-model quirk and the model
        # list above only covers the ones that have been tested, so an unlisted
        # router can be rejected purely for using the wrong goformId. Only the
        # unclassified failure is worth retrying: a credentials rejection means
        # the password is wrong whichever form carries it, and retrying would
        # just burn a second attempt against routers that lock out.
        if attempt.stok is None and attempt.auth_error is None:
            fallback = "LOGIN_MULTI_USER" if primary == "LOGIN" else "LOGIN"
            _LOGGER.debug(
                "Login form %s did not yield a session; retrying once with %s",
                primary,
                fallback,
            )
            retry = await self._attempt_login(fallback, zte_pass, tout)
            if retry.stok is not None:
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
            raise ZTEAuthError(attempt.auth_error)
        if attempt.conn_error:
            raise ZTEConnectionError(attempt.conn_error)

        if attempt.stok is None:  # pragma: no cover - defensive, narrows for mypy
            raise ZTEConnectionError("Failed to obtain stok from login")
        return attempt.stok

    async def _attempt_login(
        self, goform_id: str, zte_pass: str, tout: int
    ) -> _LoginAttempt:
        """Post one login form, setting `self.stok` on success.

        Genuine transport failures raise `ZTEConnectionError` directly rather
        than being reported in the result, because there is no point retrying
        a different form against a router that is not answering at all.
        """
        payload = {
            "isTest": "false",
            "goformId": goform_id,
            "password": zte_pass,
        }
        if self.username:
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
                stok = r.cookies.get("stok")
                if not stok:
                    # Check body to classify if it is credentials rejection
                    result = None
                    try:
                        resp_json = await r.json(content_type=None)
                        result = resp_json.get("result")
                    except (ValueError, TypeError, aiohttp.ContentTypeError):
                        pass

                    if result in [
                        "password_error",
                        "invalid_password",
                        "write_error",
                        "unauth",
                    ]:
                        login_error = (
                            f"Login failed due to invalid credentials: {result}"
                        )
                    else:
                        _LOGGER.warning(
                            "Login failed: missing stok (Status: %s, Result: %s). "
                            "Treating as connection issue.",
                            r.status,
                            result,
                        )
                        conn_error = f"Failed to obtain stok from login: {result}"
                else:
                    self.stok = f"stok={stok.value.strip('"')}"

                    # Initialize session with a GET request to satisfy POST
                    # restrictions on some ZTE routers
                    init_url = f"{self.referer}goform/goform_get_cmd_process"
                    init_params = {"isTest": "false", "cmd": "wa_inner_version"}
                    init_headers = {
                        "Referer": f"{self.referer}index.html",
                        "Cookie": self.stok,
                    }
                    try:
                        async with self.session.get(
                            init_url,
                            params=init_params,
                            headers=init_headers,
                            timeout=aiohttp.ClientTimeout(total=tout),
                            ssl=False,
                        ) as init_r:
                            await init_r.read()
                    except (TimeoutError, aiohttp.ClientError) as init_err:
                        _LOGGER.debug("Session initialization GET failed: %s", init_err)

                    self.last_activity = datetime.now(UTC)
        except (TimeoutError, aiohttp.ClientError) as e:
            raise ZTEConnectionError(
                f"Login failed due to connection error: {e}"
            ) from e

        return _LoginAttempt(self.stok, login_error, conn_error)

    async def logout(self) -> None:
        """End the router session and drop local session state.

        Best effort by design: this runs on unload, and an unreachable router
        must never block Home Assistant from tearing the entry down. Local
        state is cleared regardless of whether the router acknowledged.

        It matters more here than on most hardware — a ZTE CPE permits only one
        login session at a time, so an abandoned session locks the user out of
        the router's own web UI until it times out (dev_standards Section 10).
        """
        if not self.stok:
            return

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        try:
            # LOGOUT is a command like any other on this API and needs an AD
            # token. Without it the router answers `{"result":"failure"}` and
            # leaves the session open — verified against MC7010 firmware
            # V1.0.0B03 on 2026-07-27: with AD it returns success and the stok
            # is genuinely invalidated; without it, the stok stays live.
            ad = await self.get_ad()
            await self._request(
                "POST",
                "goform/goform_set_cmd_process",
                data=f"isTest=false&goformId=LOGOUT&AD={ad}",
                headers=headers,
                _retry=False,
            )
        except Exception as err:  # noqa: BLE001 - unload must never fail
            _LOGGER.debug("Logout request failed (session dropped anyway): %s", err)
        finally:
            self.stok = None
            self.session.cookie_jar.clear(predicate=lambda m: m.key == "stok")

    async def get_all_data(self) -> dict[str, Any]:
        """Fetch primary technical data."""
        params = [
            "cell_id",
            "lan_ipaddr",
            "lte_ca_pcell_band",
            "lte_ca_pcell_bandwidth",
            "lte_ca_scell_band",
            "lte_ca_scell_bandwidth",
            "lte_pci",
            "lte_rsrp",
            "lte_rsrq",
            "lte_rssi",
            "lte_snr",
            "mdm_mcc",
            "mdm_mnc",
            "monthly_rx_bytes",
            "monthly_tx_bytes",
            "network_provider",
            "network_type",
            "nr5g_action_band",
            "nr5g_action_channel",
            "nr5g_pci",
            "realtime_time",
            "rmcc",
            "rmnc",
            "signalbar",
            "wan_active_band",
            "wan_active_channel",
            "wan_apn",
            "wan_connect_status",
            "wan_ipaddr",
            "wan_lte_ca",
            "wa_inner_version",
            "Z5g_rsrp",
            "Z5g_SINR",
            "Z5g_rsrq",
            "Z5g_rssi",
            "model_name",
            "rssi",
            "rscp",
            "imei",
            "hardware_version",
            "battery_value",
            "sim_imsi",
            "sim_iccid",
            "enodeb_id",
            "net_select",
            "ppp_status",
            "realtime_tx_thrpt",
            "realtime_rx_thrpt",
            "realtime_tx_bytes",
            "realtime_rx_bytes",
            "sms_unread_num",
            "sms_received_flag",
            "sms_nv_rev_total",
            "sms_nv_send_total",
            "sms_nv_draftbox_total",
            "sms_sim_rev_total",
            "sms_sim_send_total",
            "sms_sim_draftbox_total",
            "sms_nv_total",
            "sms_sim_total",
            "apn_index",
            "apn_mode",
            "apn_interface_version",
            "ipv6_apn_index",
            "APN_config0",
            "APN_config1",
            "APN_config2",
            "APN_config3",
            "APN_config4",
            "APN_config5",
            "APN_config6",
            "APN_config7",
            "APN_config8",
            "APN_config9",
            "APN_config10",
            "APN_config11",
            "APN_config12",
            "APN_config13",
            "APN_config14",
            "APN_config15",
            "APN_config16",
            "APN_config17",
            "APN_config18",
            "APN_config19",
            "ODU_led_switch",
            "ODU_led_off_time",
            "data_volume_limit_switch",
            "data_volume_alert_percent",
            "reboot_schedule_enable",
            "reboot_hour1",
            "reboot_min1",
            "reboot_hour2",
            "reboot_min2",
            "lte_band_lock",
            "net_select_mode",
            "sntp_server0",
            "sntp_server1",
            "sntp_dst_enable",
            "upnpEnabled",
            "alg_sip_enable",
            # Billing-cycle keys. `traffic_clear_date` is the spelling a live
            # MC7010 probe answered on (see
            # `.notes/info/zte_element_discovery_report.md`); the two
            # `data_volume_*` spellings come from a separate analysis and are
            # carried as aliases for other goform models. See `_ALIAS_CLEAR_DAY`
            # in `sensor.py`. `wan_auto_clear_flow_data_switch` is the master
            # switch for the monthly reset — with it off the counters never
            # roll over, so anything reasoning about a cycle must consult it.
            "traffic_clear_date",
            "data_volume_clear_date",
            "data_volume_clear_day",
            "wan_auto_clear_flow_data_switch",
            # Web UI power management.
            "web_sleep_switch",
            "web_wake_switch",
            # Reboot schedule detail. `reboot_schedule_enable` and the hour /
            # minute pair are requested above; these three say which day the
            # schedule fires on and how to read it.
            "reboot_schedule_mode",
            "reboot_dow",
            "reboot_dod",
            # Time configuration beyond the two servers requested above.
            "sntp_server2",
            "sntp_timezone",
            # Raw secondary-cell aggregation descriptor and operational mode.
            "lte_multi_ca_scell_info",
            "opms_wan_mode",
            "opms_wan_auto_mode",
            # Cross-model keys. Every one of these is an alternative spelling
            # used by some other member of the goform family, or optional
            # telemetry the MC7010 does not populate. Requesting a key the
            # router does not know is safe: it is simply absent from the
            # response rather than an error, and an absent key cannot trip the
            # "every value is an empty string" expired-session rule in
            # `_request`. Keep this block in step with the alias tuples in
            # `sensor.py` — an alias naming a key that is never requested can
            # never fire.
            "5g_rsrp",
            "nr5g_rsrp",
            "5g_sinr",
            "nr5g_sinr",
            "Z5g_snr",
            "Z5g_CELL_ID",
            "flux_monthly_tx_bytes",
            "flux_monthly_rx_bytes",
            "pm_sensor_pa1",
            "pm_sensor_ambient",
            "pm_sensor_mdm",
            "pm_modem_5g",
            "pm_sensor_5g",
        ]
        cmd = ",".join(params)
        path = (
            "goform/goform_get_cmd_process?multi_data=1&isTest=false"
            f"&sms_received_flag_flag=0&cmd={cmd}"
        )
        data = await self._request("GET", path)
        return cast(dict[str, Any], data)

    async def get_sms_capacity(self, timeout_sec: int | None = None) -> dict[str, Any]:
        """Get SMS capacity information."""
        path = "goform/goform_get_cmd_process?isTest=false&cmd=sms_capacity_info"
        try:
            data = await self._request("GET", path, timeout_sec=timeout_sec)
            self._require_contract(data, "sms_nv_total", "sms_capacity_info")
            return cast(dict[str, Any], data)
        except Exception as e:
            if isinstance(e, (ZTEAuthError, ZTEConnectionError)):
                raise
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

        # URL encode is handled by aiohttp when using dict data,
        # but to keep it safe and exactly matched with standard ZTE request:
        import urllib.parse

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
        """Get the AD parameter for commands."""
        version = await self.get_version(timeout_sec=timeout_sec)
        if not version:
            return ""
        is_new_gen = any(m in version for m in ["MC888", "MC889"])
        hash_func: Callable[[str], str] = (
            (lambda s: hashlib.sha256(s.encode()).hexdigest().upper())
            if is_new_gen
            # MD5 hash is required by the legacy ZTE router API authentication protocol
            else (lambda s: hashlib.md5(s.encode()).hexdigest())  # noqa: S324
        )
        a = hash_func(version)
        rd = await self.get_rd(timeout_sec=timeout_sec)
        return hash_func(a + rd)

    async def get_rd(self, timeout_sec: int | None = None) -> str:
        """Get the RD parameter for AD generation."""
        path = "goform/goform_get_cmd_process?isTest=false&cmd=RD"
        try:
            data = await self._request("GET", path, timeout_sec=timeout_sec)
            return cast(str, data.get("RD", ""))
        except Exception as e:
            if isinstance(e, (ZTEAuthError, ZTEConnectionError)):
                raise
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

    async def set_apn_mode(self, mode: str) -> dict[str, Any]:
        """Set the APN selection mode (auto or manual)."""
        ad = await self.get_ad()
        payload = f"isTest=false&goformId=APN_PROC_EX&apn_mode={mode}&AD={ad}"
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

    async def set_data_limit_switch(self, status: str) -> dict[str, Any]:
        """Set the data volume limit switch (1 = On, 0 = Off)."""
        ad = await self.get_ad()
        payload = (
            f"isTest=false&goformId=DATA_LIMIT_SETTING"
            f"&data_volume_limit_switch={status}&AD={ad}"
        )
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        res = await self._request(
            "POST", "goform/goform_set_cmd_process", data=payload, headers=headers
        )
        self._require_success(res, "DATA_LIMIT_SETTING")
        return cast(dict[str, Any], res)

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
