"""ZTE Router 5G API client."""

import contextlib
import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

import aiohttp

_LOGGER = logging.getLogger(__name__)


class ZTEConnectionError(Exception):
    """Raised when the router cannot be reached."""


class ZTEAuthError(Exception):
    """Raised when login credentials are rejected."""


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

        # Check if the session is likely expired due to inactivity (e.g. 150 seconds)
        now = datetime.now(UTC)
        if (
            authenticated
            and self.stok
            and (now - self.last_activity).total_seconds() > 150
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
            # Empty strings for status keys mean session expired
            is_status_expired = (
                resp_json.get("network_type") == "" and resp_json.get("signalbar") == ""
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

        payload = {
            "isTest": "false",
            "goformId": "LOGIN"
            if (self.username and not self.is_multi)
            else "LOGIN_MULTI_USER",
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

        if login_error:
            raise ZTEAuthError(login_error)
        if conn_error:
            raise ZTEConnectionError(conn_error)

        if self.stok is None:  # pragma: no cover - defensive; narrows type for mypy
            raise ZTEConnectionError("Failed to obtain stok from login")
        return self.stok

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
            return cast(
                dict[str, Any],
                await self._request("GET", path, timeout_sec=timeout_sec),
            )
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
            messages = resp_json.get("messages", [])
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
        """Execute a device reboot."""
        ad = await self.get_ad()
        payload = f"isTest=false&goformId=REBOOT_DEVICE&AD={ad}"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        await self._request(
            "POST", "goform/goform_set_cmd_process", data=payload, headers=headers
        )
        return 200

    async def delete_sms(self, msg_id: str) -> int:
        """Delete SMS."""
        ad = await self.get_ad()
        payload = f"isTest=false&goformId=DELETE_SMS&msg_id={msg_id}&AD=" + ad
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        await self._request(
            "POST", "goform/goform_set_cmd_process", data=payload, headers=headers
        )
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
            ids = [m["id"] for m in resp_json.get("messages", [])]

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
        # Convert message to hex utf-16-be
        hex_msg = message.encode("utf-16-be").hex()

        # Build sms_time: yy;mm;dd;HH;MM;SS;+0
        now = datetime.now(UTC)
        sms_time = now.strftime("%y;%m;%d;%H;%M;%S;+0")

        # URL encode is handled by aiohttp when using dict data,
        # but to keep it safe and exactly matched with standard ZTE request:
        import urllib.parse

        escaped_number = urllib.parse.quote_plus(number)

        payload = (
            f"isTest=false&goformId=SEND_SMS&notCallback=true&Number={escaped_number}"
            f"&MessageBody={hex_msg}&encode_type=UNICODE&ID=-1&sms_time={sms_time}&AD={ad}"
        )
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        await self._request(
            "POST", "goform/goform_set_cmd_process", data=payload, headers=headers
        )
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
            messages = resp_json.get("messages", [])
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
        return cast(dict[str, Any], res)
