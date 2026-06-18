# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## What This Integration Does

A Home Assistant custom integration (`zte_router_5g`) for ZTE 5G CPE routers (primarily the MC7010). It is a `local_polling` `hub` integration distributed via HACS. It talks to the router's undocumented `goform` HTTP API, exposing signal diagnostics, data usage, SMS, and reboot/polling controls. There are no external `requirements` — it relies only on `aiohttp` and Home Assistant core.

## Commands

### Tests

```bash
# Run the full test suite
pytest

# Run a single test file / test
pytest tests/test_coordinator.py
pytest tests/test_api.py::test_login -q
```

### Linting & Formatting

```bash
# Lint + autofix and format (config in pyproject.toml)
ruff check --fix .
ruff format .

# Type check (only custom_components; needs /ha_core mounted)
mypy custom_components/

# Run all configured checks at once
pre-commit run --all-files
```

### Running tools from a Windows host

These commands only work **inside** the devcontainer — HA imports `fcntl`, so `pytest` (and the other tools) cannot run on a Windows host directly. From Windows, run everything through `docker exec` against the running container. See [`.shared/prompts/devcon_run_gen.md`](.shared/prompts/devcon_run_gen.md) for the full mini-skill. Quick reference:

```bash
# Confirm the container is up first
docker ps --filter "name=<CONTAINER_NAME>" --format "{{.Names}}"

# Run a tool inside the container (-w sets the in-container working dir)
docker exec -w /workspaces/<PROJECT_DIR> <CONTAINER_NAME> bash -c "PYTHONPATH=. pytest tests/"
docker exec -w /workspaces/<PROJECT_DIR> <CONTAINER_NAME> bash -c "ruff check ."
```

Do not install or run these tools on the host as a workaround.

## Architecture

Data flows in one direction: **`api.py` → `coordinator.py` → platform entities**. Entities never call the API directly for reads; they read `coordinator.data`.

- **`api.py` (`ZTERouterAPI`)** — stateless-ish async client for the `goform` API. Key behaviors that are easy to break:
  - Auth uses a chained SHA-256 hash of password + a per-session `LD` token; commands need an `AD` token derived from firmware version + `RD` (MD5 vs SHA-256 depending on model — see `get_ad`).
  - `_request` is the single choke point: it auto-detects expired sessions (HTML redirect, unparsable JSON, or empty/`fail` status fields) and transparently re-logs-in **once** (`_retry` guard prevents loops).
  - An inactivity check in `_request` proactively clears `stok` if the gap since the last request exceeds 150 seconds, forcing a new login.
  - A GET request to `wa_inner_version` is executed inside `login()` immediately after obtaining a new `stok` to fully initialize/activate the session on the router, enabling subsequent POST commands.
  - Two exception types drive everything downstream: `ZTEAuthError` (bad credentials → reauth) vs `ZTEConnectionError` (network/transient). Raise the right one.
  - SMS content/numbers are hex-encoded on the wire; `_hex_decode` / `_parse_date` produce the `*_decoded` fields entities and services consume.

- **`coordinator.py` (`ZTERouterDataUpdateCoordinator`)** — polling + resilience layer.
  - **Failure resilience**: on timeout/auth/generic errors it holds the last known values for up to 3 consecutive failures before marking entities unavailable (`UpdateFailed`). After 3 auth failures it triggers reauth via `async_start_reauth`.
  - **Dynamic polling**: `CONF_STOP_POLLING` returns cached data without hitting the router (the router allows only one login session, so pausing frees the web UI); `CONF_SCAN_INTERVAL` sets the interval.
  - Detects new SMS by timestamp + per-message hash and fires the `zte_router_5g_sms_received` bus event; raises a repair issue when SMS storage is full.
  - Persists a stable `boot_time` into `entry.data` so the uptime timestamp doesn't jitter. The boot instant is latched once and only re-derived when the router's uptime counter drops by more than `UPTIME_REBOOT_MARGIN` (a genuine reboot); missing/garbage uptime readings leave the latched value untouched. `last_uptime` is persisted alongside `boot_time` as the reboot-detection anchor.

- **`__init__.py`** — entry setup forwards platforms **immediately**, then runs login + first refresh in a background task (`async_create_background_task`) so HA startup isn't blocked. Also registers the 4 SMS services (`send_sms`, `delete_sms`, `delete_all_sms`, `get_sms_list`). The coordinator is stored on `entry.runtime_data`, not `hass.data`.

- **Platforms** (`sensor`, `binary_sensor`, `button`, `number`, `switch`, `select`) — read `coordinator.data` and attach to sub-devices via `helpers.build_device_info`.

### Device Identity Model ("Flat Identity")

Hardware metadata (`model`, `sw_version`, `imei`) is read once and stored in `entry.data`, so device info is stable from boot before the first poll completes. Entities are grouped into sub-devices (System / Signal / Data / SMS) all linked `via_device` to a `{prefix}_system` root, where `prefix` is the IMEI (or `host_{host}` fallback). The System device is registered early in `async_setup_entry` to avoid `via_device` warnings.

### Config Entry Data vs. Options

This integration intentionally splits config entry storage:

- **`entry.options`** holds the live, user-editable connection settings: `CONF_HOST`, `CONF_USERNAME`, `CONF_PASSWORD`, plus `scan_interval` / `stop_polling`.
- **`entry.data`** holds discovered hardware metadata: `model`, `sw_version`, `imei`, `boot_time`, `last_uptime`.

Read credentials from `entry.options`, not `entry.data`. The config flow is `VERSION = 2` and supports user / reconfigure / reauth / options steps.

## Key Patterns & Conventions

- Ruff is strict: `D` (pydocstyle — every module/class/function needs a docstring), `N`, `ASYNC`, `T20` (no `print`), `SIM`, `UP` are all enabled. Target `py314`, line length 88.
- mypy runs in strict mode (`disallow_untyped_defs`, `disallow_any_generics`, etc.) over `custom_components/` only.
- `_LOGGER` messages are prefixed with `self.entry.title` (`"%s: ..."`) — match that style.
- The `.notes` and `.shared` symlinks point outside the repo (project notes / shared validation configs) and are not part of the shipped integration.

### Exception Tuple Syntax — Settled Decision

Always use `except (A, B):` with explicit parentheses for multi-exception catches. Never use the bare-tuple form `except A, B:`.

- **Do not flag or change this** — it has been researched and decided.
- `except A, B:` silently catches only `A` on Python 3.12–3.13 (what HA runs on in production), making it a correctness issue, not just style.
- `except (A, B):` is correct and unambiguous across Python 2.6 through 3.14+.
- Full background: `shared/SharedNotes/info/py_exception_tuple_syntax/issue_summary.md`

## Development Environment

The project uses a VS Code devcontainer (`.devcontainer/`, image `ha-dev-base:latest`; see `.devcontainer/docker-compose.yml`) running a Home Assistant instance for live testing. HA core source is mounted read-only at `/ha_core`; mypy resolves HA types against it via `mypy_path = "/ha_core"` and will not typecheck correctly outside an environment where that path exists.

### MCP Access (ha-mcp-dev)

When the devcontainer is running, the `ha-mcp-dev` MCP server automatically connects to the HA instance inside it (`http://localhost:8123`). Use it to verify integration changes without leaving the editor.

**After any modification, follow the post-modification process** — see [`.shared/prompts/post_mod_process.md`](.shared/prompts/post_mod_process.md). Specify a `SCOPE` when invoking it:

| SCOPE      | What runs                                                 |
| :--------- | :-------------------------------------------------------- |
| `None`     | Changes only — no validation                              |
| `Basic`    | HA restart + error check + lint/format fixes              |
| `Full`     | Basic + mypy (standard) + pytest (fix failing tests only) |
| `Complete` | Full + pre-commit --all-files + mypy --strict             |

Additional tools useful during development:

- `ha_get_state` / `ha_search_entities` — verify entity states and attributes after a reload
- `ha_call_service` — trigger service calls (e.g. `homeassistant.update_entity`) to exercise platform callbacks directly

Live HA for manual testing runs at `http://localhost:8123`; the integration is mounted read-only into `/config/custom_components/`. Tests use `pytest-homeassistant-custom-component` with `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed).

Validation reports are written to the `.reports/` directory (gitignored outputs from lint/test runs).

### Skill Prompts

Three reusable prompts are available via `.shared/prompts/` for working within this devcontainer:

| Prompt | Purpose |
| :-- | :-- |
| `devcon_run_gen.md` | Run any single command inside the container |
| `devcon_run_and_fix.md` | Full test + lint cycle: pytest, ruff, prettier, validate — with auto-fix |
| `devcon_coverage.md` | Coverage report, target file selection, and new test writing |

Container identity values (`CONTAINER_NAME`, `PROJECT_DIR`) are in `.devcontainer/.env`.
