"""Recorder hygiene, value rounding and icon coverage.

These cover dev_standards Sections 6, 12, 14 and 18 — the parts that are easy
to regress silently, because nothing fails at runtime when an attribute starts
being recorded or a sensor starts storing twelve decimal places.
"""

import json
import pathlib
import re
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.binary_sensor import ZTEIntegrationHealthSensor
from custom_components.zte_router_5g.const import DOMAIN
from custom_components.zte_router_5g.sensor import ZTERouterSensor, _safe_float

COMPONENT = pathlib.Path("custom_components/zte_router_5g")


# --------------------------------------------------------------------------
# Section 6 — rounding at parse time
# --------------------------------------------------------------------------


def test_safe_float_rounds_at_parse_time() -> None:
    """Controller noise must not reach the recorder verbatim."""
    assert _safe_float("99.930600002408") == 99.931
    assert _safe_float(-85.7777777) == -85.778


def test_safe_float_still_tolerates_bad_input() -> None:
    """Rounding must not weaken the None/empty/garbage guards."""
    assert _safe_float(None) is None
    assert _safe_float("") is None
    assert _safe_float("not-a-number") is None
    assert _safe_float("-85") == -85.0


# --------------------------------------------------------------------------
# Section 14 — unrecorded attributes
# --------------------------------------------------------------------------


def test_sms_sender_number_is_never_recorded() -> None:
    """The SMS sender's number is third-party personal data.

    Recording it would write someone else's phone number into the user's
    database on every poll.
    """
    assert "number" in ZTERouterSensor._unrecorded_attributes


def test_every_attribute_the_sensor_emits_is_unrecorded() -> None:
    """Section 14: the default is total — no attribute is recorded.

    `sntp_server1` and `sntp_dst_enable` were previously exempted here as
    "static configuration worth seeing in history". Section 14 (Standard
    Version 1.12.0) withdrew that reasoning: attributes are not a history
    mechanism, and a value whose history is genuinely wanted should be an
    entity or a user template sensor.
    """
    emitted = {
        "about",
        "id",
        "number",
        "date",
        "sms_nv_total",
        "sms_sim_total",
        "sms_nv_rev_total",
        "sms_nv_send_total",
        "sms_nv_draftbox_total",
        "sms_sim_rev_total",
        "sms_sim_send_total",
        "sms_sim_draftbox_total",
        "sntp_server1",
        "sntp_dst_enable",
    }
    assert emitted == set(ZTERouterSensor._unrecorded_attributes)


def test_health_detail_is_unrecorded() -> None:
    """The health sensor's detail churns with every failure."""
    assert "issues" in ZTEIntegrationHealthSensor._unrecorded_attributes


# --------------------------------------------------------------------------
# Section 12 — icons resolve for everything that needs one
# --------------------------------------------------------------------------


def _load(name: str) -> dict:
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def test_refresh_button_has_an_icon() -> None:
    """Refresh Now has no device_class to derive one from."""
    assert "system_refresh" in _load("icons.json")["entity"]["button"]


def test_services_have_icons() -> None:
    """Section 12 requires icons.json to cover services, not just entities."""
    declared = set(_load("icons.json").get("services", {}))
    expected = {"send_sms", "delete_sms", "delete_all_sms", "get_sms_list"}
    assert expected <= declared


def test_registered_services_match_the_icon_entries() -> None:
    """Guards against an icon entry drifting from the real service name."""
    source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    registered = set(
        re.findall(r'hass\.services\.async_register\(\s*DOMAIN,\s*"(\w+)"', source)
    )
    assert registered == set(_load("icons.json")["services"])


def test_translation_keys_resolve_in_both_files() -> None:
    """Every translation_key used in code must resolve in both files.

    Compared against the code, not file-to-file: a healthy entry count in one
    file conceals both stale entries and live entities with no entry at all.
    """
    source = "".join(p.read_text(encoding="utf-8") for p in COMPONENT.glob("*.py"))
    keys = set(re.findall(r'translation_key="([^"]+)"', source))

    for name in ("strings.json", "translations/en.json"):
        data = _load(name)
        resolved = {k for platform in data["entity"].values() for k in platform}
        resolved |= set(data.get("issues", {}))
        resolved |= set(data.get("exceptions", {}))
        assert not keys - resolved, f"{name} missing: {sorted(keys - resolved)}"


def test_every_raised_exception_has_translated_text() -> None:
    """A user-facing exception with no `exceptions` entry shows a raw key.

    Every HomeAssistantError / ServiceValidationError reaching the user must
    carry translation metadata and resolve in both files.
    """
    keys = set()
    for path in COMPONENT.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(
            r"raise (?:HomeAssistantError|ServiceValidationError)"
            r"\((.*?)\)\s*(?:from|\n)",
            source,
            re.DOTALL,
        ):
            found = re.search(r'translation_key="(\w+)"', match.group(1))
            assert found, f"untranslated raise in {path.name}: {match.group(1)[:60]}"
            keys.add(found.group(1))

    assert keys, "no exception raises found — the pattern has drifted"
    for name in ("strings.json", "translations/en.json"):
        defined = set(_load(name).get("exceptions", {}))
        assert not keys - defined, f"{name} missing: {sorted(keys - defined)}"


def test_every_repair_issue_has_translated_text() -> None:
    """A missing issues entry shows the raw key on the Repairs card."""
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")
    raised = set(re.findall(r'translation_key="(\w+)"', source))

    for name in ("strings.json", "translations/en.json"):
        issues = set(_load(name).get("issues", {}))
        assert raised <= issues, f"{name} missing issue text for {raised - issues}"


# --------------------------------------------------------------- Section 14
# Runtime sweep: every attribute every live entity publishes must be excluded
# from the recorder. This has to run against a real hass rather than by reading
# source, because description-driven entities build their attributes from a
# function on the entity description — no static check can see those keys.


# Attributes deliberately left recorded, with the justification required by
# Section 14. Empty by design: attributes carry detail that does not merit its
# own entity, not history. Anything needing history should be an entity or a
# user template sensor. Adding an entry here is a reviewable act; forgetting to
# add a key to `_unrecorded_attributes` is not, which is the whole point.
ALLOWED_RECORDED: frozenset[str] = frozenset()

SWEEP_DATA = {
    "network_type": "ENDC",
    "signalbar": "4",
    "wa_inner_version": "IRL_H3G_MC7010DV1.0.0B01",
    "model_name": "MC7010",
    "realtime_time": "3600",
    "wan_connect_status": "ppp_connected",
    # Populate every branch of the description-driven attribute functions, or
    # the sweep passes by finding nothing to check.
    "sntp_server0": "0.pool.ntp.org",
    "sntp_server1": "1.pool.ntp.org",
    "sntp_dst_enable": "1",
    "sms_nv_total": "10",
    "sms_sim_total": "5",
    "sms_nv_rev_total": "4",
    "sms_nv_send_total": "3",
    "sms_nv_draftbox_total": "1",
    "sms_sim_rev_total": "2",
    "sms_sim_send_total": "1",
    "sms_sim_draftbox_total": "0",
}


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    """Make the custom component importable by the real hass fixture."""
    return


@asynccontextmanager
async def _live_entities(hass: HomeAssistant):
    """Set the integration up and yield every live entity it created.

    Shared by the Section 12 and Section 14 sweeps. Both need the same thing —
    the real entity list — and both are worthless without the
    `entity_registry_enabled_default` patch below, so the setup lives in one
    place rather than being copied and drifting.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="864155042229309",
        title="ZTE 5G",
        data={"model": "MC7010", "sw_version": "V1.0.0", "imei": "864155042229309"},
        options={
            CONF_HOST: "192.168.0.1",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "password",
        },
    )
    entry.add_to_hass(hass)

    # Force every disabled-by-default entity to be added. Without this both
    # sweeps silently skip them — they are never instantiated, so they are
    # never inspected, and the tests pass while a whole class of entities goes
    # unchecked. Verified by mutation: removing a key from
    # `_unrecorded_attributes` on a disabled-by-default sensor did not fail the
    # Section 14 sweep until this patch was added.
    with (
        patch(
            "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
            property(lambda self: True),
        ),
        patch("custom_components.zte_router_5g.ZTERouterAPI") as api_class,
    ):
        api = api_class.return_value
        api.protocol = "http"
        api.try_set_protocol = AsyncMock(return_value=None)
        api.login = AsyncMock(return_value="stok=test")
        api.logout = AsyncMock(return_value=None)
        api.get_all_data = AsyncMock(return_value=dict(SWEEP_DATA))
        api.get_sms_capacity = AsyncMock(return_value={})
        api.get_sms_messages = AsyncMock(
            return_value=[
                {
                    "id": "1",
                    "number_decoded": "+353871234567",
                    "content_decoded": "hello",
                    "date_decoded": "2026-07-27T10:00:00+00:00",
                }
            ]
        )

        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        yield [
            e
            for component in hass.data["entity_components"].values()
            for e in component.entities
            if getattr(e, "platform", None) is not None
            and e.platform.platform_name == DOMAIN
        ]


async def test_no_entity_publishes_a_recorded_attribute(hass: HomeAssistant) -> None:
    """Section 14: `_unrecorded_attributes` must cover every published key.

    The failure this guards is silent — a new attribute is simply written to
    the recorder on every state change, and nothing errors. It is also the
    failure that actually occurred: three of four PlayFaster integrations had
    `_unrecorded_attributes` lagging `extra_state_attributes`.
    """
    async with _live_entities(hass) as entities:
        checked = 0
        offenders: list[str] = []
        for entity in entities:
            published = set(entity.extra_state_attributes or {})
            if not published:
                continue
            checked += 1
            leaked = published - entity._unrecorded_attributes - ALLOWED_RECORDED
            if leaked:
                offenders.append(f"{entity.entity_id}: {sorted(leaked)}")

    assert not offenders, "attributes published but recorded:\n" + "\n".join(offenders)
    # Guard the guard: if the fixture stops producing attributes, the sweep
    # would pass vacuously and go on passing after a real regression.
    assert checked >= 3, f"sweep only inspected {checked} entities — fixture is stale"


async def test_every_live_entity_has_an_icon_or_a_device_class(
    hass: HomeAssistant,
) -> None:
    """Section 12: `icons.json` must cover every entity, on every platform.

    Supersedes the static `SENSOR_TYPES`-only check above, which was blind in
    two directions at once: it iterated the sensor platform only, so 15
    entities across binary_sensor/switch/select/number/button could lose their
    icon with the suite green; and it flattened `icons.json` into one set of
    keys, so an entry filed under the *wrong* platform still satisfied it.

    Entity descriptions here live in a mix of tuples and module-level
    singletons, so any static enumeration would drift the moment one is added.
    Sweeping live entities is the only form that cannot.
    """
    icons = _load("icons.json")["entity"]

    async with _live_entities(hass) as entities:
        missing = []
        checked = 0
        for entity in entities:
            if entity.device_class is not None:
                continue
            key = entity.translation_key
            if key is None:
                continue
            checked += 1
            # Look under this entity's OWN platform — a key filed under another
            # platform is a miss, not a pass.
            if key not in icons.get(entity.platform.domain, {}):
                missing.append(f"{entity.entity_id} ({entity.platform.domain}/{key})")

    assert not missing, "entities with neither device_class nor icon:\n" + "\n".join(
        missing
    )
    assert checked >= 10, f"only {checked} entities swept — the fixture is stale"
