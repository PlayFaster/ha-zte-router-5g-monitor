# Development & Architecture Notes: ZTE Router 5G Monitor

## 1. Project Objective

To develop a high-performance Home Assistant custom component for monitoring and managing ZTE 5G Routers (MC801, MC888, MC7010, MC889 series). The integration leverages the router's internal `goform` API to extract signal metrics (RSRP, RSRQ, SNR), data usage, and SMS management features into the Home Assistant ecosystem. The primary reference for discovering all available API data parameters and commands exposed by the router's firmware is the internal Web UI JavaScript source file `js/service.js`.

## 2. Architecture & File Structure

The integration follows the standard Home Assistant Custom Component pattern, optimized for asynchronous performance.

### Core Files (`custom_components/zte_router_5g/`)

- **`api.py`**: Async wrapper for the router's internal `goform` API using `aiohttp`. Handles Z-hashed authentication, hex decoding, and protocol detection (HTTP/HTTPS).
- **`coordinator.py`**: Specialized `DataUpdateCoordinator` implementation. Centralizes polling logic to ensure only one API call is made per refresh interval, distributing data to all entities. Includes retry logic, "Pause Polling" detection, and device registry updates for hardware metadata changes.
- **`helpers.py`**: Shared helper functions (`get_router_model`, `build_device_info` for sub-device grouping).
- **`__init__.py`**: Manages the integration lifecycle (setup/unload). Also handles background initialization to prevent blocking HA startup.
- **`sensor.py`**: Extracts technical metrics using declarative `value_fn` callbacks and handles transformations (e.g., Bytes to GB, Uptime to ISO Datetime).
- **`binary_sensor.py`**: Maps boolean states (e.g., `best_connection` logic).
- **`switch.py`**: Implements "Pause Polling" to stop API calls without disabling the integration, allowing temporary exclusive access to the router WebUI.
- **`button.py`**: Triggers stateless actions (Refresh Now, Reboot, Delete All SMS). "Refresh Now" forces an immediate coordinator poll via `async_request_refresh()`, complementing the Pause Polling switch and the configurable polling interval.
- **`number.py`**: Provides UI control over the `DataUpdateCoordinator` refresh interval with persistent storage in `ConfigEntry` options.
- **`config_flow.py`**: Manages initial setup and reconfiguration via `OptionsFlow`, storing credentials in `entry.options`. Normalises the host input (`_clean_host`) before storage, and on edit screens leaves credential fields blank (masked, never pre-filled) — restoring the stored password on a blank submit via `_merge_credentials`, so the password can be re-set without ever being displayed.

## 3. Historical Architectural Shifts

To reach its current "modern" state, the project underwent several major refactors:

### From Monolithic to Orchestrated (v2.2.4 -> v2.3.1)

- **Initial State**: All data fetching and coordination logic resided within `__init__.py`.
- **Change**: Extracted fetching logic into a dedicated `coordinator.py`.
- **Result**: Improved separation of concerns, where `__init__.py` handles lifecycle and `coordinator.py` handles data. This aligned the project with Home Assistant's professional development standards.

### From Synchronous to Native Async (v2.3.1 -> v3.0.0)

- **Initial State**: Used the `requests` library, which is synchronous and blocking. This required wrapping every API call in `hass.async_add_executor_job` to avoid stalling the HA event loop.
- **Change**: Migrated the entire API layer to `aiohttp`.
- **Result**: Native asynchronous execution. Removed the overhead of thread-switching, simplified the code by removing executor wrappers, and eliminated the need to pin and maintain the `requests` dependency in `manifest.json`.

### Python Standards & Strict Linting (v3.0.0)

- **Standard**: Adherence to PEP8 naming conventions and `pydocstyle` requirements.
- **Change**: Renamed internal API methods (e.g., `get_LD` to `get_ld`) and enabled strict linting (`N`, `D`) in `pyproject.toml`.
- **Result**: Improved codebase maintainability and alignment with Home Assistant's core coding standards.

### Architectural Synchronization & Declarative Refactor (v3.0.0)

- **Initial State**: Imperative `if/elif` blocks in sensors and manual retry loops in the coordinator.
- **Change**: Refactored the entity engine to use **Declarative Callbacks** (`value_fn`). Standardized on the **Flat Identity Pattern** (loading hardware info from `entry.data` at boot). Unified background tasks using `entry.async_create_background_task`.
- **Result**: **100% architectural parity** with the TP-Link and WiFi Monitor integrations. Massive reduction in boilerplate code and improved reliability through native HA lifecycle management.

- **Standardized Resilience (v3.0.0)**: Aligned the Data Update Coordinator with the "PlayFaster" architectural standards. Increased the failure threshold to 3 cycles and synchronized warning logs. The coordinator now holds last known values for up to 3 consecutive failures before reporting "Unavailable", ensuring stable sensor data during brief API interruptions.
- **Custom User Naming (v3.0.0)**: Implemented global name prefixing using `CONF_NAME`. Users can define a custom string (e.g., "Guest Gateway") that is prepended to every device and entity, allowing for multiple instances to be clearly distinguished in the UI without technical entity ID conflicts.
- **Declarative Guard Bands (v3.0.0)**: Implemented "Standard 4" data integrity validation. Technical sensors (Signal Strength, SNR, Signal Bar, and SMS counts) now utilize declarative `min_limit` and `max_limit` boundaries to filter out transient hardware reporting spikes, preventing dashboard corruption.

### Sub-Device Architecture & Standards Alignment (v3.0.0)

- **Initial State**: All entities were grouped under a single monolithic "ZTE Router" device. Data volume was reported in GB (legacy), and signal units were inconsistent.
- **Change**: Refactored the entity engine to support **Sub-Device Grouping** (System, Signal, Data, SMS). Aligned volume sensors with Home Assistant's `DATA_SIZE` standard (Bytes) and normalized signal metrics (RSRP/RSSI in dBm; RSRQ/SNR/SINR in dB).
- **Result**: Improved UI organization in the Device Registry and full compatibility with Home Assistant's native unit conversion and dashboarding features. Enhanced `unique_id` stability by using lowercase internal keys (e.g., `z5g_rsrp`).

## 4. Success Patterns

- **`DataUpdateCoordinator`**: Essential for preventing the router from being overwhelmed by simultaneous requests. Using `coordinator.async_request_refresh()` for write actions ensures immediate UI feedback.
- **Sub-device Grouping**: Automatically routing entities to logical sub-devices (Signal, SMS, Data) via the `group` attribute in `EntityDescription`. This prevents "entity fatigue" in the main device view.
- **Stable Identity Strategy**: Using hardcoded internal keys (e.g., `z5g_rsrp`) combined with the IMEI (or `host_{IP}` fallback) for `unique_id`, rather than relying on friendly names or the host IP. IMEI is hardware-bound and survives IP changes, SIM swaps, and firmware updates. This ensures entity settings (icons, hidden status) survive renames or router reconfiguration.
- **Shared `build_device_info()` Helper**: All five platform files (`sensor.py`, `binary_sensor.py`, `button.py`, `switch.py`, `number.py`) delegate `device_info` to a single shared function in `helpers.py`. This eliminates the 5-way copy-paste drift and ensures identifiers, naming, manufacturer, model, version, and `configuration_url` (using the detected protocol) are always consistent. Adding a new platform requires no `device_info` boilerplate.
- **Translation-Based Naming**: Sensors use `translation_key="<key>"` instead of hardcoded `name="..."`. This makes `strings.json` the canonical display-name source, enables multi-language support, and ensures display names can be changed without redeploying the integration code.
- **Icon Translations (`icons.json`)**: Declare entity icons centrally in `icons.json` rather than hardcoding an `icon` property on entity classes. State-dependent icons use `"state": {"on": "mdi:...", "off": "mdi:..."}` syntax. This keeps Python classes free of display-layer concerns and allows HA to resolve the correct icon without a code redeploy. The `icon` property on the entity class becomes unnecessary and should be removed.
- **Repair Issues for Persistent States**: Use `ir.async_create_issue` / `ir.async_delete_issue` (from `homeassistant.helpers.issue_registry`) inside the coordinator's success path for conditions requiring deliberate user intervention (e.g., SMS storage full). Call the check on every successful poll — the create/delete calls are idempotent. The issue is surfaced in HA's Repairs panel with a translated title and description. Provide a `translation_key` matching an entry in `strings.json` → `issues` → `<key>`.
- **Declarative Entities**: Using a `value_fn` lambda in `EntityDescription` allows for a completely generic entity class. This makes adding new sensors a "data entry" task rather than a coding task.
- **Data Integrity (Guard Bands)**: Validating sensor values against realistic boundaries (e.g., -140 to -30 for RSRP) before committing them to the state machine. This ensures that transient API artifacts or hardware glitches don't trigger false automation states or corrupt historical graphs.
- **Flat Identity Pattern**: By storing Model, Version, and IMEI in `entry.data` and loading them into the coordinator at `__init__`, the integration provides stable metadata to the UI instantly at boot, even if the hardware is offline.
- **Setting Modification & immediate UI refresh (Select/Switch)**: When executing setting changes (such as default APN profile switching, network mode selections, or toggling ODU LED switches), the entity performs the async API request, and then immediately triggers `await self.coordinator.async_request_refresh()`. This forces a poll cycle instantly so the new setting values are fetched from the router and reflected in the Home Assistant UI without waiting for the next scheduled update.
- **Explicit Coordinator `config_entry` (HA polling option)**: Pass `config_entry=entry` to `DataUpdateCoordinator.__init__`. HA core's `_schedule_refresh()` reads `self.config_entry.pref_disable_polling` — the flag behind the "Enable polling for changes" system option — and skips arming the next timer when it's OFF (manual `update_entity` / "Refresh Now" still fetch, since those go through `async_request_refresh` which ignores the flag). Passing the entry explicitly is also required going forward: HA deprecated implicit `ContextVar` detection and reports it as an error from **2026.8** (the `config_entry` argument itself dates from **2024.8**, hence the minimum-HA bump). This is orthogonal to the custom "Pause Polling" switch (`CONF_STOP_POLLING`), which short-circuits `_async_update_data` to cached data for *all* triggers to free the router's single login session. Full write-up: `.shared/info/sys_options_enable_polling.md`.
- **Suggested Display Units & Precision**: Keep sensors in their **canonical native unit** (`BYTES`, `BYTES_PER_SECOND`, `SECONDS`, `MHz`, `dBm`) so long-term statistics and guard-band limits stay unit-stable, then add `suggested_unit_of_measurement` / `suggested_display_precision` to control the **display** only — HA stores/accumulates the native value and renders in the suggested unit (the user can still override per-entity). Applied mapping: data size `BYTES`→`GIGABYTES` (precision 1 monthly, 2 session); data rate `BYTES_PER_SECOND`→`MEGABITS_PER_SECOND` (precision 2); duration `SECONDS`→`HOURS` (precision 1); MHz bandwidth and dBm signal strength → precision 0 (no unit change). **Gotcha**: `suggested_unit_of_measurement` must be in the same HA unit class as the native unit or HA silently ignores it; when only precision changes, omit the suggested unit entirely. This is preferred over the legacy `_get_bytes_to_gb` value-fn conversion sensors (which pre-scale in Python and can't be re-based for statistics). See `shared/SharedNotes/dev_std/dev_standards.md` Section 5.

## 5. Technical Pitfalls & Fixes

- **ConfigEntry Data vs. Options**: In this integration, `entry.options` is used for user-changeable settings (credentials, polling interval), while `entry.data` is reserved for immutable hardware metadata (Model, IMEI, Version).
  - _Fix_: Standardized all platforms to initialize from `entry.data`. Hardware metadata changes detected mid-poll are propagated via the device registry (`device_registry.async_update_device`) rather than rewriting `entry.data`, avoiding unnecessary disk writes and maintaining the principle that `entry.data` is immutable after initial setup.
- **MockConfigEntry Immutability**: In Home Assistant tests, `MockConfigEntry.options` is a frozen property. Attempting to update it directly via `entry.options = {...}` fails with an `AttributeError`.
  - _Fix_: Use `object.__setattr__(entry, "options", new_options)` in test code to bypass the frozen attribute restriction.
- **Background Task Mocking**: When `hass.async_create_task` is mocked, tasks created via `entry.async_create_background_task` may not execute, leading to `RuntimeWarning: coroutine was never awaited`.
  - _Fix_: In `conftest.py`, ensure the background task mock explicitly schedules the coroutine via `asyncio.create_task` and that the test awaits `hass.async_block_till_done()`.
- **Manual Sleep in Coordinators**: Sleeping inside `_async_update_data` blocks the coordinator task and delays other integrations.
  - _Fix_: Removed `asyncio.sleep` retries. Use `asyncio.timeout` and raise `UpdateFailed` to let HA handle backoffs.
- **Background Task Orphaning**: Standard `hass.async_create_task` is not tracked by the entry.
  - _Fix_: Migrated to `entry.async_create_background_task` for automatic cleanup on unload.
- **MappingProxy TypeError**: In unit tests, `ZTEConfigFlow().context` is a read-only `mappingproxy`.
  - _Fix_: Explicitly set `flow.context = {}` in test setups.
- **Translation Key Synchronization (Hassfest)**: When using `translation_key` in entity descriptions, Home Assistant (via `hassfest`) requires that these keys exist in both `strings.json` and all `translations/*.json` files. Furthermore, `strings.json` must be free of duplicate keys (e.g., accidental duplicate `reauth` blocks).
  - _Fix_: Consolidated duplicate `reauth` keys and performed a full audit to ensure every `translation_key` used in platform files has a corresponding entry in both translation source files.
- **Stale Icon Assertions after `icons.json` Migration**: When entity `icon` properties are removed in favour of `icons.json` declarations, any existing `assert sensor.icon == "mdi:..."` test assertions silently regress — the property returns `None` rather than raising. This is easy to miss because the test file itself is not touched during the migration.
  - _Fix_: Remove the stale `assert sensor.icon` lines. Icon correctness is validated via `hassfest` linting of `icons.json`, not by entity unit tests.
- **Centralized `_request()` API Client Wrapper**: Having duplicate logic for checking `stok`, verifying redirects, checking Content-Type text/html, and handling session re-authentication across all endpoints leads to code drift and bugs (e.g. SMS polling dropping).
  - _Fix_: Implemented a centralized async `_request()` helper in `api.py` to route all calls. The helper extracts and validates responses, logs HTML redirects, and transparently attempts a single login retry upon session expiry.
- **Uptime Boot-Timestamp Drift**: The naive `boot_time = now() − uptime_seconds` calculation ties the result to two independently ticking clocks (HA wall clock and the router's internal counter). Small, continuous rate divergence causes the computed boot time to drift by several minutes over hours or days with no actual restart. Truncating to the nearest minute converts drift into periodic 60-second jumps. A timestamp-delta tolerance latch (e.g. ±30 s) suppresses small jitter but not monotonic clock-rate divergence — once accumulated drift exceeds the threshold, the latch re-trips and steps the value, and the steps accumulate.
  - _Fix_: Reboot-detection latch (`coordinator.py`). The boot instant is physically constant between reboots, so compute it once and freeze it. Re-derive `boot_time` only when the router's uptime counter drops by more than `UPTIME_REBOOT_MARGIN` (30 s) — a comparison of uptime-to-uptime that is immune to clock-rate divergence. A bad-reading guard ensures missing or unparsable `realtime_time` readings leave the latched value untouched. `last_uptime` is persisted alongside `boot_time` in `entry.data` as the reboot-detection anchor, surviving HA restarts. See `.notes/issues/` for full strategy and rejected alternatives.
- **Reauth Loops on Transient Dropped Connections**: If the coordinator raises `ZTEAuthError` on transient failures, Home Assistant triggers an options reconfiguration flow immediately.
  - _Fix_: Classified login/polling errors. Raise `ZTEAuthError` only on explicit credential error codes returned from the API (`password_error`, `invalid_password`, `unauth`). Hold last known values for up to 3 consecutive poll cycles on connection errors before declaring failure.
- **Cookie Jar Cleardown Side-Effects**: Domain-based cookie clearing can have unexpected effects when multiple integrations run in the same container.
  - _Fix_: Refined cookie jar cleanup in `api.py` to target only the `stok` cookie using a predicate lambda check: `self.session.cookie_jar.clear(predicate=lambda m: m.key == "stok")`.
- **IP Host Input Prefix Scheme Issues**: Users entering URL scheme prefixes (like `http://` or `https://`) or trailing slashes in the config flow IP field cause malformed paths when endpoints build host URLs dynamically.
  - _Fix_: Cleaned the incoming host input string in `ZTERouterAPI.__init__` by stripping out any scheme prefixes and trailing slashes.
- **Doubled `configuration_url` from Stored Host Scheme**: `ZTERouterAPI` strips scheme prefixes at runtime, but the config flow previously stored the **raw** host value in `entry.options`. Because `__init__.py` builds the device link as `configuration_url=f"http://{host}"`, storing `http://192.168.0.1` produced `http://http://192.168.0.1` — an invalid link — and left the stored host inconsistent with what the API actually connected to.
  - _Fix_: Added `_clean_host()` to `config_flow.py` and applied it at the top of all four steps (user, reconfigure, reauth, options) so only the bare host is ever persisted, independent of the API-layer cleaning. This is a PlayFaster standard — see `shared/SharedNotes/dev_std/dev_standards.md` Section 9.
- **Stored Password Exposed on Reconfigure**: Pre-filling the password field from `entry.options` on the Reconfigure/Options screens meant the stored secret was sent to the browser as a masked value — and could be revealed with the UI eye icon.
  - _Fix_: Split the config-flow schema into `_user_schema` (setup) and `_edit_schema` (edit). Edit screens use a masked `TextSelector` (`TextSelectorType.PASSWORD`) and leave the password blank; `_merge_credentials()` restores the stored value on a blank submit, so the field can re-set the password without ever displaying it. A `data_description` under the field tells the user "Leave blank to keep the current password." See `shared/SharedNotes/dev_std/dev_standards.md` Section 9.
- **HA ConfigFlow Type Stub Incompatibility (mypy `--strict`)**: Home Assistant's type stubs define `ConfigFlow` step methods as returning `ConfigFlowResult`, but the `FlowResult` type (imported from `homeassistant.data_entry_flow`) is what the integration code uses and what older HA versions expose. Under mypy `--strict`, this produces `[override]` errors on every step method and `[return-value]` errors on every return statement. Naively adding `# type: ignore[return-value]` to each return triggers a cascade of `[unused-ignore]` errors because mypy resolves the conflict inconsistently depending on which HA stubs are active.
  - _Fix_: Apply `# type: ignore[override]` to each async step method signature (not the class). For return statements that mypy still flags, move the comment to the end of the closing parenthesis line. Accept that a small number of residual errors may remain due to HA stub version drift — they do not affect runtime behaviour. `MappingProxyType` argument mismatches (e.g. passing `entry.options` to a `dict[str, Any]` parameter) are resolved by wrapping with `dict()` at the call site.
- **ZTE SMS API Requirements**: Interfacing with the ZTE router SMS API requires specific encoding and security handling:
  - _Message Encoding_: Messages must be hex-encoded using UTF-16BE format (`encode("utf-16-be").hex()`). If not encoded, characters will be garbled or rejected by the modem.
  - _Recipient Numbers_: Phone numbers must be URL-escaped.
  - _Timestamp format_: The router demands a semicolon-delimited date-time string of the format `yy;mm;dd;HH;MM;SS;+0` matching the time the message is sent.
  - _AD Security Parameter_: State-changing actions (like reboot, send_sms, delete_sms) must pass an `AD` security parameter. This is dynamically generated by hashing (SHA256 in uppercase for newer MC888/MC889 modems, MD5 for older ones like MC7010) the router version string combined with a transient `RD` value fetched from the router API.
  - _Bulk/Partial Deletions_: Bulk deletion is optimized by passing a semicolon-joined string of IDs (e.g. `"1;2;3"`) to the `msg_id` parameter of `DELETE_SMS`, allowing the integration to delete multiple messages in a single POST request rather than making sequential calls.
- **SMS Received Event Firing**: To fire events when a new SMS is received without missing intermediate messages or double-firing existing ones:
  - _List Polling instead of Last SMS_: The coordinator polls the local inbox (up to 500 messages) via `self.api.get_sms_messages` on every update cycle. The latest message in the list is used to populate `data["last_sms"]` for the `msg_recent` sensor, eliminating the need for a separate `get_last_sms_content` API request.
  - _Chronological Firing & Baseline_: On the first coordinator poll, we establish a baseline (`self.last_sms_timestamp` and a set of `self.fired_sms_hashes` of baseline messages) to prevent historic messages from firing events on startup. On subsequent polls, we identify messages newer than the baseline timestamp or sharing the baseline timestamp but not seen in the hash set, sorting them chronologically to fire bus events in the correct order.
- **Silent SMS Emptiness on Session Timeout**: On ZTE routers, if a POST query to `sms_data_total` (for reading messages) is made with an expired or invalid session, the router does not return an error code or redirect. Instead, it silently returns a valid empty structure (e.g., `{"messages": []}`). Because the SMS response does not contain the standard status fields (`network_type`/`signalbar`), the client cannot detect session expiration from the JSON response structure alone. Thus, the client returns the empty list successfully, and the caller never realizes it was logged out, resulting in a silent failure returning no SMS messages.
  - _Fix_: Implemented an inactivity timer check inside the centralized `_request()` wrapper. If more than 150 seconds (2.5 minutes) elapse without authenticated request activity, the stored session token (`self.stok`) is proactively cleared. This forces a fresh login and session-activating GET request before sending the next API request.

- **VS16 Compound Emoji in README Headings (2026-06-08)**: Using VS16 compound emoji (e.g., `⚙️`, `🏗️`, `⚠️`, `🗑️`) in README headings causes Table of Contents links to silently 404. GitHub's anchor generator strips VS16 bytes (U+FE0F) when computing heading slugs, but Markdown tooling includes them in `href` values. The mismatch is completely invisible in source editors — the heading renders fine and GitHub preview looks correct, but clicking a ToC link jumps nowhere.
  - _Fix_: Replace all VS16 compound emoji in headings and their corresponding ToC `href` values with always-colour single-codepoint alternatives (e.g., 🔧 🔩 ❌ ❗ 🔄 💬). See root `CLAUDE.md` → "Shared Markdown Notes" for the full replacement table and detection script.

## 6. Environment Constraints

- **Native Async API**: The integration uses `aiohttp` for all network communication, aligning with the Home Assistant event loop. This removes the need for `executor_job` threading and eliminates the maintenance burden of pinning external libraries like `requests`.
- **SSL Verification**: Local routers typically use self-signed certificates. The `ZTERouterAPI` uses `ssl=False` in its `aiohttp` calls to maintain connectivity.
- **Shared Session**: The integration uses `async_get_clientsession(hass)` to leverage Home Assistant's optimized, shared connection pool.

## 7. Technical Debt & Future Work

- **Token Persistence**: Currently, the `stok` (Session Token) is stored in memory. A fresh login is required on every integration restart.
- **Translation-Key Naming**: When migrating from `name="..."` to `translation_key="..."`, both `strings.json` and `translations/en.json` must be kept in sync. `strings.json` is the authoritative source; `translations/en.json` is the runtime-loaded file. Adding a sensor requires adding entries to both files, not just the Python code.
- **Device Registry Lookup for Metadata Updates**: When the coordinator detects hardware metadata changes (model, firmware version), it looks up the system device by identifier `(DOMAIN, f"{sub_id_prefix}_system")` in the device registry. This avoids needing to pass device IDs around but requires that the device was already created by an entity's `device_info` property in a previous update cycle. If the device doesn't exist yet (first poll), the update is safely skipped.

- **SMS Page Limits**: The `delete_all` feature is limited to the first 500 messages to avoid API timeouts.
- **Service Integration**: Evaluate implementing a `send_sms` service to match the TP-Link integration's capability if the ZTE API supports it.

---

## Version Control

- **v1.0.1** (2026-05-07) — Added diagnostics platform, reauthentication flow, runtime-data migration, parallel-updates, button exception handling, log-on-unavailability improvements, config-flow data descriptions, and expanded test coverage.
- **v1.0.2** (2026-05-07) — Replaced host-IP unique_id with IMEI-based stable device identity. Added 12 new sensors (System: IMEI, Hardware Version, Battery, SIM IMSI, SIM ICCID; Signal: eNodeB ID, Network Mode, PPP Status; Data: Upload Speed, Download Speed, Session Sent, Session Received). Guard bands applied to Battery (0–100) and throughput/session-byte sensors (min 0). Added sensitive identifiers (imei, sim_imsi, sim_iccid) to diagnostics redaction.
- **v1.0.3** (2026-05-07) — Code review bugfix pass (13 items). Extracted 5-way duplicated `device_info` into shared `build_device_info()` helper. Migrated `configuration_url` to dynamic protocol. Replaced mid-poll `async_update_entry` with device registry updates. Migrated 58 sensor descriptions to `translation_key=` naming. Added `async_will_remove_from_hass` for debounce task cleanup. Added recursion guard to `get_all_data`. Fixed null deref in reauth, Python 2 `except` syntax, `ValueError` escape, bare Exception, `delete_sms()` stok clearing, orphaned test body, and weak type annotation in diagnostics.
- **v1.0.4** (2026-05-08) — Gold Standard README overhaul and Hassfest translation synchronization fix.
- **v1.0.5** (2026-05-08) — Fixed hassfest CI failure caused by invalid top-level `"reauth"` key in both translation files; HA schema requires reauth steps under `config.step.reauth_confirm`, not a standalone `reauth` block. Fixed `{host}` placeholder not resolving in reauth dialog by passing `description_placeholders` to `async_show_form`.
- **v1.0.6** (2026-05-10) — Adopted Option B hierarchical translation pattern and implemented native HA reconfiguration flow.
- **v1.0.7** (2026-05-13) — Implemented `icons.json` icon translations (state-dependent icons, all 51+ entities; `signal_best_connection` on/off icons). Achieved mypy `--strict` 0-error compliance across 12 source files. IQS SCAN=Full pass: corrected 6 stale matrix cells and 10 stale `quality_scale.yaml` entries. Closed all 3 remaining IQS gaps (`icon-translations`, `strict-typing`, `repair-issues`). Added `sms_storage_full` repair issue via `coordinator._check_sms_storage` with translated strings. `zte_router_5g` reaches 46/46 IQS rules DONE — 100% compliance, first project in the PlayFaster family to achieve this.
- **v1.0.8** (2026-05-22) — Implemented centralized `_request` API client wrapper, boot time jitter prevention, login response classification, refined cookie jar clearing, and IP input cleaning.
- **v1.0.9** (2026-05-23) — Documented HA ConfigFlow type stub incompatibility pitfall and `type: ignore[override]` fix pattern for mypy `--strict` compliance.
- **v1.0.10** (2026-05-23) — Documented ZTE SMS API requirements (UTF-16BE encoding, URL-escaping, AD security hashing, and semicolon-concatenated bulk deletions).
- **v1.0.11** (2026-05-23) — Documented SMS received event firing mechanism and chronological baseline tracking.
- **v1.0.12** (2026-05-23) — Replaced stale "Uptime Boot-Timestamp Jitter" pitfall entry with the current reboot-detection latch strategy. Documents root cause (two independent clocks), why truncation and tolerance-latch approaches fail, and the `UPTIME_REBOOT_MARGIN` / bad-reading guard fix.
- **v1.0.13** (2026-05-25) — Documented the silent SMS empty list pitfall, the ZTE POST request login rejection constraint, and the inactivity-timer session reset pattern.
- **v1.0.14** (2026-05-27) — Added setting modification and immediate coordinator refresh pattern for Select and Switch entities. Exceeded entity count to 75.
- **v1.0.15** (2026-05-27) — Documented the router's `js/service.js` as the source of all available API data elements.
- **[2026-06-08]** — Added VS16 compound emoji in README headings pitfall entry.
- **v3.2.5-dev7** (2026-07-02) — Documented config-flow host normalisation (doubled `configuration_url` fix) and the blank/masked password-on-edit pattern (stored secret no longer exposed via the eye icon). Added the "Refresh Now" button (immediate coordinator refresh).
- **v3.2.5-dev8** (2026-07-02) — Added "Suggested Display Units & Precision" success pattern. Applied `suggested_unit_of_measurement` / `suggested_display_precision` to 16 sensors (data size → GB, data rate → Mbit/s, uptime duration → hours, bandwidth/dBm → 0 dp).
- **v3.2.5-dev9** (2026-07-02) — Documented passing `config_entry=entry` to the coordinator (honours the "Enable polling for changes" system option via `pref_disable_polling`; required as HA removes implicit context detection in 2026.8). Minimum HA raised to 2024.8.0.
