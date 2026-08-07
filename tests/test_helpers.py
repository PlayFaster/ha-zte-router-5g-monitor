"""Tests for the ZTE Router helpers."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.zte_router_5g.helpers import (
    arfcn_to_band,
    cycle_bounds,
    earfcn_to_band,
    get_router_model,
    is_gsm7,
    project_cycle_usage,
)


def test_get_router_model_none():
    """Test get_router_model with None data."""
    assert get_router_model(None) == "ZTE Router"


def test_get_router_model_empty():
    """Test get_router_model with empty dict."""
    assert get_router_model({}) == "ZTE Router"


def test_get_router_model_unknown():
    """Test get_router_model with unknown model string."""
    assert get_router_model({"wa_inner_version": "UNKNOWN_MODEL_123"}) == "ZTE Router"


def test_get_router_model_direct_name():
    """Test get_router_model with a direct model_name field (covers helpers.py:35)."""
    assert get_router_model({"model_name": "MC7010"}) == "MC7010"


def test_get_router_model_known():
    """Test get_router_model with known model strings."""
    assert (
        get_router_model({"wa_inner_version": "IRL_H3G_MC7010DV1.0.0B01"}) == "MC7010"
    )
    assert get_router_model({"wa_inner_version": "MC801A_V1.0.0"}) == "MC801"
    assert get_router_model({"wa_inner_version": "MC888_FIRMWARE"}) == "MC888"
    assert get_router_model({"wa_inner_version": "MC889_PRO"}) == "MC889"


def test_is_gsm7_plain_ascii():
    """Ordinary ASCII text is GSM-7 encodable."""
    assert is_gsm7("Router rebooted at 03:14 - signal restored.") is True


def test_is_gsm7_accepts_the_accented_and_greek_members():
    """The default alphabet is wider than ASCII; these must not force UCS-2."""
    assert is_gsm7("Ç£5 à Ωmega éöñ") is True


def test_is_gsm7_rejects_near_misses_in_the_accented_range():
    """The alphabet is a specific list, not "anything Latin-1 looking".

    Lowercase c-cedilla and u-circumflex are absent from GSM 03.38 even
    though their uppercase or unaccented forms are present.
    """
    assert is_gsm7("ç") is False
    assert is_gsm7("û") is False


def test_is_gsm7_accepts_the_extension_table():
    """Extension-table characters cost two septets but are still GSM-7."""
    assert is_gsm7("{price} [€] ~ |x|^2") is True


def test_is_gsm7_rejects_characters_outside_the_alphabet():
    """A single out-of-alphabet character forces UNICODE for the whole message."""
    assert is_gsm7("Signal restored \U0001f4f6") is False
    assert is_gsm7("Curly “quotes”") is False


def test_is_gsm7_empty_string():
    """An empty message is vacuously GSM-7."""
    assert is_gsm7("") is True


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        (9360, "B28"),  # live MC7010 reading
        ("9360", "B28"),  # the goform API returns everything as strings
        (0, "B1"),  # lower edge of the first range
        (599, "B1"),
        (600, "B2"),  # first channel of the next band
        (1800, "B3"),
        (6300, "B20"),
        (39150, "B40"),
        (60254, "B53"),  # upper edge of the last sub-6 FDD/TDD range
        (68586, "B71"),
        (70645, "B88"),  # upper edge of the whole table
    ],
)
def test_earfcn_to_band_resolves_known_channels(channel, expected):
    """EARFCN ranges do not overlap, so each channel has one correct answer."""
    assert earfcn_to_band(channel) == expected


@pytest.mark.parametrize(
    "channel", [None, "", "not-a-number", 10360, 35999, 70646, 999999]
)
def test_earfcn_to_band_returns_none_rather_than_guessing(channel):
    """Missing, unparsable and out-of-range channels must report unknown."""
    assert earfcn_to_band(channel) is None


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        (630000, "n78"),
        ("630000", "n78"),
        (620000, "n78"),  # n78 wins the overlap with n77 at the shared lower edge
        (653333, "n78"),
        (660000, "n77"),  # above n78, only n77 remains
        (700000, "n79"),
        (500000, "n41"),
        (425000, "n1"),
        (370000, "n3"),
        (155000, "n28"),
        (125000, "n71"),
        (2100000, "n257"),
    ],
)
def test_arfcn_to_band_resolves_known_channels(channel, expected):
    """Overlapping NR ranges are broken by table order; assert that order holds."""
    assert arfcn_to_band(channel) == expected


@pytest.mark.parametrize("channel", [None, "", "n78", 1000, 123399, 2279166])
def test_arfcn_to_band_returns_none_rather_than_guessing(channel):
    """Missing, unparsable and out-of-range channels must report unknown."""
    assert arfcn_to_band(channel) is None


def test_channel_resolvers_accept_float_shaped_strings():
    """Some firmware pads numeric fields; int(float(...)) absorbs that."""
    assert earfcn_to_band("9360.0") == "B28"
    assert arfcn_to_band("630000.0") == "n78"


# --- Billing-cycle arithmetic ---

_DUB = ZoneInfo("Europe/Dublin")


def _local(year, month, day, hour=0, minute=0):
    """Build a timezone-aware local datetime for the cycle tests."""
    return datetime(year, month, day, hour, minute, tzinfo=_DUB)


def test_cycle_bounds_mid_month_clear_day():
    """A cycle starting on the 15th runs to the 15th of the next month."""
    start, end, length = cycle_bounds(15, _local(2026, 7, 20, 12))
    assert start == _local(2026, 7, 15)
    assert end == _local(2026, 8, 15)
    assert length == 31


def test_cycle_bounds_before_the_clear_day_looks_back_a_month():
    """On the 3rd with a clear day of 15, the cycle in flight began last month."""
    start, end, length = cycle_bounds(15, _local(2026, 7, 3, 9))
    assert start == _local(2026, 6, 15)
    assert end == _local(2026, 7, 15)
    assert length == 30


def test_cycle_bounds_on_the_clear_day_starts_a_new_cycle():
    """Midnight on the clear day is the first moment of the new cycle."""
    start, _end, _length = cycle_bounds(15, _local(2026, 7, 15, 0, 1))
    assert start == _local(2026, 7, 15)


def test_cycle_bounds_spans_the_year_boundary():
    """A January date with a later clear day reaches back into December."""
    start, end, length = cycle_bounds(20, _local(2026, 1, 5))
    assert start == _local(2025, 12, 20)
    assert end == _local(2026, 1, 20)
    assert length == 31


def test_cycle_bounds_forward_across_the_year_boundary():
    """A December cycle ends in January, not month 13."""
    start, end, _length = cycle_bounds(10, _local(2026, 12, 25))
    assert start == _local(2026, 12, 10)
    assert end == _local(2027, 1, 10)


def test_cycle_bounds_clamps_a_clear_day_february_cannot_have():
    """Day 31 in February resets on the 28th rather than being skipped."""
    start, end, length = cycle_bounds(31, _local(2026, 3, 5))
    assert start == _local(2026, 2, 28)
    assert end == _local(2026, 3, 31)
    assert length == 31


def test_cycle_bounds_clamps_in_a_leap_year():
    """2028 is a leap year, so the clamp lands on the 29th."""
    start, _end, _length = cycle_bounds(31, _local(2028, 2, 29, 6))
    assert start == _local(2028, 2, 29)


def test_cycle_bounds_length_is_calendar_days_across_a_dst_change():
    """A cycle containing a 23-hour day is still a whole number of days."""
    # Europe/Dublin springs forward on 2026-03-29.
    _start, _end, length = cycle_bounds(15, _local(2026, 4, 1))
    assert length == 31


# --- Projection ---


def test_projection_floors_the_denominator_at_one_day():
    """Without the floor, seconds into a cycle the figure is unbounded."""
    # 2 GB one second in. Naive maths gives 2 / (1/86400) * 30 = 5.2 million GB.
    projected = project_cycle_usage(
        used=2.0,
        elapsed_days=1.0 / 86400,
        cycle_length_days=30,
        prior_rate=None,
        credibility_days=3.0,
    )
    assert projected == pytest.approx(62.0, abs=0.1)


def test_projection_without_a_prior_is_a_plain_run_rate():
    """Half way through at 50 GB projects to 100 GB."""
    projected = project_cycle_usage(
        used=50.0,
        elapsed_days=15.0,
        cycle_length_days=30,
        prior_rate=None,
        credibility_days=3.0,
    )
    assert projected == pytest.approx(100.0)


def test_projection_leans_on_the_prior_at_the_start_of_a_cycle():
    """Day one with a 100 GB prior should read near 100, not near 60."""
    projected = project_cycle_usage(
        used=2.0,
        elapsed_days=0.25,
        cycle_length_days=30,
        prior_rate=100.0 / 30,
        credibility_days=3.0,
    )
    assert 90.0 < projected < 105.0


def test_projection_prior_barely_moves_the_answer_late_in_the_cycle():
    """By day 28 the figure is nearly all meter reading, so the prior is noise.

    This is the property that makes the blend safe: it decays with the days
    remaining, not with the credibility constant.
    """
    kwargs = {
        "used": 130.0,
        "elapsed_days": 28.0,
        "cycle_length_days": 30,
        "credibility_days": 3.0,
    }
    blended = project_cycle_usage(prior_rate=100.0 / 30, **kwargs)
    unblended = project_cycle_usage(prior_rate=None, **kwargs)
    assert abs(blended - unblended) / unblended < 0.01


def test_projection_tracks_a_heavy_month_within_a_week():
    """A prior must not hold the figure down when usage genuinely climbs."""
    projected = project_cycle_usage(
        used=35.0,
        elapsed_days=7.0,
        cycle_length_days=30,
        prior_rate=100.0 / 30,
        credibility_days=3.0,
    )
    assert projected > 125.0


def test_projection_at_the_end_of_a_cycle_is_the_observed_total():
    """With no days left there is nothing to forecast."""
    projected = project_cycle_usage(
        used=90.0,
        elapsed_days=30.0,
        cycle_length_days=30,
        prior_rate=100.0 / 30,
        credibility_days=3.0,
    )
    assert projected == pytest.approx(90.0)


def test_projection_never_goes_backwards_past_the_cycle_end():
    """A clock skew past the cycle end must not subtract from observed usage."""
    projected = project_cycle_usage(
        used=90.0,
        elapsed_days=33.0,
        cycle_length_days=30,
        prior_rate=None,
        credibility_days=3.0,
    )
    assert projected == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# Mutation survivors, 2026-08-07. Boundary and arithmetic mutants — the ~17%
# category worth the time; string-literal survivors were triaged as noise.
# ---------------------------------------------------------------------------


def test_cycle_bounds_treats_the_reset_instant_as_the_new_cycle():
    """At exactly the reset moment the cycle has started, not ended.

    Separates `start > now` from `start >= now`. Called precisely at midnight
    on the clear day, the `>=` form steps back a whole month, so the
    projection divides a few seconds of usage by a nearly complete cycle and
    reports a figure ~30x too low for one poll. Only an exact-boundary call
    can tell the two apart.
    """
    tz = ZoneInfo("UTC")
    now = datetime(2026, 8, 15, 0, 0, 0, tzinfo=tz)

    start, end, length = cycle_bounds(15, now)

    assert start == datetime(2026, 8, 15, 0, 0, 0, tzinfo=tz)
    assert end == datetime(2026, 9, 15, 0, 0, 0, tzinfo=tz)
    assert length == 31
    # A second earlier is still the previous cycle — the other side of the edge.
    prev_start, _, _ = cycle_bounds(15, now.replace(day=14, hour=23, minute=59))
    assert prev_start == datetime(2026, 7, 15, 0, 0, 0, tzinfo=tz)


def test_cycle_bounds_starts_at_midnight_exactly():
    """The cycle boundary is a date, not the time of day it was computed at.

    `cycle_bounds` derives its start from `now`, so dropping the second and
    microsecond resets would carry the current clock into the boundary and
    make the cycle length depend on when the poll happened to run.
    """
    now = datetime(2026, 8, 20, 13, 47, 29, 123456, tzinfo=ZoneInfo("UTC"))

    start, end, _ = cycle_bounds(15, now)

    assert (start.hour, start.minute, start.second, start.microsecond) == (0, 0, 0, 0)
    assert (end.hour, end.minute, end.second, end.microsecond) == (0, 0, 0, 0)


def test_prior_rate_weight_decays_as_the_cycle_progresses():
    """The blend weight is `elapsed / (elapsed + credibility)`, not a difference.

    The distinction: with `-` the denominator shrinks toward zero and then goes
    negative, so the prior's influence *grows* as evidence accumulates and
    inverts past the credibility horizon — the opposite of what the blend is
    for. A single mid-cycle assertion cannot see that; two points and a
    direction can.
    """
    common = dict(cycle_length_days=30, prior_rate=10.0, credibility_days=5.0)

    early = project_cycle_usage(used=20.0, elapsed_days=2.0, **common)
    late = project_cycle_usage(used=200.0, elapsed_days=20.0, **common)

    # At a steady 10/day the prior agrees with observation, so both land near
    # the same place; the point is that neither is dominated by the prior.
    assert early == pytest.approx(300.0, rel=0.05)
    assert late == pytest.approx(300.0, rel=0.05)

    # With the prior disagreeing, pin the arithmetic itself at two points. A
    # trend assertion is not enough here — `elapsed - credibility` also yields
    # a decreasing pull, so only the values separate the two forms.
    #
    #   day 2:  weight = 2/(2+5)   = 0.2857 -> rate 74.29 -> 20 + 28 * 74.29
    #   day 20: weight = 20/(20+5) = 0.8    -> rate 28.00 -> 200 + 10 * 28.00
    common_hi = dict(cycle_length_days=30, prior_rate=100.0, credibility_days=5.0)

    assert project_cycle_usage(
        used=20.0, elapsed_days=2.0, **common_hi
    ) == pytest.approx(2100.0, rel=1e-3)
    assert project_cycle_usage(
        used=200.0, elapsed_days=20.0, **common_hi
    ) == pytest.approx(480.0, rel=1e-3)
