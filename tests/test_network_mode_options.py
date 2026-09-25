"""Network Mode Selection offers the router's own list (3.4.4-dev1).

The options come from `AUTO_MODES` in the model-specific `config.js`, which is
what the router's own network mode page offers. Nothing learned means the
current value alone and no change; nothing at all means unavailable. The fixed
four values the select used to offer are gone: the MC888 Pro reads
`WL_AND_5G`, which was not among them, and a value outside a router's own list
has never been tested as a write.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.zte_router_5g import device_profile, web_sources
from custom_components.zte_router_5g.diagnostics import _device_files_summary
from custom_components.zte_router_5g.select import SELECT_TYPES, ZTERouterSelect
from homeassistant.exceptions import HomeAssistantError

# The MC7010's model-specific files as served on 2026-09-25, shortened to the
# parts the parser reads.
_DEVICE_CONFIG = (
    'define(function(){return{INCLUDE_MOBILE:!1,HAS_FOTA:!0,PRODUCT_TYPE:"CPE",'
    'sysLogModes:[{name:"ALL",value:"all"},{name:"SMS",value:"sms"}],'
    'AUTO_MODES:[{name:"auto",value:"4G_AND_5G"},{name:"5G NSA",value:"LTE_AND_5G"},'
    '{name:"5G SA",value:"Only_5G"},{name:"4G Only",value:"Only_LTE"}],'
    'VPN_TYPE_MODES:[{name:"PPTP",value:"PPTP"},{name:"L2TP",value:"L2TP"}]}});'
)
_MENU_BRIDGE = (
    'define(function(){return[{hash:"#login",path:"login",level:"1"},'
    '{hash:"#home",path:"home",level:"1"},{hash:"#net_select",path:"network/net_select"},'
    '{hash:"#group_all",path:"phonebook/phonebook"},{hash:"#group_common",path:"phonebook/phonebook"}]});'
)
SOURCES = {
    "js/config/config.js": 'define({DEVICE:"cpe/MF253V",HAS_SMS:!0})',
    "js/config/cpe/MF253V/config.js": _DEVICE_CONFIG,
    "js/config/cpe/MF253V/menu_bridge.js": _MENU_BRIDGE,
    "js/config/cpe/MF253V/menu_4ggateway.js": 'define(function(){return[{hash:"#a",path:"adm/lan"}]});',
}
MC7010_MODES = ["4G_AND_5G", "LTE_AND_5G", "Only_5G", "Only_LTE"]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_auto_modes_parse_in_the_routers_order() -> None:
    """Auto modes parse in the routers order."""
    parsed = device_profile.parse_device_config(SOURCES)
    assert parsed["auto_modes"] == MC7010_MODES
    assert parsed["path"] == "js/config/cpe/MF253V/config.js"


def test_every_option_list_and_flag_of_the_device_file_is_read() -> None:
    """Every option list and flag of the device file is read."""
    parsed = device_profile.parse_device_config(SOURCES)
    assert parsed["option_lists"]["VPN_TYPE_MODES"] == ["PPTP", "L2TP"]
    assert parsed["option_lists"]["sysLogModes"] == ["all", "sms"]
    assert parsed["flags"]["HAS_FOTA"] is True
    assert parsed["flags"]["INCLUDE_MOBILE"] is False


def test_the_general_config_is_not_taken_for_the_device_file() -> None:
    """`js/config/config.js` has no model directory and declares no modes."""
    assert (
        device_profile.parse_device_config(
            {"js/config/config.js": SOURCES["js/config/config.js"]}
        )
        == {}
    )


def test_a_list_that_does_not_parse_is_not_learned() -> None:
    """A list that does not parse is not learned."""
    broken = {"js/config/cpe/X/config.js": "define({AUTO_MODES:BUILD_MODES()})"}
    parsed = device_profile.parse_device_config(broken)
    assert "auto_modes" not in parsed
    profile = device_profile.parse_profile(broken, "FW")
    assert "device_config.auto_modes" in profile["unlearned"]
    assert device_profile.auto_modes(profile) is None


def test_the_profile_carries_the_learned_modes() -> None:
    """The profile carries the learned modes."""
    profile = device_profile.parse_profile(SOURCES, "FW")
    assert device_profile.auto_modes(profile) == MC7010_MODES
    assert "device_config.auto_modes" not in profile["unlearned"]
    assert profile["profile_version"] == 2


def test_menus_list_each_page_once_in_order() -> None:
    """Menus list each page once in order."""
    menus = device_profile.parse_menus(SOURCES)
    assert menus["menu_bridge"] == [
        "login",
        "home",
        "network/net_select",
        "phonebook/phonebook",
    ]
    assert menus["menu_4ggateway"] == ["adm/lan"]


@pytest.mark.parametrize(
    ("mode", "menu"),
    [
        ("LTE_BRIDGE", "menu_bridge"),
        ("AUTO_DHCP", "menu_pppoe"),
        ("STATIC", "menu_pppoe"),
        ("AUTO_LTE_GATEWAY", "menu_4ggateway"),
        ("PPP", "menu_4ggateway"),
        (None, "menu_4ggateway"),
    ],
)
def test_the_menu_follows_the_wan_mode_as_main_js_chooses_it(mode, menu) -> None:
    """The menu follows the wan mode as main js chooses it."""
    assert device_profile.menu_for_mode(mode) == menu


def test_the_download_summarises_the_menu_for_the_current_mode() -> None:
    """The download summarises the menu for the current mode."""
    profile = device_profile.parse_profile(SOURCES, "FW")
    coordinator = MagicMock()
    coordinator.data = {"opms_wan_mode": "LTE_BRIDGE"}
    summary = _device_files_summary(profile, coordinator)
    assert summary["auto_modes"] == MC7010_MODES
    assert summary["current_menu"] == "menu_bridge"
    assert summary["current_menu_pages"][0] == "login"
    assert summary["menus_read"] == ["menu_4ggateway", "menu_bridge"]
    assert summary["flags"]["PRODUCT_TYPE"] == "CPE"


# ---------------------------------------------------------------------------
# The crawl
# ---------------------------------------------------------------------------


def test_the_crawl_asks_for_all_three_device_menus() -> None:
    """The loader picks one by `opms_wan_mode`, which the crawl does not read."""
    assert set(web_sources._DEVICE_MODULES) >= {
        "config.js",
        "menu_bridge.js",
        "menu_4ggateway.js",
        "menu_pppoe.js",
    }


# ---------------------------------------------------------------------------
# The select
# ---------------------------------------------------------------------------


def _select(mock_coordinator, mock_config_entry, data: Any, profile: Any):
    mock_coordinator.data = data
    mock_coordinator.last_update_success = True
    mock_coordinator.api.profile = profile
    mock_coordinator.api.set_bearer_preference = AsyncMock()
    description = next(d for d in SELECT_TYPES if d.key == "net_select")
    return ZTERouterSelect(mock_coordinator, mock_config_entry, description)


def _learned(modes: list[str]) -> dict[str, Any]:
    return {"device_config": {"auto_modes": modes}}


def test_the_learned_list_is_offered(mock_coordinator, mock_config_entry) -> None:
    """The learned list is offered."""
    select = _select(
        mock_coordinator,
        mock_config_entry,
        {"net_select": "4G_AND_5G"},
        _learned(MC7010_MODES),
    )
    assert select.options == MC7010_MODES
    assert select.available


def test_a_current_value_outside_the_list_is_added(
    mock_coordinator, mock_config_entry
) -> None:
    """The MC888 Pro's `WL_AND_5G`: shown as the state, and only while current."""
    select = _select(
        mock_coordinator,
        mock_config_entry,
        {"network_net_select": "WL_AND_5G"},
        _learned(MC7010_MODES),
    )
    assert select.current_option == "WL_AND_5G"
    assert select.options == [*MC7010_MODES, "WL_AND_5G"]


def test_nothing_learned_offers_only_the_current_value(
    mock_coordinator, mock_config_entry
) -> None:
    """Nothing learned offers only the current value."""
    select = _select(
        mock_coordinator, mock_config_entry, {"net_select": "Only_LTE"}, {}
    )
    assert select.options == ["Only_LTE"]
    assert select.available


def test_nothing_learned_and_no_value_is_unavailable(
    mock_coordinator, mock_config_entry
) -> None:
    """Nothing learned and no value is unavailable."""
    select = _select(mock_coordinator, mock_config_entry, {"net_select": ""}, {})
    assert select.options == []
    assert not select.available


async def test_a_change_is_refused_while_nothing_is_learned(
    mock_coordinator, mock_config_entry
) -> None:
    """A change is refused while nothing is learned."""
    select = _select(
        mock_coordinator, mock_config_entry, {"net_select": "Only_LTE"}, {}
    )
    with pytest.raises(HomeAssistantError) as err:
        await select.async_select_option("Only_LTE")
    assert err.value.translation_key == "select_options_not_learned"
    mock_coordinator.api.set_bearer_preference.assert_not_awaited()


async def test_a_value_outside_the_learned_list_is_never_written(
    mock_coordinator, mock_config_entry
) -> None:
    """A value outside the learned list is never written."""
    select = _select(
        mock_coordinator,
        mock_config_entry,
        {"net_select": "WL_AND_5G"},
        _learned(MC7010_MODES),
    )
    with pytest.raises(HomeAssistantError) as err:
        await select.async_select_option("WL_AND_5G")
    assert err.value.translation_key == "select_option_not_offered"
    mock_coordinator.api.set_bearer_preference.assert_not_awaited()


async def test_a_learned_value_is_written(mock_coordinator, mock_config_entry) -> None:
    """A learned value is written."""
    select = _select(
        mock_coordinator,
        mock_config_entry,
        {"net_select": "4G_AND_5G"},
        _learned(MC7010_MODES),
    )
    await select.async_select_option("LTE_AND_5G")
    mock_coordinator.api.set_bearer_preference.assert_awaited_once_with("LTE_AND_5G")


# ---------------------------------------------------------------------------
# Upgrade and learning
# ---------------------------------------------------------------------------


async def test_a_version_1_profile_is_discarded_and_the_relearn_offers_the_list(
    mock_coordinator, mock_config_entry
) -> None:
    """The upgrade sequence: a 3.4.3 profile, the first 3.4.4 start, the learn."""
    from .test_device_profile_lifecycle import _coordinator

    coordinator = _coordinator()
    stored_by_343 = {"profile_version": 1, "firmware": "FW1", "token": {}}
    with patch("custom_components.zte_router_5g.coordinator.Store") as store:
        store.return_value.async_load = AsyncMock(return_value=stored_by_343)
        await coordinator.async_load_profile()
    assert coordinator.api.profile == {}

    # Before the learn: the current value only.
    select = _select(
        mock_coordinator, mock_config_entry, {"net_select": "4G_AND_5G"}, {}
    )
    assert select.options == ["4G_AND_5G"]

    # The learn runs because no profile is held, even on the same firmware.
    coordinator.api.get_version = AsyncMock(return_value="FW1")
    coordinator.api.learn_profile = AsyncMock(
        return_value=device_profile.parse_profile(SOURCES, "FW1")
    )
    coordinator.data = {"net_select": "4G_AND_5G"}
    await coordinator.async_learn_profile()
    coordinator.api.learn_profile.assert_awaited_once()

    mock_coordinator.api.profile = coordinator.api.learn_profile.return_value
    assert select.options == MC7010_MODES


async def test_entities_are_re_rendered_when_a_profile_is_learned() -> None:
    """Otherwise the options wait for the next poll, and forever while paused.

    Found in the 3.4.4-dev1 live check: the profile was learned three seconds
    after the select wrote its state, with polling paused, and the select kept
    offering the current value alone.
    """
    from .test_device_profile_lifecycle import _coordinator

    coordinator = _coordinator()
    coordinator.data = {"net_select": "4G_AND_5G"}
    coordinator.api.get_version = AsyncMock(return_value="FW1")
    coordinator.api.learn_profile = AsyncMock(
        return_value=device_profile.parse_profile(SOURCES, "FW1")
    )
    await coordinator.async_learn_profile()
    coordinator.async_update_listeners.assert_called_once()


# ---------------------------------------------------------------------------
# Defaults and display (3.4.4 plan §3.6 and §3.7)
# ---------------------------------------------------------------------------


def test_the_owners_defaults_for_new_installs() -> None:
    """The owners defaults for new installs."""
    from custom_components.zte_router_5g.sensor import SENSOR_TYPES
    from custom_components.zte_router_5g.switch import SWITCH_TYPES
    from homeassistant.const import UnitOfTime

    sensors = {d.key: d for d in SENSOR_TYPES}
    for key in ("total_data_bytes", "total_time"):
        assert sensors[key].entity_registry_enabled_default is not False, key
    assert (
        next(
            d for d in SWITCH_TYPES if d.key == "data_limit_switch"
        ).entity_registry_enabled_default
        is not False
    )
    for key in ("connection_duration", "realtime_time", "total_time"):
        assert sensors[key].suggested_unit_of_measurement == UnitOfTime.HOURS, key
        assert sensors[key].suggested_display_precision is None, key
    # Matching the other duration sensors: no long-term statistics.
    assert sensors["total_time"].state_class is None
    assert sensors["total_data_bytes"].state_class is not None


def test_a_select_without_a_learned_list_has_none(
    mock_coordinator, mock_config_entry
) -> None:
    """The APN selects take their options from polled data, not the profile."""
    description = next(d for d in SELECT_TYPES if d.key == "apn_mode")
    select = ZTERouterSelect(mock_coordinator, mock_config_entry, description)
    assert select._learned_options() is None


def test_a_list_of_objects_without_values_is_not_an_option_list() -> None:
    """A named array of objects with no `value` field is skipped."""
    parsed = device_profile.parse_device_config(
        {"js/config/cpe/X/config.js": 'define({LABELS:[{name:"a"},{name:"b"}]})'}
    )
    assert parsed["option_lists"] == {}
