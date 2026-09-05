"""Which entities are enabled by default, per router model.

An entity description carries one `entity_registry_enabled_default`, so the
same defaults ship to every device. That suits a single-model integration and
does not survive contact with a family whose members answer different keys: on
an MC888 Pro six enabled sensors are permanently blank, while RSSI and SINR —
the only signal-quality figures that firmware reports — are off.

The overlay states the intended suite for a model rather than filtering blanks.
Being populated is not the criterion in either direction: plenty of populated
fields are low-value and stay off everywhere, and an entity is enabled here
because it is worth a user's attention on that hardware.

**One resolver, two callers.** `default_enabled` is called by each platform
when it builds an entity, and by the `reset_entities` action when it restores
defaults later. If those two read different sources they disagree, and a reset
would undo the overlay every time it ran.

**It only takes effect at first registration.** Home Assistant reads
`entity_registry_enabled_default` when an entity is first added and never
again, so an overlay added today does nothing for an installation that already
exists. `reset_entities` is the retrofit path, which is why it must resolve
through this function rather than through the description.
"""

from __future__ import annotations

from typing import Final, Protocol


class _HasEnabledDefault(Protocol):
    """The part of an entity description this module reads."""

    key: str
    entity_registry_enabled_default: bool


# Model to the entities whose default this model overrides.
#
# Matched as a **substring** of the model the router reports, longest key
# first, so a specific entry can override a general one without restructuring
# the lookup. Family matching is deliberate: the `network_` vocabulary and the
# `zsidn` session cookie are firmware-family behaviours rather than variant
# ones, and `api._hash` already selects SHA-256 on `MC888` or `MC889`
# appearing anywhere in the version string — a higher-stakes decision than an
# entity default.
#
# Seeded from measurement only. Every entry below is a reading from the
# 2026-09-02 diagnostics download attached to issue #56, not an inference
# about what a model probably supports.
MODEL_OVERLAY: Final[dict[str, dict[str, bool]]] = {
    # ZTE MC888 Pro, firmware `CR_ABPLMC888PROV1.0.1B04`.
    #
    # The bare LTE vocabulary is present and empty on this firmware — its own
    # web pages request `lte_rsrq`, `lte_rssi` and `lte_snr` and the router
    # answers blank — while the `network_` vocabulary carries the LTE RSRP.
    # The five disabled here have no spelling that this device populates.
    #
    # `enodeb_id` was disabled here when this overlay was written and is not
    # any more. It was measured blank on the download, but the derivation
    # added in the same release fills it from the cell identity, so the entry
    # was suppressing a sensor that works.
    #
    # RSSI and SINR are enabled because the unqualified `network_` names are
    # the only signal-quality figures this device reports. They stay off by
    # default elsewhere, where the technology-specific sensors carry more.
    "MC888": {
        "lte_rsrq": False,
        "lte_rssi": False,
        "lte_snr": False,
        "z5g_rssi": False,
        "wan_connect_status": False,
        "rssi": True,
        "sinr": True,
    },
    # ZTE MC7010, firmware `IRL_H3G_MC7010DV1.0.0B03`.
    #
    # An outdoor unit with no WiFi of its own. It answers neither
    # `wifi_access_sta_num` nor `wifi_onoff_state`, so the two sensors that
    # read them are off here and on everywhere else — including hardware
    # nobody has measured, where a router serving WiFi is the likelier case.
    "MC7010": {
        "wifi_clients": False,
        "wifi_enabled": False,
    },
}


def default_enabled(description: _HasEnabledDefault, model: str | None) -> bool:
    """Return whether this entity should be enabled by default on this model.

    Falls back to the description's own flag, so an unrecognised model gets
    the curated default the integration was built around and a model with no
    opinion about a given entity keeps it.
    """
    if model:
        for name in sorted(MODEL_OVERLAY, key=len, reverse=True):
            if name in model:
                override = MODEL_OVERLAY[name].get(description.key)
                if override is not None:
                    return override
                break
    return description.entity_registry_enabled_default
