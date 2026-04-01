# Development & Architecture Notes: ZTE Router 5G Monitor

## 1. Project Objective
To develop a high-performance Home Assistant custom component for monitoring and managing ZTE 5G Routers (MC801, MC888, MC7010, MC889 series). The integration leverages the router's internal `goform` API to extract signal metrics (RSRP, RSRQ, SNR), data usage, and SMS management features into the Home Assistant ecosystem.

## 2. Architecture & File Structure
The integration follows the standard Home Assistant Custom Component pattern, optimized for asynchronous performance.

### Core Files (`custom_components/zte_router_5g/`)
- **`api.py`**: Low-level wrapper for `requests.Session`. Handles Z-hashed authentication, hex decoding, and protocol detection (HTTP/HTTPS).
- **`__init__.py`**: Implements the `DataUpdateCoordinator`. Centralizes polling logic to ensure only one API call is made per refresh interval, distributing data to all entities. Also handles background initialization to prevent blocking HA startup.
- **`sensor.py`**: Extracts technical metrics and handles transformations (e.g., Bytes to GB, Uptime to ISO Datetime).
- **`binary_sensor.py`**: Maps boolean states (e.g., `best_connection` logic).
- **`switch.py`**: Implements "Pause Polling" to stop API calls without disabling the integration, allowing temporary exclusive access to the router WebUI.
- **`button.py`**: Triggers stateless actions (Reboot, Delete All SMS).
- **`number.py`**: Provides UI control over the `DataUpdateCoordinator` refresh interval with persistent storage in `ConfigEntry` options.
- **`config_flow.py`**: Manages initial setup and reconfiguration via `OptionsFlow`, storing credentials in `entry.options`.

## 3. Success Patterns
- **`DataUpdateCoordinator`**: Essential for preventing the router from being overwhelmed by simultaneous requests. Using `coordinator.async_request_refresh()` for write actions ensures immediate UI feedback.
- **Protocol Discovery**: The `api.try_set_protocol` method identifies whether a router is on HTTP or HTTPS by attempting short-timeout requests before authentication.
- **Background Safety**: Connection and login are offloaded to a background task in `async_setup_entry` to ensure Home Assistant starts quickly even if the router is slow to respond.
- **Single-Domain Discovery**: Configuring `hacs.json` to be minimal allows HACS to automatically discover the domain and class from the `manifest.json`.

## 4. Technical Pitfalls & Fixes
- **Catching `AbortFlow`**: Using a generic `except Exception:` block in `config_flow.py` can break HA’s "Already Configured" logic.
  - *Fix*: Explicitly allow `AbortFlow` to propagate before catching generic exceptions.
- **NTFS/OneDrive Locking**: Development within OneDrive-synced Windows folders causes intermittent `.git` corruption and `PermissionError` during test runs.
- **MappingProxy TypeError**: In unit tests, `ZTEConfigFlow().context` is a read-only `mappingproxy`.
  - *Fix*: Explicitly set `flow.context = {}` in test setups.
- **HACS Branch Resolution**: HACS validation actions on non-default branches (like `dev`) often fail to find the manifest or brand assets.
  - *Fix*: Explicitly provide the repository context as `repository: ${{ github.repository }}@${{ github.ref_name }}` in the workflow.

## 5. Environment Constraints
- **I/O Bound API**: The ZTE goform API is synchronous and blocking. All API calls must be wrapped in `hass.async_add_executor_job` to avoid stalling the HA event loop.
- **SSL Verification**: Local routers typically use self-signed certificates. The `ZTERouterAPI` uses `urllib3.disable_warnings()` and `verify=False`.
- **Requirements Pinning**: Home Assistant requires all PyPI dependencies in `manifest.json` to be pinned to a specific version (e.g., `requests==2.32.3`).

## 6. Technical Debt & Future Work
- **Token Persistence**: Currently, the `stok` (Session Token) is stored in memory. A fresh login is required on every integration restart.
- **SMS Page Limits**: The `delete_all` feature is limited to the first 500 messages to avoid API timeouts.
- **Debounce Dependency**: The `ZTEPollingInterval` entity uses an `asyncio.sleep(2)` debounce. This creates a task that must be handled carefully in unit tests to avoid `UnraisableExceptionWarnings`.
