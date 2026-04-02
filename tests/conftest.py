"""Fixtures and utilities for testing the ZTE Router integration."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import CONF_HOST


@pytest.fixture
def mock_config_entry():
    """Fixture to mock a ConfigEntry."""
    mock_entry = MagicMock()
    mock_entry.unique_id = "zte_unique_123"
    mock_entry.title = "My ZTE Router"
    # Your code specifically looks in .options for the host
    mock_entry.options = {CONF_HOST: "192.168.0.1"}
    mock_entry.data = {}
    return mock_entry


@pytest.fixture
def mock_coordinator():
    """Fixture to mock a DataUpdateCoordinator."""
    coordinator = MagicMock()
    coordinator.data = {}
    coordinator.last_update_success_time = None
    coordinator.async_request_refresh = AsyncMock()
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
