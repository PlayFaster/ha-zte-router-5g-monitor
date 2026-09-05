"""Tests for the ZTE Router init."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.zte_router_5g import (
    _validate_sms_length,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.zte_router_5g.api import (
    ZTEAuthError,
    ZTEConnectionError,
    ZTECredentialsError,
)
from custom_components.zte_router_5g.const import (
    CONF_STOP_POLLING,
    SMS_MAX_CHARS_GSM7,
    SMS_MAX_CHARS_UNICODE,
)
from custom_components.zte_router_5g.coordinator import (
    ZTERouterDataUpdateCoordinator,
)


@pytest.fixture(autouse=True)
def mock_report_usage():
    """Mock report_usage to avoid 'Frame helper not set up' error."""
    with patch("homeassistant.helpers.frame.report_usage"):
        yield


@pytest.fixture
def mock_hass():
    """Create a mock HomeAssistant instance with necessary async methods."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_update_entry = MagicMock()
    return hass


@pytest.mark.asyncio
async def test_setup_entry_success(mock_hass, mock_config_entry):
    """Test successful setup of the integration."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI"),
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        assert await async_setup_entry(mock_hass, mock_config_entry) is True

        coordinator = mock_config_entry.runtime_data
        assert isinstance(coordinator, ZTERouterDataUpdateCoordinator)

        mock_hass.config_entries.async_forward_entry_setups.assert_called_once()
        mock_config_entry.async_create_background_task.assert_called_once()


@pytest.mark.asyncio
async def test_unload_entry_success(mock_hass, mock_config_entry):
    """Test successful unloading of the integration."""
    coordinator = MagicMock()
    # Unload releases the router session (dev_standards Section 10).
    coordinator.api.logout = AsyncMock()
    mock_config_entry.runtime_data = coordinator

    assert await async_unload_entry(mock_hass, mock_config_entry) is True
    coordinator.api.logout.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_update_data_success(mock_hass, mock_config_entry):
    """Test the coordinator's update method success path."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI") as mock_api_class,
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        mock_api = mock_api_class.return_value
        mock_api.get_all_data = AsyncMock(return_value={"network_type": "LTE"})
        mock_api.get_sms_capacity = AsyncMock(return_value={"total": 10})
        mock_api.get_sms_messages = AsyncMock(
            return_value=[
                {
                    "id": "1",
                    "content": "00480065006c006c006f",
                    "content_decoded": "hello",
                    "number_decoded": "123",
                    "date_decoded": "2026-05-23T02:00:00",
                    "tag": "1",
                }
            ]
        )

        # Setup to get the coordinator
        await async_setup_entry(mock_hass, mock_config_entry)
        coordinator = mock_config_entry.runtime_data

        data = await coordinator._async_update_data()

        assert data["network_type"] == "LTE"
        assert data["total"] == 10
        assert data["last_sms"] == {
            "id": "1",
            "content": "00480065006c006c006f",
            "content_decoded": "hello",
            "number_decoded": "123",
            "date_decoded": "2026-05-23T02:00:00",
            "tag": "1",
        }
        assert coordinator.consecutive_failures == 0


@pytest.mark.asyncio
async def test_async_update_data_paused(mock_hass, mock_config_entry):
    """Test update data when paused."""
    # Use object.__setattr__ to bypass the read-only protection of ConfigEntry
    # and ensure required connection options are preserved
    new_options = dict(mock_config_entry.options)
    new_options[CONF_STOP_POLLING] = True
    object.__setattr__(mock_config_entry, "options", new_options)

    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI"),
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        await async_setup_entry(mock_hass, mock_config_entry)
        coordinator = mock_config_entry.runtime_data

        # Case 1: Paused but NOT first run
        coordinator.data = {"cached": "data"}
        data = await coordinator._async_update_data()
        assert data == {"cached": "data"}

        # Case 2: Paused and first run -> attempts fetch (mock failure)
        coordinator.data = None
        coordinator.api.get_all_data = AsyncMock(side_effect=Exception("Fail"))

        data = await coordinator._async_update_data()
        assert data == {}


@pytest.mark.asyncio
async def test_async_update_data_resilience(mock_hass, mock_config_entry):
    """Test failure resilience."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI"),
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        await async_setup_entry(mock_hass, mock_config_entry)
        coordinator = mock_config_entry.runtime_data
        coordinator.data = {"old": "data"}

        coordinator.api.get_all_data = AsyncMock(
            side_effect=Exception("Persistent Fail")
        )

        # First, second and third failures: should return old data
        data = await coordinator._async_update_data()
        assert data == {"old": "data"}
        assert coordinator.consecutive_failures == 1

        data = await coordinator._async_update_data()
        assert data == {"old": "data"}
        assert coordinator.consecutive_failures == 2

        data = await coordinator._async_update_data()
        assert data == {"old": "data"}
        assert coordinator.consecutive_failures == 3

        # Fourth failure: should raise UpdateFailed
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
        assert coordinator.consecutive_failures == 4


@pytest.mark.asyncio
async def test_background_setup_failure(mock_hass, mock_config_entry):
    """A background startup failure must not escape, and must stop before login.

    §1's accepted trade: setup has already returned True and the platforms are
    forwarded, so the background task raising would surface as an unhandled
    task exception rather than a retry. The distinction from the success case
    is that the chain stops at the protocol probe — attempting a login against
    a router that never answered is what counts against a lockout.
    """
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI") as mock_api_class,
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        mock_api = mock_api_class.return_value
        mock_api.try_set_protocol = AsyncMock(
            side_effect=TimeoutError("Background Fail")
        )
        mock_api.login = AsyncMock()

        background_coro = None

        def mock_capture_task(hass, coro, name):
            nonlocal background_coro
            background_coro = coro
            return MagicMock()

        mock_config_entry.async_create_background_task = mock_capture_task

        assert await async_setup_entry(mock_hass, mock_config_entry) is True

        assert background_coro is not None, "setup created no background task"
        await background_coro

        mock_api.try_set_protocol.assert_awaited_once()
        mock_api.login.assert_not_awaited()


@pytest.mark.asyncio
async def test_background_setup_adopts_a_measured_key_set(mock_hass, mock_config_entry):
    """A measurement that passed validation replaces the module constant.

    The constant is five names taken from one MC7010; the MC888 Pro in issue
    #56 answers a different set, and a dead session on that device reads as
    `live` while the constant is in force.
    """
    measured = frozenset({"imei", "model_name", "network_type"})
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI") as mock_api_class,
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        mock_api = mock_api_class.return_value
        mock_api.try_set_protocol = AsyncMock(return_value=None)
        mock_api.login = AsyncMock(return_value=None)
        mock_api.logout = AsyncMock(return_value=None)
        mock_api.get_all_data = AsyncMock(return_value={"network_type": "ENDC"})
        mock_api.measure_unauthenticated_keys = AsyncMock(return_value=measured)

        background_coro = None

        def mock_capture_task(hass, coro, name):
            nonlocal background_coro
            background_coro = coro
            return MagicMock()

        mock_config_entry.async_create_background_task = mock_capture_task
        await async_setup_entry(mock_hass, mock_config_entry)
        await background_coro

        assert mock_api.unauthenticated_keys == measured


async def test_background_setup_success(mock_hass, mock_config_entry):
    """The offloaded task probes the protocol, logs in, and stores the session.

    Separates "the task ran" from "the task did its job". The order matters:
    `login()` builds its URL from the protocol the probe resolves, so a login
    awaited before the probe would go to the wrong scheme and still look fine
    against a mock that answers either way.
    """
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI") as mock_api_class,
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        mock_api = mock_api_class.return_value
        mock_api.try_set_protocol = AsyncMock(return_value=None)
        mock_api.login = AsyncMock(return_value="stok=test")
        mock_api.get_all_data = AsyncMock(return_value={"network_type": "ENDC"})
        mock_api.measure_unauthenticated_keys = AsyncMock(return_value=frozenset())
        mock_api.logout = AsyncMock(return_value=None)

        background_coro = None

        def mock_capture_task(hass, coro, name):
            nonlocal background_coro
            background_coro = coro
            return MagicMock()

        mock_config_entry.async_create_background_task = mock_capture_task

        assert await async_setup_entry(mock_hass, mock_config_entry) is True

        assert background_coro is not None, "setup created no background task"
        await background_coro

        # Both carry the short §1 probe budget explicitly. Reusing the client
        # default (10-15 s) is the trap that section names: it blocks startup
        # long enough to trip the very warning the offload exists to prevent.
        mock_api.try_set_protocol.assert_awaited_once_with(5)
        # Twice: once to establish the session, and once to restore it after
        # the unauthenticated key measurement, which can only be taken with no
        # session and so ends the first one.
        assert mock_api.login.await_count == 2
        assert all(call.args == (5,) for call in mock_api.login.await_args_list)
        mock_api.logout.assert_awaited_once()
        mock_api.measure_unauthenticated_keys.assert_awaited_once()
        mock_api.get_all_data.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        # A password the router rejects is the user's to fix, so it earns the
        # reauth prompt.
        (ZTECredentialsError("Bad password"), ConfigEntryAuthFailed),
        # A session that merely lapsed is ours, and re-login has already been
        # tried. Prompting here would tell the user their credentials were
        # wrong when they were not, and re-entering them would change nothing.
        (ZTEAuthError("Session expired"), UpdateFailed),
    ],
)
async def test_only_a_rejected_password_triggers_reauth(
    mock_hass, mock_config_entry, error, expected
):
    """Both auth failures hold values for three strikes, then diverge."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI"),
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        await async_setup_entry(mock_hass, mock_config_entry)
        coordinator = mock_config_entry.runtime_data
        coordinator.data = {"old": "data"}
        coordinator.api.get_all_data = AsyncMock(side_effect=error)
        coordinator.api.login = AsyncMock(side_effect=error)

        # First 3 failures return cached data (resilience)
        for i in range(3):
            data = await coordinator._async_update_data()
            assert data == {"old": "data"}
            assert coordinator.consecutive_failures == i + 1

        with pytest.raises(expected):
            await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_async_setup_registers_services(mock_hass):
    """Test that async_setup registers the integration services."""
    from custom_components.zte_router_5g import async_setup

    with patch.object(mock_hass.services, "async_register") as mock_register:
        assert await async_setup(mock_hass, {}) is True
        assert mock_register.call_count == 5
        # Verify the service names registered
        registered_services = [call[0][1] for call in mock_register.call_args_list]
        assert "send_sms" in registered_services
        assert "delete_sms" in registered_services
        assert "delete_all_sms" in registered_services
        assert "reset_entities" in registered_services
        assert "get_sms_list" in registered_services


@pytest.mark.asyncio
async def test_service_send_sms(mock_hass, mock_config_entry):
    """Test the send_sms service call."""
    from custom_components.zte_router_5g import async_send_sms

    mock_api = AsyncMock()
    mock_coordinator = MagicMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_coordinator.api = mock_api
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"target": ["+123456"], "message": "test msg"}

    await async_send_sms(mock_hass, call)
    mock_api.send_sms.assert_called_once_with("+123456", "test msg")


@pytest.mark.asyncio
async def test_service_delete_sms(mock_hass, mock_config_entry):
    """Test the delete_sms service call."""
    from custom_components.zte_router_5g import async_delete_sms

    mock_api = AsyncMock()
    mock_coordinator = MagicMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_coordinator.api = mock_api
    mock_coordinator.async_request_refresh = AsyncMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"index": 5}

    await async_delete_sms(mock_hass, call)
    mock_api.delete_sms.assert_called_once_with("5")
    mock_coordinator.async_force_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_service_delete_all_sms_simple(mock_hass, mock_config_entry):
    """Test the delete_all_sms service call with keep_last = 0."""
    from custom_components.zte_router_5g import async_delete_all_sms

    mock_api = AsyncMock()
    mock_coordinator = MagicMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_coordinator.api = mock_api
    mock_coordinator.async_request_refresh = AsyncMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"keep_last": 0}

    await async_delete_all_sms(mock_hass, call)
    mock_api.delete_all.assert_called_once()
    mock_api.get_sms_messages.assert_not_called()
    mock_coordinator.async_force_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_service_delete_all_sms_keep_last(mock_hass, mock_config_entry):
    """Test the delete_all_sms service call with keep_last > 0."""
    from custom_components.zte_router_5g import async_delete_all_sms

    mock_api = AsyncMock()
    mock_api.get_sms_messages.return_value = [
        {"id": "4"},
        {"id": "3"},
        {"id": "2"},
        {"id": "1"},
    ]
    mock_coordinator = MagicMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_coordinator.api = mock_api
    mock_coordinator.async_request_refresh = AsyncMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"keep_last": 2}

    await async_delete_all_sms(mock_hass, call)
    mock_api.get_sms_messages.assert_called_once_with(mem_store="1")
    mock_api.delete_sms.assert_called_once_with("2;1")
    mock_coordinator.async_force_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_service_get_sms_list(mock_hass, mock_config_entry):
    """Test the get_sms_list service call with response."""
    from custom_components.zte_router_5g import async_get_sms_list

    mock_api = AsyncMock()
    mock_api.get_sms_messages.return_value = [
        {
            "id": "10",
            "number_decoded": "123",
            "content_decoded": "text1",
            "date_decoded": "2026-05-23T01:27:08",
            "tag": "1",
        },
        {
            "id": "9",
            "number_decoded": "456",
            "content_decoded": "text2",
            "date_decoded": "2026-05-23T01:25:08",
            "tag": "0",
        },
        {
            "id": "8",
            "number_decoded": "789",
            "content_decoded": "text3",
            "date_decoded": "2026-05-23T01:20:08",
            "tag": "2",
        },
    ]
    mock_coordinator = MagicMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_coordinator.api = mock_api
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {
        "page": 1,
        "count": 10,
        "box_type": 1,
    }

    result = await async_get_sms_list(mock_hass, call)
    messages = result["messages"]

    assert len(messages) == 2
    assert messages[0]["index"] == 10
    assert messages[0]["phone"] == "123"
    assert messages[0]["content"] == "text1"
    assert messages[0]["read"] is False

    assert messages[1]["index"] == 9
    assert messages[1]["phone"] == "456"
    assert messages[1]["content"] == "text2"
    assert messages[1]["read"] is True

    # `date` is the fifth field of a published response and was asserted
    # nowhere in the suite. It is also the one field that is not a straight
    # copy — it comes from `_parse_date`, which returns the router's raw string
    # unchanged when it cannot parse it.
    assert messages[0]["date"] == "2026-05-23T01:27:08"
    assert messages[1]["date"] == "2026-05-23T01:25:08"


@pytest.mark.asyncio
async def test_get_sms_list_reports_a_missing_date_as_empty_not_null(
    mock_hass, mock_config_entry, mock_coordinator
):
    """A record with no date must return "", never None.

    The distinction a template author needs: `""` means the router reported no
    date, and it is a string like every other value in the response. Changing
    the `.get("date_decoded", "")` default to `.get("date_decoded")` puts
    `null` into a published field, which is otherwise invisible — nothing
    asserted this field at all.
    """
    from custom_components.zte_router_5g import async_get_sms_list

    mock_api = AsyncMock()
    mock_api.get_sms_messages.return_value = [
        {
            "id": "2",
            "number_decoded": "1",
            "content_decoded": "a",
            "date_decoded": "2026-05-23T01:00:00",
            "tag": "1",
        },
        {"id": "1", "number_decoded": "2", "content_decoded": "b", "tag": "1"},
    ]
    mock_coordinator.api = mock_api
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"page": 1, "count": 10, "box_type": 1}

    messages = (await async_get_sms_list(mock_hass, call))["messages"]

    assert messages[0]["date"] == "2026-05-23T01:00:00"
    assert messages[1]["date"] == ""


@pytest.mark.asyncio
async def test_get_sms_list_page_two_returns_the_second_slice(
    mock_hass, mock_config_entry, mock_coordinator
):
    """Pagination is only ever exercised on page 1, where the maths cannot fail.

    `(page - 1) * count` is `0` for any `count` when `page` is 1, so every
    existing call executes the slice without distinguishing it. A regression to
    `page * count`, or a dropped `- 1`, silently drops or repeats a whole page
    of a documented service response.
    """
    from custom_components.zte_router_5g import async_get_sms_list

    mock_api = AsyncMock()
    mock_api.get_sms_messages.return_value = [
        {
            "id": str(i),
            "number_decoded": "1",
            "content_decoded": f"m{i}",
            "date_decoded": f"2026-05-23T01:0{i}:00",
            "tag": "1",
        }
        for i in range(5, 0, -1)
    ]
    mock_coordinator.api = mock_api
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    def page(n):
        call = MagicMock(spec=ServiceCall)
        call.data = {"page": n, "count": 2, "box_type": 1}
        return call

    first = (await async_get_sms_list(mock_hass, page(1)))["messages"]
    second = (await async_get_sms_list(mock_hass, page(2)))["messages"]
    third = (await async_get_sms_list(mock_hass, page(3)))["messages"]

    assert [m["index"] for m in first] == [5, 4]
    assert [m["index"] for m in second] == [3, 2]
    assert [m["index"] for m in third] == [1]


@pytest.mark.asyncio
async def test_get_coordinator_with_entry_id(mock_hass, mock_config_entry):
    """Test _get_coordinator with specific entry_id (__init__.py:78-81)."""
    from custom_components.zte_router_5g import _get_coordinator

    mock_coordinator = MagicMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_get_entry.return_value = mock_config_entry

    result = _get_coordinator(mock_hass, {"entry_id": "test_entry"})
    assert result is mock_coordinator


@pytest.mark.asyncio
async def test_get_coordinator_with_entry_id_not_ready(mock_hass, mock_config_entry):
    """Test _get_coordinator with entry_id but entry not ready (__init__.py:82)."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.zte_router_5g import _get_coordinator

    mock_config_entry.runtime_data = None
    mock_hass.config_entries.async_get_entry.return_value = mock_config_entry

    with pytest.raises(HomeAssistantError) as err:
        _get_coordinator(mock_hass, {"entry_id": "test_entry"})

    assert err.value.translation_key == "entry_not_ready"


@pytest.mark.asyncio
async def test_get_coordinator_no_entries(mock_hass):
    """Test _get_coordinator when no entries exist (__init__.py:90)."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.zte_router_5g import _get_coordinator

    mock_hass.config_entries.async_entries.return_value = []

    with pytest.raises(HomeAssistantError) as err:
        _get_coordinator(mock_hass, {})

    assert err.value.translation_key == "no_entries_found"


@pytest.mark.asyncio
async def test_get_coordinator_single_entry_fallback(mock_hass, mock_config_entry):
    """Test _get_coordinator auto-selects the sole entry when no entry_id is given."""
    from custom_components.zte_router_5g import _get_coordinator

    mock_coordinator = MagicMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    result = _get_coordinator(mock_hass, {})
    assert result is mock_coordinator


@pytest.mark.asyncio
async def test_get_coordinator_multiple_entries(mock_hass):
    """Test _get_coordinator requires entry_id when more than one router is loaded."""
    from homeassistant.exceptions import ServiceValidationError

    from custom_components.zte_router_5g import _get_coordinator

    entry_a = MagicMock()
    entry_a.runtime_data = MagicMock()
    entry_b = MagicMock()
    entry_b.runtime_data = MagicMock()
    mock_hass.config_entries.async_entries.return_value = [entry_a, entry_b]

    # ServiceValidationError (a HomeAssistantError subclass) — the caller can fix
    # this by naming an entry_id, so it is a validation fault, not an integration
    # failure. The message is resolved through hass at render time, so the stable
    # thing to assert on is the translation key.
    with pytest.raises(ServiceValidationError) as err:
        _get_coordinator(mock_hass, {})
    assert err.value.translation_key == "multiple_entries"


@pytest.mark.asyncio
async def test_service_send_sms_exception(mock_hass, mock_config_entry):
    """Test send_sms service exception handling (__init__.py:102-103)."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.zte_router_5g import async_send_sms

    mock_api = AsyncMock()
    mock_api.send_sms.side_effect = RuntimeError("Send failed")
    mock_coordinator = MagicMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_coordinator.api = mock_api
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"target": ["+123456"], "message": "test msg"}

    with pytest.raises(HomeAssistantError) as err:
        await async_send_sms(mock_hass, call)

    assert err.value.translation_key == "send_sms_failed"


@pytest.mark.asyncio
async def test_service_delete_sms_exception(mock_hass, mock_config_entry):
    """Test delete_sms service exception handling (__init__.py:114-115)."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.zte_router_5g import async_delete_sms

    mock_api = AsyncMock()
    mock_api.delete_sms.side_effect = RuntimeError("Delete failed")
    mock_coordinator = MagicMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_coordinator.api = mock_api
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"index": 5}

    with pytest.raises(HomeAssistantError) as err:
        await async_delete_sms(mock_hass, call)

    assert err.value.translation_key == "delete_sms_failed"


@pytest.mark.asyncio
async def test_service_delete_all_sms_exception(mock_hass, mock_config_entry):
    """Test delete_all_sms service exception handling (__init__.py:135-136)."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.zte_router_5g import async_delete_all_sms

    mock_api = AsyncMock()
    mock_api.delete_all.side_effect = RuntimeError("Delete all failed")
    mock_coordinator = MagicMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_coordinator.api = mock_api
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"keep_last": 0}

    with pytest.raises(HomeAssistantError) as err:
        await async_delete_all_sms(mock_hass, call)

    assert err.value.translation_key == "delete_all_sms_failed"


@pytest.mark.asyncio
async def test_service_get_sms_list_mix_box_type(mock_hass, mock_config_entry):
    """Test get_sms_list with mixed box_type (__init__.py:165-168)."""
    from custom_components.zte_router_5g import async_get_sms_list

    mock_api = AsyncMock()
    mock_api.get_sms_messages.side_effect = [
        [
            {
                "id": "1",
                "tag": "0",
                "number_decoded": "111",
                "content_decoded": "nv",
                "date_decoded": "2026-05-23T01:00:00",
            }
        ],
        [
            {
                "id": "2",
                "tag": "1",
                "number_decoded": "222",
                "content_decoded": "sim",
                "date_decoded": "2026-05-23T02:00:00",
            }
        ],
    ]
    mock_coordinator = MagicMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_coordinator.api = mock_api
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"page": 1, "count": 10, "box_type": 8}

    result = await async_get_sms_list(mock_hass, call)
    messages = result["messages"]
    assert len(messages) == 2
    assert mock_api.get_sms_messages.call_count == 2


@pytest.mark.asyncio
async def test_service_get_sms_list_exception(mock_hass, mock_config_entry):
    """Test get_sms_list service exception handling (__init__.py:188-189)."""
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.zte_router_5g import async_get_sms_list

    mock_api = AsyncMock()
    mock_api.get_sms_messages.side_effect = RuntimeError("List failed")
    mock_coordinator = MagicMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_coordinator.api = mock_api
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"page": 1, "count": 10, "box_type": 1}

    with pytest.raises(HomeAssistantError) as err:
        await async_get_sms_list(mock_hass, call)

    assert err.value.translation_key == "get_sms_list_failed"


@pytest.mark.asyncio
async def test_async_setup_service_handlers(mock_hass, mock_config_entry):
    """Test async_setup service handlers are callable (__init__.py:196,199,202,205).

    Captures the registered callbacks and invokes them to cover the inner handlers.
    """
    from custom_components.zte_router_5g import async_setup

    registered_handlers = {}

    def capture_register(domain, service, handler, **kwargs):
        registered_handlers[service] = handler

    mock_hass.services.async_register.side_effect = capture_register

    assert await async_setup(mock_hass, {}) is True

    # Set up coordinator for handler calls
    mock_api = AsyncMock()
    mock_coordinator = MagicMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_coordinator.api = mock_api
    mock_coordinator.async_request_refresh = AsyncMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]
    mock_hass.config_entries.async_get_entry.return_value = mock_config_entry

    # Invoke _handle_send_sms
    send_call = MagicMock(spec=ServiceCall)
    send_call.data = {"target": ["+1"], "message": "hi"}
    await registered_handlers["send_sms"](send_call)
    mock_api.send_sms.assert_called_once()

    # Invoke _handle_delete_sms
    delete_call = MagicMock(spec=ServiceCall)
    delete_call.data = {"index": 1}
    await registered_handlers["delete_sms"](delete_call)
    mock_api.delete_sms.assert_called_once_with("1")

    # Invoke _handle_delete_all_sms
    delete_all_call = MagicMock(spec=ServiceCall)
    delete_all_call.data = {"keep_last": 0}
    await registered_handlers["delete_all_sms"](delete_all_call)
    mock_api.delete_all.assert_called_once()

    # Invoke _handle_get_sms_list
    mock_api.get_sms_messages.return_value = []
    list_call = MagicMock(spec=ServiceCall)
    list_call.data = {"page": 1, "count": 20, "box_type": 1}
    result = await registered_handlers["get_sms_list"](list_call)
    assert result == {"messages": []}

    # Invoke _handle_reset_entities. The action itself is tested in
    # test_reset_entities.py; this covers the handler that reaches it, which
    # is the one place the service data and the coordinator are joined.
    reset_call = MagicMock(spec=ServiceCall)
    reset_call.data = {"dry_run": True}
    with patch(
        "custom_components.zte_router_5g.async_reset_entities",
        new=AsyncMock(return_value={"dry_run": True}),
    ) as mock_reset:
        assert await registered_handlers["reset_entities"](reset_call) == {
            "dry_run": True
        }
    mock_reset.assert_awaited_once()


@pytest.mark.asyncio
async def test_sms_received_event_firing(mock_hass, mock_config_entry):
    """Test that the coordinator fires zte_router_5g_sms_received events."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI") as mock_api_class,
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        mock_api = mock_api_class.return_value
        mock_api.get_all_data = AsyncMock(return_value={"network_type": "LTE"})
        mock_api.get_sms_capacity = AsyncMock(return_value={"total": 10})

        # 1. Establish baseline (first poll)
        mock_api.get_sms_messages = AsyncMock(
            return_value=[
                {
                    "id": "1",
                    "content_decoded": "hello",
                    "number_decoded": "123",
                    "date_decoded": "2026-05-23T02:00:00",
                }
            ]
        )

        await async_setup_entry(mock_hass, mock_config_entry)
        coordinator = mock_config_entry.runtime_data

        # Run first update to set last_sms_timestamp = "2026-05-23T02:00:00"
        await coordinator._async_update_data()
        assert coordinator.last_sms_timestamp == "2026-05-23T02:00:00"
        assert coordinator.fired_sms_hashes == {"1_2026-05-23T02:00:00"}
        mock_hass.bus.async_fire.assert_not_called()

        # 2. Second poll: receives new message
        mock_api.get_sms_messages.return_value = [
            {
                "id": "1",
                "content_decoded": "hello",
                "number_decoded": "123",
                "date_decoded": "2026-05-23T02:00:00",
            },
            {
                "id": "2",
                "content_decoded": "new message",
                "number_decoded": "456",
                "date_decoded": "2026-05-23T02:05:00",
            },
        ]

        await coordinator._async_update_data()
        assert coordinator.last_sms_timestamp == "2026-05-23T02:05:00"
        assert coordinator.fired_sms_hashes == {"2_2026-05-23T02:05:00"}

        # Verify that the event was fired on the bus
        mock_hass.bus.async_fire.assert_called_once_with(
            "zte_router_5g_sms_received",
            {
                "entry_id": mock_config_entry.entry_id,
                "phone": "456",
                "content": "new message",
                "date": "2026-05-23T02:05:00",
                "index": 2,
            },
        )


# ── Fixture for coordinator sync-method tests ──────────────────────────────


@pytest.fixture
def coordinator_fixture(mock_hass, mock_config_entry):
    """Create a coordinator instance with mocked API for sync method testing."""
    mock_api = MagicMock()
    coordinator = ZTERouterDataUpdateCoordinator(mock_hass, mock_config_entry, mock_api)
    coordinator.last_sms_timestamp = None
    coordinator.fired_sms_hashes = set()
    return coordinator


# ── Strategy 1: Boundary Value Analysis ────────────────────────────────────


@pytest.mark.asyncio
async def test_failure_no_cached_data_raises_immediately(mock_hass, mock_config_entry):
    """1A: First failure with data=None raises UpdateFailed immediately (no holding)."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI"),
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        await async_setup_entry(mock_hass, mock_config_entry)
        coordinator = mock_config_entry.runtime_data
        assert coordinator.data is None

        coordinator.api.get_all_data = AsyncMock(side_effect=Exception("First fail"))
        with pytest.raises(UpdateFailed, match="Communication error"):
            await coordinator._async_update_data()
        assert coordinator.consecutive_failures == 1


@pytest.mark.asyncio
async def test_failure_count_resets_after_success(mock_hass, mock_config_entry):
    """1B: consecutive_failures resets on success; new failure can hold again."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI"),
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        await async_setup_entry(mock_hass, mock_config_entry)
        coordinator = mock_config_entry.runtime_data
        coordinator.data = {"old": "data"}
        coordinator.api.get_all_data = AsyncMock(side_effect=Exception("Fail"))

        await coordinator._async_update_data()
        await coordinator._async_update_data()
        assert coordinator.consecutive_failures == 2

        coordinator.api.get_all_data = AsyncMock(return_value={"network_type": "LTE"})
        coordinator.api.get_sms_capacity = AsyncMock(return_value={})
        coordinator.api.get_sms_messages = AsyncMock(return_value=[])
        await coordinator._async_update_data()
        assert coordinator.consecutive_failures == 0

        coordinator.api.get_all_data = AsyncMock(side_effect=Exception("New fail"))
        result = await coordinator._async_update_data()
        assert coordinator.consecutive_failures == 1
        assert result == {"old": "data"}


@pytest.mark.parametrize(
    "uptime,expect_reboot",
    [
        (70, False),
        (69, True),
        (71, False),
    ],
)
@pytest.mark.asyncio
async def test_reboot_detection_boundary(
    uptime, expect_reboot, mock_hass, mock_config_entry
):
    """1C: Reboot only when uptime drops strictly more than margin."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI"),
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        await async_setup_entry(mock_hass, mock_config_entry)
        coordinator = mock_config_entry.runtime_data
        original_boot = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        coordinator._boot_time = original_boot
        coordinator._last_uptime = 100
        # This case is about the running-session margin, so startup
        # reconciliation is already done. The first poll of a session takes the
        # startup path instead, which is covered in `test_uptime_latch.py`.
        coordinator._startup_reconciled = True

        coordinator.api.get_all_data = AsyncMock(
            return_value={"realtime_time": str(uptime), "network_type": "LTE"}
        )
        coordinator.api.get_sms_capacity = AsyncMock(return_value={})
        coordinator.api.get_sms_messages = AsyncMock(return_value=[])

        await coordinator._async_update_data()
        if expect_reboot:
            assert coordinator._boot_time != original_boot
        else:
            assert coordinator._boot_time == original_boot


@pytest.mark.parametrize("bad_value", ["-1", "-100", None, "", "abc"])
@pytest.mark.asyncio
async def test_boot_time_unchanged_on_bad_uptime(
    bad_value, mock_hass, mock_config_entry
):
    """1D: Bad/missing uptime leaves boot_time latched, anchor unchanged."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI"),
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        await async_setup_entry(mock_hass, mock_config_entry)
        coordinator = mock_config_entry.runtime_data
        original_boot = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        coordinator._boot_time = original_boot
        coordinator._last_uptime = 3600

        coordinator.api.get_all_data = AsyncMock(
            return_value={"realtime_time": bad_value, "network_type": "LTE"}
        )
        coordinator.api.get_sms_capacity = AsyncMock(return_value={})
        coordinator.api.get_sms_messages = AsyncMock(return_value=[])

        data = await coordinator._async_update_data()
        assert data["boot_time"] == original_boot
        assert coordinator._last_uptime == 3600


# ── Strategy 2: Combinatorial / Path Coverage ──────────────────────────────


def test_check_new_sms_same_timestamp_new_hash(coordinator_fixture, mock_hass):
    """2B: Second message at the same timestamp as baseline is detected by hash only."""
    coordinator = coordinator_fixture
    coordinator.last_sms_timestamp = "2026-01-01T10:00:00"
    coordinator.fired_sms_hashes = {"1_2026-01-01T10:00:00"}

    messages = [
        {
            "id": "1",
            "content_decoded": "old",
            "number_decoded": "111",
            "date_decoded": "2026-01-01T10:00:00",
        },
        {
            "id": "2",
            "content_decoded": "same-time-new",
            "number_decoded": "222",
            "date_decoded": "2026-01-01T10:00:00",
        },
    ]
    coordinator._check_new_sms(messages)

    mock_hass.bus.async_fire.assert_called_once()
    event = mock_hass.bus.async_fire.call_args[0][1]
    assert event["phone"] == "222"
    assert "1_2026-01-01T10:00:00" in coordinator.fired_sms_hashes
    assert "2_2026-01-01T10:00:00" in coordinator.fired_sms_hashes
    assert coordinator.last_sms_timestamp == "2026-01-01T10:00:00"


def test_check_new_sms_multiple_new_fire_in_order(coordinator_fixture, mock_hass):
    """2C: Multiple new messages all fire, in chronological order."""
    coordinator = coordinator_fixture
    coordinator.last_sms_timestamp = "2026-01-01T10:00:00"
    coordinator.fired_sms_hashes = {"1_2026-01-01T10:00:00"}

    messages = [
        {
            "id": "3",
            "content_decoded": "c",
            "number_decoded": "333",
            "date_decoded": "2026-01-01T10:02:00",
        },
        {
            "id": "2",
            "content_decoded": "b",
            "number_decoded": "222",
            "date_decoded": "2026-01-01T10:01:00",
        },
        {
            "id": "1",
            "content_decoded": "a",
            "number_decoded": "111",
            "date_decoded": "2026-01-01T10:00:00",
        },
    ]
    coordinator._check_new_sms(messages)

    assert mock_hass.bus.async_fire.call_count == 2
    calls = mock_hass.bus.async_fire.call_args_list
    assert calls[0][0][1]["phone"] == "222"
    assert calls[1][0][1]["phone"] == "333"
    assert coordinator.last_sms_timestamp == "2026-01-01T10:02:00"
    assert coordinator.fired_sms_hashes == {"3_2026-01-01T10:02:00"}


def test_check_new_sms_missing_date_decoded_filtered(coordinator_fixture, mock_hass):
    """2D: Messages lacking date_decoded are silently excluded from event detection."""
    coordinator = coordinator_fixture
    coordinator.last_sms_timestamp = "2026-01-01T10:00:00"
    coordinator.fired_sms_hashes = set()

    messages = [
        {"id": "1", "number_decoded": "111"},
        {"id": "2", "number_decoded": "222", "date_decoded": "2026-01-01T11:00:00"},
    ]
    coordinator._check_new_sms(messages)
    mock_hass.bus.async_fire.assert_called_once()
    assert mock_hass.bus.async_fire.call_args[0][1]["phone"] == "222"


def test_check_new_sms_all_missing_date_decoded_early_return(
    coordinator_fixture, mock_hass
):
    """2D: Early return at coordinator.py:309 when no messages have date_decoded."""
    coordinator = coordinator_fixture
    coordinator.last_sms_timestamp = "2026-01-01T10:00:00"
    original_ts = coordinator.last_sms_timestamp

    coordinator._check_new_sms([{"id": "1", "number_decoded": "111"}])

    mock_hass.bus.async_fire.assert_not_called()
    assert coordinator.last_sms_timestamp == original_ts


@pytest.mark.asyncio
async def test_coordinator_auth_retry_also_raises_outer_handler(
    mock_hass, mock_config_entry
):
    """2E: ZTEAuthError on post-login retry enters outer handler."""
    with (
        patch("custom_components.zte_router_5g.ZTERouterAPI"),
        patch("custom_components.zte_router_5g.async_get_clientsession"),
        patch("homeassistant.helpers.device_registry.async_get"),
    ):
        await async_setup_entry(mock_hass, mock_config_entry)
        coordinator = mock_config_entry.runtime_data
        coordinator.data = {"cached": "data"}

        call_count = 0

        def always_auth_error(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ZTEAuthError("Still rejected")

        coordinator.api.get_all_data = AsyncMock(side_effect=always_auth_error)
        coordinator.api.login = AsyncMock()

        result = await coordinator._async_update_data()
        assert result == {"cached": "data"}
        assert coordinator.consecutive_failures == 1
        assert call_count == 2


@pytest.mark.asyncio
async def test_delete_all_sms_keep_last_gte_total_deletes_nothing(
    mock_hass, mock_config_entry
):
    """2F: keep_last >= total: delete_sms is not called."""
    from custom_components.zte_router_5g import async_delete_all_sms

    mock_api = AsyncMock()
    mock_api.get_sms_messages.return_value = [{"id": "3"}, {"id": "2"}, {"id": "1"}]
    mock_coordinator = MagicMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_coordinator.api = mock_api
    mock_coordinator.async_request_refresh = AsyncMock()
    mock_coordinator.async_force_refresh = AsyncMock()
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)

    for n in [3, 5, 100]:
        mock_api.delete_sms.reset_mock()
        call.data = {"keep_last": n}
        await async_delete_all_sms(mock_hass, call)
        mock_api.delete_sms.assert_not_called()
    mock_coordinator.async_force_refresh.assert_called()


# ── Strategy 3: Error State & Negative Path Engineering ─────────────────────


def test_plain_text_may_use_the_full_gsm7_length():
    """765 = 5 concatenated segments of 153 septets, as the router advertises."""
    _validate_sms_length("A" * SMS_MAX_CHARS_GSM7)


def test_plain_text_is_rejected_past_the_gsm7_limit():
    """Beyond five segments the router's behavior is untested; stay out of it."""
    with pytest.raises(ServiceValidationError) as err:
        _validate_sms_length("A" * (SMS_MAX_CHARS_GSM7 + 1))
    assert err.value.translation_key == "sms_too_long"


def test_unicode_gets_the_shorter_limit():
    """One emoji forces UCS-2 for the whole message, at 67 chars per segment."""
    message = "\U0001f4f6" + "A" * SMS_MAX_CHARS_UNICODE
    with pytest.raises(ServiceValidationError) as err:
        _validate_sms_length(message)
    assert err.value.translation_key == "sms_too_long"


def test_unicode_within_its_own_limit_is_accepted():
    """335 = 5 x 67. Valid, even though it is far below the GSM-7 ceiling."""
    _validate_sms_length("\U0001f4f6" + "A" * (SMS_MAX_CHARS_UNICODE - 1))


def test_a_message_between_the_two_limits_turns_on_content_alone():
    """The same length passes as plain text and fails with one emoji in it.

    This is the whole point of validating per-message: a flat limit is either
    too small for plain text or lets a Unicode message become several charged
    segments without saying so.
    """
    length = SMS_MAX_CHARS_UNICODE + 10
    _validate_sms_length("A" * length)
    with pytest.raises(ServiceValidationError):
        _validate_sms_length("\U0001f4f6" + "A" * (length - 1))


# ---------------------------------------------------------------------------
# Branch coverage — partial branches recorded 2026-08-05. Each was a missing
# test rather than dead code.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_coordinator_ignores_an_entry_id_from_another_integration(
    mock_hass, mock_config_entry
):
    """An `entry_id` naming a foreign entry falls through to auto-selection.

    The distinction: "no entry_id given" and "an entry_id that is not ours"
    must reach the same place. Trusting the lookup blindly would hand back
    another integration's `runtime_data` — the id is caller-supplied, and
    `async_get_entry` is not scoped to this domain.
    """
    from custom_components.zte_router_5g import _get_coordinator

    foreign = MagicMock()
    foreign.domain = "some_other_integration"
    foreign.runtime_data = MagicMock()
    mock_hass.config_entries.async_get_entry.return_value = foreign

    ours = MagicMock()
    mock_config_entry.runtime_data = ours
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    assert _get_coordinator(mock_hass, {"entry_id": "not_ours"}) is ours


@pytest.mark.asyncio
async def test_unload_leaves_the_session_open_when_platforms_refuse_to_unload(
    mock_hass, mock_config_entry
):
    """A failed platform unload must not log the router out.

    Separates "unloading" from "unloaded". HA keeps the entry loaded when
    `async_unload_platforms` returns False, so entities are still live and
    still need the session — ending it here would leave a loaded integration
    with no way to talk to the device.
    """
    coordinator = MagicMock()
    coordinator.api.logout = AsyncMock()
    mock_config_entry.runtime_data = coordinator
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

    assert await async_unload_entry(mock_hass, mock_config_entry) is False
    coordinator.api.logout.assert_not_awaited()


@pytest.mark.asyncio
async def test_unload_succeeds_when_setup_never_stored_a_coordinator(
    mock_hass, mock_config_entry
):
    """Unloading an entry that failed early must not raise.

    `runtime_data` is unset when setup raised before the coordinator was
    built. The distinction from the success case is that there is no session
    to release and the unload must still report True — an exception here
    leaves HA unable to remove a half-set-up entry.
    """
    if hasattr(mock_config_entry, "runtime_data"):
        delattr(type(mock_config_entry), "runtime_data")
    object.__setattr__(mock_config_entry, "runtime_data", None)

    assert await async_unload_entry(mock_hass, mock_config_entry) is True


# ---------------------------------------------------------------------------
# Write services — a successful write must never be reported as a failure.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_sent_sms_is_not_reported_as_failed_when_the_refresh_fails(
    mock_hass, mock_config_entry, mock_coordinator
):
    """The refresh is cosmetic. Its failure must not become the write's.

    This is the distinction that matters on a charged path: the message went
    out, so telling the user it did not invites a retry, and the retry sends a
    second one. Section 22 — unverified is not failed, and a write with
    real-world effect is never retried on an ambiguous outcome.
    """
    from custom_components.zte_router_5g import async_send_sms

    mock_coordinator.api = AsyncMock()
    mock_coordinator.async_force_refresh = AsyncMock(
        side_effect=ZTEConnectionError("router busy right after the write")
    )
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"target": ["07700900000"], "message": "hello"}

    # Must not raise.
    await async_send_sms(mock_hass, call)

    mock_coordinator.api.send_sms.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_partial_send_names_the_recipients_already_reached(
    mock_hass, mock_config_entry, mock_coordinator
):
    """Stopping at the first failure is deliberate; hiding it is not.

    Sending to three numbers and failing on the second leaves the first sent
    and the third unattempted. A bare "failed" cannot be told from a total
    failure, so a caller retries and re-sends to whoever already received it.
    The error names them; the loop still stops, because continuing would send
    messages this call would not otherwise have sent.
    """
    from custom_components.zte_router_5g import async_send_sms

    mock_coordinator.api = AsyncMock()
    mock_coordinator.api.send_sms = AsyncMock(
        side_effect=[None, ZTEConnectionError("second recipient failed")]
    )
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"target": ["111", "222", "333"], "message": "hello"}

    with pytest.raises(HomeAssistantError) as err:
        await async_send_sms(mock_hass, call)

    assert err.value.translation_key == "send_sms_failed"
    assert err.value.translation_placeholders["sent"] == "111"
    # The third was never attempted — two calls, not three.
    assert mock_coordinator.api.send_sms.await_count == 2


@pytest.mark.asyncio
async def test_a_send_that_reaches_nobody_says_so(
    mock_hass, mock_config_entry, mock_coordinator
):
    """Reports `none`, not an empty string, so the message reads correctly."""
    from custom_components.zte_router_5g import async_send_sms

    mock_coordinator.api = AsyncMock()
    mock_coordinator.api.send_sms = AsyncMock(side_effect=ZTEConnectionError("down"))
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"target": ["111"], "message": "hello"}

    with pytest.raises(HomeAssistantError) as err:
        await async_send_sms(mock_hass, call)

    assert err.value.translation_placeholders["sent"] == "none"


@pytest.mark.asyncio
async def test_delete_all_removes_what_it_can_when_a_record_has_no_id(
    mock_hass, mock_config_entry, mock_coordinator
):
    """A message with no id came that way from the router and cannot be deleted.

    Deletion targets ids, so refusing the whole operation would not spare that
    record — it would simply leave every other message in place as well. The
    identifiable ones are removed and the skipped count is logged.
    """
    from custom_components.zte_router_5g import async_delete_all_sms

    mock_coordinator.api = AsyncMock()
    mock_coordinator.api.get_sms_messages = AsyncMock(
        return_value=[
            {"id": "3", "date_decoded": "c"},
            {"id": "2", "date_decoded": "b"},
            {"date_decoded": "a"},  # router sent no id
        ]
    )
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"keep_last": 1}

    await async_delete_all_sms(mock_hass, call)

    # Kept the newest; deleted the one identifiable remainder; skipped the
    # id-less record rather than crashing on it or deleting nothing.
    mock_coordinator.api.delete_sms.assert_awaited_once_with("2")


@pytest.mark.asyncio
async def test_delete_all_sends_nothing_when_no_record_has_an_id(
    mock_hass, mock_config_entry, mock_coordinator
):
    """An empty target list must never reach a destructive command.

    `";".join([])` is `""`, and what the router does with a blank `delete_sms`
    is unknown. On a command that cannot be undone, "unknown" is not a risk
    worth taking to save one call.
    """
    from custom_components.zte_router_5g import async_delete_all_sms

    mock_coordinator.api = AsyncMock()
    mock_coordinator.api.get_sms_messages = AsyncMock(
        return_value=[{"date_decoded": "b"}, {"date_decoded": "a"}]
    )
    mock_config_entry.runtime_data = mock_coordinator
    mock_hass.config_entries.async_entries.return_value = [mock_config_entry]

    call = MagicMock(spec=ServiceCall)
    call.data = {"keep_last": 1}

    await async_delete_all_sms(mock_hass, call)

    mock_coordinator.api.delete_sms.assert_not_awaited()
