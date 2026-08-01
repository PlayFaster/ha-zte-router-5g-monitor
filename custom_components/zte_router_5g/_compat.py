"""Device-registry compatibility across Home Assistant versions.

HA 2026.8 makes a device belong to a single config entry and deprecates several
registry surfaces (removed in 2027.8): the ambiguous ``async_get_device`` and the
``DeviceInfo.via_device`` identifier tuple. This integration stays **floor-free**
— one behavior on <=2026.7 and on post-2027.8 alike — by feature-detecting each
surface and using the new API where present, the old one otherwise.

Detection probes the HA **classes** (not instances), so it reflects the actually
installed HA and is not fooled by a ``MagicMock`` registry in tests. The boolean
is a module global so tests can patch it to exercise either path regardless of
the HA version the suite runs against.

Ported from ``unifi_network_monitor``, which implemented and validated this first
— see that project's ``.notes/device_registry/device_model_2026_08.md`` for the
full rationale. Its third shim (``owning_entry_ids``, wrapping
``DeviceEntry.config_entries``) is deliberately **not** carried over: this
integration never inspects a device's owning entries, and an unused shim would be
dead code.
"""

from __future__ import annotations

from typing import Any, cast

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

# Both deprecated surfaces land together in 2026.8; one probe covers the pair.
_HAS_BY_IDENTIFIER = hasattr(dr.DeviceRegistry, "async_get_device_by_identifier")


def device_by_identifier(
    dev_reg: dr.DeviceRegistry, domain: str, ident: str, entry_id: str
) -> dr.DeviceEntry | None:
    """Look up a device by ``(domain, ident)``.

    2026.8+ scopes the lookup to the owning config entry
    (``async_get_device_by_identifier``); older HA takes an ``identifiers`` set.
    """
    if _HAS_BY_IDENTIFIER:
        # 2026.8+ only; cast past the older type stubs that lack this method.
        return cast(
            "dr.DeviceEntry | None",
            cast(Any, dev_reg).async_get_device_by_identifier(
                (domain, ident), entry_id
            ),
        )
    return dev_reg.async_get_device(identifiers={(domain, ident)})


def via_device_link(
    hass: HomeAssistant, domain: str, parent_ident: str, entry_id: str
) -> dict[str, Any]:
    """Return the ``DeviceInfo`` kwarg linking a sub-device to the root.

    2026.8+ deprecates the ``via_device`` identifier tuple in favour of
    ``via_device_id`` (a resolved device id), because identifiers are no longer
    globally unique — so resolve the parent's id from its identifier. Older HA
    gets the ``via_device`` tuple unchanged. An unresolved parent yields no link
    (the same outcome a dangling tuple would have had).

    Resolution is safe at entity-construction time because ``async_setup_entry``
    registers the System root device *before* forwarding platforms
    (dev_standards Section 3), so the parent always exists by the time a
    sub-device builds its ``DeviceInfo``.
    """
    if _HAS_BY_IDENTIFIER:
        # 2026.8+ only; cast past the older type stubs that lack this method.
        parent = cast(Any, dr.async_get(hass)).async_get_device_by_identifier(
            (domain, parent_ident), entry_id
        )
        return {"via_device_id": parent.id} if parent is not None else {}
    return {"via_device": (domain, parent_ident)}
