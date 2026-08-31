# Changelog

All notable changes to this project will be documented in this file.

---

## [3.3.6] - 2026-08-31 - Release: Device Uptime Boot Timestamp Reconciliation Across Restarts

### Summary

- **Device Uptime Startup Accuracy**: Resolved an issue where the `Device Uptime` sensor could retain a stale boot timestamp across Home Assistant restarts if the router rebooted during the restart gap.

### Fixed

- **Stale Boot Time Across Restarts**: Fixed a bug where a router reboot occurring during a Home Assistant restart, host power cycle, or system update was not detected on startup, causing `Device Uptime` to freeze on the prior boot time indefinitely. Startup now cross-checks the live uptime counter and calculated boot instant against persisted history to reconcile reboots accurately.
  - This issue could be seen when:
    - HA restarted after a long downtime, during which time the router had rebooted.
    - HA and the ROuter restarted at the same time, after a power outaage.

### Under the hood

- **Startup Reconciliation Test Suite**: Added 34 tests verifying startup reconciliation across multi-week offline gaps, clock skew, un-synchronized host clocks, and storage error conditions.

---

## [3.3.5] - 2026-08-31 - Release: Diagnostics Capture on Setup Failures and Multi-User Login Alignment

### Summary

- **Multi-User Login Compatibility**: Aligned the multi-user login payload shape and token derivation with the reference hardware standard.
- **Session Recovery Resilience**: Prevented false authentication failure alerts when a newly authenticated session receives unsupported or missing keys.
- **Diagnostics Capture on Setup Failures**: Diagnostic downloads now capture the sanitized router response, key map, and login metadata even if initial connection fails.

### Added

- **Diagnostic Capture on Setup Failures**: Diagnostics downloads now retain the sanitized rejected response, key presence map (populated, empty, or absent keys), and login response metadata when initial setup encounters errors, allowing troubleshooting directly from diagnostic downloads without raw debug logs.

### Changed

- **Multi-User Login Payload**: Aligned the `LOGIN_MULTI_USER` form payload to send the username parameter as `user` and include the pre-login `AD` token, matching multi-user router requirements.

### Fixed

- **Session Expiry Misclassification**: Refined session expiry detection so responses missing requested keys (from firmware schema variations or truncated requests) are no longer misidentified as dead sessions.
- **False Re-Authentication Alerts**: An identical empty response on a freshly established session is now correctly classified as a communication issue rather than a lapsed session, routing to the coordinator's value-holding resilience path.

### Under the hood

- **Diagnostic Test Harness and Negative Token Verification**: Added comprehensive diagnostic capture test suites and explicit assertions ensuring session tokens and credentials are never stored or exported in diagnostics.

---

## [3.3.4] - 2026-08-30 - Release: Re-authentication Repair Flow, SMS Storage Sensor, and Login Compatibility

### Summary

- **Interactive Re-authentication**: Fix button in Repairs opens a guided re-authentication dialog when the router password is changed or rejected.
- **Cookieless Login Compatibility**: Added support for router models and firmware (such as the MC888 Pro) that authenticate without issuing a session cookie.
- **Repairs Panel Cleanup**: Aligned repairs with Home Assistant guidelines to show actionable issues only, mapping warnings to Integration Health.
- **Dedicated SMS Storage Sensor**: New binary sensor alerts when message storage on the SIM card or device is full.

### Added

- **Interactive Re-authentication Repair**: A persistent, fixable repair is raised when router credentials fail. Clicking **Fix** opens the re-authentication dialog directly to update the stored password.
- **SMS Storage Full Binary Sensor**: Added `binary_sensor.*_sms_storage_full` (enabled by default) under the SMS sub-device to monitor when message storage on either the SIM or device is full.

### Changed

- **Login Form Ordering**: Routers configured without a username now post the single-user login form directly, avoiding an initial failed attempt and connection warning.
- **Repairs Alignment**: Retired non-actionable repair cards (`firmware_contract_drift` and `sms_storage_full`). Schema changes are now tracked via `drift` on Integration Health, while message capacity is tracked by the new binary sensor. Renamed unreachable router issue to `conn_error`.
- **Bandwidth Sensor Unit Conversion**: LTE Carrier Aggregation bandwidth sensors (`lte_ca_pcell_bandwidth` and `lte_ca_scell_bandwidth`) now declare `device_class: frequency`, allowing unit switching (MHz/GHz/kHz) in the Home Assistant UI.
- **SMS Logging Privacy**: The sender's phone number is no longer logged at `INFO` level when receiving SMS messages; the internal message index is logged instead.
- **Health Telemetry Drift Limit**: Split the contract drift strike limit into an independent budget (`HEALTH_DRIFT_STRIKE_LIMIT = 3`) separate from poll fetch failures.

### Fixed

- **Cookieless Router Authentication**: Fixed an issue where router models/firmware that authenticate without issuing a `stok` cookie (such as the ZTE MC888 Pro) failed connection setup with an unreachable router error.
- **Session Token Detection**: Expanded session token discovery to inspect raw response headers, cookie jars across HTTP redirects, and response payloads.
- **Repair Translation Schema Compatibility**: Corrected repair translation structure for fixable issues to adhere strictly to Home Assistant issue schema requirements.
- **Health Snapshot Attribute Completeness**: Resolved an issue where the `repairs` attribute could be omitted from Integration Health sensor fallback snapshots.
- **Orphaned Repair Issue Cleanup**: Ensured legacy and retired repair issue IDs are cleaned up during integration entry removal.

### Under the hood

- **Transport Test Harness and Coverage Enforcement**: Added full HTTP transport-level mock suites (`aioclient_mock`), enforced 100% line and branch test coverage across all authentication and recovery paths, and added suppression allow-list enforcement.

---

## [3.3.3] - 2026-08-08 - Release: SMS Bugfix and Polling Resilience

### Summary

A Send SMS fix, plus several resilience and robustness changes for edge case behavior.

### Fixed

- **Get SMS List Action now reads Emoji Messages.** Fixed an internal error when decoding messages containing emojis or extended characters, which previously caused the entire message list to fail loading.

### Changed

- **Send SMS resilience**: The action now handles transient counter refresh failures without reporting the send itself as failed.

- **Multi-recipient SMS error reporting**: When sending SMS to multiple recipients fails midway, the error message now specifies which numbers were successfully reached.

- **Delete All Messages resilience**: The action now skips and logs messages with missing identifiers, allowing the deletion of remaining messages to complete.

- **Data entities polling resilience**: Decoupled `Allowance` and `Alert Threshold` from secondary poll status to prevent them from going unavailable during transient secondary failures.

- **Total Messages robust handling**: The sensor now handles empty responses from individual message storage areas without blanking out the entire count.

- **Repairs lifecycle cleanup**: Repairs are now automatically cleared when the integration is reloaded or removed, and are isolated per-device.

- **Command error description**: Unreachable routers are now reported as communication failures rather than command rejections across all commands.

- **Projected Cycle Usage edge cases**: Handled additional string representations of "off" from the router to accurately detect when the billing cycle counter is disabled.

- **Polling interval updates**: Ensured rapid polling interval changes are preserved even if the integration is reloaded immediately after.

---

## [3.3.2] - 2026-08-02 - Release: Expanded Model Support, Billing Cycle Tracking, and Health Telemetry

### Summary

Adds broader router model support, router-aligned data usage tracking, extended SMS message lengths, and an Integration Health diagnostic sensor.

- **Data usage tracking**: the router's own billing cycle, data cap and alert threshold now appear as entities, alongside a new projection of where the current cycle will finish.

- **Wider ZTE model support**: Expands compatibility across the family of ZTE 5G/LTE routers using the `goform` API.
  - MC7010, MC801, MC888, MC889, MF266, MF286, MF289

- **SMS improvements**: send the same long messages the router's own web page allows.

- **Action & Settings Fixes**: Fixed issues where Actions (SMS read or send etc.) and Settings Changes (APN, Data Limit switch etc.) could fail silently on long polling intervals.

- **`about` attribute**: Most entities now carry a short built-in explanation of what the value means — and for signal metrics, what counts as good, fair or poor.

- **Integration Health** problem sensor: tells you when the integration is running but the data coming back from the router has issues.

### Added

- **Data usage tracking follows router Data Management settings.** Exposes the router's configured **Clear Date**, **Data Plan** cap, and **Limit Reminder** as **Reset Day**, **Allowance**, and **Alert Threshold** entities. If Data Management is disabled on the router, tracking defaults automatically to the calendar month.
  - Alongside these, a new **Projected Cycle Usage** sensor forecasts total end-of-cycle data consumption based on observed daily run rates, providing `confidence`, `basis`, `cycle_day`, `cycle_start`, and `cycle_source` attributes.

- **Integration Health sensor**: A new diagnostic problem sensor on the System device that alerts on connectivity failures, empty data responses, and contract drift, carrying `issues`, `severity`, `degraded_capabilities`, `drift`, `repairs`, and `consecutive_failures` attributes.

- **Built-in explanations on entities**: Most entities now carry an `about` attribute providing clear operational guidance, expected signal ranges, and threshold interpretations without persisting to recorder history.

- **Router Unreachable repair**: after multiple consecutive failed fetches, a repair appears in the Repairs panel.

- **Seven new diagnostic entities** (disabled by default): Added Carrier Aggregation Secondary Cells, WAN Operating Mode, WAN Fallback Mode, Router Timezone, APN Interface Version, Web Page Sleep, and Web Page Auto-Wake.

### Changed

- **Extended SMS length support**: `send_sms` now accepts multi-part messages up to **765** ASCII characters or **335** Unicode characters (with emoji/special characters), matching router hardware capacity with automatic encoding selection and validation errors.
  - **Obligatory Warning**: It is _**YOUR**_ responsibility to understand whether having your Router send SMS messages is going to incur an extra charge from your ISP.
    - Remember **longer** messages generally get **billed** as multiple SMS.

- **Wider ZTE model support**: signal and data-usage sensors now recognize the alternative field names used by other `goform` routers, the login falls back to the other form when a model rejects the first, and the LTE/5G band name is worked out from the channel number when the router leaves it blank.

- **Attributes are not written to history**: no entity in this integration records any attribute to the database — only its state. The current state of all Attributes stay visible in the More Info dialog, Tools and templates.

- **Documentation**: the README's example automations now ignore `unknown` and `unavailable` states, to avoid false alerts from a HA restart or router reboot.

- **Icons and branding refreshed**.

### Fixed

- **APN Profile display alignment**: Aligned the dropdown to display only the active profile in manual APN mode, returning a blank state under auto mode where the router's default is used.

- **APN Selection Mode toggling**: Ensured switching between automatic and manual APN modes is correctly registered and processed by the router.

- **Session handling on write actions**: Implemented proactive login and session checks across all configuration writes and actions to prevent dropped credentials from causing silent update failures.

- **Actions reliability**: Hardened action pipelines to confirm responses, propagate error messages, refresh counters immediately on send, and re-login proactively.

- **Settings write stability**: Resolved state-setting errors on the **Data Limit Switch** and prevented temporary state desyncs on the **ODU LED Switch** after toggling.

- **Monthly Data state classification**: Corrected monthly data sensors' state class from `TOTAL` to `TOTAL_INCREASING` to ensure correct long-term statistics tracking and reset behavior.

---

## [3.2.5] - 2026-07-03 - Release: Refresh Now Button, Display Units, and Config Flow Hardening

### Added

- **Refresh Now Button**: New System button that triggers an immediate data refresh, complementing the existing Pause Polling switch and configurable polling interval

### Changed

- **Display Units & Precision**: 16 sensors now display expected units and decimal places in the UI — data sizes in GB, throughput in Mbit/s, uptime duration in hours, and rounded signal-strength/bandwidth values. Underlying native values (used for long-term statistics) are unchanged.
- **SMS Actions Default to the Sole Router**: The `delete_sms`, `delete_all_sms`, and `get_sms_list` actions no longer require `entry_id`. When exactly one router is configured it is selected automatically; with more than one configured, `entry_id` is required and omitting it now raises a clear "specify entry_id".
- **Polling Toggle Future Ready**: Turning off "Enable polling for changes" in the entry's system options now reliably stops scheduled polling and will satisfy the upcoming HA requirement (implicit `ContextVar` detection is being removed in HA 2026.8).
- **Minimum Home Assistant Version**: Documented minimum raised to 2024.8.0 (driven by polling option change above, this was added to HA in 2024.8)

### Fixed

- **Edit screen credential security**: Configured the password field on configuration screens to be masked and blank by default, preventing the stored password from being pre-filled or exposed.
- **Host URL sanitization**: Host input is now automatically sanitized to strip redundant prefixes or trailing slashes, preventing malformed device links.

## [3.2.4] - 2026-06-15 - Release: Shared CI Validation v2.0.3

### Changed

- **CI Validation Bump**: Shared CI validation bumped to v2.0.3. No user changes in this release, background/infrastructure only.

## [3.2.3] - 2026-06-14 - Maintenance: Shared CodeQL Permissions Alignment for Zizmor

### Summary

- **CI Validation Only**: Changes to the CI Validation set-up require another release to test properly, but there are no user changes in this release, background/infrastructure only.

## [3.2.2] - 2026-06-14 - Maintenance: Shared CodeQL Security Scanning

### Summary

- **CI Validation Only**: Changes to the CI Validation set-up require another release to test properly, but there are no user changes in this release, background/infrastructure only.

## [3.2.1] - 2026-06-14 - Maintenance: CI Validation Infrastructure Test Release

### Summary

- **CI Validation Only**: Changes to the CI Validation set-up require a release to test properly, but there are no user changes in this release, background/infrastructure only.

## [3.2.0] - 2026-05-28 - Release: APN Profile Control, Network Mode Select, and Diagnostic Entities

### Added

- **New APN and Configuration Entities**: Added several new controls and diagnostic sensors:
  - **APN Control Selects**: Added select entities for switching active APN profiles (`apn_profile`) and toggling between automatic/manual APN mode (`apn_mode`).
  - **Network Mode Select**: Added carrier network preference selection (`net_select_mode`) to choose between Auto (4G/5G), 5G NSA, 5G SA, and 4G Only.
  - **ODU LED Control Switch**: Added a switch (`odu_led_switch`) to toggle the physical outdoor unit status LEDs.
  - **Data Limit Control Switch**: Added a switch (`data_limit_switch`) to toggle data limit enforcement on the router.
  - **Reboot Schedule & Security Binary Sensors**: Added binary sensors to monitor Reboot Schedule, UPnP status, and SIP ALG status.
  - **New Diagnostic Sensors**: Added sensors for LTE Band Lock Mask, Data Volume Alert %, and SNTP Time Server.

### Changed

- **Database Cleanup (Reduced LTS)**: Removed long-term statistics tracking from 8 non-critical sensors (realtime throughput, uptime duration, etc.) to prevent database bloat.

### Fixed

- **Centralized session stability**: The request helper now proactively detects and resets expired session tokens to prevent transient errors and empty sensor states.

## [3.1.0] - 2026-05-24 - Release: SMS Service Actions, Received Bus Events, and Storage Full Repairs

### Added

- **SMS Services**: Four new Home Assistant actions — `send_sms`, `delete_sms`, `delete_all_sms`, and `get_sms_list` — for full SMS management from automations and scripts.
- **SMS Received Event**: Integration now fires a `zte_router_5g_sms_received` event when a new SMS arrives, enabling event-triggered automations.
- **SMS Storage Full Repair**: A repair issue is raised in the HA Repairs panel when NV SMS storage reaches capacity; it clears automatically when resolved.
- **Uptime Duration Sensor**: New sensor reporting how long the router has been running (disabled by default).
- **State-Dependent Entity Icons**: Entity icons now reflect live state (e.g. Best Connection sensor shows an active signal icon when connected).

### Changed

- **Flexible Host Input**: The host field now accepts addresses with `http://` or `https://` prefixes; they are stripped automatically during setup and reconfiguration.

### Fixed

- **Uptime tracking stability**: Latched the boot time calculation to prevent timestamp drift from independently ticking clocks, updating it only when a physical reboot drops the counter.
- **Empty value handling**: Standardized empty router responses to map to `Unknown` states in Home Assistant instead of displaying blank values.
- **Reauthentication flow triggers**: Isolated the reauthentication flow to explicit router credential rejections, preventing transient network drops from triggering configuration prompts.
- **Legacy data unit calculation**: Aligned legacy monthly data sensor conversions to standard decimal gigabytes (GB) instead of binary gibibytes (GiB).

## [3.0.1] - 2026-05-10 - Maintenance: README Documentation and Standards Alignment

### Changed

- **Readme**: Overhaul of the readme file, additional example automations, re-ordered for readability.
- **Under the Hood**: Several internal code changes to improve maintainability and alignment with Home Assistant development standards (no functional breaking changes).
- **Validations**: Improved local and automated remote testing to ensure code remains secure and follows best practices.

## [3.0.0] - 2026-05-08 - Major Release: Native Async Rewrite, Sub-Device Architecture, and IMEI Identity

### Added

#### Major Refactoring (Version 3.0)

- This release introduces a modern, safer, and more resilient core architecture designed to improve the reliability and customization of the integration.

#### Performance & Stability

- **Non-Blocking Startup**: Integration setup runs asynchronously in the background, preventing startup delays while awaiting router responses.
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
- **Reauthentication Support**: If your router password changes, Home Assistant will now notify you and provide a simple dialog to update your credentials without needing to re-install the integration.
- **Download Diagnostics**: Added support for Home Assistant's diagnostic tool, allowing you to easily export redacted integration data for troubleshooting.
- **Monthly Data in Bytes**: Added Monthly data in native bytes unit (up, down, total). This is the default and supports Home Assistant's built-in unit conversion.

### Changed

- **User-Friendly Labels**: Refined entity labels for better readability (e.g., "PPP Status" → "**Bridge Mode**", "Wa Inner Version" → "**Firmware Version**").
- **Readme**: Updated and added automation examples.

## [2.3.1] - 2026-04-01 - Release: DataUpdateCoordinator Migration and HACS Branding Assets

### Added

- **Screenshots**: Added images to `README.md`.

### Fixed

- **Grace period error handling**: Adjusted grace period configuration to ensure sensors correctly transition to `Unavailable` when the router goes offline.

## [2.1.1] - 2026-03-29 - Maintenance: Diagnostic Error Logging

### Added

- **Error Logging**: Significantly improved home assistant (logger) error logging.

## [2.0.1] - 2026-03-29 - Feature: Options Flow for Dynamic Reconfiguration

### Added

- **Options Flow**: Allow reconfiguration of integration in-situ rather than delete and re-add.

## [1.9.4] - 2026-03-29 - Feature: Hardware Model Reading and Session Management

### Added

- **Model Number**: Pulls model number from device.

## [1.7.3] - 2026-03-29 - Maintenance: Standardized Entity Naming

### Fixed

- **Entity naming alignment**: Aligned and standardized the sensor naming scheme.

## [1.6.3] - 2026-03-28 - Maintenance: Non-Blocking Async Startup for Offline Routers

### Changed

- **Reduced Startup Risk**: Moved to async for startup to avoid any potential for slowness/hangs/locks if router is unavailable at HA start.

## [1.5.7] - 2026-03-28 - UI: ZTE Brand Icons and Sub-Device Sensor Naming

### Added

- **Integration Icon**: Added ZTE icons.

### Fixed

- **Sub-device naming alignment**: Standardized sensor naming for secondary data and SMS entities.

## [1.5.1] - 2026-03-28 - Maintenance: Home Assistant Integration Naming Alignment

### Changed

- **Aligned Integration Naming**: All naming now ZTE Router 5G Monitor.

## [1.4.5] - 2026-03-28 - Documentation: Local Changelog Addition and Standard Sensor Names

### Changed

- **Standard Names**: Changed specific sensor names (with ID tag) to standard names.

## [1.4.4] - 2026-03-28 - Telemetry: Router Attribute Exposure as Entities

### Added

- **All Relevant Attributes**: Added all relevant signal and status attributes available from the router as sensors.

## [1.4.3] - 2026-03-28 - Controls: Pause Polling Switch and Polling Interval Number Entity

### Added

- **Pause Polling Switch**: New entity to manually halt API traffic to the router.
- **Polling Interval Slider**: Number entity to adjust the refresh rate (30s to 3600s) directly from the UI.
- **Persistence**: Integration now saves Polling State and Interval to `ConfigEntry` options, ensuring settings survive a Home Assistant restart.

### Fixed

- **Startup deadlock prevention**: Implemented initial bypass checks to ensure integration entities load successfully on Home Assistant restart when polling is paused.
- **Boot-phase connection resilience**: Added a startup fail-safe to prevent entities from loading in an unavailable state when the router is temporarily unreachable at startup.

## [1.4.2] - 2026-03-27 - Feature: SMS Inbox Monitoring and Initial GitHub Release

### Added

- **SMS Monitoring**: Added sensors for SMS capacity (total/used) and a sensor to display the content of the latest received message.
- **Hybrid Resilience**: Implemented a "one-cycle grace period" where sensors hold their last known value during a single failed poll before marking as unavailable.
- **GitHub**: Initial release to GitHub repository.

## [1.4.0] - 2026-03-26 - Telemetry: Core Signal and Cellular Data Sensors

### Added

- Core sensors: Signal Strength (RSRP/RSRQ/SINR), Network Type, and Data Usage.
- Connection status binary sensor.

## [1.3.6] - 2026-03-25 - Initial Release: Custom Component for ZTE MC7010

### Added

- Initial release for ZTE MC7010 5G Router.
- Moved from one sensor with all data as sensor attributes to separate sensors.
- Added config flow.
- Added single device, then sub-devices (router, data, sms).

---

### Format

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entry structure — headers, titles, category headings and the split between this file and its counterpart — follows `.shared/dev_std/changelog_format.md`.

---

- [Changelog](#changelog)
  - [\[3.3.6\] - 2026-08-31 - Release: Device Uptime Boot Timestamp Reconciliation Across Restarts](#336---2026-08-31---release-device-uptime-boot-timestamp-reconciliation-across-restarts)
  - [\[3.3.5\] - 2026-08-31 - Release: Diagnostics Capture on Setup Failures and Multi-User Login Alignment](#335---2026-08-31---release-diagnostics-capture-on-setup-failures-and-multi-user-login-alignment)
  - [\[3.3.4\] - 2026-08-30 - Release: Re-authentication Repair Flow, SMS Storage Sensor, and Login Compatibility](#334---2026-08-30---release-re-authentication-repair-flow-sms-storage-sensor-and-login-compatibility)
  - [\[3.3.3\] - 2026-08-08 - Release: SMS Bugfix and Polling Resilience](#333---2026-08-08---release-sms-bugfix-and-polling-resilience)
  - [\[3.3.2\] - 2026-08-02 - Release: Expanded Model Support, Billing Cycle Tracking, and Health Telemetry](#332---2026-08-02---release-expanded-model-support-billing-cycle-tracking-and-health-telemetry)
  - [\[3.2.5\] - 2026-07-03 - Release: Refresh Now Button, Display Units, and Config Flow Hardening](#325---2026-07-03---release-refresh-now-button-display-units-and-config-flow-hardening)
  - [\[3.2.4\] - 2026-06-15 - Release: Shared CI Validation v2.0.3](#324---2026-06-15---release-shared-ci-validation-v203)
  - [\[3.2.3\] - 2026-06-14 - Maintenance: Shared CodeQL Permissions Alignment for Zizmor](#323---2026-06-14---maintenance-shared-codeql-permissions-alignment-for-zizmor)
  - [\[3.2.2\] - 2026-06-14 - Maintenance: Shared CodeQL Security Scanning](#322---2026-06-14---maintenance-shared-codeql-security-scanning)
  - [\[3.2.1\] - 2026-06-14 - Maintenance: CI Validation Infrastructure Test Release](#321---2026-06-14---maintenance-ci-validation-infrastructure-test-release)
  - [\[3.2.0\] - 2026-05-28 - Release: APN Profile Control, Network Mode Select, and Diagnostic Entities](#320---2026-05-28---release-apn-profile-control-network-mode-select-and-diagnostic-entities)
  - [\[3.1.0\] - 2026-05-24 - Release: SMS Service Actions, Received Bus Events, and Storage Full Repairs](#310---2026-05-24---release-sms-service-actions-received-bus-events-and-storage-full-repairs)
  - [\[3.0.1\] - 2026-05-10 - Maintenance: README Documentation and Standards Alignment](#301---2026-05-10---maintenance-readme-documentation-and-standards-alignment)
  - [\[3.0.0\] - 2026-05-08 - Major Release: Native Async Rewrite, Sub-Device Architecture, and IMEI Identity](#300---2026-05-08---major-release-native-async-rewrite-sub-device-architecture-and-imei-identity)
  - [\[2.3.1\] - 2026-04-01 - Release: DataUpdateCoordinator Migration and HACS Branding Assets](#231---2026-04-01---release-dataupdatecoordinator-migration-and-hacs-branding-assets)
  - [\[2.1.1\] - 2026-03-29 - Maintenance: Diagnostic Error Logging](#211---2026-03-29---maintenance-diagnostic-error-logging)
  - [\[2.0.1\] - 2026-03-29 - Feature: Options Flow for Dynamic Reconfiguration](#201---2026-03-29---feature-options-flow-for-dynamic-reconfiguration)
  - [\[1.9.4\] - 2026-03-29 - Feature: Hardware Model Reading and Session Management](#194---2026-03-29---feature-hardware-model-reading-and-session-management)
  - [\[1.7.3\] - 2026-03-29 - Maintenance: Standardized Entity Naming](#173---2026-03-29---maintenance-standardized-entity-naming)
  - [\[1.6.3\] - 2026-03-28 - Maintenance: Non-Blocking Async Startup for Offline Routers](#163---2026-03-28---maintenance-non-blocking-async-startup-for-offline-routers)
  - [\[1.5.7\] - 2026-03-28 - UI: ZTE Brand Icons and Sub-Device Sensor Naming](#157---2026-03-28---ui-zte-brand-icons-and-sub-device-sensor-naming)
  - [\[1.5.1\] - 2026-03-28 - Maintenance: Home Assistant Integration Naming Alignment](#151---2026-03-28---maintenance-home-assistant-integration-naming-alignment)
  - [\[1.4.5\] - 2026-03-28 - Documentation: Local Changelog Addition and Standard Sensor Names](#145---2026-03-28---documentation-local-changelog-addition-and-standard-sensor-names)
  - [\[1.4.4\] - 2026-03-28 - Telemetry: Router Attribute Exposure as Entities](#144---2026-03-28---telemetry-router-attribute-exposure-as-entities)
  - [\[1.4.3\] - 2026-03-28 - Controls: Pause Polling Switch and Polling Interval Number Entity](#143---2026-03-28---controls-pause-polling-switch-and-polling-interval-number-entity)
  - [\[1.4.2\] - 2026-03-27 - Feature: SMS Inbox Monitoring and Initial GitHub Release](#142---2026-03-27---feature-sms-inbox-monitoring-and-initial-github-release)
  - [\[1.4.0\] - 2026-03-26 - Telemetry: Core Signal and Cellular Data Sensors](#140---2026-03-26---telemetry-core-signal-and-cellular-data-sensors)
  - [\[1.3.6\] - 2026-03-25 - Initial Release: Custom Component for ZTE MC7010](#136---2026-03-25---initial-release-custom-component-for-zte-mc7010)

---
