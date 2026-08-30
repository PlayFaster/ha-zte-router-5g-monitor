"""Repair flows for ZTE Router 5G.

This module exists for one repair: `auth_failed`, the only `is_fixable=True`
issue the integration raises. Its purpose is narrow and worth stating, because
the alternative looks like it works.

Home Assistant resolves a fixable issue's Fix button through the integration's
`repairs` platform. When an integration has none, `RepairsFlowManager`
substitutes `ConfirmRepairFlow` — an empty confirm form that deletes the issue
on submit. The button therefore appears, is clickable, and *dismisses the card
without touching the credentials*. A user whose password the router rejected
would press Fix, watch the problem disappear, and still have a broken
integration until the next poll raised it again.

The flow below starts the reauth flow instead, which is what the repair's own
text promises.
"""

import voluptuous as vol
from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant


class AuthFailedRepairFlow(RepairsFlow):
    """Send the user to the reauth flow for the entry that failed."""

    def __init__(self, entry_id: str) -> None:
        """Store the entry this repair was raised for."""
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first step of the fix flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Confirm, then hand off to reauth.

        `async_start_reauth` is a no-op when a reauth flow for this entry is
        already in progress, which is the normal case: the coordinator raises
        `ConfigEntryAuthFailed` in the same breath as this repair, and Home
        Assistant starts one from that. Calling it here covers the case where
        that flow was dismissed and the card is the only way back.
        """
        if user_input is not None:
            entry = self.hass.config_entries.async_get_entry(self._entry_id)
            if entry is not None:
                entry.async_start_reauth(self.hass)
            return self.async_create_entry(data={})

        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the fix flow for a repair issue.

    The entry is read from `data` rather than parsed out of `issue_id`. The id
    format is an internal detail — it is `{entry_id}_{name}` here and
    `{name}_{entry_id}` on `huawei_router_5g` — and an entry id containing an
    underscore would make either parse ambiguous.
    """
    entry_id = str((data or {}).get("entry_id", ""))
    return AuthFailedRepairFlow(entry_id)


__all__ = ["AuthFailedRepairFlow", "async_create_fix_flow"]
