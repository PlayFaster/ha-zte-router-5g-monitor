"""Button platform for ZTE Router 5G."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ZTERouterDataUpdateCoordinator
from .helpers import ZTEAboutEntity, build_device_info

_LOGGER = logging.getLogger(__name__)

# Writes are serialised — see the note in `switch.py`. `0` (unlimited) stays
# correct for the read-only platforms; a platform that commands this
# single-session router must not issue concurrent `goform` writes.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class ZTEButtonEntityDescription(ButtonEntityDescription):
    """Describes ZTE button entity."""

    group: str = "system"


# Define metadata for the Refresh Now button
REFRESH_DESCRIPTION = ZTEButtonEntityDescription(
    key="refresh",
    translation_key="system_refresh",
    entity_category=EntityCategory.CONFIG,
    group="system",
)

# Define metadata for the Reboot button
REBOOT_DESCRIPTION = ZTEButtonEntityDescription(
    key="reboot",
    translation_key="system_reboot",
    device_class=ButtonDeviceClass.RESTART,
    group="system",
)

# Define metadata for the Delete SMS button
DELETE_SMS_DESCRIPTION = ZTEButtonEntityDescription(
    key="delete_all",
    translation_key="sms_delete_all",
    group="sms",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    coordinator: ZTERouterDataUpdateCoordinator = entry.runtime_data

    # Create the button entities using their respective descriptions
    async_add_entities(
        [
            ZTERefreshButton(coordinator, entry, REFRESH_DESCRIPTION),
            ZTERebootButton(coordinator, entry, REBOOT_DESCRIPTION),
            ZTEDeleteAllSMSButton(coordinator, entry, DELETE_SMS_DESCRIPTION),
        ],
        True,
    )


class ZTEButton(
    ZTEAboutEntity, CoordinatorEntity[ZTERouterDataUpdateCoordinator], ButtonEntity
):
    """Base class for ZTE Router buttons."""

    _attr_has_entity_name = True
    entity_description: ZTEButtonEntityDescription

    def __init__(
        self,
        coordinator: ZTERouterDataUpdateCoordinator,
        entry: ConfigEntry,
        description: ZTEButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information with sub-device support."""
        return build_device_info(
            self.coordinator, self._entry, self.entity_description.group
        )


class ZTERefreshButton(ZTEButton):
    """Button to trigger an immediate data refresh."""

    _attr_about = (
        "Fetches from the router immediately, without waiting for the next "
        "scheduled poll. It works even while polling is paused - explicit "
        "actions always fetch."
    )

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_force_refresh()


class ZTERebootButton(ZTEButton):
    """Button to reboot the ZTE router."""

    _attr_about = (
        "Restarts the router. The connection drops for a minute or two, and "
        "session data counters reset to zero. Monthly counters are unaffected."
    )

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            await self.coordinator.api.reboot()
        except Exception as err:
            _LOGGER.error("%s: Reboot failed: %s", self._entry.title, err)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="reboot_failed",
                translation_placeholders={"error": str(err)},
            ) from err


class ZTEDeleteAllSMSButton(ZTEButton):
    """Button to delete all SMS messages."""

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            await self.coordinator.api.delete_all()
            await self.coordinator.async_force_refresh()
        except Exception as err:
            _LOGGER.error("%s: Delete SMS failed: %s", self._entry.title, err)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="delete_all_button_failed",
                translation_placeholders={"error": str(err)},
            ) from err
