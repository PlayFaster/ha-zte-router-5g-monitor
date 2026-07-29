"""The ZTE Router 5G integration."""

import logging
from collections.abc import Mapping
from typing import Any, cast

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import ZTEAuthError, ZTEConnectionError, ZTERouterAPI
from .const import (
    DOMAIN,
    LIVE_OPTION_KEYS,
    SMS_MAX_CHARS_GSM7,
    SMS_MAX_CHARS_UNICODE,
    SMS_SEGMENTS_MAX,
)
from .coordinator import ZTERouterDataUpdateCoordinator
from .helpers import is_gsm7

_LOGGER = logging.getLogger(__name__)

SERVICE_SEND_SMS_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Required("target"): vol.All(cv.ensure_list, [str]),
        # The absolute ceiling only. Which limit actually applies depends on
        # whether the text forces UCS-2, so the real check lives in
        # `async_send_sms` where the message content is known.
        vol.Required("message"): vol.All(
            str, vol.Length(min=1, max=SMS_MAX_CHARS_GSM7)
        ),
    }
)

SERVICE_DELETE_SMS_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Required("index"): vol.Coerce(int),
    }
)

SERVICE_DELETE_ALL_SMS_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("keep_last", default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=50)
        ),
    }
)

SERVICE_GET_SMS_LIST_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("page", default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=100)
        ),
        vol.Optional("count", default=20): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=50)
        ),
        vol.Optional("box_type", default=0): vol.All(
            vol.Coerce(int), vol.In([0, 1, 2, 3, 5, 6, 7, 8, 9, 10])
        ),
    }
)

PLATFORMS = [
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SELECT,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _get_coordinator(
    hass: HomeAssistant, call_data: dict[str, Any]
) -> ZTERouterDataUpdateCoordinator:
    """Get coordinator from service call data."""
    entry_id = call_data.get("entry_id")
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == DOMAIN:
            if hasattr(entry, "runtime_data") and entry.runtime_data:
                return cast(ZTERouterDataUpdateCoordinator, entry.runtime_data)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="entry_not_ready",
                translation_placeholders={"title": entry.title},
            )

    # No entry_id given: auto-select only when exactly one router is loaded.
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if getattr(entry, "runtime_data", None)
    ]
    if len(entries) == 1:
        return cast(ZTERouterDataUpdateCoordinator, entries[0].runtime_data)

    # ServiceValidationError rather than HomeAssistantError: both of these are
    # faults in how the action was called, which the user can correct, not
    # failures of the integration itself.
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_entries_found",
        )
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="multiple_entries",
    )


def _validate_sms_length(message: str) -> None:
    """Reject a message longer than the router will carry, before sending it.

    Which ceiling applies depends on the content: a message drawn entirely
    from the GSM 03.38 alphabet is packed as septets and fits far more than
    one containing a single emoji or curly quote, which forces UCS-2 for the
    whole message. A flat limit is wrong in both directions — too small for
    plain text, and large enough to let a Unicode message silently become
    several charged segments.

    `ServiceValidationError` rather than `HomeAssistantError`: the caller got
    the call wrong and can fix it (dev_standards Section 9).
    """
    gsm7 = is_gsm7(message)
    limit = SMS_MAX_CHARS_GSM7 if gsm7 else SMS_MAX_CHARS_UNICODE
    if len(message) <= limit:
        return
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="sms_too_long",
        translation_placeholders={
            "length": str(len(message)),
            "limit": str(limit),
            "encoding": "GSM-7" if gsm7 else "Unicode",
            "segments": str(SMS_SEGMENTS_MAX),
        },
    )


async def async_send_sms(hass: HomeAssistant, call: ServiceCall) -> None:
    """Service to send an SMS."""
    coordinator = _get_coordinator(hass, call.data)
    target = call.data["target"]
    message = call.data["message"]
    _validate_sms_length(message)

    try:
        for num in target:
            await coordinator.api.send_sms(num, message)
        # Every write action refreshes, or the SMS counters and Recent Message
        # stay frozen until the next poll — and never, while Pause Polling is
        # on. `async_force_refresh` is the variant that bypasses the pause.
        await coordinator.async_force_refresh()
    except Exception as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="send_sms_failed",
            translation_placeholders={"error": str(err)},
        ) from err


async def async_delete_sms(hass: HomeAssistant, call: ServiceCall) -> None:
    """Service to delete an SMS."""
    coordinator = _get_coordinator(hass, call.data)
    index = call.data["index"]

    try:
        await coordinator.api.delete_sms(str(index))
        await coordinator.async_force_refresh()
    except Exception as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="delete_sms_failed",
            translation_placeholders={"error": str(err)},
        ) from err


async def async_delete_all_sms(hass: HomeAssistant, call: ServiceCall) -> None:
    """Service to delete all SMS messages."""
    coordinator = _get_coordinator(hass, call.data)
    keep_last = call.data.get("keep_last", 0)

    try:
        if keep_last == 0:
            await coordinator.api.delete_all()
        else:
            messages = await coordinator.api.get_sms_messages(mem_store="1")
            messages.sort(key=lambda x: int(x.get("id", 0)), reverse=True)
            to_delete = messages[keep_last:] if keep_last < len(messages) else []
            if to_delete:
                ids = [m["id"] for m in to_delete]
                await coordinator.api.delete_sms(";".join(ids))

        await coordinator.async_force_refresh()
    except Exception as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="delete_all_sms_failed",
            translation_placeholders={"error": str(err)},
        ) from err


async def async_get_sms_list(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    """Service to get SMS list with response."""
    coordinator = _get_coordinator(hass, call.data)
    page = call.data["page"]
    count = call.data["count"]
    box_type = call.data["box_type"]

    box_mapping = {
        0: (None, ["0", "1", "2", "3", "4"]),  # All Boxes
        1: ("1", ["0", "1"]),  # Local Inbox
        2: ("1", ["2", "3"]),  # Local Sent
        3: ("1", ["4"]),  # Local Draft
        5: ("0", ["0", "1"]),  # SIM Inbox
        6: ("0", ["2", "3"]),  # SIM Sent
        7: ("0", ["4"]),  # SIM Draft
        8: (None, ["0", "1"]),  # Mix Inbox
        9: (None, ["2", "3"]),  # Mix Sent
        10: (None, ["4"]),  # Mix Draft
    }

    mem_store, target_tags = box_mapping.get(
        box_type, (None, ["0", "1", "2", "3", "4"])
    )

    # Both stores are fetched in full for a combined box, and each store is
    # fetched in full even when `count` is small. That is not an oversight:
    # tag filtering happens below, client-side, so server-side pagination would
    # return fewer than `count` messages once filtered — and a combined box has
    # to merge two stores before it can sort by date at all.
    try:
        raw_msgs = []
        if mem_store is not None:
            raw_msgs = await coordinator.api.get_sms_messages(mem_store=mem_store)
        else:
            nv_msgs = await coordinator.api.get_sms_messages(mem_store="1")
            sim_msgs = await coordinator.api.get_sms_messages(mem_store="0")
            raw_msgs = nv_msgs + sim_msgs
            raw_msgs.sort(key=lambda x: x.get("date", ""), reverse=True)
    except Exception as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="get_sms_list_failed",
            translation_placeholders={"error": str(err)},
        ) from err

    filtered_msgs = [m for m in raw_msgs if str(m.get("tag")) in target_tags]

    start_idx = (page - 1) * count
    end_idx = start_idx + count
    paginated_msgs = filtered_msgs[start_idx:end_idx]

    formatted_messages = [
        {
            "index": int(msg.get("id", 0)),
            "phone": msg.get("number_decoded", ""),
            "content": msg.get("content_decoded", ""),
            "date": msg.get("date_decoded", ""),
            "read": str(msg.get("tag", "0")) == "0",
        }
        for msg in paginated_msgs
    ]

    return {"messages": formatted_messages}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the ZTE Router 5G Monitor component."""

    async def _handle_send_sms(call: ServiceCall) -> None:
        await async_send_sms(hass, call)

    async def _handle_delete_sms(call: ServiceCall) -> None:
        await async_delete_sms(hass, call)

    async def _handle_delete_all_sms(call: ServiceCall) -> None:
        await async_delete_all_sms(hass, call)

    async def _handle_get_sms_list(call: ServiceCall) -> dict[str, Any]:
        return await async_get_sms_list(hass, call)

    hass.services.async_register(
        DOMAIN,
        "send_sms",
        _handle_send_sms,
        schema=SERVICE_SEND_SMS_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        "delete_sms",
        _handle_delete_sms,
        schema=SERVICE_DELETE_SMS_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        "delete_all_sms",
        _handle_delete_all_sms,
        schema=SERVICE_DELETE_ALL_SMS_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        "get_sms_list",
        _handle_get_sms_list,
        schema=SERVICE_GET_SMS_LIST_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    return True


def _reload_signature(options: Mapping[str, Any]) -> dict[str, Any]:
    """Return the options that require a reload when they change.

    Everything outside LIVE_OPTION_KEYS is structural or connection-affecting,
    so a change to any of it must rebuild the entry rather than be applied to
    the running one.
    """
    return {k: v for k, v in options.items() if k not in LIVE_OPTION_KEYS}


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when a non-live option changes.

    Reload-by-default (Section 9). The allow-list exists so that the two
    frequently-tuned options — polling interval and pause — do not tear down
    and rebuild every entity each time the user nudges a slider. A change to
    the host or credentials falls outside it and reloads, which is the whole
    point: without this the running API client keeps using the old host and
    password until Home Assistant restarts.
    """
    coordinator: ZTERouterDataUpdateCoordinator | None = getattr(
        entry, "runtime_data", None
    )
    if coordinator is None:
        return

    signature = _reload_signature(entry.options)
    if signature == coordinator.reload_signature:
        # Live-apply only — no reload.
        coordinator.apply_live_options()
        return

    coordinator.reload_signature = signature
    _LOGGER.debug(
        "%s: Connection or structural option changed; reloading entry.", entry.title
    )
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ZTE Router 5G Monitor from a config entry with Background Safety."""
    session = async_get_clientsession(hass)
    api = ZTERouterAPI(
        session,
        entry.options[CONF_HOST],
        entry.options.get(CONF_USERNAME),
        entry.options[CONF_PASSWORD],
    )

    # Create the specialized coordinator
    coordinator = ZTERouterDataUpdateCoordinator(hass, entry, api)

    # Store for platform access via runtime_data
    entry.runtime_data = coordinator

    # Remember which non-live options this entry was set up with, so the update
    # listener can tell a connection change (reload) from a tuning change
    # (live-apply). Section 9.
    coordinator.reload_signature = _reload_signature(entry.options)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # Register the System root device early to prevent via_device warnings in platforms
    device_registry = dr.async_get(hass)
    host = entry.options[CONF_HOST]
    imei = entry.data.get("imei")
    sub_id_prefix = imei or f"host_{host}"

    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{sub_id_prefix}_system")},
        name=f"{entry.title} System",
        manufacturer="ZTE",
        model=entry.data.get("model", "ZTE Router"),
        sw_version=entry.data.get("sw_version"),
        configuration_url=f"http://{host}",
    )

    # Forward platforms immediately so entities appear in HA
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # BACKGROUND INITIALIZATION TASK
    # Offloads the initial connection to keep startup instant.
    async def _async_background_setup() -> None:
        try:
            await api.try_set_protocol(5)
            await api.login(5)
            await coordinator.async_refresh()
            _LOGGER.info("%s: Background initialization complete.", entry.title)
        except (
            TimeoutError,
            ZTEAuthError,
            ZTEConnectionError,
            UpdateFailed,
            HomeAssistantError,
            aiohttp.ClientError,
        ) as err:
            _LOGGER.warning(
                "%s: Background initialization failed (will retry): %s",
                entry.title,
                err,
            )

    # Use the modern background task API for better lifecycle management
    entry.async_create_background_task(
        hass, _async_background_setup(), "zte-router-setup"
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and release resources."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Release the router session. The device allows only one login at a
        # time, so leaving it open locks the user out of its web UI until it
        # times out (Section 10). logout() is best-effort and never raises.
        # runtime_data is cleaned up automatically by HA, and api.session is
        # owned by HA core, so neither needs manual teardown here.
        coordinator: ZTERouterDataUpdateCoordinator | None = getattr(
            entry, "runtime_data", None
        )
        if coordinator is not None:
            await coordinator.api.logout()
    return unload_ok if isinstance(unload_ok, bool) else False
