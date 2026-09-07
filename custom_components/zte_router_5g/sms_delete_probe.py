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
from copy import deepcopy
from datetime import UTC, datetime
from time import monotonic
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
    coordinator: ZTERouterDataUpdateCoordinator,
    name: str,
    run: Any,
    *,
    sent: str | None = None,
) -> dict[str, Any]:
    """Run one probe and record its outcome, whether it returns or raises.

    A refusal is the finding, so the record has to survive the raise with the
    router's own answer in it. `error` alone is not enough: the first live run
    of this probe recorded `Request failed:` with nothing behind it, on the one
    rung that failed.
    """
    api = coordinator.api
    started = monotonic()
    record: dict[str, Any] = {"probe": name, "at": datetime.now(UTC).isoformat()}
    if sent is not None:
        record["sent"] = sent
    # Read before the request: the flag is cleared once one has gone out.
    record["session_was_fresh"] = api._session_was_fresh  # noqa: SLF001
    record["login_form"] = api.login_metadata.get("form")
    try:
        record["result"] = await run()
        record["outcome"] = "returned"
    except Exception as err:  # noqa: BLE001 - the outcome is the finding
        record["outcome"] = "raised"
        record["error_type"] = type(err).__name__
        record["error"] = str(err)[:300]
        # What the router actually said. `_request` records this against every
        # non-live verdict, and the next successful poll clears it, so it is
        # snapshotted here or lost. Sanitized on the way into the download.
        rejection = api.last_rejection
        if isinstance(rejection, dict):
            record["rejection"] = deepcopy(rejection)
    record["elapsed_seconds"] = round(monotonic() - started, 3)
    record["status"] = api.last_response_status
    record["body_preview"] = api.last_response_preview
    return record


async def _surviving_ids(coordinator: ZTERouterDataUpdateCoordinator) -> list[str]:
    """Ids the router still holds, across both storage banks."""
    messages = await coordinator.api.get_sms_messages(mem_store=SMS_STORE_ALL)
    return [str(msg.get("id")) for msg in messages if msg.get("id") is not None]


async def _message_summary(
    coordinator: ZTERouterDataUpdateCoordinator,
) -> list[dict[str, Any]]:
    """Id, tag and date for each message. Never the message.

    Whether deletion depends on read state or on age is a live question, and
    the tag and date answer it. The content and the sender answer nothing and
    would put a stranger's message into a file written to be posted publicly,
    so they are not read here at all.
    """
    messages = await coordinator.api.get_sms_messages(mem_store=SMS_STORE_ALL)
    return [
        {
            "id": str(msg.get("id")),
            "tag": msg.get("tag"),
            "date": msg.get("date_decoded") or msg.get("date"),
        }
        for msg in messages
        if msg.get("id") is not None
    ]


def _delete_body(
    msg_id: str,
    ad: str,
    *,
    mem_store: str | None = None,
    not_callback: bool = False,
) -> str:
    """The exact body one variant sends. Shared so the record cannot drift."""
    parts = ["isTest=false", "goformId=DELETE_SMS", f"msg_id={msg_id}"]
    if not_callback:
        parts.append("notCallback=true")
    if mem_store is not None:
        parts.append(f"mem_store={mem_store}")
    parts.append(f"AD={ad}")
    return "&".join(parts)


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
    body = _delete_body(msg_id, ad, mem_store=mem_store, not_callback=not_callback)
    result = await api._request(  # noqa: SLF001 - a deliberate variant, not the API's own form
        "POST",
        "goform/goform_set_cmd_process",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return cast("dict[str, Any]", result)


def _redacted_body(
    msg_id: str,
    *,
    mem_store: str | None = None,
    not_callback: bool = False,
) -> str:
    """The body as it will be sent, with the write token replaced.

    Recorded so a reader can see the exact form rather than infer it from a
    variant's name. The token is a credential and never leaves the device.
    """
    return _delete_body(
        msg_id, "REDACTED", mem_store=mem_store, not_callback=not_callback
    )


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
                "deletion. Probes 3-14 build their own request and never reach "
                "the integration's own recording, so an empty "
                "sms.write_failures means probe 15 succeeded rather than that "
                "the recording failed."
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
                    sent=_redacted_body(
                        ABSENT_ID,
                        mem_store=kwargs.get("mem_store"),
                        not_callback=bool(kwargs.get("not_callback")),
                    ),
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
        # Id, tag and date only. Whether deletion depends on read state or on
        # age is a live question; the message itself answers nothing.
        report["messages_before"] = await _message_summary(coordinator)
        available = [str(entry["id"]) for entry in report["messages_before"]]
        report["messages_available"] = list(available)
        real_variants: list[tuple[str, dict[str, Any], int]] = [
            ("8_single_id", {}, 1),
            # Repeated so a failure can be told apart from a one-off.
            ("9_single_id_repeat", {}, 1),
            ("10_single_id_store_all", {"mem_store": SMS_STORE_ALL}, 1),
            ("11_single_id_not_callback", {"not_callback": True}, 1),
            ("12_single_id_delayed_relist", {}, 1),
            ("13_single_id_fresh_session", {}, 1),
            # The form the Delete All button actually sends. Nothing above
            # tests it, and a router that accepts one id but refuses a batch
            # would pass every rung above while the button kept failing.
            ("14_batch_semicolon", {}, 2),
        ]
        consumed = 0
        for name, kwargs, needs in real_variants:
            targets = available[consumed : consumed + needs]
            if len(targets) < needs:
                probes.append(
                    {
                        "probe": name,
                        "outcome": "skipped",
                        "reason": f"needs {needs} message(s), not enough left",
                    }
                )
                continue
            consumed += needs
            msg_id = ";".join(targets)
            if name.endswith("fresh_session"):
                await api.login()
            record = await _capture(
                coordinator,
                name,
                lambda i=msg_id, k=kwargs: _delete_raw(coordinator, i, **k),
                sent=_redacted_body(
                    msg_id,
                    mem_store=kwargs.get("mem_store"),
                    not_callback=bool(kwargs.get("not_callback")),
                ),
            )
            record["id_targeted"] = msg_id
            if name.endswith("delayed_relist"):
                # A router that deletes lazily would be reported as refusing,
                # because the check re-lists at once.
                await asyncio.sleep(LAZY_DELETE_WAIT)
                record["waited_seconds"] = LAZY_DELETE_WAIT
            with contextlib.suppress(Exception):
                record["ids_after"] = await _surviving_ids(coordinator)
            probes.append(record)

        # --- 15. The integration's own path, unmodified ---------------------
        # Everything above builds its own request, so none of it exercises
        # delete_all, its verification step, or the write-failure recording
        # this release added. Without this rung a report can show every variant
        # succeeding while the button the user presses still fails.
        #
        # api.delete_all() directly, never the service handler: that ends in a
        # refresh which takes the lock this run is already holding.
        record = await _capture(
            coordinator, "15_integration_delete_all", api.delete_all
        )
        with contextlib.suppress(Exception):
            record["ids_after"] = await _surviving_ids(coordinator)
        probes.append(record)

        with contextlib.suppress(Exception):
            report["ids_remaining"] = await _surviving_ids(coordinator)
        report["finished"] = datetime.now(UTC).isoformat()

    api.delete_probe = report
    return report
