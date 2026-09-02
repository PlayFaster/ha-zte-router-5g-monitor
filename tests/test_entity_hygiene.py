"""Recorder hygiene, value rounding and icon coverage.

These cover dev_standards Sections 6, 12, 14 and 18 — the parts that are easy
to regress silently, because nothing fails at runtime when an attribute starts
being recorded or a sensor starts storing twelve decimal places.
"""

import ast
import json
import pathlib
import re
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.api import (
    _CORE_PARAMS,
    _EXTENDED_PARAMS,
    ZTERouterAPI,
)
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


def test_no_log_line_carries_the_sms_sender_number() -> None:
    """Section 20: the log is a wider surface than the event bus.

    The sender's number is third-party personal data, and it used to be
    interpolated into an INFO line on every new message. The bus event still
    carries it, scoped to this entry; the log is copied into every diagnostics
    download, issue report and screenshot, and nothing redacts it there.

    Asserted over the source rather than over captured output because the
    interesting case is the line nobody wrote a test for. `%s` formatting means
    the number never appears as a literal, so a search of `caplog.text` on the
    one path a test happens to drive would pass while a second site leaked.
    """
    source = (COMPONENT / "coordinator.py").read_text(encoding="utf-8")

    leaking = [
        line.strip()
        for line in source.splitlines()
        if "number_decoded" in line and "_LOGGER" in line
    ]
    assert not leaking, f"phone number reaches a log line: {leaking}"

    # The value is passed as an argument on the following lines, so the call has
    # to be read as a block rather than a line.
    for call in re.findall(r"_LOGGER\.\w+\((?:[^()]|\([^()]*\))*\)", source):
        assert "number_decoded" not in call, f"phone number reaches a log call: {call}"


async def test_a_new_sms_logs_nothing_that_identifies_the_sender(
    hass: HomeAssistant, caplog
) -> None:
    """The runtime half of the check above, on the path that used to leak."""
    import logging

    from custom_components.zte_router_5g.coordinator import (
        ZTERouterDataUpdateCoordinator,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="ZTE 5G",
        data={"imei": "864155042229309"},
        options={
            CONF_HOST: "192.168.0.1",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "password",
        },
    )
    entry.add_to_hass(hass)
    coordinator = ZTERouterDataUpdateCoordinator(hass, entry, AsyncMock())
    coordinator.last_sms_timestamp = "20260101000000"

    number = "+353871234567"
    with caplog.at_level(logging.DEBUG):
        coordinator._check_new_sms(
            [
                {
                    "id": "7",
                    "date_decoded": "20260102000000",
                    "number_decoded": number,
                    "content_decoded": "hello",
                }
            ]
        )

    assert number not in caplog.text
    assert "New SMS received" in caplog.text


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
        "sntp_server2",
        "sntp_dst_enable",
        # Projection context. `cycle_day` and `cycle_start` are static within a
        # cycle and the other two describe how much of the state rests on
        # observed data — none of it is a measurement whose history is wanted.
        "confidence",
        "basis",
        "cycle_day",
        "cycle_start",
        "cycle_source",
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


# `test_every_repair_issue_has_translated_text` lived here until 2026-08-26.
# It asserted only that each raised key was *present* in the `issues` block,
# which a key with a title and no description passes — the card then renders
# with an empty body. Superseded by the sweeps in `tests/test_health_contract.py`,
# which checks title and description in `strings.json` and in every
# `translations/*.json`, and by 8b, which catches text left behind by a rename.


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
        api.probe_discovery_candidates = AsyncMock(return_value={})
        api.measure_unauthenticated_keys = AsyncMock(return_value=frozenset())
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


# Sensors allowed to use `SensorStateClass.TOTAL`, with the justification this
# test demands. Empty by design — see the docstring below. Adding an entry is a
# reviewable act; typing `TOTAL` into a new description is not.
ALLOWED_TOTAL_STATE_CLASS: frozenset[str] = frozenset()


async def test_no_sensor_uses_the_total_state_class(hass: HomeAssistant) -> None:
    """No sensor may use `SensorStateClass.TOTAL`.

    `TOTAL` and `TOTAL_INCREASING` look interchangeable and are not. Under
    `TOTAL` the recorder recognises a new cycle *only* from a changing
    `last_reset` attribute; a counter that simply drops to zero is not treated
    as having reset. `TOTAL_INCREASING` detects the drop itself and needs no
    attribute. Every counter this integration exposes resets to zero without
    publishing `last_reset`, so `TOTAL_INCREASING` is always the correct class
    and `TOTAL` is always a mistake. Nothing fails at runtime when it is wrong,
    which is why this is a test and not a code review item.

    **If this test fails, the `TOTAL` must be justified, not silenced.** A
    genuine `TOTAL` sensor is one whose value can legitimately fall without
    that being a reset — net import/export, a draining tank — and it must
    publish `last_reset`. If the new sensor is really that, add its key to
    `ALLOWED_TOTAL_STATE_CLASS` with a comment saying why; the allowlist exists
    for exactly that case. If it is a counter that resets to zero, the sensor
    is wrong, not the test.
    """
    async with _live_entities(hass) as entities:
        checked = 0
        offenders: list[str] = []
        for entity in entities:
            state_class = getattr(entity, "state_class", None)
            if state_class is None:
                continue
            checked += 1
            if (
                state_class is SensorStateClass.TOTAL
                and entity.entity_id not in ALLOWED_TOTAL_STATE_CLASS
            ):
                offenders.append(entity.entity_id)

    assert not offenders, (
        "sensors using SensorStateClass.TOTAL — use TOTAL_INCREASING for a "
        "counter that resets to zero, or justify the TOTAL in "
        "ALLOWED_TOTAL_STATE_CLASS:\n" + "\n".join(sorted(offenders))
    )
    # Guard the guard: if the fixture stops producing sensors with a state
    # class, the sweep passes vacuously and keeps passing after a regression.
    assert checked >= 3, f"sweep only inspected {checked} sensors — fixture is stale"


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


# ---------------------------------------------------------------------------
# Suppressed static-analysis directives — every one is a reviewed decision
# ---------------------------------------------------------------------------
#
# `masked_errors_check` Class D. That prompt is a point-in-time audit; this is
# the mechanism that keeps its result true afterwards.
# The set cannot grow without someone editing the table below and writing a
# reason.
#
# **Why ruff and mypy do not already cover this.** `RUF100` and mypy's
# `warn_unused_ignores` report a suppression that is *unnecessary* — one where
# no error would have fired. They are silent on the dangerous case: a
# suppression that IS doing work, because the error is real. On
# `huawei_router_5g` both tools were clean while two calls to non-existent
# library methods sat behind `type: ignore`, so Logout and Clear Traffic
# Statistics had never worked.
#
# Ported from `huawei_router_5g` on 2026-08-26, keeping all four points the
# chore names: `tokenize` rather than a regex, keyed on `(file, directive)`
# rather than line number, three tests rather than one, and both
# `custom_components/` and `tests/` swept. `scripts/` is included here too —
# it is the one place that talks to real hardware.
#
# The table started **empty** and was filled by running the sweep and writing a
# reason for each finding, per the chore. Copying Huawei's entries would have
# been meaningless: they describe that project's library.
ALLOWED_SUPPRESSIONS: dict[tuple[str, str], str] = {
    ("diagnostics.py", "noqa: BLE001"): (
        "`_guarded` catches `Exception` because Home Assistant does not wrap "
        "`config_entry_diagnostics` — an exception escaping this function is "
        "an HTTP 500 and no file at all, which is worse than any partial "
        "download. The breadth is the point: a narrower catch would let an "
        "unanticipated type destroy the file a user is trying to attach to an "
        "issue. Every caught error is recorded as a field in that file, so "
        "nothing is swallowed, and `test_diagnostics_never_raises_when_every"
        "_router_call_fails` proves the guarantee it buys."
    ),
    ("api.py", "noqa: S324"): (
        "MD5 is the hash the legacy `goform` login protocol specifies for the "
        "`AD` token on pre-new-generation firmware. It is the router's choice, "
        "not this integration's, and it is not being used to protect anything: "
        "the value is a per-session challenge response the device compares "
        "against its own computation. Newer firmware takes SHA-256 and "
        "`get_ad` selects on the firmware version, so the branch cannot be "
        "removed without dropping support for the older models."
    ),
    ("api.py", "pragma: no cover"): (
        "Two defensive guards. `login()` re-checks `attempt.stok` after both "
        "error branches have raised, which narrows the type for mypy and "
        "cannot be reached at runtime; and `set_data_volume_settings` rejects "
        "an unknown field name, which guards a programming error rather than "
        "any input a user or router can supply. Writing a test for either "
        "would mean constructing a state the code already proves impossible."
    ),
    ("api.py", "noqa: BLE001"): (
        "Three sites, all deliberate containment at a boundary. `logout()` "
        "runs on unload and must never block Home Assistant tearing the entry "
        "down, so an unreachable router cannot be allowed to raise. "
        "`get_sms_capacity` and `get_sms_messages` are optional endpoints "
        "whose failure degrades their own entities and nothing else — the "
        "domain exceptions are re-raised first, above each of these, so this "
        "catches only what is genuinely unanticipated."
    ),
    ("coordinator.py", "noqa: BLE001"): (
        "`_fetch_optional` must contain any failure of an optional endpoint, "
        "because Section 8 requires one flaky endpoint to degrade only its own "
        "entities. `ZTEAuthError` is re-raised on the line above so reauth "
        "still fires; narrowing further would let an unanticipated error take "
        "down the whole poll, which is the outcome this exists to prevent."
    ),
    ("coordinator.py", "pragma: no cover"): (
        "The two Section 19 health-snapshot computations. A health verdict "
        "that crashes the update it is diagnosing is worse than no verdict, so "
        "both are wrapped. The handler is unreachable while the snapshot code "
        "is correct, and a test would have to break the snapshot deliberately "
        "to reach it — which tests nothing about the product."
    ),
    ("__init__.py", "noqa: BLE001"): (
        "The follow-up refresh after a successful SMS write. The write has "
        "already landed at this point, so a failure here costs the user a "
        "slightly stale reading until the next poll and nothing more. Raising "
        "would report a failed action that in fact succeeded, which is the "
        "more misleading of the two outcomes."
    ),
    ("switch.py", "noqa: BLE001"): (
        "The read-back that confirms a switch position. A read that fails "
        "leaves the write *unverified*, not failed — the command may well have "
        "landed, and the next poll settles it. Only a successful read "
        "reporting the wrong value proves a refusal, and that path raises."
    ),
    ("diag_check.py", "ruff: noqa: T201"): (
        "The console report is this script's entire output, exactly as in "
        "`hardware_check.py`. There is no logger to route it through, and a "
        "caller reading the transcript is the point. File-level because every "
        "print in the file is the same deliberate choice."
    ),
    ("diag_check.py", "noqa: S104"): (
        "`0.0.0.0` appears in a set of addresses the leak sweep treats as "
        "non-identifying, alongside the broadcast and loopback addresses. It "
        "is matched as text inside a produced file and never bound to: this "
        "script opens no socket and serves nothing."
    ),
    ("diag_check.py", "noqa: SLF001"): (
        "Five sites. Three replace `_probe_chunk` for the sabotage mode, which "
        "takes a real session away from a real router partway through a real "
        "pass — the one thing the unit suite cannot do, because a mock is "
        "written from the same model the code is. Two more drive the coordinator's own refresh the way "
        "`async_force_refresh` does. That method is the public route but goes "
        "through the debouncer, which needs a running Home Assistant to fire, "
        "and this script runs none. Setting `_force_refresh_once` and awaiting "
        "`_async_update_data` performs the same two steps minus the "
        "scheduling. Adding public surface to the integration for the sake of "
        "a script HACS never distributes would be the worse trade."
    ),
    ("diag_check.py", "type: ignore[method-assign]"): (
        "The sabotage mode replaces `_probe_chunk` on the class so that a real "
        "pass finds its session gone partway through, which is what another "
        "client logging into the router does. Assigning to a method is exactly "
        "the intent, it is restored in a `finally`, and the script is never "
        "imported by the integration or distributed by HACS."
    ),
    ("diag_check.py", "noqa: PLW0603"): (
        "One module-level colour flag, set once from the parsed arguments "
        "before any output is produced — the same pattern, and the same "
        "reasoning, as `hardware_check.py`."
    ),
    ("diag_check.py", "pragma: no cover"): (
        "The import guard that tells an operator running the script with the "
        "wrong interpreter what to do about it. Reachable only when Home "
        "Assistant is absent, which is never true where the suite runs."
    ),
    ("hardware_check.py", "ruff: noqa: T201"): (
        "The console report is this script's entire output. There is no logger "
        "to route it through and a caller reading the transcript is the point. "
        "File-level rather than per-line because every print in the file is the "
        "same deliberate choice."
    ),
    ("hardware_check.py", "ruff: noqa: SLF001"): (
        "The script reads private API state to confirm what a call actually "
        "did to the session — whether logout released it, whether a token was "
        "cleared. There is no public accessor, and adding one would put "
        "shipped API surface into the integration for the sake of a script "
        "HACS never distributes. Read-only: it observes, never assigns."
    ),
    ("hardware_check.py", "noqa: BLE001"): (
        "Twenty-three sites, each wrapping one hardware interaction whose "
        "failure IS the result being reported. A narrower except would let an "
        "unanticipated error abort the run and discard every check already "
        "recorded, which is the opposite of what a diagnostic script should "
        "do. The exception type is always printed, never swallowed."
    ),
    ("hardware_check.py", "noqa: PLW0603"): (
        "One module-level colour flag, set once from the parsed arguments "
        "before any output is produced. Threading it through every print in a "
        "1400-line report script would be a large change for no behavioural "
        "difference, and the alternative — a module-level mutable default — is "
        "worse."
    ),
    ("hardware_check.py", "pragma: no cover"): (
        "The import guard that tells an operator running the script from the "
        "wrong directory what to do about it. It is reachable only when the "
        "component is not importable, which is by definition not a state the "
        "test suite can be in."
    ),
    ("test_transport_seam.py", "noqa: BLE001"): (
        "`_drive_until_it_gives_up` returns whatever the failing poll raised "
        "so the test can assert on its type and message. Naming a type here "
        "would move the assertion out of the test and into the helper, and the "
        "point of several of those tests is precisely *which* exception "
        "arrived. Nothing is swallowed: the exception is returned to the "
        "caller, which asserts on it."
    ),
    ("transport.py", "pragma: no cover"): (
        "The unknown-fault-mode guard in the test router. It fires on a typo "
        "in a test rather than on any runtime path, and covering it would mean "
        "writing a test whose only purpose is to misspell a fault name."
    ),
}


def _shipped_root():
    """Return the project root of the **shipped** tree, not a working copy.

    `mutmut` runs the suite from a `mutants/` directory holding a rewritten
    copy of `custom_components/` and `tests/` and nothing else. This sweep is
    about the shipped tree rather than about behavior, and every mutated copy
    of a function carries its suppression comment again — which would turn a
    handful of reviewed suppressions into several hundred unreviewed ones and
    fail the run before a single mutant was tested.

    Resolving from the first ancestor that actually carries a `docs/` directory
    steps out of the mutant tree and reads what ships. It never falls back to a
    copy and never skips: a genuinely missing tree still raises.
    """
    import custom_components.zte_router_5g as component

    start = pathlib.Path(component.__path__[0]).parent.parent
    for base in (start, *start.parents):
        if (base / "docs").is_dir():
            return base
    raise FileNotFoundError(f"no docs/ directory found above {start}")


def _real_comments() -> list[tuple[str, int, str]]:
    """Return every genuine comment in the component, tests and scripts.

    Uses `tokenize` rather than a regex over raw text: docstrings in these
    projects quote directives while explaining why a past one was wrong, and a
    text search cannot tell those apart from a live suppression. It would
    report phantom findings, and the allow-list would fill with entries
    matching nothing.
    """
    import tokenize

    root = _shipped_root()
    roots = [
        root / "custom_components" / "zte_router_5g",
        root / "tests",
        root / "scripts",
    ]

    found: list[tuple[str, int, str]] = []
    for base in roots:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            with path.open("rb") as handle:
                found.extend(
                    (path.name, token.start[0], token.string)
                    for token in tokenize.tokenize(handle.readline)
                    if token.type == tokenize.COMMENT
                )
    return found


def _live_suppressions() -> dict[tuple[str, str], list[int]]:
    """Map (file, directive) to the lines carrying it.

    The optional file-level prefix is caught deliberately: that directive at
    the top of a module suppresses its rule for **every line in the file**,
    which is broader than any per-line form. The prefix is kept in the captured
    code rather than normalized away, so a file-level suppression can never be
    reviewed as if it were one line.

    The literal prefix is not written out in this comment: ruff scans comments
    for it and would read an example as a real directive.
    """
    pattern = re.compile(
        r"#\s*((?:ruff:\s*)?(?:type:\s*ignore(?:\[[^\]]*\])?"
        r"|noqa(?::\s*[A-Z0-9, ]+)?|pragma:\s*no cover))"
    )

    live: dict[tuple[str, str], list[int]] = {}
    for filename, line, comment in _real_comments():
        for raw in pattern.findall(comment):
            code = " ".join(raw.split())
            live.setdefault((filename, code), []).append(line)
    return live


def test_every_suppression_is_on_the_reviewed_allow_list() -> None:
    """No `type: ignore`, `noqa` or `pragma: no cover` without a written reason.

    **If this fails, the new suppression needs a reason, not an entry.** Ask
    what the tool would have said and whether that thing is actually true — an
    `attr-defined` ignore on a library call is a *claim about that library*.
    """
    unlisted = sorted(
        f"{filename}:{','.join(str(n) for n in lines)}  {code}"
        for (filename, code), lines in _live_suppressions().items()
        if (filename, code) not in ALLOWED_SUPPRESSIONS
    )

    assert not unlisted, (
        "suppressions with no reviewed justification:\n"
        + "\n".join(unlisted)
        + "\n\nAdd to ALLOWED_SUPPRESSIONS with a reason, or fix the underlying "
        "problem. Removing the suppression alone is not a fix."
    )


def test_allowed_suppressions_has_no_dead_entries() -> None:
    """An allow-list entry must not outlive the suppression it covers.

    A dead entry silently pre-approves the next occurrence of the same
    directive in the same file, which is how a reviewed exception becomes an
    unreviewed habit.
    """
    live = set(_live_suppressions())
    stale = sorted(f"{f}  {c}" for (f, c) in ALLOWED_SUPPRESSIONS if (f, c) not in live)

    assert not stale, (
        "ALLOWED_SUPPRESSIONS entries that no longer match anything:\n"
        + "\n".join(stale)
    )


def test_every_allowed_suppression_states_a_reason() -> None:
    """The reason is the entire value of the allow-list.

    An entry with a token justification is indistinguishable from one added to
    make a check pass, which is the thing being guarded against.
    """
    thin = sorted(
        f"{f}  {c}"
        for (f, c), reason in ALLOWED_SUPPRESSIONS.items()
        if len(reason.strip()) < 40
    )
    assert not thin, "allow-list entries with no real justification:\n" + "\n".join(
        thin
    )


# ---------------------------------------------------------------------------
# Every polled key is read by something
# ---------------------------------------------------------------------------

# Polled keys with no entity behind them, each with the reason it is requested.
# The sweep below asks the reverse question to the alias sweeps: those check
# that every key an entity names is requested, this checks that every key
# requested is read. `net_select_mode` was polled on every device and read by
# nothing, and an alias for it was added to the MC888 work before anyone
# noticed — a second key in every request feeding the same nothing.
POLLED_WITHOUT_AN_ENTITY: dict[str, str] = {
    "network_type": (
        "Contract key. `coordinator.CORE_CONCEPTS` judges payload drift on it, "
        "and `_classify_session` needs it to tell a dead session from a quiet "
        "one. Also read by the Network Type sensor through an alias tuple."
    ),
    "wan_connect_status": (
        "Session sentinel. `get_params` appends it to single-key reads so a "
        "write read-back can still be classified."
    ),
    "ppp_status": "Session sentinel, the second spelling of the same concept.",
}

# Families consumed by prefix rather than by name. `APN_config0` through
# `APN_config9` are read by `key.startswith("APN_config")` in the diagnostics
# sanitizer and by the APN profile builder, so a literal-name search finds
# nothing for any of them.
POLLED_PREFIX_FAMILIES: tuple[str, ...] = ("APN_config",)


# The batch definitions themselves. Their members are the question the sweep
# asks, so counting them as reads would make every polled key look consumed —
# which is what the first version of this test did, and it passed while
# `net_select_mode` sat unread.
BATCH_DEFINITIONS: frozenset[str] = frozenset({"_CORE_PARAMS", "_EXTENDED_PARAMS"})

# Modules that catalogue parameter names rather than read them. `known_names.py`
# is the cross-device vocabulary the discovery probe asks for; every name in it
# appears as a string literal and none of them is a consumer. Counting those
# literals as reads is what made the first version of this sweep pass while
# `net_select_mode` sat unread — the name was in `KNOWN_NAMES`, so it looked
# consumed.
VOCABULARY_MODULES: frozenset[str] = frozenset({"known_names.py"})

# Name catalogues inside modules that do have consumers. Same reasoning.
VOCABULARY_NAMES: frozenset[str] = frozenset(
    {"DISCOVERY_CANDIDATES", "DISCOVERY_VALUE_SAFE"}
)


def _alias_tuples_and_reads(tree: ast.AST) -> tuple[dict[str, set[str]], set[str]]:
    """Return module-level string tuples, and every other string used."""
    tuples: dict[str, set[str]] = {}
    declared: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        value = node.value
        if not isinstance(target, ast.Name):
            continue
        if not isinstance(value, ast.Tuple | ast.List):
            continue
        members = {
            el.value
            for el in value.elts
            if isinstance(el, ast.Constant) and isinstance(el.value, str)
        }
        if not members:
            continue
        if target.id in BATCH_DEFINITIONS | VOCABULARY_NAMES:
            declared |= members
        elif isinstance(value, ast.Tuple):
            tuples[target.id] = members

    in_tuples = {s for members in tuples.values() for s in members}
    reads = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    return tuples, reads - in_tuples - declared


def test_every_polled_key_is_read_by_something() -> None:
    """A key in the request that nothing reads is a round trip for nothing.

    The alias sweeps run one way — every key an entity names must be polled.
    Nothing ran the other way, so `net_select_mode` sat in `_CORE_PARAMS`
    unread, and `network_net_select_mode` was added beside it to let a second
    device answer the same unread key.

    A key counts as read when an entity names it, when it belongs to an alias
    tuple some entity uses, when it feeds the data-volume write form, when it
    belongs to a prefix-matched family, or when it is listed above with the
    reason it is requested anyway.
    """
    root = pathlib.Path(__file__).resolve().parent.parent / "custom_components"
    package = root / "zte_router_5g"

    consumed: set[str] = set()
    for path in sorted(package.glob("*.py")):
        if path.name in VOCABULARY_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tuples, reads = _alias_tuples_and_reads(tree)
        consumed |= reads
        used_names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        for name, members in tuples.items():
            if name in used_names:
                consumed |= members

    for field, aliases in ZTERouterAPI.DATA_VOLUME_FIELDS.items():
        consumed.add(field)
        consumed |= set(aliases)

    polled = set(_CORE_PARAMS) | set(_EXTENDED_PARAMS)
    unread = {
        key
        for key in polled - consumed - set(POLLED_WITHOUT_AN_ENTITY)
        if not key.startswith(POLLED_PREFIX_FAMILIES)
    }

    assert not unread, (
        f"polled but read by nothing: {sorted(unread)}. Either give the key a "
        f"consumer, drop it from the batch, or list it in "
        f"POLLED_WITHOUT_AN_ENTITY with the reason it is requested."
    )
