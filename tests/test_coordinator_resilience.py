"""Coordinator resilience, force-refresh and self-diagnosis tests.

These follow the failure paths rather than the happy path: what the coordinator
does on the very first failure before anything has ever succeeded, what it does
once a strike budget is exhausted, and whether a success clears the verdict in
the same cycle. The success path says nothing about any of it.
"""

from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.api import (
    ZTEAuthError,
    ZTEConnectionError,
    ZTERouterAPI,
)
from custom_components.zte_router_5g.const import (
    CONF_STOP_POLLING,
    DOMAIN,
    FETCH_STRIKE_LIMIT,
    REPAIR_AUTH_FAILED,
    REPAIR_CONN_ERROR,
    UNREACHABLE_STRIKE_LIMIT,
)
from custom_components.zte_router_5g.coordinator import (
    DRIFT_CONTRACT,
    ENDPOINT_EXTENDED,
    ENDPOINT_SMS_MESSAGES,
    ZTERouterDataUpdateCoordinator,
)

GOOD_DATA = {
    "network_type": "ENDC",
    "signalbar": "4",
    "wa_inner_version": "IRL_H3G_MC7010DV1.0.0B01",
    "realtime_time": "3600",
    "wan_connect_status": "ppp_connected",
}


@pytest.fixture
def entry():
    """Return a config entry with credentials in options."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="864155042229309",
        title="ZTE 5G",
        data={"imei": "864155042229309"},
        options={
            CONF_HOST: "192.168.0.1",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "password",
        },
    )


@pytest.fixture
def coordinator(hass: HomeAssistant, entry):
    """Return a coordinator wired to a fully mocked API."""
    entry.add_to_hass(hass)
    api = MagicMock(spec=ZTERouterAPI)
    api.get_all_data = AsyncMock(return_value=dict(GOOD_DATA))
    api.get_extended_data = AsyncMock(return_value={})
    api.get_sms_capacity = AsyncMock(return_value={})
    api.get_sms_messages = AsyncMock(return_value=[])
    api.login = AsyncMock(return_value="stok=test")
    return ZTERouterDataUpdateCoordinator(hass, entry, api)


# --------------------------------------------------------------------------
# Section 13 — force refresh bypasses pause
# --------------------------------------------------------------------------


async def test_paused_scheduled_poll_returns_cache(coordinator, entry, hass) -> None:
    """A scheduled poll while paused must not touch the router."""
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_STOP_POLLING: True}
    )
    coordinator.data = {"cached": "value"}

    result = await coordinator._async_update_data()

    assert result == {"cached": "value"}
    coordinator.api.get_all_data.assert_not_awaited()


async def test_force_refresh_fetches_while_paused(coordinator, entry, hass) -> None:
    """Refresh Now must fetch even while Pause Polling is on.

    This is the regression the standard records: wired to a bare
    ``async_request_refresh`` the fetch is silently swallowed exactly when the
    user most wants it.
    """
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_STOP_POLLING: True}
    )
    coordinator.data = {"cached": "value"}

    with patch.object(coordinator, "async_request_refresh", AsyncMock()):
        await coordinator.async_force_refresh()
    assert coordinator._force_refresh_once is True

    result = await coordinator._async_update_data()

    coordinator.api.get_all_data.assert_awaited_once()
    assert result["network_type"] == "ENDC"


async def test_force_flag_is_one_shot(coordinator, entry, hass) -> None:
    """The forced cycle must not disable the pause for later polls."""
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_STOP_POLLING: True}
    )
    coordinator.data = {"cached": "value"}
    coordinator._force_refresh_once = True

    await coordinator._async_update_data()
    assert coordinator._force_refresh_once is False

    result = await coordinator._async_update_data()
    assert result == {"cached": "value"}
    assert coordinator.api.get_all_data.await_count == 1


# --------------------------------------------------------------------------
# Section 8 — per-endpoint resilience
# --------------------------------------------------------------------------


async def test_failing_sms_endpoint_does_not_blank_the_integration(
    coordinator,
) -> None:
    """A broken optional endpoint degrades only its own entities."""
    coordinator.api.get_sms_messages = AsyncMock(
        side_effect=ZTEConnectionError("sms endpoint down")
    )

    for _ in range(FETCH_STRIKE_LIMIT + 1):
        data = await coordinator._async_update_data()
        # The mandatory fetch keeps working throughout.
        assert data["network_type"] == "ENDC"

    assert coordinator.consecutive_failures == 0
    assert coordinator.endpoint_available(ENDPOINT_SMS_MESSAGES) is False


async def test_endpoint_holds_last_good_within_budget(coordinator) -> None:
    """Within its budget an endpoint serves its last-good payload."""
    message = {"id": "1", "content_decoded": "hello", "date_decoded": "2026-01-01"}
    coordinator.api.get_sms_messages = AsyncMock(return_value=[message])
    await coordinator._async_update_data()

    coordinator.api.get_sms_messages = AsyncMock(side_effect=ZTEConnectionError("blip"))
    data = await coordinator._async_update_data()

    assert data["last_sms"]["content_decoded"] == "hello"
    assert coordinator.endpoint_available(ENDPOINT_SMS_MESSAGES) is True


async def test_endpoint_failures_reports_counts_without_exposing_state(
    coordinator,
) -> None:
    """The diagnostics accessor reports strike counts but cannot be used to set them.

    `diagnostics.py` is a read path (Section 20), so the distinction that earns
    this test is the copy: mutating what the property hands back must not reach
    the coordinator. Returning `self._endpoint_failures` directly would satisfy
    the count assertion and fail the second one.
    """
    coordinator.api.get_sms_messages = AsyncMock(side_effect=ZTEConnectionError("down"))
    await coordinator._async_update_data()

    reported = coordinator.endpoint_failures
    assert reported[ENDPOINT_SMS_MESSAGES] == 1

    reported[ENDPOINT_SMS_MESSAGES] = 99
    assert coordinator.endpoint_failures[ENDPOINT_SMS_MESSAGES] == 1
    assert coordinator.endpoint_available(ENDPOINT_SMS_MESSAGES) is True


async def test_endpoint_recovers(coordinator) -> None:
    """A success resets the endpoint's strike count."""
    coordinator.api.get_sms_messages = AsyncMock(side_effect=ZTEConnectionError("down"))
    for _ in range(FETCH_STRIKE_LIMIT + 1):
        await coordinator._async_update_data()
    assert coordinator.endpoint_available(ENDPOINT_SMS_MESSAGES) is False

    coordinator.api.get_sms_messages = AsyncMock(return_value=[])
    await coordinator._async_update_data()

    assert coordinator.endpoint_available(ENDPOINT_SMS_MESSAGES) is True


# --------------------------------------------------------------------------
# Section 19 — health snapshot
# --------------------------------------------------------------------------


async def test_health_flags_on_first_failure_at_cold_start(coordinator) -> None:
    """Cold start has no held values, so the first failure must flag.

    Waiting out the strike budget here would leave the user with a wholly
    unavailable integration and no explanation for up to N poll intervals.
    """
    coordinator.api.get_all_data = AsyncMock(side_effect=ZTEConnectionError("down"))
    assert coordinator.data is None

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator.health_snapshot["problem"] is True
    assert coordinator.health_snapshot["severity"] == "error"
    assert "no data has been fetched" in coordinator.health_snapshot["issues"][0]


async def test_health_holds_quiet_within_runtime_budget(coordinator) -> None:
    """At runtime a single blip must raise no alarm."""
    await coordinator._async_update_data()
    coordinator.data = dict(GOOD_DATA)
    coordinator.api.get_all_data = AsyncMock(side_effect=ZTEConnectionError("blip"))

    await coordinator._async_update_data()

    assert coordinator.health_snapshot["problem"] is False


async def test_health_flags_at_runtime_strike_limit(coordinator) -> None:
    """At the Nth consecutive runtime failure the verdict flips."""
    await coordinator._async_update_data()
    coordinator.data = dict(GOOD_DATA)
    coordinator.api.get_all_data = AsyncMock(side_effect=ZTEConnectionError("down"))

    for _ in range(FETCH_STRIKE_LIMIT):
        await coordinator._async_update_data()

    assert coordinator.health_snapshot["problem"] is True
    assert coordinator.health_snapshot["consecutive_failures"] == FETCH_STRIKE_LIMIT


async def test_health_clears_in_the_same_cycle_as_a_success(coordinator) -> None:
    """Recovery must clear the verdict immediately, not on some later poll."""
    await coordinator._async_update_data()
    coordinator.data = dict(GOOD_DATA)
    coordinator.api.get_all_data = AsyncMock(side_effect=ZTEConnectionError("down"))
    for _ in range(FETCH_STRIKE_LIMIT):
        await coordinator._async_update_data()
    assert coordinator.health_snapshot["problem"] is True

    coordinator.api.get_all_data = AsyncMock(return_value=dict(GOOD_DATA))
    await coordinator._async_update_data()

    assert coordinator.health_snapshot["problem"] is False
    assert coordinator.health_snapshot["consecutive_failures"] == 0


async def test_health_detects_contract_drift(coordinator) -> None:
    """A successful poll that parses to nothing meaningful is a problem.

    This is the failure HA cannot see: the fetch succeeds, so nothing goes
    unavailable, but every field the integration reads has been renamed.
    """
    await coordinator._async_update_data()
    assert coordinator.health_snapshot["problem"] is False

    # Every field the integration knows about stops being reported — a firmware
    # rename is one way to get here, an integration fault is another.
    coordinator.api.get_all_data = AsyncMock(
        return_value={"totally_different_key": "1", "another_new_one": "2"}
    )
    for _ in range(FETCH_STRIKE_LIMIT):
        await coordinator._async_update_data()

    assert coordinator.health_snapshot["problem"] is True
    # Compared against the constant rather than a substring: the wording is
    # user-facing and has been revised, the condition it reports has not.
    assert coordinator.health_snapshot["issues"][0] == DRIFT_CONTRACT


async def test_drift_needs_no_verdict_before_a_baseline(coordinator) -> None:
    """Startup grace — an empty first poll must not be called drift."""
    coordinator.api.get_all_data = AsyncMock(return_value={"unknown": "shape"})

    await coordinator._async_update_data()

    assert coordinator.health_snapshot["problem"] is False


async def test_drift_never_fires_on_a_router_that_never_reported(coordinator) -> None:
    """Drift means data went away, not that it was never there.

    A router this integration does not fully support — a `goform` sibling that
    spells the core keys differently — would return a payload containing none
    of `CORE_KEYS` on *every* poll, forever. Calling that "the data has changed
    unexpectedly" would be wrong twice over: nothing changed, and the user
    cannot act on it.

    The guarantee is carried implicitly, by `_drift_baseline` starting as an
    empty set and the grace branch testing it for truthiness — so it never
    establishes until a core key actually appears. That is easy to break in a
    refactor (`None` plus an `is None` test would behave completely
    differently) and nothing else asserts it, which is why this test loops well
    past the strike limit rather than checking a single poll.
    """
    coordinator.api.get_all_data = AsyncMock(return_value={"unknown": "shape"})

    for _ in range(FETCH_STRIKE_LIMIT * 4):
        await coordinator._async_update_data()

    assert coordinator.health_snapshot["problem"] is False
    assert coordinator.health_snapshot["drift"] == []
    assert not coordinator._drift_baseline


async def test_health_reports_degraded_endpoint_on_success(coordinator) -> None:
    """A dead optional endpoint shows up even while the poll succeeds."""
    coordinator.api.get_sms_messages = AsyncMock(side_effect=ZTEConnectionError("down"))
    for _ in range(FETCH_STRIKE_LIMIT + 1):
        await coordinator._async_update_data()

    assert coordinator.health_snapshot["problem"] is True
    assert coordinator.health_snapshot["degraded_capabilities"] == ["SMS messages"]


async def test_health_reports_degraded_endpoint_during_a_total_outage(
    coordinator,
) -> None:
    """Both failure kinds at once must both be reported.

    A dead optional endpoint plus an unreachable router is the state a user is
    most likely to be in when they finally look at this sensor, and it is the
    one combination neither single-failure test covers.
    """
    coordinator.api.get_sms_messages = AsyncMock(side_effect=ZTEConnectionError("down"))
    for _ in range(FETCH_STRIKE_LIMIT + 1):
        await coordinator._async_update_data()
    coordinator.data = dict(GOOD_DATA)

    coordinator.api.get_all_data = AsyncMock(side_effect=ZTEConnectionError("down"))
    for _ in range(FETCH_STRIKE_LIMIT):
        await coordinator._async_update_data()

    snapshot = coordinator.health_snapshot
    assert snapshot["problem"] is True
    assert snapshot["degraded_capabilities"] == ["SMS messages"]
    assert any("consecutive failures" in issue for issue in snapshot["issues"])
    assert any("Degraded" in issue for issue in snapshot["issues"])


async def test_unreachable_repair_waits_out_a_reboot(coordinator, hass) -> None:
    """Three strikes is a router reboot, not a fault worth a Repair.

    Raising at FETCH_STRIKE_LIMIT would put a Repair on screen every time the user
    restarts their router, which is the Repairs-panel noise Section 19 warns
    against.
    """
    registry = ir.async_get(hass)
    await coordinator._async_update_data()
    coordinator.data = dict(GOOD_DATA)
    coordinator.api.get_all_data = AsyncMock(side_effect=ZTEConnectionError("down"))

    for _ in range(UNREACHABLE_STRIKE_LIMIT - 1):
        with suppress(UpdateFailed):
            await coordinator._async_update_data()

    assert coordinator.health_snapshot["problem"] is True
    assert (
        registry.async_get_issue(DOMAIN, coordinator._repair_ids[REPAIR_CONN_ERROR])
        is None
    )


async def test_unreachable_repair_raised_after_sustained_failure(
    coordinator, hass
) -> None:
    """A condition that has stopped resolving itself earns a Repair."""
    registry = ir.async_get(hass)
    await coordinator._async_update_data()
    coordinator.data = dict(GOOD_DATA)
    coordinator.api.get_all_data = AsyncMock(side_effect=ZTEConnectionError("down"))

    for _ in range(UNREACHABLE_STRIKE_LIMIT):
        with suppress(UpdateFailed):
            await coordinator._async_update_data()

    issue = registry.async_get_issue(DOMAIN, coordinator._repair_ids[REPAIR_CONN_ERROR])
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    # The text names the host so the user can compare it against the router's
    # actual address — the single most useful fact when an IP has changed.
    assert issue.translation_placeholders["host"] == "192.168.0.1"
    assert REPAIR_CONN_ERROR in coordinator.health_snapshot["repairs"]


async def test_unreachable_repair_clears_on_recovery(coordinator, hass) -> None:
    """One successful poll clears it, however long it was raised."""
    registry = ir.async_get(hass)
    await coordinator._async_update_data()
    coordinator.data = dict(GOOD_DATA)
    coordinator.api.get_all_data = AsyncMock(side_effect=ZTEConnectionError("down"))
    for _ in range(UNREACHABLE_STRIKE_LIMIT):
        with suppress(UpdateFailed):
            await coordinator._async_update_data()
    assert (
        registry.async_get_issue(DOMAIN, coordinator._repair_ids[REPAIR_CONN_ERROR])
        is not None
    )

    coordinator.api.get_all_data = AsyncMock(return_value=dict(GOOD_DATA))
    await coordinator._async_update_data()

    assert (
        registry.async_get_issue(DOMAIN, coordinator._repair_ids[REPAIR_CONN_ERROR])
        is None
    )
    assert coordinator.health_snapshot["repairs"] == []


async def test_health_computation_never_crashes_the_update(coordinator) -> None:
    """A broken health computation must not break the poll it diagnoses."""
    with patch.object(
        coordinator, "_check_contract_drift", side_effect=ValueError("boom")
    ):
        data = await coordinator._async_update_data()

    assert data["network_type"] == "ENDC"
    assert coordinator.health_snapshot["severity"] == "unknown"


# --------------------------------------------------------------------------
# The split batch poll — a failing second half must not blank the first
# --------------------------------------------------------------------------


async def test_extended_fetch_failure_leaves_core_data_intact(coordinator) -> None:
    """The whole point of splitting by criticality.

    Signal and Data come from the mandatory fetch. A diagnostics fetch that
    fails must not take them with it.
    """
    coordinator.api.get_extended_data = AsyncMock(
        side_effect=ZTEConnectionError("second batch down")
    )

    data = await coordinator._async_update_data()

    assert data["network_type"] == GOOD_DATA["network_type"]
    assert data["signalbar"] == GOOD_DATA["signalbar"]


async def test_extended_fetch_holds_last_good_within_budget(coordinator) -> None:
    """A glitch must not blank diagnostics on the first failed cycle."""
    coordinator.api.get_extended_data = AsyncMock(
        return_value={"sntp_timezone": "0-1", "battery_value": "100"}
    )
    await coordinator._async_update_data()

    coordinator.api.get_extended_data = AsyncMock(
        side_effect=ZTEConnectionError("blip")
    )
    for _ in range(FETCH_STRIKE_LIMIT):
        data = await coordinator._async_update_data()
        assert data["sntp_timezone"] == "0-1"
        assert coordinator.endpoint_available(ENDPOINT_EXTENDED)


async def test_extended_fetch_degrades_only_itself_past_the_budget(
    coordinator,
) -> None:
    """Past three strikes its entities go unavailable — and only its."""
    coordinator.api.get_extended_data = AsyncMock(
        side_effect=ZTEConnectionError("down")
    )
    for _ in range(FETCH_STRIKE_LIMIT + 1):
        data = await coordinator._async_update_data()

    assert not coordinator.endpoint_available(ENDPOINT_EXTENDED)
    # The mandatory half is untouched, so the integration is not "unavailable".
    assert coordinator.last_update_success
    assert data["network_type"] == GOOD_DATA["network_type"]
    assert "sntp_timezone" not in data


async def test_extended_fetch_recovers(coordinator) -> None:
    """One success clears the strike count and the entities come back."""
    coordinator.api.get_extended_data = AsyncMock(
        side_effect=ZTEConnectionError("down")
    )
    for _ in range(FETCH_STRIKE_LIMIT + 1):
        await coordinator._async_update_data()
    assert not coordinator.endpoint_available(ENDPOINT_EXTENDED)

    coordinator.api.get_extended_data = AsyncMock(return_value={"rscp": "-70"})
    data = await coordinator._async_update_data()

    assert coordinator.endpoint_available(ENDPOINT_EXTENDED)
    assert data["rscp"] == "-70"


async def test_extended_fetch_auth_error_still_drives_reauth(coordinator) -> None:
    """A rejected session is integration-wide and must not be absorbed here."""
    # Fails once, then succeeds — `_fetch_all` is retried whole after the
    # re-login, so the second call must be able to answer.
    coordinator.api.get_extended_data = AsyncMock(
        side_effect=[ZTEAuthError("expired"), {"rscp": "-70"}]
    )

    data = await coordinator._async_update_data()

    # Not swallowed into this one endpoint's strike count: it reached the
    # global handler, which renewed the session and retried.
    coordinator.api.login.assert_awaited()
    assert coordinator.endpoint_available(ENDPOINT_EXTENDED)
    assert data["rscp"] == "-70"


async def test_core_data_wins_over_a_stale_extended_value(coordinator) -> None:
    """Merge order matters if the two batches ever come to share a key."""
    coordinator.api.get_extended_data = AsyncMock(
        return_value={"network_type": "STALE"}
    )

    data = await coordinator._async_update_data()

    assert data["network_type"] == GOOD_DATA["network_type"]


async def test_degraded_extended_fetch_is_named_in_health(coordinator) -> None:
    """Section 19: a degraded capability must be reported, not just silent."""
    coordinator.api.get_extended_data = AsyncMock(
        side_effect=ZTEConnectionError("down")
    )
    for _ in range(FETCH_STRIKE_LIMIT + 1):
        await coordinator._async_update_data()

    assert (
        "Extended diagnostics" in coordinator.health_snapshot["degraded_capabilities"]
    )


# --------------------------------------------------------------------------
# Repair lifecycle — x_proj_checks_20260802 §3.8a/b
# --------------------------------------------------------------------------


async def test_repair_ids_are_scoped_to_the_config_entry(coordinator, hass) -> None:
    """Two routers must not share one slot in the issue registry.

    The registry keys on `(domain, issue_id)`, so a bare id gives every entry
    the same row: with two routers and one failing, the healthy one's next
    successful poll deletes the failing one's repair. The distinction this
    asserts is that the id carries the entry, not merely that a repair is
    raised at all.
    """
    coordinator.api.get_all_data = AsyncMock(
        side_effect=ZTEConnectionError("router gone")
    )
    for _ in range(UNREACHABLE_STRIKE_LIMIT + 1):
        with suppress(UpdateFailed):
            await coordinator._async_update_data()

    issues = ir.async_get(hass).issues
    raised = [issue_id for (domain, issue_id) in issues if domain == DOMAIN]

    assert raised, "no repair was raised at all"
    assert all(coordinator.entry.entry_id in issue_id for issue_id in raised), (
        f"repair ids are not entry-scoped: {raised}"
    )


async def test_a_legacy_unscoped_repair_is_cleared_on_setup(coordinator, hass) -> None:
    """An id raised by an earlier version must not be orphaned by the rename.

    `ir.async_delete_issue` looks up by id, so a repair live under the old bare
    id has no code left that can clear it once the ids are scoped, and no UI
    path either — `is_fixable=False`. Startup deletes the legacy ids so the
    rename cannot strand one.
    """
    ir.async_create_issue(
        hass,
        DOMAIN,
        "sms_storage_full",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="sms_storage_full",
        translation_placeholders={"nv_total": "1", "nv_able": "1"},
    )
    assert (DOMAIN, "sms_storage_full") in ir.async_get(hass).issues

    coordinator.clear_legacy_repairs()

    assert (DOMAIN, "sms_storage_full") not in ir.async_get(hass).issues


async def test_unload_clears_the_repairs_this_entry_raised(
    hass: HomeAssistant, entry
) -> None:
    """A repair must not outlive the code that can clear it.

    Every repair here is `is_fixable=False`, so the only route out of the
    Repairs panel is this integration deleting it. Unloading — or deleting the
    integration outright — while one is showing would otherwise leave it there
    permanently, with nothing left that could ever remove it.
    """
    from custom_components.zte_router_5g import async_unload_entry

    entry.add_to_hass(hass)
    api = MagicMock(spec=ZTERouterAPI)
    api.logout = AsyncMock()
    coordinator = ZTERouterDataUpdateCoordinator(hass, entry, api)
    entry.runtime_data = coordinator

    coordinator._set_unreachable_repair(True)
    assert (DOMAIN, f"{entry.entry_id}_{REPAIR_CONN_ERROR}") in ir.async_get(
        hass
    ).issues

    with patch.object(
        hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)
    ):
        assert await async_unload_entry(hass, entry) is True

    assert (
        DOMAIN,
        f"{entry.entry_id}_{REPAIR_CONN_ERROR}",
    ) not in ir.async_get(hass).issues


async def test_removal_clears_repairs_left_by_a_failed_unload(
    hass: HomeAssistant, entry
) -> None:
    """Removal is the last chance, and it cannot read `runtime_data`.

    HA has already discarded `runtime_data` by the time `async_remove_entry`
    runs, so the ids have to be rebuilt from `entry_id`. The distinction from
    the unload test: this path must work with no coordinator in existence at
    all, which is exactly the case where a repair would otherwise be stranded.
    """
    from custom_components.zte_router_5g import async_remove_entry

    entry.add_to_hass(hass)
    for name in (REPAIR_CONN_ERROR, REPAIR_AUTH_FAILED):
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{entry.entry_id}_{name}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=name,
            translation_placeholders={},
        )

    await async_remove_entry(hass, entry)

    remaining = [i for (d, i) in ir.async_get(hass).issues if d == DOMAIN]
    assert remaining == []


async def test_force_refresh_clears_its_flag_when_the_request_raises(coordinator):
    """Every path out of `async_force_refresh` must leave the flag clear.

    The flag is consumed at the top of `_async_update_data`, so if the refresh
    request never runs an update, a set flag survives to the next **scheduled**
    poll — which then fetches despite Pause Polling being on. Self-correcting
    after one cycle, but Section 13 asks that the one-shot really be one-shot.
    """
    coordinator.async_request_refresh = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await coordinator.async_force_refresh()

    assert coordinator._force_refresh_once is False


async def test_drift_uses_its_own_strike_budget_not_the_fetch_one(
    coordinator,
) -> None:
    """The two budgets must be independently movable. Chore C-015.

    They are both 3 today, so a test asserting "drift fires on the third poll"
    passes whichever constant the code reads and proves nothing. Moving one of
    them is the only way to tell them apart: with the drift budget patched to 5,
    drift must still be quiet at 4 — which it would not be if the check were
    still counting against `FETCH_STRIKE_LIMIT`.
    """
    await coordinator._async_update_data()
    coordinator.api.get_all_data = AsyncMock(return_value={"renamed": "1"})

    with patch(
        "custom_components.zte_router_5g.coordinator.HEALTH_DRIFT_STRIKE_LIMIT", 5
    ):
        for _ in range(FETCH_STRIKE_LIMIT + 1):
            await coordinator._async_update_data()
        assert coordinator.health_snapshot["drift"] == [], (
            "drift fired on the fetch budget, so the split is not real"
        )

        await coordinator._async_update_data()
        assert coordinator.health_snapshot["drift"] == [DRIFT_CONTRACT]
