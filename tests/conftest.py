from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.const import CONF_HOST


@pytest.fixture
def mock_config_entry():
    mock_entry = MagicMock()
    mock_entry.unique_id = "zte_unique_123"
    mock_entry.title = "My ZTE Router"
    # Your code specifically looks in .options for the host
    mock_entry.options = {CONF_HOST: "192.168.0.1"}
    mock_entry.data = {}
    return mock_entry


@pytest.fixture
def mock_coordinator():
    coordinator = MagicMock()
    coordinator.data = {}
    coordinator.last_update_success_time = None
    coordinator.async_request_refresh = AsyncMock()
    return coordinator
