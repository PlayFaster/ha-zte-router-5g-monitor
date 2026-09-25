"""Phone numbers redacted by value shape, and the widened discovery vocabulary."""

import pytest

from custom_components.zte_router_5g import known_names
from custom_components.zte_router_5g.diagnostics import (
    _DENY_NAME_RE,
    _gate_discovery_value,
    _sweep,
    _Tokenizer,
)
from custom_components.zte_router_5g.known_names import (
    EXPECTED_NAMES,
    GENERATED_NAMES,
    KNOWN_NAMES,
)

# Synthetic numbers only.
INTL = "+15550003333"
NATIONAL = "07700900123"


# ---------------------------------------------------------------------------
# Phone numbers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [INTL, NATIONAL, f"alert to {INTL} now"])
def test_a_phone_number_is_tokenized_whatever_the_key(value: str) -> None:
    """A phone number is tokenized whatever the key."""
    swept = _sweep(value, _Tokenizer())
    assert INTL not in swept
    assert NATIONAL not in swept
    assert "phone-1" in swept


@pytest.mark.parametrize(
    "value",
    ["12345678901", "98765432109", "3600", "1,3,7,20,28,38,77,78", "0", "-104"],
)
def test_counters_and_readings_are_not_taken_for_phone_numbers(value: str) -> None:
    """An 11-digit byte counter carries neither a `+` nor a leading `0`."""
    assert _sweep(value, _Tokenizer()) == value


def test_a_national_number_inside_text_is_not_matched() -> None:
    """The national rule is on the whole value only."""
    text = f"code {NATIONAL[1:]} ref"
    assert _sweep(text, _Tokenizer()) == text


def test_an_international_number_keeps_one_token_for_one_person() -> None:
    """An international number keeps one token for one person."""
    tokenizer = _Tokenizer()
    assert _sweep(INTL, tokenizer) == _sweep(f"to {INTL}", tokenizer).split()[-1]


def test_a_discovered_phone_value_under_an_unrelated_name_is_tokenized() -> None:
    """`wps_alert_sms_number` shipped unredacted; an unknown name must not."""
    value, verdict = _gate_discovery_value("zz_unrelated_field", INTL, _Tokenizer())
    assert INTL not in str(value)
    assert verdict == "tokenized"


@pytest.mark.parametrize(
    "name",
    [
        "wps_alert_sms_number",
        "data_limit_alert_sms_number",
        "lan_wifi_alert_sms_number",
        "power_alert_sms_number",
        "webui_alert_sms_number",
        "phone_number",
    ],
)
def test_a_phone_field_is_withheld_by_its_name(name: str) -> None:
    """A phone field is withheld by its name."""
    assert _DENY_NAME_RE.search(name)
    value, verdict = _gate_discovery_value(name, INTL, _Tokenizer())
    assert verdict == "denied-name"
    assert INTL not in str(value)


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

REPORTED = {
    "rrc_stat",
    "wan_network_type",
    "network_mode",
    "band_list",
    "5g_pci",
    "5g_rsrq",
    "5g_snr",
    "5g_ca_pcell_band",
    "5g_ca_pcell_bandwidth",
    "5g_band_lock",
    "5g_pci_lock",
    "z5g_snr",
}


def test_the_reported_names_are_expected() -> None:
    """The reported names are expected."""
    assert REPORTED <= EXPECTED_NAMES


def test_generated_names_are_new() -> None:
    """Generated names are new."""
    assert not GENERATED_NAMES & (KNOWN_NAMES | EXPECTED_NAMES)


def test_generated_names_follow_only_the_evidenced_rules() -> None:
    """Generated names follow only the evidenced rules."""
    for name in GENERATED_NAMES:
        is_5g = bool(known_names._5G_NAME.match(name))
        is_network = name.startswith("network_")
        is_flux_bare = "flux_" + name in KNOWN_NAMES | EXPECTED_NAMES
        assert is_5g or is_network or is_flux_bare, name
        assert not name.lower().startswith(("4g_", "z4g_")), name


def test_network_is_not_applied_to_a_generated_name() -> None:
    """Network is not applied to a generated name."""
    for name in GENERATED_NAMES:
        if name.startswith("network_"):
            assert name.removeprefix("network_") in KNOWN_NAMES | EXPECTED_NAMES, name


def test_every_5g_suffix_appears_under_every_5g_prefix() -> None:
    """Every 5g suffix appears under every 5g prefix."""
    vocabulary = KNOWN_NAMES | EXPECTED_NAMES | GENERATED_NAMES
    suffixes = {
        m.group(1)
        for n in KNOWN_NAMES | EXPECTED_NAMES
        if (m := known_names._5G_NAME.match(n))
    }
    for suffix in suffixes:
        for prefix in known_names._5G_PREFIXES:
            assert prefix + suffix in vocabulary, prefix + suffix


def test_the_generated_set_is_pinned() -> None:
    """A change to the rules or the vocabulary changes this count on purpose."""
    assert len(GENERATED_NAMES) == 181


def test_a_name_the_mc7010_answered_is_reached() -> None:
    """`nr5g_band_lock` answered on the MC7010 in the dev1 live check."""
    assert "nr5g_band_lock" in GENERATED_NAMES
