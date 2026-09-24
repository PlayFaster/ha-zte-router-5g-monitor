"""The 3.4.3-dev2 write path: a login before every write, one rebuilt retry.

Measured on an MC7010 on 2026-09-24. After a login from another device took
the session, `loginfo` answered `ok` for several seconds and writes sent on the
old session were refused. A fresh login before each write prevented every
refusal in the phone runs, and a refused write rebuilt with a fresh token was
accepted 20 times in 20, where resending the old payload was accepted 7 in 17.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.zte_router_5g.api import (
    RETRIED_ON_REFUSAL,
    ZTEConnectionError,
    ZTERouterAPI,
    ZTERouterExpectedUnavailableError,
    ZTEWriteRefusedError,
)


def _api() -> ZTERouterAPI:
    return ZTERouterAPI(AsyncMock(), "192.168.0.1", "admin", "password")


# ---------------------------------------------------------------------------
# A login before every write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_write_logs_in_first(real_prewrite_login) -> None:
    """`ad_suffix` is the one place every write passes; it logs in there."""
    api = _api()
    with (
        patch.object(api, "login", new=AsyncMock()) as login,
        patch.object(api, "get_ad", new=AsyncMock(return_value="tok")),
    ):
        assert await api.ad_suffix("ODU_LED_SWITCH_SET") == "&AD=tok"

    login.assert_awaited_once()


@pytest.mark.asyncio
async def test_logout_does_not_log_in_first(real_prewrite_login) -> None:
    """A login before `LOGOUT` would end the session it had just made."""
    api = _api()
    with (
        patch.object(api, "login", new=AsyncMock()) as login,
        patch.object(api, "get_ad", new=AsyncMock(return_value="tok")),
    ):
        await api.ad_suffix("LOGOUT")

    login.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failed_login_does_not_stop_the_write(real_prewrite_login) -> None:
    """The write then reports its own outcome, which names the real cause."""
    api = _api()
    with (
        patch.object(api, "login", new=AsyncMock(side_effect=ZTEConnectionError("x"))),
        patch.object(api, "get_ad", new=AsyncMock(return_value="tok")),
    ):
        assert await api.ad_suffix("ODU_LED_SWITCH_SET") == "&AD=tok"


@pytest.mark.asyncio
async def test_logins_never_overlap() -> None:
    """Two logins at once had one refused with result `3` in every pair."""
    api = _api()
    running = 0
    peak = 0

    async def slow_login(timeout_sec=None) -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1

    with patch.object(api, "_login_unlocked", side_effect=slow_login) as inner:
        await asyncio.gather(api.login(), api.login(), api.login())

    assert inner.await_count == 3, "each caller still makes its own login"
    assert peak == 1


# ---------------------------------------------------------------------------
# One rebuilt retry, and only where a second send is harmless
# ---------------------------------------------------------------------------


def test_only_complete_state_writes_are_retried() -> None:
    """A resent `SEND_SMS` can deliver twice; delete re-lists; reboot retries itself."""
    assert {
        "set_data_connection",
        "set_apn",
        "set_apn_mode",
        "set_odu_led_switch",
        "set_data_volume_settings",
        "set_bearer_preference",
    } == RETRIED_ON_REFUSAL
    for never in ("send_sms", "delete_sms", "delete_all", "reboot", "logout"):
        assert never not in RETRIED_ON_REFUSAL


def test_a_refusal_is_a_connection_error() -> None:
    """Every existing handler of `ZTEConnectionError` still catches a refusal."""
    assert issubclass(ZTEWriteRefusedError, ZTEConnectionError)


@pytest.mark.asyncio
async def test_a_refusal_then_success_is_counted() -> None:
    """The second send is counted, and so is its success."""
    api = _api()
    with (
        patch.object(
            api,
            "ad_suffix",
            new=AsyncMock(return_value=""),
        ),
        patch.object(
            api,
            "_request",
            new=AsyncMock(side_effect=[{"result": "failure"}, {"result": "success"}]),
        ) as request,
        patch.object(api, "note_write_refusal", new=AsyncMock()),
    ):
        await api.set_odu_led_switch("1")

    assert request.await_count == 2
    assert api.session_check_stats["write_retries"] == 1
    assert api.session_check_stats["write_retries_succeeded"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        ZTEConnectionError("Request failed: timed out"),
        ZTERouterExpectedUnavailableError("data_disconnect", 20),
    ],
    ids=["timeout", "outage_window"],
)
async def test_only_an_explicit_refusal_is_retried(error: Exception) -> None:
    """After a timeout the write may have landed; in an outage nothing was sent."""
    api = _api()
    with (
        patch.object(api, "ad_suffix", new=AsyncMock(return_value="")),
        patch.object(api, "_request", new=AsyncMock(side_effect=error)) as request,
        pytest.raises(type(error)),
    ):
        await api.set_odu_led_switch("1")

    assert request.await_count == 1
    assert api.session_check_stats["write_retries"] == 0


@pytest.mark.asyncio
async def test_a_refused_send_is_never_resent() -> None:
    """The one write where a second send has a visible cost."""
    api = _api()
    with (
        patch.object(api, "ad_suffix", new=AsyncMock(return_value="")),
        patch.object(api, "_require_confirmed_session"),
        patch.object(
            api, "_sms_counters", new=AsyncMock(return_value=None), create=True
        ),
        patch.object(
            api, "_request", new=AsyncMock(return_value={"result": "failure"})
        ) as request,
        patch.object(api, "note_write_refusal", new=AsyncMock()),
        pytest.raises(ZTEConnectionError),
    ):
        await api.send_sms("+440000000000", "hello")

    posts = [c for c in request.await_args_list if c.args and c.args[0] == "POST"]
    assert len(posts) == 1
    assert api.session_check_stats["write_retries"] == 0
