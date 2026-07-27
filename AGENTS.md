# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

> **Read the shared conventions first:** [`.shared/dev_std/agent_conventions.md`](.shared/dev_std/agent_conventions.md) — commands (tests, lint, mypy, validation), the Windows-host `docker exec` workflow, devcontainer access, HAB/MCP for interrogating the running HA instance, the post-modification SCOPE table, code conventions, and the markdown/Python rules. That file is the single source of truth for everything shared across the integration projects; this file covers only what is specific to **ha-zte-router-5g-monitor**.

## What This Integration Does

A Home Assistant custom integration (`zte_router_5g`) for ZTE 5G CPE routers (primarily the MC7010). It is a `local_polling` `hub` integration distributed via HACS. It talks to the router's undocumented `goform` HTTP API, exposing signal diagnostics, data usage, SMS, and reboot/polling controls. There are no external `requirements` — it relies only on `aiohttp` and Home Assistant core.

> **Entity and service inventory lives in [`docs/all_sensors.md`](docs/all_sensors.md)** — it is authoritative and kept current against live HA by `sensor_review.md`. This file deliberately carries no entity counts or service descriptions.

## Commands

Standard for all integration projects — see [shared conventions §2](.shared/dev_std/agent_conventions.md). Nothing about this project's commands differs.

## Architecture

Data flows in one direction: **`api.py` → `coordinator.py` → platform entities**. Entities never call the API directly for reads; they read `coordinator.data`.

- **`api.py` (`ZTERouterAPI`)** — stateless-ish async client for the `goform` API. Key behaviors that are easy to break:
  - Auth uses a chained SHA-256 hash of password + a per-session `LD` token; commands need an `AD` token derived from firmware version + `RD` (MD5 vs SHA-256 depending on model — see `get_ad`).
  - `_request` is the single choke point: it auto-detects expired sessions (HTML redirect, unparsable JSON, or empty/`fail` status fields) and transparently re-logs-in **once** (`_retry` guard prevents loops).
  - An inactivity check in `_request` proactively clears `stok` if the gap since the last request exceeds 150 seconds, forcing a new login.
  - A GET request to `wa_inner_version` is executed inside `login()` immediately after obtaining a new `stok` to fully initialize/activate the session on the router, enabling subsequent POST commands.
  - Two exception types drive everything downstream: `ZTEAuthError` (bad credentials → reauth) vs `ZTEConnectionError` (network/transient). Raise the right one.
  - SMS content/numbers are hex-encoded on the wire; `_hex_decode` / `_parse_date` produce the `*_decoded` fields entities and services consume.
  - `logout()` ends the router session on unload. It **must** send an `AD` token like every other state-changing command — without one the router answers `{"result":"failure"}` and leaves the session live. It is best-effort: it swallows its own errors and always clears local state, because an unreachable router must never block unload.

- **`coordinator.py` (`ZTERouterDataUpdateCoordinator`)** — polling + resilience layer.
  - **Failure resilience**: on timeout/auth/generic errors it holds the last known values for up to `STRIKE_LIMIT` (3) consecutive failures before marking entities unavailable (`UpdateFailed`). After 3 auth failures it triggers reauth via `ConfigEntryAuthFailed`.
  - **Per-endpoint resilience**: `_fetch_optional()` gives each optional endpoint (the two SMS calls) its own last-good payload and strike count; entities fed by one consult `endpoint_available(source)` in their `available` property. `get_all_data` is mandatory and stays on the global path. `ZTEAuthError` is re-raised rather than absorbed so reauth still fires.
  - **Dynamic polling**: `CONF_STOP_POLLING` returns cached data without hitting the router (the router allows only one login session, so pausing frees the web UI); `CONF_SCAN_INTERVAL` sets the interval.
  - **Force refresh**: `async_force_refresh()` sets a one-shot flag consumed **before** the pause check, so explicit user actions fetch even while paused. Every write action and the Refresh Now button route through it — never `async_request_refresh()` directly, which the pause short-circuit swallows.
  - **Self-diagnosis**: `health_snapshot` is a coordinator attribute (deliberately **not** in `coordinator.data`, which is `None` before first success and frozen during an outage) written on both the success and failure paths. It reports total outage (first failure at cold start, 3rd at runtime), degraded endpoints, and contract drift — a successful response containing none of `CORE_KEYS`, which also raises the `firmware_contract_drift` repair.
  - Detects new SMS by timestamp + per-message hash and fires the `zte_router_5g_sms_received` bus event; raises a repair issue when SMS storage is full. `_check_sms_storage` runs **before** the health snapshot so the repair state it reflects is current.
  - Persists a stable `boot_time` into `entry.data` so the uptime timestamp doesn't jitter. The boot instant is latched once and only re-derived when the router's uptime counter drops by more than `UPTIME_REBOOT_MARGIN` (a genuine reboot); missing/garbage uptime readings leave the latched value untouched. `last_uptime` is persisted alongside `boot_time` as the reboot-detection anchor.

- **`__init__.py`** — entry setup forwards platforms **immediately**, then runs login + first refresh in a background task (`async_create_background_task`) so HA startup isn't blocked. Also registers the SMS services at domain level. The coordinator is stored on `entry.runtime_data`, not `hass.data`. `async_unload_entry` calls `api.logout()` after unloading platforms.
  - **Options listener**: `_async_options_updated` diffs `entry.options` against `coordinator.reload_signature` (options minus `LIVE_OPTION_KEYS`). Anything outside the allow-list — host, username, password — schedules a reload; `scan_interval` and `stop_polling` live-apply. Reload is the default; adding a new option means deciding which side it falls on, and connection or entity-topology settings must always reload.

- **Platforms** (`sensor`, `binary_sensor`, `button`, `number`, `switch`, `select`) — read `coordinator.data` and attach to sub-devices via `helpers.build_device_info`. Two exceptions read elsewhere: `ZTEIntegrationHealthSensor` reads `coordinator.health_snapshot` and overrides `available` to `True` unconditionally, and sensors with a `source` on their description gate `available` on `endpoint_available()`.

- **`diagnostics.py`** — sanitizes rather than key-redacts. `coordinator.data` is the vendor payload verbatim, so it blanks credentials/subscriber IDs/carrier identity, pseudonymizes IPs, cell IDs and SMS senders to stable tokens, summarizes `APN_config*` to its shape, and sweeps everything else for IP/MAC-shaped strings. Identifiers are matched by shape and position only — **never** seed it with real values. Verify changes against a regenerated download with an SMS present, not by reading the code.

### Device Identity Model ("Flat Identity")

Hardware metadata (`model`, `sw_version`, `imei`) is read once and stored in `entry.data`, so device info is stable from boot before the first poll completes. Entities are grouped into sub-devices (System / Signal / Data / SMS) all linked `via_device` to a `{prefix}_system` root, where `prefix` is the IMEI (or `host_{host}` fallback). The System device is registered early in `async_setup_entry` to avoid `via_device` warnings.

### Config Entry Data vs. Options

This integration intentionally splits config entry storage:

- **`entry.options`** holds the live, user-editable connection settings: `CONF_HOST`, `CONF_USERNAME`, `CONF_PASSWORD`, plus `scan_interval` / `stop_polling`.
- **`entry.data`** holds discovered hardware metadata: `model`, `sw_version`, `imei`, `boot_time`, `last_uptime`.

Read credentials from `entry.options`, not `entry.data`. The config flow is `VERSION = 2` and supports user / reconfigure / reauth / options steps.

There is **no** `async_migrate_entry`, which is safe only because the first public release (2.0.1) already shipped the v2 schema — no v1 entry exists in the wild. Bumping `VERSION` to 3 makes a migration handler mandatory. In tests, `MockConfigEntry` defaults to `version=1`, so pass `version=2` explicitly or setup fails with "Migration handler not found".

## Key Patterns & Conventions

Shared conventions (ruff/mypy strictness, `_LOGGER` prefixing, `PARALLEL_UPDATES`, `translation_key`, icons, exception tuple syntax, markdown emoji rules) are in [shared conventions §4–5](.shared/dev_std/agent_conventions.md). Nothing in this project deviates.

## Development Environment

Standard for all integration projects — see [shared conventions §3](.shared/dev_std/agent_conventions.md). Nothing about this project's environment differs.
