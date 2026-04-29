# Development & Architecture Notes: ZTE Router 5G Monitor

## 1. Project Objective

To develop a high-performance Home Assistant custom component for monitoring and managing ZTE 5G Routers (MC801, MC888, MC7010, MC889 series). The integration leverages the router's internal `goform` API to extract signal metrics (RSRP, RSRQ, SNR), data usage, and SMS management features into the Home Assistant ecosystem.

## 2. Architecture & File Structure

The integration follows the standard Home Assistant Custom Component pattern, optimized for asynchronous performance.

### Core Files (`custom_components/zte_router_5g/`)

- **`api.py`**: Async wrapper for the router's internal `goform` API using `aiohttp`. Handles Z-hashed authentication, hex decoding, and protocol detection (HTTP/HTTPS).
- **`coordinator.py`**: Specialized `DataUpdateCoordinator` implementation. Centralizes polling logic to ensure only one API call is made per refresh interval, distributing data to all entities. Includes retry logic and "Pause Polling" detection.
- **`__init__.py`**: Manages the integration lifecycle (setup/unload). Also handles background initialization to prevent blocking HA startup.
- **`sensor.py`**: Extracts technical metrics using declarative `value_fn` callbacks and handles transformations (e.g., Bytes to GB, Uptime to ISO Datetime).
- **`binary_sensor.py`**: Maps boolean states (e.g., `best_connection` logic).
- **`switch.py`**: Implements "Pause Polling" to stop API calls without disabling the integration, allowing temporary exclusive access to the router WebUI.
- **`button.py`**: Triggers stateless actions (Reboot, Delete All SMS).
- **`number.py`**: Provides UI control over the `DataUpdateCoordinator` refresh interval with persistent storage in `ConfigEntry` options.
- **`config_flow.py`**: Manages initial setup and reconfiguration via `OptionsFlow`, storing credentials in `entry.options`.

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
- **Stable Identity Strategy**: Using hardcoded internal keys (e.g., `z5g_rsrp`) combined with the MAC address for `unique_id`, rather than relying on friendly names. This ensures entity settings (icons, hidden status) survive renames or firmware updates.
- **Declarative Entities**: Using a `value_fn` lambda in `EntityDescription` allows for a completely generic entity class. This makes adding new sensors a "data entry" task rather than a coding task.
- **Data Integrity (Guard Bands)**: Validating sensor values against realistic boundaries (e.g., -140 to -30 for RSRP) before committing them to the state machine. This ensures that transient API artifacts or hardware glitches don't trigger false automation states or corrupt historical graphs.
- **Flat Identity Pattern**: By storing Model, Version, and MAC in `entry.data` and loading them into the coordinator at `__init__`, the integration provides stable metadata to the UI instantly at boot, even if the hardware is offline.

## 5. Technical Pitfalls & Fixes

- **ConfigEntry Data vs. Options**: In this integration, `entry.options` is used for user-changeable settings (credentials, polling interval), while `entry.data` is reserved for immutable hardware metadata (Model, MAC, Version).
  - _Fix_: Standardized all platforms to initialize from `entry.data` and update via `hass.config_entries.async_update_entry` only when hardware changes are detected.
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

## 6. Environment Constraints

- **Native Async API**: The integration uses `aiohttp` for all network communication, aligning with the Home Assistant event loop. This removes the need for `executor_job` threading and eliminates the maintenance burden of pinning external libraries like `requests`.
- **SSL Verification**: Local routers typically use self-signed certificates. The `ZTERouterAPI` uses `ssl=False` in its `aiohttp` calls to maintain connectivity.
- **Shared Session**: The integration uses `async_get_clientsession(hass)` to leverage Home Assistant's optimized, shared connection pool.

## 7. Technical Debt & Future Work

- **Token Persistence**: Currently, the `stok` (Session Token) is stored in memory. A fresh login is required on every integration restart.
- **SMS Page Limits**: The `delete_all` feature is limited to the first 500 messages to avoid API timeouts.
- **Service Integration**: Evaluate implementing a `send_sms` service to match the TP-Link integration's capability if the ZTE API supports it.
