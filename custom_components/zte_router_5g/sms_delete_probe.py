"""TEMPORARY — a one-off probe for the SMS deletion fault on issue #56.

**This module is not part of the integration's contract and must be removed.**
It exists to characterise one device that accepts `DELETE_SMS`, answers
success, and keeps the messages. Four diagnostics downloads produced no
evidence, because the failing path raises before anything is recorded.

Remove this file, its registration in `__init__.py`, its block in
`services.yaml`, its translation entries and its tests once the fault is
understood. `.notes/issues/other_router_access/` records that as outstanding
work so it does not rest on memory.

**What it does, in order.** Seven probes that risk nothing run first: they read
state, or they name a message id the router does not hold, so there is nothing
to destroy. Only then does it touch real messages, and every one it touches is
one the user has already asked to delete.

It does not stop at the first success. A device that behaves this differently
from the reference hardware is worth characterising once, properly, rather than
learning one fact and having to ask again.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from .api import SMS_STORE_ALL, SMS_STORE_DEVICE, SMS_STORE_SIM

if TYPE_CHECKING:
    from .coordinator import ZTERouterDataUpdateCoordinator

# An id no router holds. Naming it exercises the entire write path — token,
# form, session — while putting nothing at risk.
ABSENT_ID = "999999"

# A deliberately malformed token, so the router's answer to a bad one can be
# compared against its answer to a real refusal. Same length as a real digest.
BAD_TOKEN = "0" * 32

# Seconds to wait before the delayed re-list. Long enough to distinguish a
# lazy deletion from a refusal, short enough not to stall the action.
LAZY_DELETE_WAIT = 5


async def _capture(
    coordinator: ZTERouterDataUpdateCoordinator, name: str, run: Any
) -> dict[str, Any]:
    """Run one probe and record its outcome, whether it returns or raises."""
    api = coordinator.api
    record: dict[str, Any] = {"probe": name, "at": datetime.now(UTC).isoformat()}
    try:
        record["result"] = await run()
        record["outcome"] = "returned"
    except Exception as err:  # noqa: BLE001 - the outcome is the finding
        record["outcome"] = "raised"
        record["error_type"] = type(err).__name__
        record["error"] = str(err)[:300]
    record["status"] = api.last_response_status
    record["body_preview"] = api.last_response_preview
    return record


async def _surviving_ids(coordinator: ZTERouterDataUpdateCoordinator) -> list[str]:
    """Ids the router still holds, across both storage banks."""
    messages = await coordinator.api.get_sms_messages(mem_store=SMS_STORE_ALL)
    return [str(msg.get("id")) for msg in messages if msg.get("id") is not None]


async def _delete_raw(
    coordinator: ZTERouterDataUpdateCoordinator,
    msg_id: str,
    *,
    token: str | None = None,
    mem_store: str | None = None,
    not_callback: bool = False,
) -> dict[str, Any]:
    """Send one `DELETE_SMS` in a named variant, bypassing the normal path.

    The integration's own `delete_sms` sends exactly one form. The point here
    is to vary the form, so this builds the body directly rather than calling
    it. `token=None` means a correct one, derived now.
    """
    api = coordinator.api
    ad = token if token is not None else await api.get_ad()
    parts = ["isTest=false", "goformId=DELETE_SMS", f"msg_id={msg_id}"]
    if not_callback:
        parts.append("notCallback=true")
    if mem_store is not None:
        parts.append(f"mem_store={mem_store}")
    parts.append(f"AD={ad}")
    result = await api._request(  # noqa: SLF001 - a deliberate variant, not the API's own form
        "POST",
        "goform/goform_set_cmd_process",
        data="&".join(parts),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return cast("dict[str, Any]", result)


async def run_probe(coordinator: ZTERouterDataUpdateCoordinator) -> dict[str, Any]:
    """Run every probe, record everything, and stop for nothing.

    Held under the coordinator's update lock so a routine poll cannot log in,
    re-list or otherwise interleave with a sequence whose whole value is that
    each step is attributable.
    """
    api = coordinator.api
    async with coordinator._async_update_lock:  # noqa: SLF001 - the lock is the point
        report: dict[str, Any] = {
            "started": datetime.now(UTC).isoformat(),
            "probes": [],
            "note": (
                "Temporary diagnostic for issue #56. Probes 1-7 destroy "
                "nothing; 8 onward delete messages already targeted for "
                "deletion."
            ),
        }
        probes: list[dict[str, Any]] = report["probes"]

        # --- 1. Does the write token change when the session is renewed? ----
        # If it does, a replayed write carrying its original token was always
        # going to be refused. Read-only.
        async def token_rotation() -> dict[str, Any]:
            before_rd = await api.get_rd()
            before_ad = await api.get_ad()
            await api.login()
            after_rd = await api.get_rd()
            after_ad = await api.get_ad()
            return {
                "rd_changed_on_login": before_rd != after_rd,
                "ad_changed_on_login": before_ad != after_ad,
            }

        probes.append(await _capture(coordinator, "1_token_rotation", token_rotation))

        # --- 2. Where do the messages actually live? ------------------------
        async def bank_listing() -> dict[str, Any]:
            counts = {}
            for label, store in (
                ("device", SMS_STORE_DEVICE),
                ("sim", SMS_STORE_SIM),
                ("all", SMS_STORE_ALL),
            ):
                messages = await api.get_sms_messages(mem_store=store)
                counts[label] = [
                    str(m.get("id")) for m in messages if m.get("id") is not None
                ]
            return counts

        probes.append(await _capture(coordinator, "2_bank_listing", bank_listing))

        # --- 3-6. The write path, with nothing at risk ----------------------
        # A delete naming an id the router does not hold. If this is refused,
        # the fault is not about his messages at all.
        variants: list[tuple[str, dict[str, Any]]] = [
            ("3_absent_id", {}),
            ("4_absent_id_bad_token", {"token": BAD_TOKEN}),
            ("5_absent_id_not_callback", {"not_callback": True}),
            ("6a_absent_id_store_device", {"mem_store": SMS_STORE_DEVICE}),
            ("6b_absent_id_store_all", {"mem_store": SMS_STORE_ALL}),
        ]
        for name, kwargs in variants:
            probes.append(
                await _capture(
                    coordinator,
                    name,
                    lambda k=kwargs: _delete_raw(coordinator, ABSENT_ID, **k),
                )
            )

        # --- 7. Does any write work on this device? -------------------------
        # The data limit written back at exactly the values it already holds.
        # Chosen because this firmware populates it and the outdoor-unit LED
        # command it does not. Nothing changes.
        async def harmless_write() -> dict[str, Any]:
            # `set_data_volume_settings` is a read-modify-write and refuses a
            # partial form, so it takes the whole poll payload and picks the
            # fields out itself. Passing no changes writes back exactly what
            # is already set.
            current = dict(coordinator.data or {})
            result = await api.set_data_volume_settings(current)
            return {"result": result}

        probes.append(await _capture(coordinator, "7_harmless_write", harmless_write))

        # --- 8 onward. Real messages, one variant each ----------------------
        available = await _surviving_ids(coordinator)
        report["messages_available"] = list(available)
        real_variants: list[tuple[str, dict[str, Any]]] = [
            ("8_single_id", {}),
            ("9_single_id_store_all", {"mem_store": SMS_STORE_ALL}),
            ("10_single_id_not_callback", {"not_callback": True}),
            ("11_single_id_delayed_relist", {}),
            ("12_single_id_fresh_session", {}),
        ]
        for index, (name, kwargs) in enumerate(real_variants):
            if index >= len(available):
                probes.append(
                    {
                        "probe": name,
                        "outcome": "skipped",
                        "reason": "no message left to delete",
                    }
                )
                continue
            target = available[index]
            if name.endswith("fresh_session"):
                await api.login()
            record = await _capture(
                coordinator,
                name,
                lambda t=target, k=kwargs: _delete_raw(coordinator, t, **k),
            )
            record["id_targeted"] = target
            if name.endswith("delayed_relist"):
                # A router that deletes lazily would be reported as refusing,
                # because the check re-lists at once.
                await asyncio.sleep(LAZY_DELETE_WAIT)
                record["waited_seconds"] = LAZY_DELETE_WAIT
            with contextlib.suppress(Exception):
                record["ids_after"] = await _surviving_ids(coordinator)
            probes.append(record)

        with contextlib.suppress(Exception):
            report["ids_remaining"] = await _surviving_ids(coordinator)
        report["finished"] = datetime.now(UTC).isoformat()

    api.delete_probe = report
    return report
