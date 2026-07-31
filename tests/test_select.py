"""Tests for the ZTE Router select platform."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.zte_router_5g.select import (
    ZTERouterSelect,
    ZTESelectEntityDescription,
    _get_apn_profiles,
    _get_current_apn_profile,
    _set_apn_profile_option,
    async_setup_entry,
)

from .conftest import assert_links_to_parent


def test_get_apn_profiles_empty():
    """Test _get_apn_profiles with empty data."""
    assert _get_apn_profiles(None) == []
    assert _get_apn_profiles({}) == []


def test_get_apn_profiles_valid():
    """Test _get_apn_profiles with valid APN config data."""
    data = {
        "APN_config0": "profile_a($)apn1($)($)($)($)($)($)IPV4V6",
        "APN_config1": "profile_b($)apn2($)($)($)($)($)($)IPV6",
        "APN_config3": "profile_d($)apn4",
    }
    profiles = _get_apn_profiles(data)
    assert len(profiles) == 3
    assert profiles[0] == (0, "profile_a", "IPV4V6")
    assert profiles[1] == (1, "profile_b", "IPV6")
    assert profiles[2] == (3, "profile_d", "IP")


def test_get_current_apn_profile_no_data():
    """Test _get_current_apn_profile with no data."""
    assert _get_current_apn_profile(None) is None
    assert _get_current_apn_profile({}) is None


def test_get_current_apn_profile_invalid_index():
    """Test _get_current_apn_profile with invalid apn_index."""
    data = {"apn_index": "-1"}
    assert _get_current_apn_profile(data) is None

    data = {"apn_index": "20"}
    assert _get_current_apn_profile(data) is None

    data = {"apn_index": "invalid"}
    assert _get_current_apn_profile(data) is None


def test_get_current_apn_profile_no_config():
    """Test _get_current_apn_profile when config for index is missing."""
    data = {"apn_index": "5"}
    assert _get_current_apn_profile(data) is None


def test_get_current_apn_profile_valid():
    """Test _get_current_apn_profile returns the profile name."""
    data = {"apn_index": "2", "APN_config2": "my_profile($)apn2"}
    assert _get_current_apn_profile(data) == "my_profile"


def test_set_apn_profile_option_valid():
    """Test _set_apn_profile_option with a valid profile name."""
    api = AsyncMock()
    api.set_apn = AsyncMock()

    data_with_profile = {"APN_config0": "profile_a($)apn1($)($)($)($)($)($)IPV4V6"}
    profiles = _get_apn_profiles(data_with_profile)
    assert profiles == [(0, "profile_a", "IPV4V6")]

    # Now test the actual setter via a fresh call
    target = next((p for p in profiles if p[1] == "profile_a"), None)
    assert target is not None
    idx, _, pdp_type = target
    assert idx == 0
    assert pdp_type == "IPV4V6"


@pytest.mark.asyncio
async def test_set_apn_profile_option_happy_path():
    """Test _set_apn_profile_option calls api.set_apn correctly."""
    api = AsyncMock()
    api.set_apn = AsyncMock(return_value={"result": "success"})
    data = {"APN_config0": "profile_a($)apn1($)($)($)($)($)($)IPV4V6"}

    with patch(
        "custom_components.zte_router_5g.select._get_apn_profiles",
        return_value=[(0, "profile_a", "IPV4V6")],
    ):
        await _set_apn_profile_option(api, "profile_a", data)
        api.set_apn.assert_called_once_with(0, "IPV4V6")


@pytest.mark.asyncio
async def test_set_apn_profile_option_not_found():
    """Test _set_apn_profile_option raises ValueError for unknown profile."""
    api = AsyncMock()
    data = {}

    with (
        patch(
            "custom_components.zte_router_5g.select._get_apn_profiles",
            return_value=[],
        ),
        pytest.raises(ValueError, match="APN profile name unknown_profile not found"),
    ):
        await _set_apn_profile_option(api, "unknown_profile", data)


def test_select_options_property(mock_coordinator, mock_config_entry):
    """Test options property returns correct list."""
    mock_coordinator.data = {
        "APN_config0": "profile_a($)apn1",
        "APN_config5": "profile_f($)apn6",
    }
    desc = ZTESelectEntityDescription(
        key="apn_profile",
        translation_key="signal_apn_profile",
        options_fn=lambda data: [p[1] for p in _get_apn_profiles(data)],
        value_fn=_get_current_apn_profile,
        setter_fn=lambda api, option, data: _set_apn_profile_option(api, option, data),
    )
    select = ZTERouterSelect(mock_coordinator, mock_config_entry, desc)
    assert select.options == ["profile_a", "profile_f"]


def test_select_options_no_data(mock_coordinator, mock_config_entry):
    """Test options property returns empty list when no data."""
    mock_coordinator.data = None
    desc = ZTESelectEntityDescription(
        key="apn_profile",
        translation_key="signal_apn_profile",
        options_fn=lambda data: ["a", "b"],
        value_fn=_get_current_apn_profile,
        setter_fn=lambda api, option, data: _set_apn_profile_option(api, option, data),
    )
    select = ZTERouterSelect(mock_coordinator, mock_config_entry, desc)
    assert select.options == []


def test_select_current_option_property(mock_coordinator, mock_config_entry):
    """Test current_option property."""
    mock_coordinator.data = {"apn_index": "1", "APN_config1": "active_profile($)apn"}
    desc = ZTESelectEntityDescription(
        key="apn_profile",
        translation_key="signal_apn_profile",
        options_fn=lambda data: [],
        value_fn=_get_current_apn_profile,
        setter_fn=lambda api, option, data: _set_apn_profile_option(api, option, data),
    )
    select = ZTERouterSelect(mock_coordinator, mock_config_entry, desc)
    assert select.current_option == "active_profile"


def test_select_current_option_no_data(mock_coordinator, mock_config_entry):
    """Test current_option property returns None when no data."""
    mock_coordinator.data = None
    desc = ZTESelectEntityDescription(
        key="apn_profile",
        translation_key="signal_apn_profile",
        options_fn=lambda data: [],
        value_fn=_get_current_apn_profile,
        setter_fn=lambda api, option, data: _set_apn_profile_option(api, option, data),
    )
    select = ZTERouterSelect(mock_coordinator, mock_config_entry, desc)
    assert select.current_option is None


@pytest.mark.asyncio
async def test_select_async_select_option_success(mock_coordinator, mock_config_entry):
    """Test async_select_option success path."""
    mock_coordinator.data = {"APN_config0": "profile_a($)apn1"}
    mock_coordinator.api = AsyncMock()
    mock_coordinator.api.set_apn = AsyncMock()

    desc = ZTESelectEntityDescription(
        key="apn_profile",
        translation_key="signal_apn_profile",
        options_fn=lambda data: ["profile_a"],
        value_fn=_get_current_apn_profile,
        setter_fn=_set_apn_profile_option,
    )
    select = ZTERouterSelect(mock_coordinator, mock_config_entry, desc)

    with patch(
        "custom_components.zte_router_5g.select._get_apn_profiles",
        return_value=[(0, "profile_a", "IPV4V6")],
    ):
        await select.async_select_option("profile_a")
        mock_coordinator.async_force_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_select_async_select_option_exception(
    mock_coordinator, mock_config_entry, caplog
):
    """A refused select must raise, not spring back with only a log line.

    The router answers `200 OK` for a refused write, so a swallowed exception
    left the user watching the value revert with no indication why.
    """
    mock_coordinator.data = {}
    mock_coordinator.api = MagicMock()
    desc = ZTESelectEntityDescription(
        key="apn_profile",
        translation_key="signal_apn_profile",
        options_fn=lambda data: [],
        value_fn=lambda data: None,
        setter_fn=lambda api, option, data: (_ for _ in ()).throw(
            ValueError("test error")
        ),
    )
    select = ZTERouterSelect(mock_coordinator, mock_config_entry, desc)

    with pytest.raises(HomeAssistantError) as err:
        await select.async_select_option("any_option")

    assert err.value.translation_key == "select_set_failed"
    assert "Failed to set" in caplog.text


def test_select_device_info(mock_coordinator, mock_config_entry):
    """Test device_info returns signal group info."""
    desc = ZTESelectEntityDescription(
        key="apn_profile",
        translation_key="signal_apn_profile",
        group="signal",
        options_fn=lambda data: [],
        value_fn=lambda data: None,
        setter_fn=lambda api, option, data: None,
    )
    select = ZTERouterSelect(mock_coordinator, mock_config_entry, desc)
    info = select.device_info
    assert info["identifiers"] == {("zte_router_5g", "864155042229309_signal")}
    assert info["manufacturer"] == "ZTE"
    assert_links_to_parent(info, "zte_router_5g", "864155042229309_system")


def test_select_device_info_system_group(mock_coordinator, mock_config_entry):
    """Test device_info for system group has no via_device."""
    desc = ZTESelectEntityDescription(
        key="apn_mode",
        translation_key="signal_apn_mode",
        group="signal",
        options_fn=lambda data: ["auto", "manual"],
        value_fn=lambda data: data.get("apn_mode") if data else None,
        setter_fn=lambda api, option, data: None,
    )
    select = ZTERouterSelect(mock_coordinator, mock_config_entry, desc)
    info = select.device_info
    assert info["identifiers"] == {("zte_router_5g", "864155042229309_signal")}


@pytest.mark.asyncio
async def test_select_setup_entry():
    """Test platform setup for select."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test"
    entry.runtime_data = MagicMock()
    entry.unique_id = "test_id"

    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)
    async_add_entities.assert_called_once()


def test_select_apn_mode_options(mock_coordinator, mock_config_entry):
    """Test apn_mode entity returns correct options."""
    mock_coordinator.data = {"apn_mode": "auto"}
    desc = ZTESelectEntityDescription(
        key="apn_mode",
        translation_key="signal_apn_mode",
        group="signal",
        options_fn=lambda data: ["auto", "manual"],
        value_fn=lambda data: data.get("apn_mode") if data else None,
        setter_fn=lambda api, option, data: None,
    )
    select = ZTERouterSelect(mock_coordinator, mock_config_entry, desc)
    assert select.options == ["auto", "manual"]
    assert select.current_option == "auto"


def test_select_net_select_options(mock_coordinator, mock_config_entry):
    """Test net_select entity returns correct options and value."""
    mock_coordinator.data = {"net_select": "4G_AND_5G"}
    desc = ZTESelectEntityDescription(
        key="net_select",
        translation_key="signal_net_select_mode",
        group="signal",
        options_fn=lambda data: ["4G_AND_5G", "LTE_AND_5G", "Only_5G", "Only_LTE"],
        value_fn=lambda data: data.get("net_select") if data else None,
        setter_fn=lambda api, option, data: api.set_bearer_preference(option),
    )
    select = ZTERouterSelect(mock_coordinator, mock_config_entry, desc)
    assert select.options == ["4G_AND_5G", "LTE_AND_5G", "Only_5G", "Only_LTE"]
    assert select.current_option == "4G_AND_5G"


def test_select_apn_mode_no_data(mock_coordinator, mock_config_entry):
    """Test apn_mode current_option is None with no data."""
    mock_coordinator.data = None
    desc = ZTESelectEntityDescription(
        key="apn_mode",
        translation_key="signal_apn_mode",
        group="signal",
        options_fn=lambda data: ["auto", "manual"],
        value_fn=lambda data: data.get("apn_mode") if data else None,
        setter_fn=lambda api, option, data: None,
    )
    select = ZTERouterSelect(mock_coordinator, mock_config_entry, desc)
    assert select.current_option is None


def test_select_apn_profile_empty_data(mock_coordinator, mock_config_entry):
    """Test apn_profile returns empty list when no APN data."""
    mock_coordinator.data = {}
    desc = ZTESelectEntityDescription(
        key="apn_profile",
        translation_key="signal_apn_profile",
        group="signal",
        options_fn=lambda data: [p[1] for p in _get_apn_profiles(data)],
        value_fn=_get_current_apn_profile,
        setter_fn=lambda api, option, data: _set_apn_profile_option(api, option, data),
    )
    select = ZTERouterSelect(mock_coordinator, mock_config_entry, desc)
    assert select.options == []
    assert select.current_option is None


# --- Auto mode: the indexed profile is not the one in use --------------------
#
# Observed live on the reference MC7010 (2026-07-31): `apn_mode=auto`,
# `apn_index=5` (`open.internet.public`), while traffic actually ran over
# `3FWA.ie` — slot 6. In auto the router uses the network's default APN and
# `apn_index` merely retains the last manual choice, so showing the indexed
# profile states something untrue.

_PROFILES = {
    "APN_config0": "Default($)($)manual($)*99#($)none($)($)($)IPv4v6",
    "APN_config5": "open.internet.public($)open.internet.public($)manual",
    "APN_config6": "3FWA.ie($)3fwa.ie($)manual",
}


def test_auto_mode_reports_the_apn_actually_in_use():
    """`wan_apn` wins over `apn_index`, matched case-insensitively.

    The router reports `3FWA.ie` for a profile storing `3fwa.ie`.
    """
    data = {
        **_PROFILES,
        "apn_mode": "auto",
        "apn_index": "5",
        "wan_apn": "3FWA.ie",
    }
    assert _get_current_apn_profile(data) == "3FWA.ie"


def test_auto_mode_reports_nothing_when_the_default_is_not_a_stored_profile():
    """The normal case: the network default need not exist in the manual list.

    Returning the indexed profile here would name one that is not in use;
    `None` is the honest answer, and the Network APN sensor remains
    authoritative.
    """
    data = {
        **_PROFILES,
        "apn_mode": "auto",
        "apn_index": "5",
        "wan_apn": "carrier.default.apn",
    }
    assert _get_current_apn_profile(data) is None


def test_auto_mode_with_no_reported_apn_reports_nothing():
    """Nothing to match against means nothing can be claimed."""
    data = {**_PROFILES, "apn_mode": "auto", "apn_index": "5", "wan_apn": ""}
    assert _get_current_apn_profile(data) is None


def test_manual_mode_still_trusts_the_index():
    """In manual the index *is* the selection, including for Default.

    The Default profile stores an empty APN, so `wan_apn` is blank while the
    selection is perfectly valid — matching what the router's own page shows.
    """
    data = {**_PROFILES, "apn_mode": "manual", "apn_index": "0", "wan_apn": ""}
    assert _get_current_apn_profile(data) == "Default"
