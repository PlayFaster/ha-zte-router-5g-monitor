# Changelog

All notable changes to this project will be documented in this file.

## [3.1.0] - 2026-05-23

### Added

- **SMS Services**: Four new Home Assistant actions — `send_sms`, `delete_sms`, `delete_all_sms`, and `get_sms_list` — for full SMS management from automations and scripts.
- **SMS Received Event**: Integration now fires a `zte_router_5g_sms_received` event when a new SMS arrives, enabling event-triggered automations.
- **SMS Storage Full Repair**: A repair issue is raised in the HA Repairs panel when NV SMS storage reaches capacity; it clears automatically when resolved.
- **Uptime Duration Sensor**: New sensor reporting how long the router has been running (disabled by default).
- **State-Dependent Entity Icons**: Entity icons now reflect live state (e.g. Best Connection sensor shows an active signal icon when connected).

### Changed

- **Stable Uptime Timestamp**: Boot time is now latched once and only re-derived when the router's uptime counter drops — the only reliable reboot signal. Bad or missing uptime readings leave the cached value untouched, eliminating timestamp drift caused by independently ticking clocks.
- **Flexible Host Input**: The host field now accepts addresses with `http://` or `https://` prefixes; they are stripped automatically during setup and reconfiguration.

### Fixed

- **Empty Sensor Values**: Sensors receiving an empty string from the router now correctly report **Unknown** state in HA instead of displaying a blank value.
- **Spurious Re-authentication**: Transient connection drops and network errors no longer incorrectly trigger the re-authentication flow; reauth is reserved for explicit credential rejection from the router.
- **Monthly Data (Legacy GB Sensors)**: Corrected unit calculation from binary gibibytes (GiB, 1,073,741,824 bytes) to decimal gigabytes (GB, 1,000,000,000 bytes).

## [3.0.1] - 2026-05-10

### Changed

- **Readme**: Overhaul of the readme file, additional example automations, re-ordered for readability.
- **Under the Hood**: Several internal code changes to improve maintainability and alignment with Home Assistant development standards (no functional breaking changes).
- **Validations**: Improved local and automated remote testing to ensure code remains secure and follows best practices.

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
