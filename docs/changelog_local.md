# Changelog

All notable changes to this project will be documented in this file.

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
