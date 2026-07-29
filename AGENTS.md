# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

> **Read the shared conventions first:** [`.shared/dev_std/agent_conventions.md`](.shared/dev_std/agent_conventions.md) — commands (tests, lint, mypy, validation), the Windows-host `docker exec` workflow, devcontainer access, HAB/MCP for interrogating the running HA instance, the post-modification SCOPE table, code conventions, and the markdown/Python rules. That file is the single source of truth for everything shared across the integration projects; this file covers only what is specific to **ha-zte-router-5g-monitor**.

## What This Integration Does

A Home Assistant custom integration (`zte_router_5g`) for ZTE 5G CPE routers (primarily the MC7010). It is a `local_polling` `hub` integration distributed via HACS. It talks to the router's undocumented `goform` HTTP API, exposing signal diagnostics, data usage, SMS, and reboot/polling controls. There are no external `requirements` — it relies only on `aiohttp` and Home Assistant core.

> **Entity `about` notes are listed in [`docs/about_attribute_list.md`](docs/about_attribute_list.md), which is generated from source** - edit the note in the entity description or `_attr_about`, then regenerate; never edit that file by hand.

---

> **Entity and service inventory lives in [`docs/all_sensors.md`](docs/all_sensors.md)** — it is authoritative and kept current against live HA by `sensor_review.md`. This file deliberately carries no entity counts or service descriptions.

## Commands

Standard for all integration projects — see [shared conventions §2](.shared/dev_std/agent_conventions.md). Nothing about this project's commands differs.

## Architecture

Data flows in one direction: **`api.py` → `coordinator.py` → platform entities**. Entities never call the API directly for reads; they read `coordinator.data`.

- **`api.py` (`ZTERouterAPI`)** — stateless-ish async client for the `goform` API. Key behaviors that are easy to break:
  - Auth uses a chained SHA-256 hash of password + a per-session `LD` token; commands need an `AD` token derived from firmware version + `RD` (MD5 vs SHA-256 depending on model — see `get_ad`).
  - `_request` is the single choke point: it auto-detects expired sessions and transparently re-logs-in **once** (`_retry` guard prevents loops). Three signatures — an HTML redirect, unparsable JSON, or **a JSON dict in which every value is an empty string**.
  - **That last rule is "every value is empty", not "these named keys are empty" — do not narrow it.** A dead session answers `200 OK` with the requested keys echoed back blank: `{"sms_data_total":""}` for SMS, `{"network_type":"","signalbar":"",…}` for the batch poll. The rule previously named the batch-poll keys, so it could never fire on an SMS response (`.get("network_type")` is `None` there, and `None == ""` is `False`) — SMS actions silently returned an empty list on an expired session while Refresh Now recovered it. Signature table in [`docs/zte_how_to_access.md`](docs/zte_how_to_access.md).
  - `_require_contract()` is the second, independent defence: each SMS call asserts the key it must receive (`messages`, `sms_nv_total`) and raises rather than falling back to an empty default. An empty inbox returns `{"messages":[]}` — the key is present — which is what keeps "no messages" distinguishable from "no session". Never reintroduce a `.get(key, [])` fallback on these paths.
  - An inactivity check in `_request` proactively clears `stok` if the gap since the last request exceeds 150 seconds, forcing a new login.
  - **Only an authenticated call updates `last_activity`.** `LD` and `wa_inner_version` are served without a session, so letting them stamp the clock told the idle check a long-dead session was fresh. Every write calls `get_ad()` → `get_version()` first, so an action taken after a pause hit exactly that: the unauthenticated fetch reset the clock immediately before the authenticated call that needed it, the stale `stok` survived, and the write went out on a dead session reporting success. Do not move that update back outside the `if authenticated:` guard.
  - **`_require_success()` is checked on every write.** This API answers `200 OK` with `{"result":"failure"}` for a refused command, so an unchecked write reports success having done nothing — a user watched an SMS action go green with no message sent. Applied to all eight `goformId` writes. It raises only on an explicit non-success `result`; a response with no `result` key is left alone, because not every command returns one. **Reboot is not special-cased**: a connection error still propagates, since a dropped link cannot be told from a router that never received the command.
  - A GET request to `wa_inner_version` is executed inside `login()` immediately after obtaining a new `stok` to fully initialize/activate the session on the router, enabling subsequent POST commands.
  - Two exception types drive everything downstream: `ZTEAuthError` (bad credentials → reauth) vs `ZTEConnectionError` (network/transient). Raise the right one.
  - SMS content/numbers are hex-encoded on the wire; `_hex_decode` / `_parse_date` produce the `*_decoded` fields entities and services consume.
  - **`send_sms` picks `encode_type` per message** — `GSM7_default` when `helpers.is_gsm7()` says the text is entirely within the GSM 03.38 alphabet, `UNICODE` otherwise. **`MessageBody` stays UTF-16BE hex for both.** `encode_type` selects the router's DCS and segment accounting; it is not an instruction to change the client-side encoding. Verified against two independent implementations (`Kajkac/pygsm7.py::encodeMessage()`, `rosenrot00/zte_api.py::_encode_sms_message()`), which both hex-encode UTF-16 code units regardless of the type they declare. Do not "fix" a GSM-7 send by packing 7-bit septets.
  - **The message length limit therefore depends on content, not just length.** `SMS_MAX_CHARS_GSM7` (765 = 5 x 153) and `SMS_MAX_CHARS_UNICODE` (335 = 5 x 67) in `const.py`; enforced by `_validate_sms_length()` in `__init__.py`, **not** by the service schema, because which limit applies is only knowable from the message itself. The schema carries the absolute ceiling alone. A flat limit is wrong in both directions — too small for plain text, and large enough to let a Unicode message become several separately-charged segments unannounced. Segment arithmetic and the hardware confirmation are in [`docs/zte_how_to_access.md`](docs/zte_how_to_access.md).
  - **`login()` tries one alternate form on failure.** `_attempt_login()` posts a single `goformId` and returns a `_LoginAttempt`; `login()` retries once with the other form (`LOGIN` ↔ `LOGIN_MULTI_USER`) when the first yields no session. It deliberately does **not** retry a credentials rejection — a wrong password is wrong on either form, and a second attempt only counts against routers that lock out. Real transport failures raise straight out rather than triggering a pointless retry.
  - `get_all_data()` requests a block of cross-model keys the MC7010 does not populate. This is safe: an unknown `cmd` name is simply **absent** from the response rather than an error, and an absent key cannot trip the "every value is empty" rule above. **Keep that block in step with the alias tuples in `sensor.py`** — `test_get_all_data_requests_every_aliased_key` fails if an alias names a key that is never requested.
  - Full interface reference — every `cmd` and `goformId`, the auth and `AD` chains, and the failure modes of this API: [`docs/zte_how_to_access.md`](docs/zte_how_to_access.md).
  - `logout()` ends the router session on unload. It **must** send an `AD` token like every other state-changing command — without one the router answers `{"result":"failure"}` and leaves the session live. It is best-effort: it swallows its own errors and always clears local state, because an unreachable router must never block unload.

- **`coordinator.py` (`ZTERouterDataUpdateCoordinator`)** — polling + resilience layer.
  - **Failure resilience**: on timeout/auth/generic errors it holds the last known values for up to `FETCH_STRIKE_LIMIT` (3, in `const.py`) consecutive failures before marking entities unavailable (`UpdateFailed`). After 3 auth failures it triggers reauth via `ConfigEntryAuthFailed`.
  - **Per-endpoint resilience**: `_fetch_optional()` gives each optional endpoint (the two SMS calls) its own last-good payload and strike count; entities fed by one consult `endpoint_available(source)` in their `available` property. `get_all_data` is mandatory and stays on the global path. `ZTEAuthError` is re-raised rather than absorbed so reauth still fires.
  - **Dynamic polling**: `CONF_STOP_POLLING` returns cached data without hitting the router (the router allows only one login session, so pausing frees the web UI); `CONF_SCAN_INTERVAL` sets the interval.
  - **Force refresh**: `async_force_refresh()` sets a one-shot flag consumed **before** the pause check, so explicit user actions fetch even while paused. Every write action and the Refresh Now button route through it — never `async_request_refresh()` directly, which the pause short-circuit swallows.
  - **Self-diagnosis**: `health_snapshot` is a coordinator attribute (deliberately **not** in `coordinator.data`, which is `None` before first success and frozen during an outage) written on both the success and failure paths. It reports total outage (first failure at cold start, 3rd at runtime), degraded endpoints, and contract drift — a successful response containing none of `CORE_KEYS`, which also raises the `firmware_contract_drift` repair.
  - Detects new SMS by timestamp + per-message hash and fires the `zte_router_5g_sms_received` bus event. `_check_sms_storage` runs **before** the health snapshot so the repair state it reflects is current.
  - **Three repair issues**, all auto-clearing: `sms_storage_full` (store at capacity), `firmware_contract_drift` (3 successful polls returning none of `CORE_KEYS`), and `router_unreachable` (`UNREACHABLE_STRIKE_LIMIT` = **10** consecutive failures — deliberately far above the 3-strike unavailability threshold, so a router reboot never raises it). A Repair requires **persistence plus agency**: the condition must have stopped resolving itself _and_ there must be something the user can do. Adding a fourth needs that test applied, not just a `translation_key`.
  - Persists a stable `boot_time` into `entry.data` so the uptime timestamp doesn't jitter. The boot instant is latched once and only re-derived when the router's uptime counter drops by more than `UPTIME_REBOOT_MARGIN` (a genuine reboot); missing/garbage uptime readings leave the latched value untouched. `last_uptime` is persisted alongside `boot_time` as the reboot-detection anchor.

- **`__init__.py`** — entry setup forwards platforms **immediately**, then runs login + first refresh in a background task (`async_create_background_task`) so HA startup isn't blocked. Also registers the SMS services at domain level. The coordinator is stored on `entry.runtime_data`, not `hass.data`. `async_unload_entry` calls `api.logout()` after unloading platforms.
  - **Options listener**: `_async_options_updated` diffs `entry.options` against `coordinator.reload_signature` (options minus `LIVE_OPTION_KEYS`). Anything outside the allow-list — host, username, password — schedules a reload; `scan_interval` and `stop_polling` live-apply. Reload is the default; adding a new option means deciding which side it falls on, and connection or entity-topology settings must always reload.

- **`helpers.py`** — besides `build_device_info` and the `ZTEAboutEntity` mixin, carries two cross-model utilities with no HA dependency: `is_gsm7()` (GSM 03.38 alphabet, for the SMS encoding choice above) and `earfcn_to_band()` / `arfcn_to_band()` (3GPP channel-to-band lookup, for routers that report a channel number but no band name). **The NR ranges genuinely overlap** — n78 sits inside n77 — so `arfcn_to_band()` resolves ties by a documented table order and is best-effort by design. A band name the router reports always wins over it. All three return `None` rather than guessing on unparsable or out-of-range input.

- **Platforms** (`sensor`, `binary_sensor`, `button`, `number`, `switch`, `select`) — read `coordinator.data` and attach to sub-devices via `helpers.build_device_info`.
  - **`sensor.py` key aliasing**: `_get_first(data, keys)` returns the first spelling the router populated, treating present-but-empty as absent. Alias tuples are named constants (`_ALIAS_5G_RSRP` etc.) so the set is checkable against `api.py`. It nests **inside** the existing converters — `_safe_float(_get_first(...))`, never bare — or coercion and rounding are lost. All six monthly TX/RX call sites are aliased, including the two totals via `_monthly_total_bytes()`; aliasing only some would let the totals silently disagree with their own components on `flux_`-spelling hardware.
  - **Thermal sensors are a defined set, not a subset.** The five `pm_*` entities are the thermal keys the sibling `goform` project polls with °C units. `test_thermal_sensor_set_matches_the_descriptions` fails if one is added without a test or vice versa. No model is yet confirmed to populate any of them — all are disabled by default, and the MC7010 returns `""` for every one. Two exceptions read elsewhere: `ZTEIntegrationHealthSensor` reads `coordinator.health_snapshot` and overrides `available` to `True` unconditionally, and sensors with a `source` on their description gate `available` on `endpoint_available()`.

- **`diagnostics.py`** — sanitizes rather than key-redacts. `coordinator.data` is the vendor payload verbatim, so it blanks credentials/subscriber IDs/carrier identity, pseudonymizes IPs, cell IDs and SMS senders to stable tokens, summarizes `APN_config*` to its shape, and sweeps everything else for IP/MAC-shaped strings. Identifiers are matched by shape and position only — **never** seed it with real values. Verify changes against a regenerated download with an SMS present, not by reading the code.

### Device Identity Model ("Flat Identity")

Hardware metadata (`model`, `sw_version`, `imei`) is read once and stored in `entry.data`, so device info is stable from boot before the first poll completes. Entities are grouped into sub-devices (System / Signal / Data / SMS) all linked to a `{prefix}_system` root, where `prefix` is the IMEI (or `host_{host}` fallback). The System device is registered early in `async_setup_entry` to avoid parent-link warnings.

This is the **System-as-root** topology, and it is conformant — `dev_standards` §3 (Standard Version 1.15.0) ranks a stable non-MAC hardware identifier such as IMEI **equal** to a MAC, and names both System-as-root and hardware-as-root as valid. The `goform` API never exposes a MAC. Do not "fix" this to an IP-keyed root; the earlier ladder implied that and was wrong.

**Version compatibility (`_compat.py`).** Parent links and registry lookups go through feature-detected shims — `via_device_link` and `device_by_identifier` — emitting `via_device_id` on HA 2026.8+ and the legacy `via_device` tuple on ≤2026.7, with **no version floor**. `owning_entry_ids` is deliberately absent: this integration never reads `device.config_entries`, and an unused shim is dead code against a 100% coverage bar. Family-wide analysis and the 2026.8.0 re-verification checklist: `.shared/issues/x_project/device_registry_2026_08.md`.

### Config Entry Data vs. Options

This integration intentionally splits config entry storage:

- **`entry.options`** holds the live, user-editable connection settings: `CONF_HOST`, `CONF_USERNAME`, `CONF_PASSWORD`, plus `scan_interval` / `stop_polling`.
- **`entry.data`** holds discovered hardware metadata: `model`, `sw_version`, `imei`, `boot_time`, `last_uptime`.

Read credentials from `entry.options`, not `entry.data`. The config flow is `VERSION = 2` and supports user / reconfigure / reauth / options steps.

There is **no** `async_migrate_entry`, which is safe only because the first public release (2.0.1) already shipped the v2 schema — no v1 entry exists in the wild. Bumping `VERSION` to 3 makes a migration handler mandatory. In tests, `MockConfigEntry` defaults to `version=1`, so pass `version=2` explicitly or setup fails with "Migration handler not found".

## Key Patterns & Conventions

Shared conventions (ruff/mypy strictness, `_LOGGER` prefixing, `PARALLEL_UPDATES`, `translation_key`, icons, exception tuple syntax, markdown emoji rules) are in [shared conventions §4–5](.shared/dev_std/agent_conventions.md). Nothing in this project deviates.

### Raising user-facing exceptions

Every raise that can reach a user must be translated — no f-string messages:

```python
raise HomeAssistantError(
    translation_domain=DOMAIN,
    translation_key="send_sms_failed",
    translation_placeholders={"error": str(err)},
) from err
```

- Add a matching entry to the `exceptions` block in **both** `strings.json` and `translations/en.json`.
- Pick the type deliberately: **`ServiceValidationError`** when the caller got the call wrong and can fix it (no `entry_id` given when several routers exist); **`HomeAssistantError`** when the operation failed (the router rejected a reboot).
- `test_every_raised_exception_has_translated_text` walks every raise in the component and fails on an untranslated one or a key missing from either file.
- **Testing gotcha:** a translated exception resolves its message through `hass` at `str()` time, so `pytest.raises(..., match="some text")` fails under this suite's mocked hass with `async_get_hass called from the wrong thread`. Assert on `err.value.translation_key` instead.

### Editing `quality_scale.yaml`

Comments are plain multi-line block scalars, so a `": "` sequence in prose is parsed as a mapping and breaks the file. Write `X — because Y`, not `X: because Y`. Check with `grep -nE '^      .*: ' custom_components/zte_router_5g/quality_scale.yaml` before committing.

## Development Environment

Standard for all integration projects — see [shared conventions §3](.shared/dev_std/agent_conventions.md). Nothing about this project's environment differs.
