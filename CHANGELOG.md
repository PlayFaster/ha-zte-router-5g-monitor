# Changelog

All notable changes to this project will be documented in this file.

## [3.0.0-dev6] - Now - Unreleased

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

### Changed

- **README**: Improve screenshot visibility.

## [2.3.1] - 2026-04-01 PUBLIC RELEASE

### Added

- **Screenshots**: Added images to `README.md`.

### Fixed

- **Unavailable Bug**: Fixed an issue where sensors would never go unavailable due to misconfigured grace period.

## [2.1.1] - 2026-03-29

### Added

- **Error Logging**: Significantly improved home assistant (logger) error logging.

## [2.0.1] - 2026-03-29

### Added

- **Options Flow**: Allow reconfiguration of integration in-situ rather than delete and re-add.

## [1.9.4] - 2026-03-29

### Added

- **Model Number**: Pulls model number from device.

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
