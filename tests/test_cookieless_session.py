"""Sessions the router does not carry in a `stok` cookie.

Issue #56: an MC888 Pro on `CR_ABPLMC888PROV1.0.1B04` answers a successful
`LOGIN` with `{"result":"0"}` and no `Set-Cookie` at all, binding the session
to the client address instead. Testing the cookie alone scored that success as
a connection failure and reported it to the user as an unreachable router.

The reference MC7010 does issue a cookie, so nothing here can be observed on
hardware. Two of these tests are not about the MC888 Pro at all: they hold the
constraints that keep the change safe on the router that already works —
that the session cookie and the session flag always move together, and that a
token left in the jar by an earlier session is never adopted as a new one.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import aiohttp
import pytest
from multidict import CIMultiDict

from custom_components.zte_router_5g.api import (
    _CORE_PARAMS,
    ZTEConnectionError,
    ZTECredentialsError,
    ZTERouterAPI,
)

from .conftest import MockResponse, scripted


def _stok_cookie(value="test_stok"):
    """Build a mock stok cookie as aiohttp would expose it."""
    cookie = MagicMock()
    cookie.value = value
    return cookie


def _bootstrap(client, version="MC888_V1", *, extra_gets=1, username=False):
    """Queue the reads every login makes before it posts.

    A configured username adds an `RD` read: the multi-user form carries an
    `AD` token derived from it, and that derivation runs before the first
    attempt so the fallback can reuse it.
    """
    client.get.side_effect = [
        MockResponse(json_data={"LD": "LD"}),
        MockResponse(json_data={"wa_inner_version": version}),
        *([MockResponse(json_data={"RD": "RD"})] if username else []),
        *[
            MockResponse(json_data={"wa_inner_version": version})
            for _ in range(extra_gets)
        ],
    ]


@pytest.mark.asyncio
async def test_a_success_result_without_a_cookie_establishes_a_session(
    mock_aiohttp_client,
):
    """`{"result":"0"}` and no Set-Cookie is a login, not a connection fault."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", None, "password")
    _bootstrap(mock_aiohttp_client)
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "0"}, cookies={}
    )

    await api.login()

    assert api.session_active
    assert not api.cookies


@pytest.mark.asyncio
async def test_a_cookieless_session_sends_no_cookie_header_and_logs_in_once(
    mock_aiohttp_client,
):
    """The absent cookie must not read as "not logged in" on every request.

    Gating the re-login on the cookie rather than on the session flag would
    have this router authenticate before every single call and never settle.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", None, "password")
    _bootstrap(mock_aiohttp_client, extra_gets=3)
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "0"}, cookies={}
    )

    await api.login()
    logins_after_setup = mock_aiohttp_client.post.call_count

    mock_aiohttp_client.get.side_effect = None
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"network_type": "LTE", "signalbar": "4"}
    )
    await api.get_all_data()

    assert mock_aiohttp_client.post.call_count == logins_after_setup
    _args, kwargs = mock_aiohttp_client.get.call_args
    assert "Cookie" not in kwargs["headers"]


@pytest.mark.asyncio
async def test_a_response_with_neither_cookie_nor_success_is_a_connection_error(
    mock_aiohttp_client,
):
    """Relaxing the cookie test must not make every reply a login."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", None, "password")
    _bootstrap(mock_aiohttp_client)
    mock_aiohttp_client.post.return_value = MockResponse(json_data={}, cookies={})

    with pytest.raises(ZTEConnectionError):
        await api.login()


@pytest.mark.asyncio
async def test_a_credentials_rejection_without_a_cookie_is_still_an_auth_error(
    mock_aiohttp_client,
):
    """The rejection classification is unchanged by the cookieless path."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", None, "password")
    _bootstrap(mock_aiohttp_client)
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "password_error"}, cookies={}
    )

    with pytest.raises(ZTECredentialsError, match="invalid credentials"):
        await api.login()


@pytest.mark.asyncio
async def test_a_cookie_only_in_a_raw_header_is_captured(mock_aiohttp_client):
    """`SimpleCookie` drops a header it cannot parse, without raising.

    A cookie that exists but is not found is worse than none: the session is
    replayed without it, the router answers as it does to any anonymous
    client, and every entity publishes `unknown`. The name is kept exactly as
    the router spelled it.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", None, "password")
    _bootstrap(mock_aiohttp_client)
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "0"},
        cookies={},
        headers={"Set-Cookie": "STOK=upper_case_name; Path=/"},
    )

    await api.login()

    assert api.cookies == {"STOK": "upper_case_name"}


@pytest.mark.asyncio
async def test_the_cookie_jar_is_not_consulted(mock_aiohttp_client, monkeypatch):
    """A jar entry must not become this session's cookie.

    The jar was read for a token set on an intermediate `302`. That branch
    could never fire in the configuration it was written for: Home Assistant's
    shared client session carries aiohttp's default `CookieJar`, which refuses
    cookies from an IP-address host. Reading it also risked adopting a cookie
    the login response never set, which is the defect this project has shipped
    once — an invalidated token replayed against a live poll.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", None, "password")
    _bootstrap(mock_aiohttp_client)
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "0"}, cookies={}
    )

    jar_cookie = MagicMock()
    jar_cookie.key = "stok"
    jar_cookie.value = "from_the_jar"
    monkeypatch.setattr(
        type(mock_aiohttp_client.cookie_jar),
        "__iter__",
        lambda _self: iter([jar_cookie]),
        raising=False,
    )

    await api.login()

    assert api.cookies == {}
    assert api.session_active


@pytest.mark.asyncio
async def test_a_stok_returned_in_the_body_is_captured(mock_aiohttp_client):
    """Some firmware answers the token in the JSON rather than as a cookie.

    Read from the body that was already parsed for `result`, so this costs
    no additional request.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", None, "password")
    _bootstrap(mock_aiohttp_client)
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "0", "stok": "from_body"}, cookies={}
    )

    await api.login()

    assert api.cookies == {"stok": "from_body"}


@pytest.mark.asyncio
async def test_a_stale_token_in_the_jar_is_not_adopted(mock_aiohttp_client):
    """A cookie from the session just ended must never become the new one.

    Replaying an invalidated `stok` is a defect this integration has shipped
    once: three core keys and two extended keys answer without a session, so
    the poll scored a clean success while every entity published `unknown`.
    `login()` empties the jar before posting, which is what makes the jar
    lookup above safe — this test is what holds that ordering in place.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", None, "password")
    _bootstrap(mock_aiohttp_client)
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "0"}, cookies={}
    )

    stale = MagicMock()
    stale.key = "stok"
    stale.value = "stale_from_last_session"
    jar = mock_aiohttp_client.cookie_jar
    contents = [stale]

    def _clear(predicate=None):
        contents.clear()

    jar.clear = _clear
    type(jar).__iter__ = lambda _self: iter(contents)

    await api.login()

    assert api.cookies != {"stok": "stale_from_last_session"}
    assert api.session_active


@pytest.mark.asyncio
async def test_no_username_sends_the_single_user_form_first(mock_aiohttp_client):
    """The multi-user form has no user field to carry, so it cannot succeed.

    `Kajkac/ZTE-MC-Home-assistant-repo` branches on the username alone and
    sends `LOGIN` here first and only. Sending `LOGIN_MULTI_USER` first cost
    an attempt that could only be rejected, and logged a warning for it.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", None, "password")
    _bootstrap(mock_aiohttp_client)
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "0"}, cookies={}
    )

    await api.login()

    assert mock_aiohttp_client.post.call_count == 1
    _args, kwargs = mock_aiohttp_client.post.call_args
    assert kwargs["data"]["goformId"] == "LOGIN"
    assert "username" not in kwargs["data"]


@pytest.mark.asyncio
async def test_a_username_on_an_unlisted_model_still_sends_the_multi_user_form(
    mock_aiohttp_client,
):
    """The username branch is unchanged: only the no-username case moved."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    _bootstrap(mock_aiohttp_client, username=True)
    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": _stok_cookie()}
    )

    await api.login()

    _args, kwargs = mock_aiohttp_client.post.call_args
    assert kwargs["data"]["goformId"] == "LOGIN_MULTI_USER"
    # Kajkac's shape: the multi-user form takes `user`, not `username`, and
    # carries an `AD` token.
    assert kwargs["data"]["user"] == "admin"
    assert "username" not in kwargs["data"]
    assert kwargs["data"]["AD"]


@pytest.mark.asyncio
async def test_the_single_user_form_keeps_username_when_one_is_configured(
    mock_aiohttp_client,
):
    """Measured, not inherited from the reference implementation.

    On MC7010 firmware `IRL_H3G_MC7010DV1.0.0B03` both `username=` and
    `user=` are accepted on `LOGIN` and yield a usable session, but omitting
    the field — which is `mc.py`'s shape for this form — makes the router
    close the connection without answering.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    _bootstrap(mock_aiohttp_client, version="MC7010_V1", username=True)
    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": _stok_cookie()}
    )

    await api.login()

    _args, kwargs = mock_aiohttp_client.post.call_args
    assert kwargs["data"]["goformId"] == "LOGIN"
    assert kwargs["data"]["username"] == "admin"
    assert "user" not in kwargs["data"]
    assert "AD" not in kwargs["data"]


@pytest.mark.asyncio
async def test_an_unreadable_rd_does_not_block_the_multi_user_attempt(
    mock_aiohttp_client,
):
    """The `AD` token is one half of a shape that is itself a best guess.

    A router that will not answer `RD` before login should still get the
    attempt, and fall through to the alternate form on its own terms, rather
    than have the login fail outright over a token the form may not need.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data={"LD": "LD"}),
        MockResponse(json_data={"wa_inner_version": "MC888_V1"}),
        MockResponse(json_data={}),  # RD absent from an otherwise valid reply
        MockResponse(json_data={"wa_inner_version": "MC888_V1"}),
    ]
    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": _stok_cookie()}
    )

    await api.login()

    _args, kwargs = mock_aiohttp_client.post.call_args
    assert kwargs["data"]["goformId"] == "LOGIN_MULTI_USER"
    assert kwargs["data"]["user"] == "admin"
    assert "AD" not in kwargs["data"]
    assert api.session_active


@pytest.mark.asyncio
async def test_every_cookie_in_the_response_is_replayed(mock_aiohttp_client):
    """Which cookie carries the session is the router's business, not ours.

    Replaying one that is not the session costs nothing; missing the one that
    is costs the whole integration, and no rule for telling them apart
    survives contact with a firmware nobody has seen.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", None, "password")
    _bootstrap(mock_aiohttp_client)
    headers = CIMultiDict(
        [
            ("Content-Type", "application/json"),
            ("Set-Cookie", "sessionid=also_sent; Path=/"),
            ("Set-Cookie", "stok=the_real_one; Path=/"),
        ]
    )
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "0"}, cookies={}, headers=headers
    )

    await api.login()

    assert api.cookies == {"sessionid": "also_sent", "stok": "the_real_one"}


@pytest.mark.asyncio
async def test_a_session_cookie_named_zsidn_is_replayed(mock_aiohttp_client):
    """The reported defect, from the reporter's own diagnostics.

    An MC888 Pro on `BD_ABPLMC888PROMODV1.0.0B01` answers a successful
    `LOGIN` with `{"result":"0"}` and a cookie named `zsidn`. Matching the
    literal name `stok` discarded it, so every request went out
    unauthenticated and six of eighty-two keys came back populated behind a
    poll that scored as a success (issue #56).
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", None, "password")
    _bootstrap(mock_aiohttp_client, extra_gets=3)
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"result": "0"},
        cookies={"zsidn": MagicMock(value="session_value")},
    )

    await api.login()
    assert api.cookies == {"zsidn": "session_value"}

    mock_aiohttp_client.get.side_effect = None
    mock_aiohttp_client.get.return_value = MockResponse(
        json_data={"network_type": "LTE", "signalbar": "4"}
    )
    await api.get_all_data()

    _args, kwargs = mock_aiohttp_client.get.call_args
    assert kwargs["headers"]["Cookie"] == "zsidn=session_value"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "trigger",
    ["html_redirect", "unparsable_json", "expired_echo", "transport_error"],
)
async def test_the_cookie_and_the_flag_move_together_on_every_renewal(
    mock_aiohttp_client, trigger
):
    """The session is one piece of state held in two fields.

    A site that moves one without the other is invisible from outside: the
    client believes it is signed in, sends no Cookie header, and the router
    answers by echoing the authenticated keys back empty. Every entity then
    publishes `unknown` while the health sensor stays green. Each renewal
    trigger in `_request` is driven here and the pair asserted afterwards.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "stale"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    dead = {
        "html_redirect": MockResponse(
            json_data=None, headers={"Content-Type": "text/html"}
        ),
        "unparsable_json": MockResponse(json_data=None),
        # Every core key echoed back, which is the shape a dead session
        # actually produces; a partial response is declined by the classifier
        # rather than scored as an expiry.
        "expired_echo": MockResponse(
            json_data={**dict.fromkeys(_CORE_PARAMS, ""), "imei": "123"}
        ),
    }

    if trigger == "transport_error":
        mock_aiohttp_client.get.side_effect = aiohttp.ClientError("gone")
        with pytest.raises(ZTEConnectionError):
            await api.get_all_data()
        assert not api.session_active
        assert not api.cookies
        return

    fresh = MockResponse(json_data={"network_type": "LTE", "signalbar": "4"})
    mock_aiohttp_client.get.side_effect = scripted(
        dead[trigger],
        MockResponse(json_data={"LD": "LD"}),
        MockResponse(json_data={"wa_inner_version": "MC7010_V1"}),
        MockResponse(json_data={"RD": "RD"}),
        MockResponse(json_data={"wa_inner_version": "MC7010_V1"}),
        fresh,
    )
    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": _stok_cookie("renewed")}
    )

    await api.get_all_data()

    assert api.session_active
    assert api.cookies == {"stok": "renewed"}


@pytest.mark.asyncio
async def test_the_idle_reset_clears_both_fields(mock_aiohttp_client):
    """The one renewal trigger the hardware check cannot provoke.

    It fires on elapsed time rather than on a response, so it is reachable
    only here and in a container left polling past the interval.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "idle"}
    api.session_active = True
    api.last_activity = datetime.now(UTC) - timedelta(seconds=1000)

    mock_aiohttp_client.get.side_effect = scripted(
        MockResponse(json_data={"LD": "LD"}),
        MockResponse(json_data={"wa_inner_version": "MC7010_V1"}),
        MockResponse(json_data={"RD": "RD"}),
        MockResponse(json_data={"wa_inner_version": "MC7010_V1"}),
        MockResponse(json_data={"network_type": "LTE", "signalbar": "4"}),
    )
    mock_aiohttp_client.post.return_value = MockResponse(
        cookies={"stok": _stok_cookie("after_idle")}
    )

    await api.get_all_data()

    assert api.session_active
    assert api.cookies == {"stok": "after_idle"}


@pytest.mark.asyncio
async def test_logout_clears_both_fields(mock_aiohttp_client):
    """An abandoned session locks the user out of the router's own web UI."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    mock_aiohttp_client.post.side_effect = aiohttp.ClientError("unreachable")

    await api.logout()

    assert not api.session_active
    assert not api.cookies
