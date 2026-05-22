# Changelog

All notable changes to this project will be documented in this file.

## [3.0.2-dev5] - 2026-05-23 - Unreleased

### Fixed

- **mypy `--strict` import errors** (`sensor.py`, `switch.py`, `number.py`): Resolved `EntityCategory` import errors by importing directly from `homeassistant.const` instead of `homeassistant.helpers.entity`.
- **Unused import cleanup** (`__init__.py`): Removed unused `typing.Any` import to satisfy `ruff check`.

## [3.0.2-dev4] - 2026-05-23 - Unreleased

### Fixed

- **mypy `--strict` regression** (`coordinator.py`, `sensor.py`, `switch.py`, `number.py`, `button.py`, `binary_sensor.py`, `__init__.py`, `config_flow.py`): Resolved 43 mypy strict errors introduced by recent changes. Fixes include: removed stale `type: ignore` comments, removed redundant `cast()` calls, fixed Python 2 bare-comma `except` syntax, added explicit `datetime | None` type annotations to coordinator `_boot_time` and `last_update_success_time`, suppressed known HA ConfigFlow stub incompatibilities with `type: ignore[override]`, and fixed `MappingProxyType` argument mismatch by converting to `dict()`.

## [3.0.2-dev3] - 2026-05-22 - Unreleased

### Added

- **Uptime Duration Sensor** (`sensor.py`, `strings.json`, `translations/en.json`): Added `system_uptime_duration` sensor (disabled by default, device class `duration`, state class `measurement`, unit `"s"`).

### Changed

- **Centralized request helper** (`api.py`): Refactored all API methods to route through a centralized async `_request()` helper, automatically validating responses, handling Content-Type text/html overrides, and managing transparent login retries.
- **Uptime Timestamp stable calculation** (`coordinator.py`, `sensor.py`): Implemented cached `_boot_time` with a 15-second tolerance check to prevent boot timestamp jitter.
- **Legacy GB Sensors Correction** (`sensor.py`): Corrected `_BYTES_PER_GB` to use decimal base `1000000000` (GB) instead of binary `1073741824` (GiB) for legacy monthly data sensors.
- **Host Input Cleaning & Cookie Jar Cleardown** (`api.py`): Stripped HTTP/HTTPS scheme prefixes and trailing slashes from incoming IP/host inputs in `ZTERouterAPI.__init__`. Refined `stok` cookie clearing using a predicate lambda.

### Fixed

- **Empty Values to Unknown** (`sensor.py`): Implemented `_safe_str()` helper to map empty strings and `None` to Python `None` (Unknown state in HA) for candidates and 5G signal sensors.
- **Reauth Guard & Login Classification** (`api.py`, `coordinator.py`): Classify login responses to raise `ZTEAuthError` specifically on explicit credential error codes, preventing immediate re-auth flows on transient connection drops by holding last known values for 3 consecutive poll cycles.
- **Python Exception Syntax** (`sensor.py`): Updated legacy exception syntax to tuple format `except (ValueError, TypeError):` for Python 3.12+ compatibility.

## [3.0.2-dev2] - 2026-05-13 - Unreleased

### Added

- **Repair Issue — SMS Storage Full** (`coordinator.py`, `strings.json`, `translations/en.json`): `_check_sms_storage` raises an HA repair issue when NV SMS storage is at capacity; clears it when not. Surfaced in the HA Repairs panel with a description and Delete All button guidance.
- **`icons.json`**: State-dependent icon declarations for all 51+ entities; `signal_best_connection` uses `on: mdi:signal` / `off: mdi:signal-cellular-1`. Hardcoded `icon` properties removed from entity classes.

### Changed

- **Project Structure Document**: Updated the project structure document to v1.0.4.
- **IQS Full Compliance**: All 46 trackable rules across Bronze, Silver, Gold, and Platinum tiers now DONE — first project in the PlayFaster family to reach 100% IQS compliance. Records updated in `quality_scale.yaml` and `ha_quality_standard.md`.
- **README**: Added tested firmware version (MC7010 V1.0.0B01 and later) to Compatibility section.

### Fixed

- **mypy `--strict`**: 0 errors across all 12 source files (`mypy_strict.txt`: "Success: no issues found in 12 source files"). `quality_scale.yaml` `strict-typing` updated to DONE.
- **Stale test assertions** (`test_binary_sensor.py`): Removed `assert sensor.icon` lines that failed after `icon` property was replaced by `icons.json` declarations. CI unblocked.

## [3.0.2-dev1] - 2026-05-13 - Unreleased

### Changed

- **DevCon**: Devcontainer changes to pull in home assistant files to properly run mypy --strict
- **Devcontainer mount consolidation**: Moved `.notes` and `.shared` mounts from `devcontainer.json` to `docker-compose.yml` — mounts with absolute paths are unreliable in Docker Compose mode when declared in `devcontainer.json`; compose-file volumes are authoritative for the compose service.
- **HA core mounted for mypy**: Mounted HA core source (`C:/Local/Code/ha_core/core` → `/ha_core`) into the devcontainer via `docker-compose.yml` as read-only, so mypy can resolve HA type stubs without installing the full HA package.
- **`mypy_path` configured**: Added `mypy_path = "/ha_core"` to `[tool.mypy]` in `pyproject.toml` to point mypy at the mounted HA source.
- **mypy scoped to custom component**: Added `[[tool.mypy.overrides]]` for `homeassistant.*` with `ignore_errors = true` and `follow_imports = "silent"` to prevent mypy from checking and reporting errors from HA core files while still using them for type resolution.

## [3.0.1] - 2026-05-10

### Changed

- **Readme**: Overhaul of the readme file, additional example automations, re-ordered for readability.
- **Under the Hood**: Several internal code changes to improve maintainability and alignment with Home Assistant development standards (no functional breaking changes).
- **Validations**: Improved local and automated remote testing to ensure code remains secure and follows best practices.

## [3.0.1-rc1] - 2026-05-10 - Unreleased

### Changed

- **Readme**: Updated Readme with additional information. Re-ordered some sections. Added more emoji icons to headings.

## [3.0.1-dev8] - 2026-05-10 - Unreleased

### Changed

- **Readme**: Updated Readme with an additional automation example and some new sections.
- **`get_rd` auto-login guard** (`api.py`): Replaced `assert self.stok is not None` with `if not self.stok: self.stok = await self.login()` — consistent with 6 other methods.
- **`get_version` error return** (`api.py`): Changed from `""` to `None` (type updated to `str | None`). Both callers use `if not version`, behavior is identical.
- **Background task fallback** (`conftest.py`): Replaced `return MagicMock()` with `asyncio.ensure_future(coro)` to properly schedule coroutines and eliminate `RuntimeWarning`.

### Fixed

- **Protocol fallback silent failure** (`api.py`): Added `_LOGGER.warning` when both http/https probes fail — operators now see a log entry instead of silent failure.
- **Magic number in sensor.py**: Extracted `_BYTES_PER_GB = 1073741824` constant for clarity and maintainability.
- **2 `RuntimeWarning: coroutine was never awaited`** (`test_setup_entry_success`, `test_background_setup_failure`): Coroutine now scheduled on the event loop instead of discarded via `MagicMock()`.
- **Test assertion mismatch** (`test_api.py`): Updated `test_api_get_version_error` assertion from `== ""` → `is None` after `get_version` type change.

### Test Coverage

- **1 new test**: `test_coordinator_metadata_update_device_exists` — covers the coordinator path when a device already exists in the registry.

## [3.0.1-dev6] - 2026-05-10 - Unreleased

### Fixed

- **24 mypy errors in `api.py`**: Added type annotations to all functions, params, and return types. Changed `await self.login()` → `self.stok = await self.login()` in 7 methods so mypy sees `str` after login without breaking tests that mock `login()`.
- **6 test failures from mypy fix**: Updated 2 test files (`test_api.py`, `test_coverage_ext.py`) to set `api.stok` before calling `get_rd()` in error/success paths. Source in `api.py` changed from `assert` to return-value assignment.

### Test Coverage

- **8 new tests**: `delete_sms` exception handler, `get_all_data` retry-exhausted warning branch, `__init__` background setup success, 5 `config_flow` reconfigure flow tests (success + 3 error branches + form display).
- **Coverage to 100%**: `api.py` (98→100%), `__init__.py` (92→100%), `config_flow.py` (88→100%). Overall: 99% (824/824, 5 uncovered).

## [3.0.1-dev5] - 2026-05-10 - Unreleased

### Added

- **Reconfiguration Flow**: Support for updating host and credentials via the "Configure" menu.
- **Hierarchical Translations**: Canonical translation keys for all 63 entities with sub-device grouping.

### Changed

- **Translation Strategy**: Standardized on `translation_key` across all platforms; removed hardcoded `name` parameters.
- **Documentation**: Expanded README with Technical Architecture, Resilience (3-strike logic), and Firmware Compatibility.

## [3.0.1-dev4] - 2026-05-09 - Unreleased

### Changed

- **pyproject.toml**: pyproject.toml is now fully project agnostic. It does not contain the name of the specific project, instead just references the general custom_components folder for pytest coverage.
- **tasks.json**: tasks.json is also not fully project agnostic. It does require a settings.json file, but this now only requires one change per project.

## [3.0.1-dev3] - 2026-05-09 - Unreleased

### Dev Tooling

- **Shared Reusable CI Workflow**: Created `PlayFaster/.github` organisation repo containing a parameterised reusable workflow (`validate.yaml`, named "Validate (Shared)"). All 8 validation jobs (`hassfest`, `hacs_val`, `py_val`, `test_val`, `file_val`, `codespell`, `zizmor`, `mypy_val`) now live in the shared repo and are called by each integration via a thin caller. Changes to validation logic propagate to all 4 projects on the next CI run without per-project edits.
- **Thin Caller Workflow**: Replaced the 270-line inline `.github/workflows/validate.yaml` with a ~30-line caller that delegates to the shared workflow via `uses: PlayFaster/.github/.github/workflows/validate.yaml@main`. Permissions correctly scoped: `contents: read` at workflow level, `contents: write` and `pull-requests: write` at job level (required by `test_val` for coverage badge and PR comments).
- **Shared Workflow Concurrency**: Reusable workflow uses `${{ github.workflow }}-${{ github.ref }}-${{ github.repository }}` as its concurrency group, preventing cross-repo cancellation when multiple integrations trigger simultaneously.
- **Shared Workflow Dependabot**: Added `dependabot.yml` to `PlayFaster/.github` tracking the `github-actions` ecosystem weekly, keeping SHA pins in the shared workflow current.
- **Pre-commit: Suppress Inapplicable Hooks**: Added `stages: [manual]` to the `no-commit-to-branch` hook — direct commits to `main`/`dev` are the working pattern for this project, so the hook is retained for explicit use but removed from the default commit flow. Added `exclude: \.yamllint$` to the `yamllint` hook to prevent it from linting its own config file (which lacks `---` and uses CRLF).
- **VS Code Tasks**: Added `Zizmor: Fix (Safe Auto-Fix)` task (`zizmor --fix .github/`) for applying zizmor's safe auto-fixes on demand. Added `Pre-commit: Autoupdate Hooks` task (`pre-commit autoupdate`) for updating all hook `rev:` pins to their latest releases. Neither task is wired into `Fix All` or `Validate All`.

## [3.0.0] - 2026-05-08

### Added

#### Major Refactoring (Version 3.0)

- This release introduces a modern, safer, and more resilient core architecture designed to improve the reliability and customization of the integration.

#### Performance & Stability

- **Faster, Non-Blocking Startup**: Integration setup now runs entirely in the background. Home Assistant will not "hang" or slow down while waiting for the router to respond during startup.
- **Native Async Architecture**: Rewritten to be more efficient and optimize resource utilization. This ensures the integration operates properly with the Home Assistant event loop.
- **Improved Connection Resilience**: Sensors will now hold their last known values for up to three failed connection attempts. This prevents "Unavailable" flickers during brief network hiccups.
- **Reliable Device Info**: Hardware models and software versions are now saved locally. The Device Page will stay populated even if the router is rebooted or goes offline.
- **Stable Device Identity**: The integration now uses the hardware IMEI as a stable identifier. This ensures your entities and their history remain consistent even if the router's IP address changes.
- **Enhanced Connection Security**: Verified that no sensitive tokens or passwords are logged or persisted in state attributes.
- **Domain Cleanup**: Implemented standardized unloading logic to ensure the integration key is scrubbed from Home Assistant's internal memory when no integration instances remain.

#### New Features & Customization

- **12 New Sensors**: Significant expansion of monitored metrics including **IMEI**, **Hardware Version**, **SIM IMSI**, **SIM ICCID** (System); **eNodeB ID**, **Network Mode**, **Bridge Mode** (Signal); **Upload/Download Speed**, and **Session Usage** (Data).
- **Custom Entity Naming**: You can now set a custom prefix (e.g., _"My ZTE Router"_) for all devices and entities during setup or via the **Configure** menu.
- **Smarter Device Organization**: Entities are now automatically grouped into logical sub-devices (**System**, **Signal**, **Data**, and **SMS**) to reduce the overwhelm factor and make it easy to disable certain sections if desired.
- **Data Integrity Guards**: New "Guard Bands" and safety checks ensure your sensors don't report impossible values or cause errors during initial connection.
- **Re-authentication Support**: If your router password changes, Home Assistant will now notify you and provide a simple dialog to update your credentials without needing to re-install the integration.
- **Download Diagnostics**: Added support for Home Assistant's diagnostic tool, allowing you to easily export redacted integration data for troubleshooting.
- **Monthly Data in Bytes**: Added Monthly data in native bytes unit (up, down, total). This is the default and supports Home Assistant's built-in unit conversion.

### Changed

- **User-Friendly Labels**: Refined entity labels for better readability (e.g., "PPP Status" → "**Bridge Mode**", "Wa Inner Version" → "**Firmware Version**").
- **Readme**: Updated and added automation examples.

## [3.0.0-rc1] - 2026-05-08

### Changed

- **Entity categories and visibility**: Refined sensor categorization and default settings. Moved **Device Uptime**, **Last Updated**, and **Best Connection** to regular Sensor category; moved **WAN Connect Status** to Diagnostic. Set **Battery** to be disabled by default.
- **User-Friendly Labels**: Renamed **PPP Status** sensor to **Bridge Mode** for better clarity in the UI.

### Fixed

- **Readme**: Updates to Readme including corrections to automation examples.

## [3.0.0-dev22] - 2026-05-08

### Fixed

- **Hassfest translation schema** (`strings.json`, `translations/en.json`): Removed invalid top-level `"reauth"` key; moved `reauth_confirm` step into `config.step` where the HA translation schema requires it. Resolves hassfest CI error: `extra keys not allowed @ data['reauth']`.
- **Reauth `{host}` placeholder** (`config_flow.py`): Added `description_placeholders={"host": host}` to `async_show_form` in `async_step_reauth_confirm` so the router IP resolves in the dialog description at runtime instead of rendering as a literal `{host}` string.

## [3.0.0-dev21] - 2026-05-08

### Added

- **Gold Standard README**: Comprehensive documentation overhaul with entity tables, technical context, and YAML automation examples.
- **Missing Translations**: Added 15+ missing translation keys for 5G signal metrics and hardware diagnostics to ensure 100% coverage.

### Changed

- **User-Friendly Labels**: Refined entity labels in `strings.json` for better readability (e.g., "Wa Inner Version" → "Firmware Version").

### Fixed

- **Hassfest Validation**: Resolved duplicate `reauth` keys in `strings.json` that caused CI/CD failures.

## [3.0.0-dev19] - 2026-05-07

### Changed

- **Shared `device_info` helper**: Extracted 5-way duplicated `device_info` property into `build_device_info()` in `helpers.py`. All platform files (`sensor.py`, `binary_sensor.py`, `button.py`, `switch.py`, `number.py`) now delegate to the shared helper. Fixes Low #2.
- **Dynamic `configuration_url`**: Migrated from hardcoded `http://` to `{protocol}://` using `coordinator.api.protocol`. Fixes Low #3.
- **Device Registry metadata updates**: Replaced mid-poll `async_update_entry(entry.data)` writes with `device_registry.async_update_device()`. Hardware metadata changes propagate to the registry without writing config entry data on every poll. Fixes Medium #2.
- **Sensor naming → translation-based**: 58 sensor descriptions migrated from hardcoded `name="..."` to `translation_key="<key>"`. `strings.json` is now the canonical display-name source. Added 3 missing entries to `strings.json`; added 7 missing entries to `translations/en.json`; resolved 5 name discrepancies between the two files.

### Fixed

- **Unbounded recursion in `get_all_data`**: Added `_retry: bool = True` guard parameter. Second re-login attempt with same empty response returns partial data instead of recursing until `RecursionError`. Fixes High #2.
- **Untracked async task in `ZTEPollingInterval`**: Added `async_will_remove_from_hass` to cancel `self._refresh_task` on integration unload. Fixes High #3.
- **Null dereference in `async_step_reauth_confirm`**: Added `entry is None` guard before accessing `entry.options`. Fixes High #4.
- **Python 2 `except` syntax**: Fixed 7 occurrences of bare comma-form `except ValueError, TypeError:` → `except (ValueError, TypeError):` and `except KeyError, AttributeError:` → `except (KeyError, AttributeError):`. Fixes Medium #1.
- **`ValueError` escape in `native_value`**: Widened except from `(KeyError, AttributeError)` to `(KeyError, AttributeError, ValueError)`. Fixes Medium #3.
- **Bare `Exception` for missing password**: Changed `raise Exception("No password provided")` to `raise ZTEAuthError(...)` so it triggers reauth instead of silent retry. Fixes Medium #4.
- **`delete_sms()` missing `stok` clearing**: Wrapped POST in try/except with `self.stok = None; raise`. Fixes Medium #5.
- **Orphaned test body**: Extracted reauth flow assertions into properly decorated `test_reauth_flow_show_form`. Fixes Medium #6.
- **`diagnostics.py` weak type annotation**: Changed `DataUpdateCoordinator` to `ZTERouterDataUpdateCoordinator`. Fixes Low #4.

### Removed

- **Duplicate `PARALLEL_UPDATES = 0`**: Removed second declaration from `sensor.py`, `binary_sensor.py`, `switch.py`, `number.py`. Fixes Low #1.

## [3.0.0-dev16] - 2026-05-07

### Changed

- **Shared `device_info` helper**: Extracted 5-way duplicated `device_info` property into `build_device_info()` in `helpers.py`. All platform files (`sensor.py`, `binary_sensor.py`, `button.py`, `switch.py`, `number.py`) now delegate to the shared helper. Fixes Low #2.
- **Dynamic `configuration_url`**: Migrated from hardcoded `http://` to `{protocol}://` using `coordinator.api.protocol`. Fixes Low #3.
- **Device Registry metadata updates**: Replaced mid-poll `async_update_entry(entry.data)` writes with `device_registry.async_update_device()`. Hardware metadata changes propagate to the registry without writing config entry data on every poll. Fixes Medium #2.
- **Sensor naming → translation-based**: 58 sensor descriptions migrated from hardcoded `name="..."` to `translation_key="<key>"`. `strings.json` is now the canonical display-name source. Added 3 missing entries to `strings.json`; added 7 missing entries to `translations/en.json`; resolved 5 name discrepancies between the two files.

### Fixed

- **Unbounded recursion in `get_all_data`**: Added `_retry: bool = True` guard parameter. Second re-login attempt with same empty response returns partial data instead of recursing until `RecursionError`. Fixes High #2.
- **Untracked async task in `ZTEPollingInterval`**: Added `async_will_remove_from_hass` to cancel `self._refresh_task` on integration unload. Fixes High #3.
- **Null dereference in `async_step_reauth_confirm`**: Added `entry is None` guard before accessing `entry.options`. Fixes High #4.
- **Python 2 `except` syntax**: Fixed 7 occurrences of bare comma-form `except ValueError, TypeError:` → `except (ValueError, TypeError):` and `except KeyError, AttributeError:` → `except (KeyError, AttributeError):`. Fixes Medium #1.
- **`ValueError` escape in `native_value`**: Widened except from `(KeyError, AttributeError)` to `(KeyError, AttributeError, ValueError)`. Fixes Medium #3.
- **Bare `Exception` for missing password**: Changed `raise Exception("No password provided")` to `raise ZTEAuthError(...)` so it triggers reauth instead of silent retry. Fixes Medium #4.
- **`delete_sms()` missing `stok` clearing**: Wrapped POST in try/except with `self.stok = None; raise`. Fixes Medium #5.
- **Orphaned test body**: Extracted reauth flow assertions into properly decorated `test_reauth_flow_show_form`. Fixes Medium #6.
- **`diagnostics.py` weak type annotation**: Changed `DataUpdateCoordinator` to `ZTERouterDataUpdateCoordinator`. Fixes Low #4.

### Removed

- **Duplicate `PARALLEL_UPDATES = 0`**: Removed second declaration from `sensor.py`, `binary_sensor.py`, `switch.py`, `number.py`. Fixes Low #1.

## [3.0.0-dev15] - 2026-05-07

### Added

- **12 new sensors** from live router interrogation (MC7010): IMEI, Hardware Version, Battery, SIM IMSI, SIM ICCID (System sub-device); eNodeB ID, Network Mode, PPP Status (Signal sub-device); Upload Speed, Download Speed, Session Sent, Session Received (Data sub-device). Entity count: 51 → 63.
- **Guard bands** on new numeric sensors: Battery (0–100 %), Upload Speed (min 0 B/s), Download Speed (min 0 B/s), Session Sent (min 0 bytes), Session Received (min 0 bytes).
- **Diagnostics redaction**: `imei`, `sim_imsi`, `sim_iccid` added to `TO_REDACT` in `diagnostics.py`.
- **Translation entries**: 12 new sensor keys added to `strings.json` and `translations/en.json`.

### Changed

- **Stable device identity**: `unique_id` now uses IMEI (hardware-bound modem identifier) instead of host IP. `config_flow.py` `_validate_credentials` returns `imei`; `async_step_user` uses `info.get("imei") or host` as unique*id. Fallback to `host*{IP}` preserved for firmware that does not expose IMEI.
- **`coordinator.mac` → `coordinator.imei`**: Renamed across `coordinator.py`, `__init__.py`, and all 5 platform `device_info` properties (`sensor.py`, `binary_sensor.py`, `button.py`, `switch.py`, `number.py`). Sub-device identifiers now use IMEI prefix.
- **Tests updated**: `conftest.py` fixture renamed to `coordinator.imei = "864155042229309"`; device identifier assertions updated in `test_number.py`, `test_sensor.py`, `test_binary_sensor.py`, `test_button.py`.

## [3.0.0-dev14] - 2026-05-07

### Added

- **`diagnostics.py`**: New diagnostics platform. Exposes coordinator state, entry data, and live router data (with credential redaction) via Developer Tools → Download Diagnostics.
- **Reauthentication Flow**: `async_step_reauth` and `async_step_reauth_confirm` in `config_flow.py`. `ZTEAuthError` in coordinator triggers `entry.async_start_reauth`. `strings.json` updated with reauth strings.
- **Installation Parameters**: Documented minimum HA version (2024.6.0), Python (3.12+), and tested firmware in README.
- **Configuration Parameters**: Documented polling interval range (30–3600s), defaults, and runtime options flow in README.
- **Config Flow Test Coverage**: Added show-form paths (`user_input=None`) for both config and options steps. Added options flow `ZTEAuthError` branch test.

### Changed

- **`runtime-data`**: Migrated from `hass.data[DOMAIN][entry.entry_id]` to `entry.runtime_data` in `__init__.py` and all 5 platform files. Simplified `async_unload_entry`.
- **`parallel-updates`**: Added `PARALLEL_UPDATES = 0` to all 5 platform files (`sensor.py`, `binary_sensor.py`, `button.py`, `switch.py`, `number.py`).
- **Log-on-unavailable**: Coordinator now logs WARNING on first failure, DEBUG on intermediate retries (2/3, 3/3), ERROR on transition to unavailable, and INFO on reconnection (`_was_available` flag).
- **`strings.json`**: Added `data_description` blocks for `host` and `password` in config and options steps.

### Fixed

- **Action Exceptions**: Both `async_press` handlers (`reboot`, `delete_all`) now raise `HomeAssistantError` on API failure instead of silently logging, enabling automation failure detection.
- **Test failures**: Updated `test_coverage_ext.py` button exception tests to expect `HomeAssistantError`. Fixed `test_init.py` reauth test to use `patch.object` for `async_start_reauth`.

## [3.0.0-dev11] - 2026-05-07

### Changed

- **Badge Links**: Added links to readme badges.

## [3.0.0-dev10] - 2026-05-02 - Unreleased

### Changed

- **Badge Links**: Added links to readme badges.

- **Sub-device Architecture**: Grouped entities into System (Root), Signal, Data, and SMS devices for better Home Assistant UI organization.

## [3.0.0-dev8] - 2026-04-29 - Unreleased

### Added

- **Sub-device Architecture**: Grouped entities into System (Root), Signal, Data, and SMS devices for better Home Assistant UI organization.
- **Data Standards Alignment**: Implemented `SensorDeviceClass.DATA_SIZE` and `UnitOfInformation.BYTES` for all volume sensors.
- **Standardized Units**: Aligned Signal units with 3GPP standards (RSRP/RSSI in dBm; RSRQ/SNR/SINR in dB).
- **Entity Identity**: Implemented stable `unique_id` strategy using lowercase internal keys (e.g., `z5g_rsrp`) and MAC address prefix.
- **SMS Resilience**: Added logic to maintain sensor state attributes during update failures, preventing data loss in the UI.
- Added `zte_all_sensors.md` which documents all sensors/data-elements, their source and unit etc.
- **Monthly Data in Bytes**: Added Monthly data in native bytes unit (up, down, total). This is the default.

### Changed

- **Coordinator Logic**: Enhanced with a 3-strike failure counter before raising `UpdateFailed`, improving stability against transient network timeouts.
- **API Authentication**: Refined `stok` reset logic to force re-authentication after specific service failures (SMS/Reboot).
- **Volume Sensors**: Legacy GB sensors are now disabled by default in favor of standard Byte sensors. They remain available for legacy reasons.
- **Disabled by Default**: Set several unknown sensors and some not useful to Disabled by Default. These can be enabled by the user if desired.
- **Entity Naming**: Improved many entity names to be more human readable, not just the shortened router element name.

### Fixed

- **Test Suite Stability**: Resolved `AttributeError` on `MockConfigEntry.options` by using `object.__setattr__` for immutable properties.
- **Resource Warnings**: Eliminated `RuntimeWarning` from background tasks by falling back to `asyncio.create_task` when the HA mock is present.
- **Config Flow**: Fixed `KeyError: 'host'` in tests by ensuring mandatory connection parameters are preserved during mocking.
- **Linting**: Achieved zero violations across the codebase (Ruff format/check).

### Removed

- **Redundant Logic**: Removed "just-in-case" error swallowing in the coordinator that masked legitimate API timeouts.

### Security

- **Credential Protection**: Verified that no sensitive tokens or passwords are logged or persisted in state attributes.

## [3.0.0-dev5] - 2026-04-07 - Unreleased

### Added

- **Declarative Guard Bands**: Implemented "Standard 4" data integrity validation. Technical sensors (Signal Strength, SNR, Signal Bar, and SMS counts) now utilize declarative `min_limit` and `max_limit` boundaries to filter out transient hardware reporting spikes.

### Changed

- **Standardized Resilience**: Aligned the Data Update Coordinator with the "PlayFaster" architectural standards. Increased the failure threshold to 3 cycles and synchronized warning logs to provide consistent status reporting across all PlayFaster router integrations.
- **Custom User Naming**: Implemented `CONF_NAME` support. Users can now define a custom prefix (e.g., "Home Gateway") during setup or reconfiguration, which is applied to the integration title, device name, and all child entities.
- **Standardized Device Info**: Updated the sensor platform to strictly use the integration title for device naming, ensuring full compatibility with the new custom naming standard.

### Fixed

- **Entity Naming Integrity**: Synchronized the sensor platform's naming logic to ensure deterministic entity IDs that correctly incorporate the user-defined custom name prefix.
- **Log Consistency**: Refactored coordinator error messages to use the standardized "PlayFaster" wording for better cross-project log analysis.

## [3.0.0-dev3] - 2026-04-07 - Unreleased

### Added

- **Declarative Entity Engine**: Refactored the sensor platform to use a modern callback-based architecture (`value_fn`). This replaces 100+ lines of imperative logic with clean, maintainable entity descriptions.
- **Dynamic Sub-Device Routing**: Unified multiple sensor classes into a single dynamic engine that automatically routes entities to the correct sub-device (SMS, Monthly Data, or Main Router) based on metadata.

### Changed

- **Modern Background Tasks**: Migrated the non-blocking startup sequence to the modern `entry.async_create_background_task` API. This ensures the setup task is formally tracked by Home Assistant and automatically cancelled if the integration is unloaded.
- **Standardized Resilience**: Aligned the Data Update Coordinator with Home Assistant best practices. Removed manual retry sleeps and implemented `asyncio.timeout` with structured `UpdateFailed` reporting.
- **Flat Identity Pattern**: Refactored `device_info` across all platforms to use persistent coordinator-level attributes. This ensures hardware model information is visible in the UI from the exact second of boot, even before the first network fetch.

### Fixed

- **Domain Cleanup**: Implemented standardized unloading logic to ensure the `DOMAIN` key is scrubbed from Home Assistant's internal memory when no integration instances remain.

## [3.0.0-dev2] - 2026-04-07 - Unreleased

### Added

- **Persistent Metadata**: The integration now fetches and stores the hardware model and software version in the `ConfigEntry` during setup. This ensures the Device Page is always populated correctly, even if the router is offline.
- **Strict Linting**: Enabled `N` (pep8-naming) and `D` (pydocstyle) rules in `ruff` configuration for ongoing code quality.
- **Comprehensive Documentation**: Added module, class, and method-level docstrings across the entire codebase.

### Changed

- **Non-Blocking Startup**: Removed the initial blocking data fetch during integration setup. Home Assistant now starts instantly, and the first data poll occurs in the background.
- **PEP8 Naming**: Internal API methods to lowercase (Python standards).
- **Docstring Style**: Add missing docstrings and standardize to use imperative tone.
- **README**: Improve screenshot visibility.
- **Tests and Coverage**: Added Testing and Coverage to GitHub Validation (previously only local).

### Fixed

- **Standardized Device Info**: All 46+ entities now use consistent coordinator-based metadata for the Home Assistant Device Registry.
- **Config Entry Setup**: Resolved a `KeyError: 'host'` by correctly reading configuration from `entry.options` instead of `entry.data`.
- **Data Safety**: Implemented safety checks for `None` data in sensors to prevent runtime errors during initialization or connection loss.
- **Exception Handling**: Fixed invalid syntax in multiple exception handlers.

## [3.0.0-dev1] - 2026-04-01 - Unreleased

### Added

- **Native Async Architecture**: Migrated the entire API and polling layer to `aiohttp` for native asynchronous execution.
- **Improved Performance**: Removed thread-based `executor_job` wrappers, aligning the integration with the Home Assistant event loop.
- **Dependency Simplification**: Removed `requests` as a required dependency, eliminating maintenance of version pinning.

### Changed

- **Version Bump**: Major version update to reflect the complete architectural shift.

## [2.3.1] - 2026-04-01 PUBLIC RELEASE

### Added

- **Development Documentation**: Added `DEVELOPMENT.md` containing architectural notes and project history.
- **Screenshots**: Added images to `README.md`.
- **Icon and Logo**: Added required assets for HACS and Home Assistant branding.
- **Automated Validation**: Integrated specialized GitHub Actions for Hassfest, HACS, and Python quality.

### Changed

- **Architecture Refactor**: Introduced `coordinator.py` to centralize and optimize data fetching logic.

### Fixed

- **Unavailable Bug**: Fixed an issue where sensors would never go unavailable due to misconfigured grace period.

## [2.2.4] - 2026-03-30

### Added

- **Coverage**: Added basic test coverage.

### Changed

- **Clean Code**: Code clean-up and formatting/linting rules.
- **Testing**: Improved scope of testing.
- **Strings**: Added strings.json in addition to en.json.

## [2.2.3] - 2026-03-30

### Added

- **Testing Infrastructure**: Added python tests.

### Fixed

- **Manifest**: Fixed manifest.json for GitHub tests.

## [2.1.1] - 2026-03-29

### Added

- **Error Logging**: Significantly improved home assistant (logger) error logging.

## [2.0.1] - 2026-03-29

### Added

- **Options Flow**: Allow reconfiguration of integration in-situ rather than delete and re-add.

## [1.9.4] - 2026-03-29

### Added

- **Model Number**: Pulls model number from device.

### Changed

- **Exception Handling**: Improved exception handling.

### Fixed

- **Strings and Translate**: Fixed strings en.json structure and moved all elements to this.
- **Sessions Handling**: Explicit closing of sessions.

## [1.8.1] - 2026-03-29

### Added

- **Strings and Translate**: Added translation folder structure, just en for now.

## [1.7.3] - 2026-03-29

### Fixed

- **Entity Naming**: Fixed entity sensor naming approach.

## [1.6.3] - 2026-03-28

### Changed

- **Reduced Startup Risk**: Moved to async for startup to avoid any potential for slowness/hangs/locks if router is unavailable at HA start.

## [1.5.7] - 2026-03-28

### Added

- **Integration Icon**: Added ZTE icons.

### Fixed

- **Sub Device Sensors**: Properly align sub device (data, sms) sensor naming.

## [1.5.1] - 2026-03-28

### Changed

- **Aligned Integration Naming**: All naming now ZTE Router 5G Monitor.

## [1.4.5] - 2026-03-28

### Added

- **Changelog**: Added Changelog (this) as CHANGELOG.md.

### Changed

- **Standard Names**: Changed specific sensor names (with ID tag) to standard names.

## [1.4.4] - 2026-03-28

### Added

- **All Relevant Attributes**: Added all relevant signal and status attributes available from the router as sensors.

## [1.4.3] - 2026-03-28

### Added

- **Pause Polling Switch**: New entity to manually halt API traffic to the router.
- **Polling Interval Slider**: Number entity to adjust the refresh rate (30s to 3600s) directly from the UI.
- **Persistence**: Integration now saves Polling State and Interval to `ConfigEntry` options, ensuring settings survive a Home Assistant restart.

### Fixed

- **Startup Deadlock**: Implemented "Initial Bypass" logic to ensure entities load correctly on restart even if polling was previously paused.
- **Boot Resilience**: Added a fail-safe to prevent the integration from becoming "Unavailable" if the router is unreachable during the initial Home Assistant startup sequence.

## [1.4.2] - 2026-03-27

### Added

- **SMS Monitoring**: Added sensors for SMS capacity (total/used) and a sensor to display the content of the latest received message.
- **Hybrid Resilience**: Implemented a "one-cycle grace period" where sensors hold their last known value during a single failed poll before marking as unavailable.
- **GitHub**: Initial release to GitHub repository.

## [1.4.1] - 2026-03-27

### Changed

- Refactored `DataUpdateCoordinator` to handle centralized data fetching for all platforms.
- Improved API login reliability with automatic protocol detection (HTTP/HTTPS).

## [1.4.0] - 2026-03-26

### Added

- Core sensors: Signal Strength (RSRP/RSRQ/SINR), Network Type, and Data Usage.
- Connection status binary sensor.

## [1.3.6] - 2026-03-25

### Added

- Initial release for ZTE MC7010 5G Router.
- Moved from one sensor with all data as sensor attributes to separate sensors.
- Added config flow.
- Added single device, then sub-devices (router, data, sms).

---

### Format

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
