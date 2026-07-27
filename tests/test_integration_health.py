"""Tests for the Section 19 Integration Health sensor.

The point of this entity is to survive the failure it exists to report, so
almost every test here asserts on state *during* a fault rather than after a
successful poll.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zte_router_5g.api import ZTEConnectionError, ZTERouterAPI
from custom_components.zte_router_5g.binary_sensor import (
    INTEGRATION_HEALTH_DESCRIPTION,
    ZTEIntegrationHealthSensor,
)
from custom_components.zte_router_5g.const import DOMAIN, FETCH_STRIKE_LIMIT
from custom_components.zte_router_5g.coordinator import (
    DRIFT_CONTRACT,
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
    api.protocol = "http"
    api.get_all_data = AsyncMock(return_value=dict(GOOD_DATA))
    api.get_sms_capacity = AsyncMock(return_value={})
    api.get_sms_messages = AsyncMock(return_value=[])
    api.login = AsyncMock(return_value="stok=test")
    return ZTERouterDataUpdateCoordinator(hass, entry, api)


@pytest.fixture
def health(coordinator, entry):
    """Return the health sensor bound to that coordinator."""
    return ZTEIntegrationHealthSensor(
        coordinator, entry, INTEGRATION_HEALTH_DESCRIPTION
    )


def test_declares_problem_device_class(health) -> None:
    """The sensor must be a diagnostic `problem` binary sensor."""
    assert (
        INTEGRATION_HEALTH_DESCRIPTION.device_class is BinarySensorDeviceClass.PROBLEM
    )
    assert health.unique_id == "864155042229309_integration_health"


def test_available_before_any_poll_has_happened(health, coordinator) -> None:
    """Available at cold start, when `data` is still None.

    The default CoordinatorEntity.available would be True here only by
    accident; the following test covers the case that actually breaks.
    """
    assert coordinator.data is None
    assert health.available is True
    assert health.is_on is False


async def test_stays_available_when_every_other_entity_goes_unavailable(
    health, coordinator
) -> None:
    """The override earns its keep here.

    ``CoordinatorEntity.available`` tracks ``last_update_success``, so without
    the override this sensor would go unavailable at precisely the moment it
    has something to report — and a user reads `unavailable` as "this sensor is
    broken", not "my router is down".
    """
    coordinator.api.get_all_data = AsyncMock(side_effect=ZTEConnectionError("down"))
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    # Force the exact condition the default property keys off, so this test
    # fails if the `available` override is ever removed.
    coordinator.last_update_success = False

    assert health.available is True
    assert health.is_on is True


async def test_reports_total_outage_at_cold_start(health, coordinator) -> None:
    """A cold-start outage flags immediately, not after N intervals."""
    coordinator.api.get_all_data = AsyncMock(side_effect=ZTEConnectionError("down"))

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert health.is_on is True
    attrs = health.extra_state_attributes
    assert attrs["severity"] == "error"
    assert attrs["issues"]


async def test_clears_on_recovery_in_the_same_cycle(health, coordinator) -> None:
    """A success turns the sensor off immediately."""
    await coordinator._async_update_data()
    coordinator.data = dict(GOOD_DATA)
    coordinator.api.get_all_data = AsyncMock(side_effect=ZTEConnectionError("down"))
    for _ in range(FETCH_STRIKE_LIMIT):
        await coordinator._async_update_data()
    assert health.is_on is True

    coordinator.api.get_all_data = AsyncMock(return_value=dict(GOOD_DATA))
    await coordinator._async_update_data()

    assert health.is_on is False
    assert health.extra_state_attributes["issues"] == []


async def test_attributes_are_unrecorded(health) -> None:
    """Detail attributes must never reach the recorder."""
    for key in health.extra_state_attributes:
        assert key in ZTEIntegrationHealthSensor._unrecorded_attributes


async def test_drift_raises_and_clears_a_repair_issue(
    health, coordinator, hass: HomeAssistant
) -> None:
    """Contract drift is the one condition serious enough for a Repair."""
    registry = ir.async_get(hass)
    await coordinator._async_update_data()

    coordinator.api.get_all_data = AsyncMock(return_value={"renamed_everything": "1"})
    for _ in range(FETCH_STRIKE_LIMIT):
        await coordinator._async_update_data()

    assert health.is_on is True
    assert "firmware_contract_drift" in health.extra_state_attributes["repairs"]
    assert registry.async_get_issue(DOMAIN, "firmware_contract_drift") is not None

    # The repair is the actionable signal; `drift` is the published detail a
    # template can read. Both must be set, or the sensor raises an alarm it
    # cannot explain.
    assert health.extra_state_attributes["drift"] == [DRIFT_CONTRACT]

    coordinator.api.get_all_data = AsyncMock(return_value=dict(GOOD_DATA))
    await coordinator._async_update_data()

    assert registry.async_get_issue(DOMAIN, "firmware_contract_drift") is None
    assert health.extra_state_attributes["repairs"] == []
    assert health.extra_state_attributes["drift"] == []


async def test_publishes_the_section_19_attribute_contract(health) -> None:
    """The Section 19 attribute names are a published contract, not internal.

    Users write templates against these, so a rename is a breaking change and a
    missing one silently yields an empty template value. `auth_mode` is
    legitimately absent — this integration has a single auth mode — but `drift`
    is not, because a contract-drift check exists (`_check_contract_drift`).
    """
    attrs = health.extra_state_attributes
    for name in ("severity", "issues", "degraded_capabilities", "drift"):
        assert name in attrs, f"dev_standards Section 19 requires '{name}'"
    assert "last_good_update" in attrs


async def test_existing_repair_is_reflected_not_double_raised(
    health, coordinator
) -> None:
    """The SMS-storage repair shows in attributes without being re-raised."""
    full = {**GOOD_DATA, "nv_sms_able": "20", "sms_nv_total": "20"}
    coordinator.api.get_all_data = AsyncMock(return_value=full)

    await coordinator._async_update_data()

    assert health.is_on is True
    assert "sms_storage_full" in health.extra_state_attributes["repairs"]
    assert "SMS storage is full" in health.extra_state_attributes["issues"]


async def test_never_crashes_the_update_it_diagnoses(health, coordinator) -> None:
    """A broken health computation degrades to unknown, it does not raise."""
    with patch.object(
        coordinator, "_check_contract_drift", side_effect=ValueError("boom")
    ):
        data = await coordinator._async_update_data()

    assert data["network_type"] == "ENDC"
    assert health.available is True
    assert health.extra_state_attributes["severity"] == "unknown"
