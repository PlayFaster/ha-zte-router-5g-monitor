# Changelog

All notable changes to this project will be documented in this file.

## [3.0.0] - Future - Unreleased

### Added

#### Major Refactoring (Version 3.0)

- This release introduces a modern, safer, and more resilient core architecture designed to improve the reliability and customization of the integration.

#### Performance & Stability

- **Faster, Non-Blocking Startup**: Integration setup now runs entirely in the background. Home Assistant will not "hang" or slow down while waiting for the router to respond during startup.
- **Native Async Architecture**: Rewritten to be more efficient and optimize resource utilization. This ensures the integration operates properly with the Home Assistant event loop, preventing the integration from delaying or interfering with other system processes.
- **Improved Connection Resilience**: Sensors will now hold their last known values for up to three failed connection attempts. This prevents "Unavailable" flickers during brief network hiccups.
- **Reliable Device Info**: Hardware models and software versions are now saved locally. Your Device Page will stay populated even if the router is rebooted or goes offline.
- **Domain Cleanup**: Implemented standardized unloading logic to ensure the integration key is scrubbed from Home Assistant's internal memory when no integration instances remain.

#### New Features & Customization

- **Custom Entity Naming**: You can now set a custom prefix (e.g., _"Downstairs Gateway"_) for all devices and entities during setup or via the **Configure** menu.
- **Smarter Device Organization**: Entities are now automatically grouped into logical sub-devices (e.g., **SMS**, **Monthly Usage**, and **Main Router**) for a cleaner Look in your Dashboards.
- **Data Integrity Guards**: New "Guard Bands" and safety checks ensure your sensors don't report impossible values or cause errors during initial connection.

## [3.0.0-dev6] - Now - Unreleased

## [3.0.0-dev5] - 2026-04-07 - Unreleased

### Changed - Unreleased

- **Standardized Resilience**: Aligned the Data Update Coordinator with the "PlayFaster" architectural standards. Increased the failure threshold to 3 cycles and synchronized warning logs to provide consistent status reporting across all PlayFaster router integrations.
- **Custom User Naming**: Implemented `CONF_NAME` support. Users can now define a custom prefix (e.g., "Home Gateway") during setup or reconfiguration, which is applied to the integration title, device name, and all child entities.
- **Standardized Device Info**: Updated the sensor platform to strictly use the integration title for device naming, ensuring full compatibility with the new custom naming standard.
- **Declarative Guard Bands**: Implemented "Standard 4" data integrity validation. Technical sensors (Signal Strength, SNR, Signal Bar, and SMS counts) now utilize declarative `min_limit` and `max_limit` boundaries to filter out transient hardware reporting spikes.

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
