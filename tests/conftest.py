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

    # Mock async_create_background_task to schedule the coroutine on the event loop
    def mock_create_background_task(hass, coro, name):
        from unittest.mock import Mock

        # If it's a real HA instance, use its task creation
        if hasattr(hass, "async_create_task") and not isinstance(
            hass.async_create_task, (Mock, MagicMock)
        ):
            return hass.async_create_task(coro, name)

        # Schedule the coroutine to avoid "coroutine was never awaited" warnings
        import asyncio

        return asyncio.ensure_future(coro)

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
    # Explicit user actions route through async_force_refresh so they fetch
    # even while polling is paused (dev_standards Section 13).
    coordinator.async_force_refresh = AsyncMock()
    coordinator.endpoint_available = MagicMock(return_value=True)
    # Add flat identity attributes for modern tests
    coordinator.model = "MC7010"
    coordinator.sw_version = "V1.0.0"
    coordinator.imei = "864155042229309"
    return coordinator


class MockResponse:
    """Helper to mock aiohttp responses."""

    def __init__(self, json_data=None, status=200, cookies=None, headers=None, url=""):
        """Initialize the mock response."""
        self._json_data = json_data
        self.status = status
        self.cookies = cookies or {}
        self.headers = headers or {"Content-Type": "application/json"}
        self._url = url

    @property
    def url(self):
        """Return the URL."""
        return self._url

    async def json(self, **kwargs):
        """Return the JSON data."""
        return self._json_data

    async def text(self):
        """Return the text body."""
        if self._json_data is not None:
            return str(self._json_data)
        return ""

    async def read(self):
        """Return the raw bytes."""
        return b""

    async def __aenter__(self):
        """Enter the context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the context manager."""


@pytest.fixture
def mock_aiohttp_client():
    """Fixture to mock aiohttp ClientSession."""
    session = MagicMock()
    session.get = MagicMock(return_value=MockResponse())
    session.post = MagicMock()

    def _request_side_effect(method, *args, **kwargs):
        if method.upper() == "GET":
            return session.get(*args, **kwargs)
        if method.upper() == "POST":
            return session.post(*args, **kwargs)
        return MagicMock()

    session.request = MagicMock(side_effect=_request_side_effect)
    return session


def assert_links_to_parent(info, domain: str, parent_ident: str) -> None:
    """Assert a `DeviceInfo` links to the given parent, on either HA branch.

    The key differs by Home Assistant version and the integration
    feature-detects it (`_compat.via_device_link`): `via_device` as an
    identifier tuple on <=2026.7, `via_device_id` as a resolved device id on
    2026.8+. Hard-coding either one makes the test pass on the HA the suite
    happens to run against and fail on the other — which is exactly what
    happened when the devcontainer took 2026.8.0b0 and nine device_info tests
    broke while the production code was behaving correctly.

    Only the presence and exclusivity of the link is asserted here. Under a
    `MagicMock` coordinator the modern branch resolves against a mock registry,
    so the id has no meaningful value to compare. The *shape and value* of what
    `via_device_link` returns is covered properly, with a patched registry, in
    `test_compat.py`.
    """
    from custom_components.zte_router_5g import _compat

    if _compat._HAS_BY_IDENTIFIER:
        assert "via_device_id" in info, "no parent link emitted on the 2026.8+ branch"
        assert "via_device" not in info, (
            "both keys present — DeviceInfo raises if via_device and "
            "via_device_id are set together"
        )
    else:
        assert info["via_device"] == (domain, parent_ident)
        assert "via_device_id" not in info


def assert_is_root(info) -> None:
    """Assert a `DeviceInfo` is the root device — no parent link, either shape."""
    assert "via_device" not in info
    assert "via_device_id" not in info
