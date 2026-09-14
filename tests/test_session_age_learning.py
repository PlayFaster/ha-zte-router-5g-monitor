"""The pre-write reset learns when this device's sessions end, and keys on age.

`SESSION_IDLE_RESET_SECONDS` is compared against `last_activity` — time since
the last authenticated request. The boundary it guards is not idle-based: a
session polled every ten seconds ended at the same point as one left untouched.
And idle time between polls is roughly the scan interval, which a user may set
anywhere from 30 to 3600 seconds, so at any interval at or below the constant
the reset never fires and every poll past the boundary pays a failed request, a
login and a retry.

There is no lifetime to hardcode instead. Four runs on the reference MC7010
inside one hour ended at 15s, 85s and 110-120s, and one could not complete;
`[3.3.0-rc2]` separately measured "at or below 200s". A device holding sessions
for 300s and one expiring at 20s are both plausible, and no constant serves
both. So the threshold is learned from expiries this device actually had.
"""

import contextlib
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.zte_router_5g.api import ZTERouterAPI
from custom_components.zte_router_5g.const import (
    SESSION_AGE_FLOOR_SECONDS,
    SESSION_AGE_LEARN_MIN_SAMPLES,
    SESSION_AGE_LEARN_WINDOW,
    SESSION_AGE_SAFETY,
    SESSION_AGE_SAMPLE_EVERY,
)


def _api() -> ZTERouterAPI:
    return ZTERouterAPI(MagicMock(), "192.168.0.1", "admin", "password")


def test_nothing_is_learned_until_enough_expiries_agree() -> None:
    """One expiry is not a boundary, and the idle reset runs meanwhile.

    `[3.3.0-rc2]` declined removing the proactive reset in favour of reactive
    detection: it costs three round trips instead of two and removes the second
    line of defence behind the `[3.3.0-dev12]` blank-payload fault. Learning
    refines the threshold; it must not switch the mechanism off.
    """
    api = _api()
    assert api.learned_session_age_limit() is None

    for _ in range(SESSION_AGE_LEARN_MIN_SAMPLES - 1):
        api.session_lifetimes.append(120.0)
        assert api.learned_session_age_limit() is None

    api.session_lifetimes.append(120.0)
    assert api.learned_session_age_limit() is not None


def test_the_limit_is_the_shortest_recent_sample_less_a_margin() -> None:
    """Being early costs one login; being late costs three round trips.

    That asymmetry is why the shortest sample leads rather than the typical one.
    """
    api = _api()
    api.session_lifetimes = [200.0, 120.0, 300.0]

    assert api.learned_session_age_limit() == pytest.approx(120.0 * SESSION_AGE_SAFETY)


def test_the_limit_never_falls_below_the_floor() -> None:
    """A pathological reading must not turn into a login storm."""
    api = _api()
    api.session_lifetimes = [1.0, 2.0, 1.5]

    assert api.learned_session_age_limit() == SESSION_AGE_FLOOR_SECONDS


def test_a_short_session_is_not_learned_from() -> None:
    """Not every session that ends, ended because time ran out.

    This router grants the session to the newest login, so a web-UI visit takes
    it; a reconnect or a config reload replaces it too. The router does not
    report why a session ended and this project cannot tell the cases apart, so
    anything below the floor is discarded rather than classified.
    """
    api = _api()
    api.session_started = datetime.now(UTC) - timedelta(
        seconds=SESSION_AGE_FLOOR_SECONDS / 2
    )

    api._note_session_replaced()

    assert api.session_lifetimes == []


def test_only_the_recent_window_is_kept() -> None:
    """Shortest-ever would be set permanently by one stolen session."""
    api = _api()
    for _ in range(SESSION_AGE_LEARN_WINDOW + 5):
        api.session_started = datetime.now(UTC) - timedelta(seconds=100)
        api._note_session_replaced()

    assert len(api.session_lifetimes) == SESSION_AGE_LEARN_WINDOW


def test_the_clock_is_session_age_and_not_time_since_the_last_request() -> None:
    """`last_activity` is refreshed by every authenticated request.

    Reusing it would have kept idle semantics under an age-shaped name, which is
    the defect this item exists to correct rather than rename.
    """
    api = _api()
    api.session_lifetimes = [120.0] * SESSION_AGE_LEARN_MIN_SAMPLES
    api.session_started = datetime.now(UTC) - timedelta(seconds=200)
    # Busy right up to this moment: an idle clock would see nothing wrong.
    api.last_activity = datetime.now(UTC)

    assert api._session_is_past_its_learned_age() is True


def test_a_young_session_is_left_alone() -> None:
    """The preempt exists to save a round trip, not to churn sessions."""
    api = _api()
    api.session_lifetimes = [120.0] * SESSION_AGE_LEARN_MIN_SAMPLES
    api.session_started = datetime.now(UTC)

    assert api._session_is_past_its_learned_age() is False


def test_one_check_in_ten_lets_the_session_reach_its_real_boundary() -> None:
    """Without sampling the learner starves and the value can never rise.

    An active preempt destroys every session before it expires, so no further
    expiry is observed. The learned value would be locked to whatever was first
    seen — including across a firmware change that lengthened the boundary. One
    skipped check per `SESSION_AGE_SAMPLE_EVERY` costs one failed request and
    keeps the input coming.
    """
    api = _api()
    api.session_lifetimes = [120.0] * SESSION_AGE_LEARN_MIN_SAMPLES
    api.session_started = datetime.now(UTC) - timedelta(seconds=200)

    verdicts = [
        api._session_is_past_its_learned_age() for _ in range(SESSION_AGE_SAMPLE_EVERY)
    ]

    assert verdicts.count(False) == 1, "the session is never allowed to expire"
    assert verdicts[-1] is False


def test_nothing_learned_means_the_age_check_never_fires() -> None:
    """The idle reset is what runs until the device has taught us otherwise."""
    api = _api()
    api.session_started = datetime.now(UTC) - timedelta(days=1)

    assert api._session_is_past_its_learned_age() is False


def test_a_login_starts_the_age_clock_and_closes_the_previous_session() -> None:
    """The clock is set by `login` and by nothing else.

    Every other path that touches session state — `_clear_session`, a failed
    request, the idle reset — leaves it alone, because only a login establishes
    a session whose age means anything.
    """
    api = _api()
    api.session_started = datetime.now(UTC) - timedelta(seconds=100)

    api._note_session_replaced()
    api.session_started = datetime.now(UTC)

    assert len(api.session_lifetimes) == 1
    assert api.session_lifetimes[0] == pytest.approx(100.0, abs=2)


def test_the_report_says_whether_the_flag_applies_to_this_device() -> None:
    """The field that settles the MC888 Pro question from its next download.

    That device has never been observed with a dead session, and its downloads
    redact the flag's value by name, so whether it implements the key at all is
    unknown. `supported` answers it with no write and nothing asked of its
    owner: either it has answered `ok`, and the check applies there, or it has
    not, and the older classifier is what runs.
    """
    api = _api()

    report = api.session_flag_report()
    assert report["supported"] is False
    assert report["confirmed_on_firmware"] is None
    assert report["checks"]["checks"] == 0

    api._session_flag_seen_for = "IRL_H3G_MC7010DV1.0.0B03"
    report = api.session_flag_report()
    assert report["supported"] is True
    assert report["confirmed_on_firmware"] == "IRL_H3G_MC7010DV1.0.0B03"


def test_a_rejection_survives_the_live_reads_that_build_a_download() -> None:
    """`last_rejection` is cleared by a live verdict, and must stay that way.

    A stale rejection presented as current is its own fault. But producing a
    diagnostics download reads the router, those reads return live verdicts, and
    the field designed to explain a rejection was wiped by the act of collecting
    it — three attempts to capture the MC7010 fault of 2026-09-14 returned
    `null` for that reason. The companion is explicitly historical.
    """
    api = _api()

    api._record_verdict("expired", {"wan_connect_status": ""}, ["wan_connect_status"])
    assert api.last_rejection is not None
    assert api.last_rejection_seen is not None

    # What building a download does.
    api._record_verdict("live", {"wan_connect_status": "ppp_connected"}, None)

    assert api.last_rejection is None, "a stale rejection must not read as current"
    assert api.last_rejection_seen is not None, "the record of the fault was lost"
    assert api.last_rejection_seen["verdict"] == "expired"


@pytest.mark.asyncio
async def test_the_check_counts_when_it_earned_its_round_trip() -> None:
    """Item 102: evidence, so the check can be removed on evidence.

    It costs a read before every write. Whether that ever saves anything is a
    question about the device, not a matter of opinion, and the counters are how
    it gets answered after a few weeks in the field rather than by argument.
    """
    from unittest.mock import AsyncMock, patch

    api = _api()
    api._session_flag_seen_for = ""

    # Denied, then confirmed after a login: the case where the check saved a
    # write that would have been sent on a session the router had ended.
    answers = [{"loginfo": ""}, {"loginfo": "ok"}]
    with (
        patch.object(api, "_request", new=AsyncMock(side_effect=answers)),
        patch.object(api, "login", new=AsyncMock()),
    ):
        await api._ensure_session()

    assert api.session_check_stats["checks"] == 1
    assert api.session_check_stats["not_confirmed"] == 1
    assert api.session_check_stats["relogin_confirmed"] == 1
    assert api.session_check_stats["relogin_failed"] == 0


@pytest.mark.asyncio
async def test_a_confirmed_session_counts_only_as_a_check() -> None:
    """The common case, and the one that decides whether the cost is worth it."""
    from unittest.mock import AsyncMock, patch

    api = _api()
    with patch.object(api, "_request", new=AsyncMock(return_value={"loginfo": "ok"})):
        await api._ensure_session()

    assert api.session_check_stats["checks"] == 1
    assert api.session_check_stats["not_confirmed"] == 0


def test_a_learned_flag_with_no_firmware_known_stays_learned() -> None:
    """The empty string means "learned, firmware not yet known".

    `_ensure_session` runs ahead of the token derivation that fills the version
    cache, so the first `ok` on a fresh object is always recorded without a
    version beside it. Treating that as a mismatch discarded the proof on the
    same write and the mechanism then never fired again.
    """
    api = _api()
    api._session_flag_seen_for = ""
    assert api._cr_version_cache is None

    assert api._session_flag_supported() is True


@pytest.mark.asyncio
async def test_a_session_past_its_learned_age_is_replaced_before_the_request() -> None:
    """The preempt, end to end through `_request`.

    Busy right up to the moment of the call, so the idle clock sees nothing
    wrong — which is exactly the case an idle reset cannot catch and the reason
    the clock changed.
    """
    from unittest.mock import AsyncMock, patch

    api = _api()
    api.cookies = {"stok": "stale"}
    api.session_active = True
    api.last_activity = datetime.now(UTC)
    api.session_lifetimes = [120.0] * SESSION_AGE_LEARN_MIN_SAMPLES
    api.session_started = datetime.now(UTC) - timedelta(seconds=300)

    cleared = False

    def note_cleared(*_args, **_kwargs):
        nonlocal cleared
        cleared = True

    with (
        patch.object(api, "_clear_session", side_effect=note_cleared),
        patch.object(api, "login", new=AsyncMock()),
        contextlib.suppress(Exception),
    ):
        # The session object is a bare mock, so the transport fails after the
        # preempt has already run. The preempt is what this asserts.
        await api._request("GET", "goform/goform_get_cmd_process")

    assert cleared, "a session past its learned age was not replaced"


def test_the_firmware_is_adopted_the_first_time_it_becomes_known() -> None:
    """The empty proof is upgraded, not re-checked on every call.

    Left as an empty string it would never invalidate on a firmware change,
    which is the property the per-firmware holding exists for.
    """
    api = _api()
    api._session_flag_seen_for = ""
    api._cr_version_cache = ("FIRMWARE_A", "")

    assert api._session_flag_supported() is True
    assert api._session_flag_seen_for == "FIRMWARE_A"

    api._cr_version_cache = ("FIRMWARE_B", "")
    assert api._session_flag_supported() is False


def test_a_learned_flag_outlives_a_cleared_firmware_cache() -> None:
    """Nothing to compare against is not the same as a mismatch.

    The version cache is a token-path optimisation and may be empty for reasons
    that have nothing to do with the firmware changing. Discarding real evidence
    because a cache has not filled would turn a working check off at random.
    """
    api = _api()
    api._session_flag_seen_for = "FIRMWARE_A"
    api._cr_version_cache = None

    assert api._session_flag_supported() is True
