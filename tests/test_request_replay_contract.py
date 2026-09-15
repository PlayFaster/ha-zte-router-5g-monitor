"""The properties `_request`'s recovery path must keep, pinned before it moves.

`_request` is the single most load-bearing routine here — every read and every
write passes through it — and both faults this project has shipped lived in its
expiry detection. It is also 146 lines at a McCabe score of 21, and the reason
it resists decomposition is the replay: three sites re-issue the original call
with eleven arguments, so no section can be extracted without carrying that
argument list with it.

These tests exist so the restructure is a *move* and not a rewrite. Each pins a
property that is currently emergent — true because of where the code sits rather
than because anything asserts it — and each would fail if the move changed it.

Written deliberately ahead of the change, against the code as it stands.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from custom_components.zte_router_5g.api import (
    ZTEAuthError,
    ZTEConnectionError,
    ZTERouterAPI,
)

from .conftest import MockResponse


@pytest.mark.asyncio
async def test_a_router_that_always_looks_expired_is_retried_exactly_once(
    mock_aiohttp_client,
) -> None:
    """The recursion bound, which nothing currently asserts.

    A replay is issued with `_retry=False` and `_after_relogin=True`. The first
    of those is what makes it once: the replayed call cannot itself decide to
    log in again, so a router that keeps answering as though the session were
    dead raises rather than looping.

    After the restructure the replay is `replace(call, retry=False,
    after_relogin=True)`. Setting only one of the two leaves a loop reachable on
    exactly this router, and the symptom would be an integration that hangs
    rather than one that reports a fault.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    # A bare api object carries `last_activity` at the epoch, so the idle
    # preempt fires before the first request and logs in. Set, so these tests
    # measure the recovery path rather than the fixture.
    api.last_activity = datetime.now(UTC)

    # The dead-session shape: an authenticated key blank beside an
    # unauthenticated one that answers.
    expired = {"wan_connect_status": "", "model_name": "MC7010"}
    mock_aiohttp_client.get.return_value = MockResponse(json_data=expired)

    async def relogin(*_args, **_kwargs):
        # What the real `login` does, and what the lazy-login branch above
        # keys on. Without it that branch fires on every pass and the count
        # measures the fixture rather than the recovery.
        api.session_active = True
        api.cookies = {"stok": "fresh"}

    with (
        patch.object(api, "login", new=AsyncMock(side_effect=relogin)) as login,
        pytest.raises((ZTEAuthError, ZTEConnectionError)),
    ):
        await api._request(
            "GET",
            "goform/goform_get_cmd_process",
            requested=["wan_connect_status", "model_name"],
        )

    assert login.await_count == 1, "the replay logged in more than once"
    assert mock_aiohttp_client.get.call_count == 2, (
        "the request was put more or fewer than twice"
    )


@pytest.mark.asyncio
async def test_an_auth_error_from_inside_the_transport_is_not_remapped(
    mock_aiohttp_client,
) -> None:
    """`except (ZTEAuthError, ZTEConnectionError): raise` sits first, and must.

    The broad clause below it wraps anything it catches in
    `ZTEConnectionError("Request failed: ...")`. If the ordering were reversed,
    or the clauses separated during the move, an authentication failure raised
    by a nested call would surface as a transport failure — the router blamed
    for a session problem, which is the class of mislabelling this release
    exists to remove.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    # A bare api object carries `last_activity` at the epoch, so the idle
    # preempt fires before the first request and logs in. Set, so these tests
    # measure the recovery path rather than the fixture.
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.side_effect = ZTEAuthError("from inside")

    with pytest.raises(ZTEAuthError, match="from inside"):
        await api._request("GET", "goform/goform_get_cmd_process")


@pytest.mark.asyncio
async def test_a_transport_failure_is_reported_as_one(mock_aiohttp_client) -> None:
    """The companion to the above: the broad clause still does its job."""
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    # A bare api object carries `last_activity` at the epoch, so the idle
    # preempt fires before the first request and logs in. Set, so these tests
    # measure the recovery path rather than the fixture.
    api.last_activity = datetime.now(UTC)
    mock_aiohttp_client.get.side_effect = aiohttp.ClientError("no route")

    with pytest.raises(ZTEConnectionError, match="Request failed"):
        await api._request("GET", "goform/goform_get_cmd_process")


@pytest.mark.asyncio
async def test_the_replay_carries_the_cookie_from_the_new_session(
    mock_aiohttp_client,
) -> None:
    """The hazard a call object introduces, if it caches what it should rebuild.

    Headers are assembled inside `_request` from `self.cookies`, so the replay
    that follows a re-login picks up the *new* `stok` on its way through. A call
    object that carried assembled headers instead of the caller's would replay
    the dead cookie — a silent authentication failure presenting as a router
    fault, on the recovery path, where it is least visible.

    So the object may carry the caller's headers and nothing else.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "dead"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    expired = {"wan_connect_status": "", "model_name": "MC7010"}
    healthy = {"wan_connect_status": "ppp_connected", "model_name": "MC7010"}
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data=expired),
        MockResponse(json_data=healthy),
    ]

    async def relogin(*_args, **_kwargs):
        api.session_active = True
        api.cookies = {"stok": "fresh"}

    with patch.object(api, "login", new=AsyncMock(side_effect=relogin)):
        await api._request(
            "GET",
            "goform/goform_get_cmd_process",
            requested=["wan_connect_status", "model_name"],
        )

    sent = [
        call.kwargs["headers"]["Cookie"]
        for call in mock_aiohttp_client.get.mock_calls
        if "headers" in call.kwargs
    ]
    assert sent[0] == "stok=dead"
    assert sent[-1] == "stok=fresh", "the replay used the cookie of the dead session"


@pytest.mark.asyncio
async def test_a_write_is_never_replayed(mock_aiohttp_client) -> None:
    """The property that outranks every other one here.

    A resent `SEND_SMS` can deliver the message twice with nothing in the
    response to say that it did. `replayable` is computed from
    `_is_write_request`, and the restructure must carry it on the call rather
    than recompute it, without changing what it decides.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    # A bare api object carries `last_activity` at the epoch, so the idle
    # preempt fires before the first request and logs in. Set, so these tests
    # measure the recovery path rather than the fixture.
    api.last_activity = datetime.now(UTC)
    # The dead-session shape, from a write. A read answering this way is
    # replayed; a write answering it must not be.
    mock_aiohttp_client.post.return_value = MockResponse(
        json_data={"wan_connect_status": "", "model_name": "MC7010"}
    )

    # It raises rather than replaying — the session is reported as the cause,
    # and the command is not put a second time. That is the whole point: a
    # resent `SEND_SMS` can deliver the message twice.
    with (
        patch.object(api, "login", new=AsyncMock()) as login,
        pytest.raises(ZTEAuthError),
    ):
        await api._request(
            "POST",
            "goform/goform_set_cmd_process",
            data="isTest=false&goformId=SEND_SMS&AD=x",
            requested=["wan_connect_status", "model_name"],
        )

    assert mock_aiohttp_client.post.call_count == 1, "a write was put twice"
    assert login.await_count == 0, "a write triggered a re-login and a replay"


@pytest.mark.asyncio
async def test_the_replay_keeps_the_classification_the_caller_asked_for(
    mock_aiohttp_client,
) -> None:
    """`classify=False` means the caller does not want a session verdict at all.

    `_replay_after_login` forwarded eight of the ten parameters and dropped
    this one, so a replayed call reverted to the default and could be scored as
    an expired session — a verdict the caller had explicitly declined.

    `_probe_chunk` is the exposed caller: it passes `classify=False` with retry
    enabled, and every other `classify=False` site also sets `_retry=False` and
    so can never reach a replay. There, a chunk whose replay was classified
    raised inside a broad `except`, was logged, and returned `None` — the chunk
    dropped, and discovery reporting fewer names than the device answers.

    `requested` was forwarded and `classify` was not, and `_session_rejected`
    reads the two together. That is what makes it an oversight rather than a
    decision.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    seen: list[bool] = []
    real_request = api._request

    async def record(method, path, **kwargs):
        seen.append(kwargs.get("classify", True))
        return await real_request(method, path, **kwargs)

    async def relogin(*_args, **_kwargs):
        api.session_active = True
        api.cookies = {"stok": "fresh"}

    # The dead-session shape on both passes: the first triggers the replay, the
    # second is what the replay sees.
    expired = {"wan_connect_status": "", "model_name": "MC7010"}
    mock_aiohttp_client.get.return_value = MockResponse(json_data=expired)

    with (
        patch.object(api, "login", new=AsyncMock(side_effect=relogin)),
        patch.object(api, "_request", side_effect=record),
    ):
        await api._replay_after_login(
            "GET",
            "goform/goform_get_cmd_process",
            requested=["wan_connect_status", "model_name"],
            classify=False,
        )

    assert seen == [False], (
        "the replay was classified after the caller asked for classify=False"
    )


@pytest.mark.asyncio
async def test_last_activity_is_stamped_once_per_logical_request(
    mock_aiohttp_client,
) -> None:
    """Only the call that returns a result stamps the clock, and only once.

    `last_activity` drives the idle reset, and only an authenticated call
    proves the session is alive — `[3.3.4-dev25]` records what happened when
    unauthenticated reads stamped it. When a replay occurs the outer call
    returns the replay's result, so it is the replay that stamps.

    Pinned because the restructure splits the transport from the disposal, and
    a `_perform` that stamped after disposal returned would stamp twice.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "dead"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)

    stamps: list[object] = []

    expired = {"wan_connect_status": "", "model_name": "MC7010"}
    healthy = {"wan_connect_status": "ppp_connected", "model_name": "MC7010"}
    mock_aiohttp_client.get.side_effect = [
        MockResponse(json_data=expired),
        MockResponse(json_data=healthy),
    ]

    async def relogin(*_args, **_kwargs):
        api.session_active = True
        api.cookies = {"stok": "fresh"}

    class _Watcher:
        """Counts assignments to `last_activity` without changing them.

        `__set_name__` is not used: the descriptor is attached after the class
        exists, so Python never calls it.
        """

        _name = "_watched_last_activity"

        def __get__(self, obj, objtype=None):
            return getattr(obj, self._name)

        def __set__(self, obj, value):
            stamps.append(value)
            object.__setattr__(obj, self._name, value)

    type(api).last_activity = _Watcher()
    api.last_activity = datetime.now(UTC)
    stamps.clear()

    try:
        with patch.object(api, "login", new=AsyncMock(side_effect=relogin)):
            await api._request(
                "GET",
                "goform/goform_get_cmd_process",
                requested=["wan_connect_status", "model_name"],
            )
    finally:
        del type(api).last_activity

    assert len(stamps) == 1, f"the clock was stamped {len(stamps)} times, not once"
