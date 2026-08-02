"""Device-registry compatibility shims — both branches, forced.

The suite runs against one Home Assistant version at a time, so the branch that
version does *not* take would otherwise never execute. Patching the module-level
detection flag exercises each path regardless of the installed HA, which is the
whole point of a floor-free shim: the code has to be correct on <=2026.7 and on
post-2027.8 alike.
"""

from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant

from custom_components.zte_router_5g import _compat
from custom_components.zte_router_5g.const import DOMAIN

IDENT = "864155042229309_system"
ENTRY_ID = "entry-1"


# --------------------------------------------------------------------------
# device_by_identifier
# --------------------------------------------------------------------------


def test_device_by_identifier_legacy_branch() -> None:
    """<=2026.7 takes an `identifiers` set."""
    dev_reg = MagicMock()
    with patch.object(_compat, "_HAS_BY_IDENTIFIER", False):
        result = _compat.device_by_identifier(dev_reg, DOMAIN, IDENT, ENTRY_ID)

    dev_reg.async_get_device.assert_called_once_with(identifiers={(DOMAIN, IDENT)})
    dev_reg.async_get_device_by_identifier.assert_not_called()
    assert result is dev_reg.async_get_device.return_value


def test_device_by_identifier_modern_branch() -> None:
    """2026.8+ scopes the lookup to the owning config entry."""
    dev_reg = MagicMock()
    with patch.object(_compat, "_HAS_BY_IDENTIFIER", True):
        result = _compat.device_by_identifier(dev_reg, DOMAIN, IDENT, ENTRY_ID)

    dev_reg.async_get_device_by_identifier.assert_called_once_with(
        (DOMAIN, IDENT), ENTRY_ID
    )
    dev_reg.async_get_device.assert_not_called()
    assert result is dev_reg.async_get_device_by_identifier.return_value


# --------------------------------------------------------------------------
# via_device_link
# --------------------------------------------------------------------------


def test_via_device_link_legacy_branch(hass: HomeAssistant) -> None:
    """<=2026.7 gets the identifier tuple unchanged."""
    with patch.object(_compat, "_HAS_BY_IDENTIFIER", False):
        link = _compat.via_device_link(hass, DOMAIN, IDENT, ENTRY_ID)

    assert link == {"via_device": (DOMAIN, IDENT)}


def test_via_device_link_modern_branch(hass: HomeAssistant) -> None:
    """2026.8+ resolves the parent and returns its device id.

    Identifiers stop being globally unique in 2026.8, which is why the link has
    to carry a resolved id rather than a tuple.
    """
    parent = MagicMock()
    parent.id = "device-abc"
    registry = MagicMock()
    registry.async_get_device_by_identifier.return_value = parent

    with (
        patch.object(_compat, "_HAS_BY_IDENTIFIER", True),
        patch.object(_compat.dr, "async_get", return_value=registry),
    ):
        link = _compat.via_device_link(hass, DOMAIN, IDENT, ENTRY_ID)

    assert link == {"via_device_id": "device-abc"}
    registry.async_get_device_by_identifier.assert_called_once_with(
        (DOMAIN, IDENT), ENTRY_ID
    )


def test_via_device_link_unresolved_parent_yields_no_link(
    hass: HomeAssistant,
) -> None:
    """An unresolvable parent must not produce a broken link.

    Returning no link is the same outcome a dangling `via_device` tuple had on
    older HA, so a sub-device simply appears unparented rather than erroring.
    """
    registry = MagicMock()
    registry.async_get_device_by_identifier.return_value = None

    with (
        patch.object(_compat, "_HAS_BY_IDENTIFIER", True),
        patch.object(_compat.dr, "async_get", return_value=registry),
    ):
        link = _compat.via_device_link(hass, DOMAIN, IDENT, ENTRY_ID)

    assert link == {}


def test_detection_probes_the_ha_class_not_an_instance() -> None:
    """The flag must reflect installed HA, not whatever a test passes in.

    Probing an instance would let a MagicMock registry answer `True` to any
    hasattr, silently sending the whole suite down the modern branch.
    """
    from homeassistant.helpers import device_registry as dr

    assert (
        hasattr(dr.DeviceRegistry, "async_get_device_by_identifier")
        == _compat._HAS_BY_IDENTIFIER
    )
