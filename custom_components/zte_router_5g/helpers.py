"""Shared helpers for the ZTE Router 5G Monitor integration."""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo

from ._compat import via_device_link
from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import ZTERouterDataUpdateCoordinator

# Known model strings to detect from the wa_inner_version firmware string.
# e.g. 'IRL_H3G_MC7010DV1.0.0B01' → 'MC7010'
_KNOWN_MODELS = ["MC7010", "MC801", "MC888", "MC889"]


def get_first(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first key in `keys` that the router actually populated.

    Members of the `goform` family spell the same measurement differently, so
    an entity names every spelling it knows and takes whichever one arrives.
    A key that is present but empty counts as absent — this API answers with
    `""` for fields the hardware does not support, so `in data` alone is not
    enough to tell "supported" from "reported".

    Every key named here must also be requested in `api.py:get_all_data()`;
    an alias for a key that is never asked for can never fire.

    Lives here rather than in `sensor.py` because switches need it too: the
    MC888 Pro answers `flux_data_volume_limit_switch` and leaves the bare
    spelling empty, so a switch reading one spelling has no position to report
    on that hardware.
    """
    return next(
        (data[key] for key in keys if key in data and data[key] not in ("", None)),
        None,
    )


def get_router_model(coordinator_data: dict[str, Any] | None) -> str:
    """Extract the router model from coordinator data.

    Checks 'model_name' first (e.g. 'MC7010'), then falls back to parsing
    'wa_inner_version' (e.g. 'IRL_H3G_MC7010DV1.0.0B01').
    Returns 'ZTE Router' if no model is recognized.
    """
    if not coordinator_data:
        return "ZTE Router"

    # 1. Direct model name check
    model_name = coordinator_data.get("model_name")
    if model_name:
        return cast(str, model_name)

    # 2. Firmware version parsing fallback
    version = coordinator_data.get("wa_inner_version", "")
    for model in _KNOWN_MODELS:
        if model in version:
            return model
    return "ZTE Router"


# GSM 03.38 (3GPP TS 23.038) default alphabet. A message drawn entirely from
# this set fits 160 characters per SMS; anything outside it forces UCS-2 and
# drops the limit to 70. The router will not work this out for us — `send_sms`
# has to name the encoding, and naming the wrong one either mangles the text or
# wastes more than half the payload.
_GSM7_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
# The extension table. These are still GSM-7, but each costs two septets
# because it is sent as ESC + character, so they are counted separately by
# anything that cares about segment boundaries.
_GSM7_EXTENDED = "\f^{}\\[~]|€"

GSM7_CHARS = frozenset(_GSM7_BASIC + _GSM7_EXTENDED)


def is_gsm7(text: str) -> bool:
    """Return True when every character is in the GSM 03.38 alphabet.

    Used to pick `encode_type` for outgoing SMS. False means at least one
    character needs UCS-2 — a single emoji or curly quote is enough.
    """
    return all(char in GSM7_CHARS for char in text)


# E-UTRA downlink EARFCN ranges, 3GPP TS 36.101 Table 5.7.3-1. Ranges do not
# overlap, so the lookup is exact.
_EARFCN_BANDS: tuple[tuple[int, int, str], ...] = (
    (0, 599, "B1"),
    (600, 1199, "B2"),
    (1200, 1949, "B3"),
    (1950, 2399, "B4"),
    (2400, 2649, "B5"),
    (2650, 2749, "B6"),
    (2750, 3449, "B7"),
    (3450, 3799, "B8"),
    (3800, 4149, "B9"),
    (4150, 4749, "B10"),
    (4750, 4949, "B11"),
    (5010, 5179, "B12"),
    (5180, 5279, "B13"),
    (5280, 5379, "B14"),
    (5730, 5849, "B17"),
    (5850, 5999, "B18"),
    (6000, 6149, "B19"),
    (6150, 6449, "B20"),
    (6450, 6599, "B21"),
    (6600, 7399, "B22"),
    (7500, 7699, "B23"),
    (7700, 8039, "B24"),
    (8040, 8689, "B25"),
    (8690, 9039, "B26"),
    (9040, 9209, "B27"),
    (9210, 9659, "B28"),
    (9660, 9769, "B29"),
    (9770, 9869, "B30"),
    (9870, 9919, "B31"),
    (9920, 10359, "B32"),
    (36000, 36199, "B33"),
    (36200, 36349, "B34"),
    (36350, 36949, "B35"),
    (36950, 37549, "B36"),
    (37550, 37749, "B37"),
    (37750, 38249, "B38"),
    (38250, 38649, "B39"),
    (38650, 39649, "B40"),
    (39650, 41589, "B41"),
    (41590, 43589, "B42"),
    (43590, 45589, "B43"),
    (45590, 46589, "B44"),
    (46590, 46789, "B45"),
    (46790, 54539, "B46"),
    (54540, 55239, "B47"),
    (55240, 56739, "B48"),
    (56740, 58239, "B49"),
    (58240, 59089, "B50"),
    (59090, 59139, "B51"),
    (59140, 60139, "B52"),
    (60140, 60254, "B53"),
    (65536, 66435, "B65"),
    (66436, 67335, "B66"),
    (67336, 67535, "B67"),
    (67536, 67835, "B68"),
    (67836, 68335, "B69"),
    (68336, 68585, "B70"),
    (68586, 68935, "B71"),
    (68936, 68985, "B72"),
    (68986, 69035, "B73"),
    (69036, 69465, "B74"),
    (69466, 70315, "B75"),
    (70316, 70365, "B76"),
    (70366, 70545, "B85"),
    (70546, 70595, "B87"),
    (70596, 70645, "B88"),
)

# NR downlink ARFCN ranges, 3GPP TS 38.104 Table 5.4.2.3-1.
#
# Unlike E-UTRA these ranges genuinely overlap — n78 sits wholly inside n77,
# and n41 straddles n38 and n7 — so a channel number alone cannot identify the
# band. The list is ordered by what a ZTE CPE is actually likely to be camped
# on, first match wins, and the result is a best guess used only when the
# router declines to name the band itself. Where the router does report a name,
# that always takes precedence.
_ARFCN_BANDS: tuple[tuple[int, int, str], ...] = (
    (620000, 653333, "n78"),
    (693334, 733333, "n79"),
    (499200, 537999, "n41"),
    (422000, 434000, "n1"),
    (361000, 376000, "n3"),
    (185000, 192000, "n8"),
    (158200, 164200, "n20"),
    (151600, 160600, "n28"),
    (524000, 538000, "n7"),
    (460000, 480000, "n40"),
    (514000, 524000, "n38"),
    (173800, 178800, "n5"),
    (145800, 149200, "n12"),
    (123400, 130400, "n71"),
    (386000, 398000, "n2"),
    (386000, 399000, "n25"),
    (434001, 440000, "n66"),
    (399000, 404000, "n70"),
    (402000, 405000, "n34"),
    (636667, 646666, "n48"),
    (286400, 303400, "n50"),
    (285400, 286400, "n51"),
    (653334, 680000, "n77"),
    (2016667, 2070832, "n258"),
    (2054166, 2104165, "n257"),
    (2070833, 2084999, "n261"),
    (2229166, 2279165, "n260"),
)


def _channel_to_band(
    channel: int | str | None, table: tuple[tuple[int, int, str], ...]
) -> str | None:
    """Resolve a channel number against a range table, or None."""
    if channel in (None, ""):
        return None
    try:
        value = int(float(cast(Any, channel)))
    except (TypeError, ValueError):
        return None
    return next(
        (name for low, high, name in table if low <= value <= high),
        None,
    )


def earfcn_to_band(channel: int | str | None) -> str | None:
    """Map a 4G LTE EARFCN to its band name, e.g. 9360 -> 'B28'.

    Returns None for missing, unparsable or out-of-range channel numbers so
    the sensor reports unknown rather than a wrong band.
    """
    return _channel_to_band(channel, _EARFCN_BANDS)


def arfcn_to_band(channel: int | str | None) -> str | None:
    """Map a 5G NR ARFCN to its band name, e.g. 630000 -> 'n78'.

    Best-effort only — NR band ranges overlap, so see `_ARFCN_BANDS` for how
    ties are broken. Returns None when the channel is missing, unparsable or
    outside every known range.
    """
    return _channel_to_band(channel, _ARFCN_BANDS)


GROUP_NAMES = {
    "system": "System",
    "signal": "Signal",
    "data": "Data",
    "sms": "SMS",
    # Wi-Fi is its own sub-device rather than two more entries on System.
    # Only indoor models report it — the reference MC7010 answers nothing, so
    # this card is empty there — but the alternative is entity ids that would
    # have to change the first time a third Wi-Fi entity is added, and this
    # placement is free before release and not afterwards.
    "wifi": "WiFi",
}


class ZTEAboutEntity:
    """Mixin exposing a static, human-facing ``about`` note as an attribute.

    Ported from ``unifi_network_monitor`` / ``wifi_ssid_monitor``; keep the three
    implementations interchangeable. Set the text via ``_attr_about`` (class-level,
    for single-instance entities) or an ``about`` field on the entity description
    (for description-driven ones). The note shows in Tools and the More
    Info dialog but is listed in ``_unrecorded_attributes``, so the recorder never
    writes it to history — zero storage cost however often the state changes
    (dev_standards Section 14).

    List this mixin FIRST in an entity's bases so its ``extra_state_attributes``
    wins over the platform default. An entity that defines its own
    ``extra_state_attributes`` must route the result through ``_with_about``, or
    the note silently disappears for that entity only.

    The text is hardcoded rather than translated — it is a pragmatic use of the
    attribute channel, and there is no HA-native "entity description" field.
    """

    _unrecorded_attributes = frozenset({"about"})
    _attr_about: str | None = None

    @property
    def _about_text(self) -> str | None:
        """Resolve the note from ``_attr_about`` or the entity description."""
        if self._attr_about is not None:
            return self._attr_about
        description = getattr(self, "entity_description", None)
        return getattr(description, "about", None) if description is not None else None

    def _with_about(self, attrs: dict[str, Any] | None) -> dict[str, Any] | None:
        """Merge the ``about`` note into an entity's own attribute dict."""
        about = self._about_text
        if about is None:
            return attrs
        return {"about": about, **(attrs or {})}

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Default: expose only the ``about`` note when one is set."""
        return self._with_about(None)


def build_device_info(
    coordinator: ZTERouterDataUpdateCoordinator,
    entry: ConfigEntry,
    group: str,
) -> DeviceInfo:
    """Build device info dict for a sub-device group.

    Returns a dict suitable for Entity.device_info, with identifiers,
    name, manufacturer, model, sw_version, configuration_url, and
    via_device for non-system groups.
    """
    host = entry.options[CONF_HOST]
    display_group = GROUP_NAMES.get(group, group.capitalize())
    sub_name = f"{entry.title} {display_group}"

    sub_id_prefix = coordinator.imei or f"host_{host}"

    protocol = coordinator.api.protocol
    info: DeviceInfo = {
        "identifiers": {(DOMAIN, f"{sub_id_prefix}_{group}")},
        "name": sub_name,
        "manufacturer": "ZTE",
        "model": coordinator.model,
        "sw_version": coordinator.sw_version,
        "configuration_url": f"{protocol}://{host}",
    }

    if group != "system":
        # via_device (tuple) is deprecated in HA 2026.8 and removed in 2027.8;
        # via_device_link feature-detects and emits via_device_id where available.
        # The registry and entry id are resolved from the coordinator so no new
        # argument has to be threaded through every entity call site.
        cast(dict[str, Any], info).update(
            via_device_link(
                coordinator.hass, DOMAIN, f"{sub_id_prefix}_system", entry.entry_id
            )
        )

    return info


def cycle_bounds(clear_day: int, now: datetime) -> tuple[datetime, datetime, int]:
    """Return (start, end, length_in_days) of the billing cycle containing `now`.

    `clear_day` is the day of the month the router zeroes its counters on. It
    is clamped to the length of each month it is applied to, so a clear day of
    31 lands on the 28th in February rather than being skipped — the router
    cannot reset on a date that does not exist, and skipping would silently
    merge two cycles into one.

    `now` must be timezone-aware and in the user's local zone. Cycle boundaries
    are local midnight: computing them in UTC would shift the reset day by up to
    a day for anyone not on UTC.

    The length is measured in **calendar days** rather than by dividing seconds,
    so a cycle spanning a DST transition is still 30 or 31 days rather than
    30.04.
    """

    def _at(year: int, month: int) -> datetime:
        """Return local midnight on the clear day of the given month."""
        last = monthrange(year, month)[1]
        return now.replace(
            year=year,
            month=month,
            day=min(clear_day, last),
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    start = _at(now.year, now.month)
    if start > now:
        # The clear day has not arrived yet this month, so the cycle in flight
        # began last month.
        prev_year, prev_month = (
            (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
        )
        start = _at(prev_year, prev_month)

    next_year, next_month = (
        (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    )
    end = _at(next_year, next_month)

    return start, end, (end.date() - start.date()).days


def project_cycle_usage(
    used: float,
    elapsed_days: float,
    cycle_length_days: int,
    prior_rate: float | None,
    credibility_days: float,
) -> float:
    """Project end-of-cycle usage from usage so far.

    The naive form — `used / elapsed * length` — divides by a number
    approaching zero, so its error early in a cycle is unbounded: half a
    gigabyte one second after a reset projects to over a million. Two things
    tame it.

    First, the denominator is floored at one day. That alone bounds the result
    without inventing a cap.

    Second, when a previous cycle is known, its daily rate is blended in — but
    **only into the unobserved remainder**. Blending the whole projection would
    be wrong: by day 20 most of the figure is a meter reading rather than a
    forecast, and shrinking observed bytes toward last cycle is meaningless.
    Applying it to the remainder alone makes the prior's influence decay
    structurally, because it is multiplied by a shrinking number of days. No
    clamp and no cliff: at day 20 of 30 the prior moves the answer by around one
    percent, and by day 28 it is noise.

    `credibility_days` sets how quickly this cycle's own rate displaces the
    prior — the weight reaches one half at that many days elapsed.
    """
    elapsed = max(elapsed_days, 0.0)
    remaining = max(cycle_length_days - elapsed, 0.0)

    current_rate = used / max(elapsed, 1.0)

    if prior_rate is None:
        rate = current_rate
    else:
        weight = elapsed / (elapsed + credibility_days)
        rate = weight * current_rate + (1.0 - weight) * prior_rate

    return used + remaining * rate
