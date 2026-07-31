# Changelog

All notable changes to this project will be documented in this file.

## [3.3.2] - 2026-08-01 - Release

### Summary

Wider router support, better data use tracking, SMS improvements, several fixes and a lot of under the hood improvements in this release.

- **Data usage tracking**: the router's own billing cycle, data cap and alert threshold now appear as entities, alongside a new projection of where the current cycle will finish.

- **Wider ZTE model support**: should now have better support for the wider family of ZTE 5G/LTE Routers that use the `goform` API.
  - MC7010, MC801, MC888, MC889, MF266, MF286, MF289

- **SMS improvements**: send the same long messages the router's own web page allows.

- **Action & Settings Fixes**: Fixed issues where Actions (SMS read or send etc.) and Settings Changes (APN, Data Limit switch etc.) could fail silently on long polling intervals.

- **`about` attribute**: Most entities now carry a short built-in explanation of what the value means — and for signal metrics, what counts as good, fair or poor.

- **Integration Health** problem sensor: tells you when the integration is running but the data coming back from the router has issues.

### Added

- **Data usage tracking follows your router's Data Management settings.** If you enable **Data Management** in the router's web page, you can set a **Clear Date** matching your provider's billing day, a **Data Plan** cap, and a **limit reminder** percentage. Those three settings now appear in Home Assistant as **Reset Day**, **Allowance** and **Alert Threshold**. Data use automations can use your router plan numbers — the README has a worked example. Note the router counts in binary units, so a plan it calls "2TB" shows here as about 2199 GB: the same amount, counted the way Home Assistant counts. If you have not set Data Management on the router, the integration falls back to the calendar month.
  - Alongside these, a new **Projected Cycle Usage** sensor estimates how much data you will have used by the end of the cycle, based on your average daily consumption so far. It follows whichever cycle applies — the router's or the calendar month — and reads low on the first day before settling within 24 hours. Its attributes say how much of the figure rests on real usage rather than assumption: `confidence`, `basis`, `cycle_day`, `cycle_start` and `cycle_source`.

- **Integration Health sensor**: a new problem binary sensor on the System device that turns on when the integration detects a problem — including the case where a fetch _succeeds_ but returns nothing usable (which can otherwise be a silent fail, unless you are watching the entities closely). Attributes carry the detail: `issues`, `severity`, `degraded_capabilities`, `drift`, `repairs`, `last_good_update` and `consecutive_failures`.

- **Built-in explanations on entities**: most entities now carry an `about` attribute — a plain sentence saying what the value is. Click the entity, then **⋮ → Details**. Signal metrics also give typical ranges ("better than -80 excellent, -80 to -90 good…"). The note is never written to the history database, to avoid bloat.

- **Router Unreachable repair**: after multiple consecutive failed fetches, a repair appears in the Repairs panel.

- **Seven new entities**, all **disabled by default**: Carrier Aggregation Secondary Cells, WAN Operating Mode, WAN Fallback Mode, Router Timezone, APN Interface Version, Web Page Sleep and Web Page Auto-Wake.
  - This is part of _completeness_. These are included because they are available, and may be of use to some, not necessarily because they contain critical info.

### Changed

- **Longer SMS messages**: `send_sms` now accepts the same message length the router's own web page does — up to **765** characters, where the integration previously capped you at 160. A message containing an emoji, curly quote or other special character uses a different encoding and is limited to **335**, again matching the router. The limit is chosen automatically per message, with nothing to configure, and going over it gives a clear error naming the limit that applied.
  - **Obligatory Warning**: It is _**YOUR**_ responsibility to understand whether having your Router send SMS messages is going to incur an extra charge from your ISP.
    - Remember **longer** messages generally get **billed** as multiple SMS.

- **Wider ZTE model support**: signal and data-usage sensors now recognize the alternative field names used by other `goform` routers, the login falls back to the other form when a model rejects the first, and the LTE/5G band name is worked out from the channel number when the router leaves it blank.

- **Attributes are not written to history**: no entity in this integration records any attribute to the database — only its state. The current state of all Attributes stay visible in the More Info dialog, Developer Tools and templates.

- **Documentation**: the README's example automations now ignore `unknown` and `unavailable` states, to avoid false alerts from a HA restart or router reboot.

- **Icons and branding** refreshed.

### Fixed

- **APN Profile could show a profile that was not in use**: while APN Selection Mode is **Auto** the router uses the routers default APN — but the dropdown still displayed whichever profile was last chosen **manually**. It now shows the profile only when it genuinely matches the APN in use, and blank otherwise. The **Network APN** sensor remains the authoritative answer to which APN is in use.

- **APN Selection Mode could not be set to Manual**: switching it to **Auto** worked, but switching back to **Manual** was silently rejected by the router.
  - Both directions now work. Switching to **Manual** requires the router to be told _which_ stored profile to use, so if the APN currently in use is not one of your saved profiles, the integration asks you to choose one from **APN Profile** instead — which sets the mode and the profile together, in one step.
  - The integration can only **select** among profiles already stored on the router. Creating, editing or deleting an APN profile is done on the router's own web page; a new one appears in the **APN Profile** dropdown at the next poll, or immediately if you press **Refresh Now**.

- **Settings & Actions did not check for login**: If the polling interval was long, Pause Polling was on or the web GUI was used, the integrations login to the router could get dropped.
  - It re-establishes on every new read, but independent activities, e.g. changing settings or running actions, were not properly checking for an active login.
  - This, coupled with problems with some of the setting writes, could result in silent failures and unpredictable behavior.
  - This was also an issue immediately after Router reboot, as that also logged out active sessions.
  - Now addressed across all Actions and Writes (Settings changes), and for Router reboots.

- **Actions Fixes**:
  - re-login if the session has expired
  - confirm the router's action response
  - provide an error message if there is an error
  - update the message counters on SMS send immediately

- **Settings Fixes**:
  - **Data Limit Switch**: This always read the correct state but could fail to set the state, now fixed.
  - **ODU LED Switch**: Could show incorrect state and invalid toggles temporarily after trying to change. Now fixed.
  - **APN Prole & Mode**: Also fixed, see above.

- **Monthly Data counters misclassified**: the monthly upload, download and total sensors were recorded state_class=TOTAL, which is incorrect and can cause issues on reset. This has now been corrected to TOTAL_INCREASING - a resetting counter.

---

## [3.2.5] - 2026-07-03 - Release

### Added

- **Refresh Now Button**: New System button that triggers an immediate data refresh, complementing the existing Pause Polling switch and configurable polling interval

### Changed

- **Display Units & Precision**: 16 sensors now display expected units and decimal places in the UI — data sizes in GB, throughput in Mbit/s, uptime duration in hours, and rounded signal-strength/bandwidth values. Underlying native values (used for long-term statistics) are unchanged.
- **SMS Actions Default to the Sole Router**: The `delete_sms`, `delete_all_sms`, and `get_sms_list` actions no longer require `entry_id`. When exactly one router is configured it is selected automatically; with more than one configured, `entry_id` is required and omitting it now raises a clear "specify entry_id".
- **Polling Toggle Future Ready**: Turning off "Enable polling for changes" in the entry's system options now reliably stops scheduled polling and will satisfy the upcoming HA requirement (implicit `ContextVar` detection is being removed in HA 2026.8).
- **Minimum Home Assistant Version**: Documented minimum raised to 2024.8.0 (driven by polling option change above, this was added to HA in 2024.8)

### Fixed

- **Password No Longer Pre-filled on Edit Screens**: On Reconfigure, Options, and Reauth, the password field is now masked and left blank — the stored value is never pre-filled or revealable. Leave it blank to keep the current password, or enter a new one to change it.
- **Doubled Device URL**: A full URL or trailing slash entered in the Host field is now stripped before storage, preventing a malformed device link (e.g. `http://http://192.168.0.1`).

## [3.2.4] - 2026-06-15 - Release

### Changed

- **CI Validation Bump**: Shared CI validation bumped to v2.0.3. No user changes in this release, background/infrastructure only.

## [3.2.3] - 2026-06-14

### Summary

- **CI Validation Only**: Changes to the CI Validation set-up require another release to test properly, but there are no user changes in this release, background/infrastructure only.

## [3.2.2] - 2026-06-14

### Summary

- **CI Validation Only**: Changes to the CI Validation set-up require another release to test properly, but there are no user changes in this release, background/infrastructure only.

## [3.2.1] - 2026-06-14

### Summary

- **CI Validation Only**: Changes to the CI Validation set-up require a release to test properly, but there are no user changes in this release, background/infrastructure only.

## [3.2.0] - 2026-05-28

### Added

- **New Sensors**: Added several new entities, the most useful of which is a select for **APN Profile**. Changing APN can be as or more effective than rebooting to restore 5G signal that has dropped to 4G (+ or LTE) only. New entities are:
  - **APN Control Selects**: Added select entities for switching active APN profiles (`apn_profile`) and toggling between automatic/manual APN mode (`apn_mode`).
  - **Network Mode Select**: Added carrier network preference selection (`net_select_mode`) to choose between Auto (4G/5G), 5G NSA, 5G SA, and 4G Only.
  - **ODU LED Control Switch**: Added a switch (`odu_led_switch`) to toggle the physical outdoor unit status LEDs.
  - **Data Limit Control Switch**: Added a switch (`data_limit_switch`) to toggle data limit enforcement on the router.
  - **Reboot Schedule & Security Binary Sensors**: Added binary sensors to monitor Reboot Schedule, UPnP status, and SIP ALG status.
  - **New Diagnostic Sensors**: Added sensors for LTE Band Lock Mask, Data Volume Alert %, and SNTP Time Server.

### Changed

- **Database Cleanup (Reduced LTS)**: Removed long-term statistics tracking from 8 non-critical sensors (realtime throughput, uptime duration, etc.) to prevent database bloat.

### Fixed

- **Centralized Session Stability**: central request helper now resets expired tokens proactively, preventing transient authentication errors and empty sensor states.

## [3.1.0] - 2026-05-24

### Added

- **SMS Services**: Four new Home Assistant actions — `send_sms`, `delete_sms`, `delete_all_sms`, and `get_sms_list` — for full SMS management from automations and scripts.
- **SMS Received Event**: Integration now fires a `zte_router_5g_sms_received` event when a new SMS arrives, enabling event-triggered automations.
- **SMS Storage Full Repair**: A repair issue is raised in the HA Repairs panel when NV SMS storage reaches capacity; it clears automatically when resolved.
- **Uptime Duration Sensor**: New sensor reporting how long the router has been running (disabled by default).
- **State-Dependent Entity Icons**: Entity icons now reflect live state (e.g. Best Connection sensor shows an active signal icon when connected).

### Changed

- **Flexible Host Input**: The host field now accepts addresses with `http://` or `https://` prefixes; they are stripped automatically during setup and reconfiguration.

### Fixed

- **Stable Uptime Timestamp**: Boot time is now latched once and only re-derived when the router's uptime counter drops — the only reliable reboot signal. Bad or missing uptime readings leave the cached value untouched, eliminating timestamp drift caused by independently ticking clocks.
- **Empty Sensor Values**: Sensors receiving an empty string from the router now correctly report **Unknown** state in HA instead of displaying a blank value.
- **Spurious Reauthentication**: Transient connection drops and network errors no longer incorrectly trigger the reauthentication flow; reauth is reserved for explicit credential rejection from the router.
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
- **Reauthentication Support**: If your router password changes, Home Assistant will now notify you and provide a simple dialog to update your credentials without needing to re-install the integration.
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
