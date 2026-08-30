"""A fake ZTE router at the HTTP layer, for driving real polls in tests.

Every other suite in this project builds the coordinator over a `MagicMock`
standing in for `ZTERouterAPI`. That proves the coordinator handles what the API
object returns, and proves nothing about `api.py`, because none of it runs —
anything the payload *derives* is supplied by the fixture instead of computed.

The seam is `aioclient_mock`, which `pytest-homeassistant-custom-component`
ships and which intercepts `async_get_clientsession`. No dependency is added,
and it is the seam Home Assistant's own suite uses.

Pattern, from `wifi_ssid_monitor`'s worked example:

1. build the component's real API object over the mocked session
2. register the payload for this cycle
3. drive `_async_update_data()`, assigning `coordinator.data` yourself, because
   the coordinator wrapper is not in play when you call it directly
4. repeat with a changed payload for as many cycles as the budget needs

Two things about this router in particular:

**Login turns on a cookie, not a body field.** `_attempt_login` reads
`r.cookies.get("stok")`, so a fake that returns a success-shaped JSON body and
no cookie fails login exactly as a wrong password does. `AiohttpClientMocker`
supports `cookies=`, which is what makes this small.

**The bootstrap is three calls, in order.** `login()` reads `LD` (a per-session
nonce) and `wa_inner_version` unauthenticated, derives the password hash from
both, POSTs the login form, and then issues one more `wa_inner_version` GET to
activate the session. All four are registered here.

Matching is by scheme, host and path, plus the requirement that every query
component in the matcher appears in the request. The two `cmd=`-specific
registrations therefore cannot collide with the batch poll, whose `cmd` is a
single comma-joined string.
"""

from __future__ import annotations

from typing import Any

import aiohttp

HOST = "192.168.0.1"
BASE = f"http://{HOST}/"
GET_URL = f"{BASE}goform/goform_get_cmd_process"
SET_URL = f"{BASE}goform/goform_set_cmd_process"

# A payload that satisfies every `CORE_KEYS` member, so a poll built on it takes
# the success path and establishes the drift baseline. Values are invented, not
# captured: `tests/fixtures/mc7010_observed.json` records which key names the
# MC7010 answers, not what it answered with.
GOOD_PAYLOAD: dict[str, Any] = {
    "network_type": "ENDC",
    "signalbar": "4",
    "realtime_time": "3600",
    "wan_connect_status": "ppp_connected",
    "wa_inner_version": "IRL_H3G_MC7010DV1.0.0B01",
    "model_name": "MC7010",
    "lte_rsrp": "-95",
    "lte_rsrq": "-11",
    "lte_snr": "12",
    "monthly_tx_bytes": "1024",
    "monthly_rx_bytes": "2048",
    # The SMS capacity endpoint asserts `sms_nv_total` through
    # `_require_contract`, so a payload without it degrades that endpoint and
    # muddies every failure this module is trying to isolate. `sms_nv_total` is
    # the bank's **capacity**; the fill is the three counters beside it.
    "sms_nv_total": "100",
    "sms_nv_rev_total": "3",
    "sms_sim_total": "20",
}

# The SMS capacity endpoint answers with its own small set. Serving the whole
# batch payload here instead would be wrong in a way that hides defects: the
# per-endpoint cache would then hold every `CORE_KEYS` member, so a later drift
# poll would find them in the merged data via the cache and never fire.
CAPACITY_PAYLOAD: dict[str, Any] = {
    "sms_nv_total": "100",
    "sms_nv_rev_total": "3",
    "sms_sim_total": "20",
}

# Two payloads that are byte-similar and mean opposite things, which is the
# distinction `_classify_session` exists to draw and the reason both are here.
#
# `expired` — every **authenticated** key blank while an unauthenticated one
# still carries a value. The router is plainly answering, so blankness is the
# session, and re-logging in is the right response.
EXPIRED_SESSION_PAYLOAD: dict[str, Any] = {
    **dict.fromkeys(GOOD_PAYLOAD, ""),
    "wa_inner_version": GOOD_PAYLOAD["wa_inner_version"],
    "model_name": GOOD_PAYLOAD["model_name"],
}

# `not_ready` — everything blank, unauthenticated keys included. The router is
# answering but has nothing to say yet, which is what it does for a while after
# a reboot. Logging in again would not help, and treating it as an expiry would
# burn a re-login and then prompt the user for credentials that are fine.
NOT_READY_PAYLOAD: dict[str, Any] = dict.fromkeys(GOOD_PAYLOAD, "")


class RouterFake:
    """Registers router responses, and can be re-armed between poll cycles."""

    def __init__(self, aioclient_mock: Any) -> None:
        """Take the mocker this fake writes its registrations into."""
        self._mock = aioclient_mock
        self.version = GOOD_PAYLOAD["wa_inner_version"]
        self.ld = "0123456789ABCDEF"

    # ---------------------------------------------------------------- serving

    def serve(
        self,
        payload: dict[str, Any] | None = None,
        *,
        credentials_ok: bool = True,
    ) -> None:
        """Arm the router for one or more cycles.

        Replaces every previous registration, so a test can change what the
        router says between polls — which is the whole point of driving several.
        """
        body = GOOD_PAYLOAD if payload is None else payload
        self._mock.clear_requests()

        # Order matters: the two `cmd=`-specific reads are registered before the
        # catch-all, and the mocker takes the first match.
        self._arm_root()
        self._mock.get(f"{GET_URL}?cmd=LD", json={"LD": self.ld})
        self._mock.get(
            f"{GET_URL}?cmd=wa_inner_version",
            json={"wa_inner_version": self.version},
        )
        self._mock.get(f"{GET_URL}?cmd=sms_capacity_info", json=dict(CAPACITY_PAYLOAD))

        if credentials_ok:
            self._mock.post(SET_URL, json={"result": "success"}, cookies={"stok": "s1"})
        else:
            # No cookie and a classified result: `_attempt_login` reads this as
            # a credentials rejection rather than a transport problem, which is
            # the distinction `ZTECredentialsError` carries.
            self._mock.post(SET_URL, json={"result": "password_error"})

        self._mock.get(GET_URL, json=body)
        # The message list is a POST to the same path. Registered after the
        # login POST, which carries its own URL, so the two cannot collide.
        self._mock.post(GET_URL, json={"messages": []})

    # ----------------------------------------------------------------- faults

    def fault(self, mode: str) -> None:
        """Make the router misbehave in one named way.

        The set covers a router that is not answering at all, one that is
        answering too slowly, one that rejects the credentials, one whose
        session has died, one still starting up, and one that answers with
        something that is not the API.
        """
        self._mock.clear_requests()

        if mode == "unreachable":
            self._arm_bootstrap()
            self._mock.get(GET_URL, exc=aiohttp.ClientError("connection refused"))
        elif mode == "timeout":
            self._arm_bootstrap()
            self._mock.get(GET_URL, exc=TimeoutError("timed out"))
        elif mode == "credentials_rejected":
            # The session has to be gone before a refused password matters —
            # serving a rejection alongside a working session tests nothing,
            # because no login is attempted. The router's "your session is
            # over" answer is its HTML login page, and `_request` responds to
            # that by renewing the session (`api.py:580`). So: HTML on the
            # read, refusal on the login that follows. That ordering is the
            # real sequence a user hits after changing the router's password.
            self.serve(credentials_ok=False)
            self._mock.clear_requests()
            self._arm_root()
            self._mock.get(f"{GET_URL}?cmd=LD", json={"LD": self.ld})
            self._mock.get(
                f"{GET_URL}?cmd=wa_inner_version",
                json={"wa_inner_version": self.version},
            )
            self._mock.post(SET_URL, json={"result": "password_error"})
            self._mock.get(
                GET_URL,
                text="<html><body>Login</body></html>",
                headers={"Content-Type": "text/html"},
            )
            self._mock.post(GET_URL, json={"messages": []})
        elif mode == "expired_session":
            self.serve(EXPIRED_SESSION_PAYLOAD)
        elif mode == "not_ready":
            self.serve(NOT_READY_PAYLOAD)
        elif mode == "contract_drift":
            # A successful poll whose payload carries none of `CORE_KEYS` — the
            # firmware-change signature the health sensor exists to catch.
            self.serve({"renamed_everything": "1"})
        elif mode == "html_page":
            self._arm_bootstrap()
            self._mock.get(
                GET_URL,
                text="<html><body>Login</body></html>",
                headers={"Content-Type": "text/html"},
            )
        else:  # pragma: no cover - a typo in a test, not a runtime path
            raise ValueError(f"unknown fault mode: {mode}")

    def _arm_root(self) -> None:
        """Answer the bare-root probe `try_set_protocol` makes.

        The config flow calls it before logging in, walking `http` then `https`
        and keeping the first that answers under 400. Only the config-flow path
        reaches this; the coordinator uses the `http` default set in
        `__init__`, which is why the poll tests never needed it.
        """
        self._mock.get(BASE.rstrip("/"), text="")

    def _arm_bootstrap(self) -> None:
        """Register the login chain, so a fault lands on the poll not the login."""
        self._arm_root()
        self._mock.get(f"{GET_URL}?cmd=LD", json={"LD": self.ld})
        self._mock.get(
            f"{GET_URL}?cmd=wa_inner_version",
            json={"wa_inner_version": self.version},
        )
        self._mock.post(SET_URL, json={"result": "success"}, cookies={"stok": "s1"})


def real_api(hass: Any) -> Any:
    """Build the real `ZTERouterAPI` over Home Assistant's mocked session."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.zte_router_5g.api import ZTERouterAPI

    return ZTERouterAPI(async_get_clientsession(hass), HOST, "admin", "password")
