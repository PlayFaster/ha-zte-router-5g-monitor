"""Tests for the ZTE Router helpers."""

import pytest

from custom_components.zte_router_5g.helpers import (
    arfcn_to_band,
    earfcn_to_band,
    get_router_model,
    is_gsm7,
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
    assert is_gsm7("Ça coûte £5 à Ωmega") is True


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
