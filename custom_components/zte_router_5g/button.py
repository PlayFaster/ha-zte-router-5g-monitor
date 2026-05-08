"""Button platform for ZTE Router 5G."""

import logging
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ZTERouterDataUpdateCoordinator
from .helpers import build_device_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZTEButtonEntityDescription(ButtonEntityDescription):
    """Describes ZTE button entity."""

    group: str = "system"


# Define metadata for the Reboot button
REBOOT_DESCRIPTION = ZTEButtonEntityDescription(
    key="reboot",
    translation_key="reboot",
    icon="mdi:restart",
    device_class=ButtonDeviceClass.RESTART,
    group="system",
)

# Define metadata for the Delete SMS button
DELETE_SMS_DESCRIPTION = ZTEButtonEntityDescription(
    key="delete_all",
    translation_key="delete_all",
    icon="mdi:email-remove",
    group="sms",
)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the button platform."""
    coordinator: ZTERouterDataUpdateCoordinator = entry.runtime_data

    # Create the button entities using their respective descriptions
    async_add_entities(
        [
            ZTERebootButton(coordinator, entry, REBOOT_DESCRIPTION),
            ZTEDeleteAllSMSButton(coordinator, entry, DELETE_SMS_DESCRIPTION),
        ],
        True,
    )


class ZTEButton(CoordinatorEntity[ZTERouterDataUpdateCoordinator], ButtonEntity):
    """Base class for ZTE Router buttons."""

    _attr_has_entity_name = True
    entity_description: ZTEButtonEntityDescription

    def __init__(
        self,
        coordinator: ZTERouterDataUpdateCoordinator,
        entry,
        description: ZTEButtonEntityDescription,
    ):
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def device_info(self):
        """Return device information with sub-device support."""
        return build_device_info(
            self.coordinator, self._entry, self.entity_description.group
        )


class ZTERebootButton(ZTEButton):
    """Button to reboot the ZTE router."""

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            await self.coordinator.api.reboot()
        except Exception as err:
            _LOGGER.error("%s: Reboot failed: %s", self._entry.title, err)
            raise HomeAssistantError(f"Reboot failed: {err}") from err


class ZTEDeleteAllSMSButton(ZTEButton):
    """Button to delete all SMS messages."""

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            await self.coordinator.api.delete_all()
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("%s: Delete SMS failed: %s", self._entry.title, err)
            raise HomeAssistantError(f"Delete SMS failed: {err}") from err
