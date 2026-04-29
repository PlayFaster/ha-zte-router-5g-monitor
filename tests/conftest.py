"""Fixtures and utilities for testing the ZTE Router integration."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture
def mock_config_entry():
    """Fixture to mock a ConfigEntry."""
    entry = MockConfigEntry(
        unique_id="zte_unique_123",
        domain="zte_router_5g",
        title="My ZTE Router",
        data={"model": "MC7010", "sw_version": "V1.0.0"},
        options={
            CONF_HOST: "192.168.0.1",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "password",
        },
    )

    # Mock async_create_background_task to actually run the task
    def mock_create_background_task(hass, coro, name):
        import asyncio
        from unittest.mock import Mock

        # If it's a real HA instance, use its task creation
        if hasattr(hass, "async_create_task") and not isinstance(
            hass.async_create_task, (Mock, MagicMock)
        ):
            return hass.async_create_task(coro, name)

        # Otherwise, try to run it in the current loop to avoid RuntimeWarning
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(coro)
        except RuntimeError:
            # Fallback if no loop is running
            coro.close()
            return MagicMock()

    entry.async_create_background_task = MagicMock(
        side_effect=mock_create_background_task
    )
    return entry


@pytest.fixture
def mock_coordinator():
    """Fixture to mock a DataUpdateCoordinator."""
    coordinator = MagicMock()
    coordinator.data = {}
    coordinator.last_update_success_time = None
    coordinator.async_request_refresh = AsyncMock()
    # Add flat identity attributes for modern tests
    coordinator.model = "MC7010"
    coordinator.sw_version = "V1.0.0"
    coordinator.mac = "00:11:22:33:44:55"
    return coordinator


class MockResponse:
    """Helper to mock aiohttp responses."""

    def __init__(self, json_data=None, status=200, cookies=None):
        """Initialize the mock response."""
        self._json_data = json_data
        self.status = status
        self.cookies = cookies or {}

    async def json(self, **kwargs):
        """Return the JSON data."""
        return self._json_data

    async def __aenter__(self):
        """Enter the context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the context manager."""
        pass


@pytest.fixture
def mock_aiohttp_client():
    """Fixture to mock aiohttp ClientSession."""
    session = MagicMock()
    # We initialize get/post as MagicMocks.
    # Tests can then set .return_value = MockResponse(...) OR .side_effect = [...]
    session.get = MagicMock()
    session.post = MagicMock()
    return session
