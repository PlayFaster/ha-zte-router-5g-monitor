# ZTE Router 5G Monitor Capabilities Dossier

An architectural reference and at-a-glance inventory of verified capabilities, interfaces, technical guarantees, and version lineage for `ha-zte-router-5g-monitor`.

**Current Through:** `v3.4.6-dev1` (covering `v1.3.6` to `v3.4.6-dev1`) · **Last Audited:** 2026-10-13 · **Status:** `In-Progress Dev`
*Version lineage: 3.4.6-dev1 in-progress dev build following 3.4.5 release.*

---

## 1. Connection & Session Control

### Dual-Path Session Resilience & Lockout Guard

- **Purpose**: Authenticates against ZTE web interfaces without triggering brute-force lockouts or corrupting router session state across multi-client environments.
- **Entities & Interfaces**: `sensor.<name>_system_login_attempts_remaining`, `binary_sensor.<name>_system_integration_health`.
- **Technical Guarantees**:
  - Pre-login attempt inspection withholds requests when exactly 1 attempt remains or during an active lockout.
  - Interactive outage countdown feedback without false re-authentication flows.
  - Mutex-serialized logins (`asyncio.Lock`) before write operations with single-rebuild retry.
  - Adaptive session lifetime learning dynamically calculates reset thresholds from observed expirations (`SESSION_AGE_LEARN_MIN_SAMPLES`).
  - Dynamic session cookie capture (`zsidn` / `stok`) and multi-key pre-write validation (`wan_connect_status`, `ppp_status`, `model_name`).
- **Lifecycle Timeline**:
  - `v1.9.4`: Initial session management and hardware model reading.
  - `v2.1.1`: Diagnostic session error logging.
  - `v3.0.0`: Centralized session handling and non-blocking asynchronous setup.
  - `v3.2.0`: Expired session token auto-detection and reset.
  - `v3.3.4`: Cookieless authentication support and raw header session token inspection.
  - `v3.3.5`: Multi-user login payload shape alignment; false session expiry classification fixed.
  - `v3.3.7`: Dynamic session cookie capture (`zsidn` / `stok`); startup unauthenticated key discovery.
  - `v3.3.16`: Multi-key pre-write session status validation (`wan_connect_status`, `ppp_status`, `model_name`).
  - `v3.3.22`: Dynamic pre-write session key selection from active coordinator keys.
  - `v3.3.25`: Web-client driven write contracts; firmware login indicator checks (`loginfo`); adaptive session lifetime learning.
  - `v3.4.0`: Dynamic session cookie discovery integration with profile subsystem.
  - `v3.4.3`: Authenticated pre-write login enforcement and serialized login mutex.
  - `v3.4.5`: Pre-login lockout protection and remaining attempts sensor.

### Cellular Data Connection Management

- **Purpose**: Enables programmatic control of mobile cellular data connectivity directly from Home Assistant.
- **Entities & Interfaces**:
  - `switch.<name>_signal_data_connection`
  - `sensor.<name>_signal_data_connection_status`
  - `sensor.<name>_signal_connection_mode_status`
- **Technical Guarantees**:
  - Outage protection window (up to 60s) suppresses coordinator poll failures while connection renegotiates.
  - Intermediate state tracking (`ppp_connecting`, `ppp_connected`, `ppp_disconnecting`, `ppp_disconnected`) prevents UI flapping.
  - Automatic follow-up state verification reconciles intermediate states when the router settles.
- **Lifecycle Timeline**:
  - `v3.4.1`: Introduced Data Connection switch and connection mode status.
  - `v3.4.2`: Turn-on outage protection window and state latch verification.
  - `v3.4.3`: Polling error suppression during active outage windows.

### Expected Outage Window Protection

- **Purpose**: Suppresses false error logs, alerts, and Integration Health degradations during intentional disconnects or device restarts.
- **Entities & Interfaces**: `button.<name>_system_reboot`, `switch.<name>_signal_data_connection`.
- **Technical Guarantees**:
  - Automatic suppression window (up to 60s for data disconnect, 240s for reboot).
  - Explicit interactive command refusal with remaining seconds countdown during active outage.
  - Integration Health alerts bypass normal strike budgets when active lockouts or outages occur.
- **Lifecycle Timeline**:
  - `v1.4.3`: Pause polling and startup failsafe checks.
  - `v3.4.1`: Introduced expected-outage windows for reboot and disconnect.
  - `v3.4.3`: Outage hold window standardized with interactive countdown feedback.

### Configurable Polling Interval & Polling Suspension

- **Purpose**: Controls update frequency and allows pausing scheduled background polling without taking integration entities offline.
- **Entities & Interfaces**:
  - `number.<name>_system_polling_interval`
  - `switch.<name>_system_pause_polling`
  - `button.<name>_system_refresh`
- **Technical Guarantees**:
  - Polling interval changes debounced and persisted to config entry options surviving Home Assistant restarts.
  - Pausing polling halts API traffic while keeping entities in their last known valid state rather than unavailable.
  - Manual Refresh Now overrides pause state to fetch immediate router status.
- **Lifecycle Timeline**:
  - `v1.4.3`: Added Pause Polling switch and Polling Interval number entity with config entry persistence.
  - `v2.0.1`: Options flow support for dynamic reconfiguration.
  - `v3.2.5`: Introduced Refresh Now button and system option polling toggle compatibility.
  - `v3.4.4`: Periodic full polls and manual refresh force-evaluate learned keys.

---

## 2. Data, Metrics & Uptime Tracking

### Independent Hardware & Connection Uptime Tracking

- **Purpose**: Tracks physical device uptime independently from cellular link drops or APN reconnects.
- **Entities & Interfaces**:
  - `sensor.<name>_system_device_uptime`
  - `sensor.<name>_system_uptime_duration`
  - `sensor.<name>_system_connection_uptime`
  - `sensor.<name>_system_connection_duration`
  - `sensor.<name>_system_total_connected_time`
- **Technical Guarantees**:
  - Hardware uptime (`system_uptime`) latching isolates physical boot time from cellular session resets (`realtime_time`).
  - Startup reconciliation cross-checks live uptime counters against persisted history across system restarts.
  - Counter sanity guard enforces 10-year ceiling and wall-clock progression to reject counter overflow jumps.
- **Lifecycle Timeline**:
  - `v1.4.0`: Initial uptime calculation from raw router counters.
  - `v3.1.0`: Whole-second latching introduced to prevent clock tick drift.
  - `v3.3.6`: Startup boot instant reconciliation across host downtime and reboots.
  - `v3.3.10`: Duration-weighted hardware timer drift calibration per installation.
  - `v3.4.2`: Separated hardware uptime from cellular link uptime; added connection uptime.
  - `v3.4.3`: Introduced Total Connected Time sensor; duration display set to minutes.
  - `v3.4.4`: Duration suggested display units switched to hours (`h`).
  - `v3.4.5`: Counter validation guard added to reject corrupted multi-year jumps.

### Intelligent Hybrid Polling & Request Batching

- **Purpose**: Discovers and queries only the exact parameter keys answered by the router's firmware, optimizing network traffic and reducing router CPU load.
- **Entities & Interfaces**: Dynamic coordinator poller.
- **Technical Guarantees**:
  - Request payload volume reduced by 20%–35% during steady-state polling.
  - Background rotation (1 in 5 polls) tests unresolved keys without poll degradation.
  - Automated URL character length partitioning (1,600 characters) splits oversized queries into sequential chunks.
  - Automatic full sweeps triggered on LTE-to-5G network mode transitions and every 30 cycles.
- **Lifecycle Timeline**:
  - `v3.3.9`: URL character ceiling partitioning preventing query truncation.
  - `v3.4.4`: Introduced intelligent hybrid parameter polling.

### Radio & Neighbor Cell Diagnostics

- **Purpose**: Provides detailed RF metrics and neighbor cell tower data to assist with antenna orientation and cell tower lock analysis.
- **Entities & Interfaces**:
  - `sensor.<name>_signal_ngbr_cell_info`
  - Diagnostic signal sensors (RSRP, RSRQ, SINR, RSSI, Band, Cell ID, CA Bandwidth).
- **Technical Guarantees**:
  - Attributes expose EARFCN, PCI, RSRQ, and RSRP for each detected neighbor cell tower.
  - Automated eNodeB ID mathematical derivation from cell IDs when unpopulated by firmware.
  - Dual spelling schema support handles firmware variance (`ENDC` vs `EN-DC`).
- **Lifecycle Timeline**:
  - `v1.4.0`: Core signal strength (RSRP, RSRQ, SINR) and network type sensors.
  - `v1.4.4`: Full router signal attribute exposure as individual sensors.
  - `v3.0.0`: Added eNodeB ID, network mode, and signal bar sensors.
  - `v3.2.0`: Carrier Aggregation Secondary Cells and Band Lock Mask sensors.
  - `v3.3.4`: LTE CA bandwidth frequency unit switching (MHz/GHz/kHz) in HA UI.
  - `v3.3.9`: Per-antenna 5G signal sensors (`5g_rsrp_antenna_1/2`) and secondary CA metrics added.
  - `v3.3.10`: Generic MC888 RSSI/SINR sensors (`network_rssi`, `network_sinr`); eNodeB ID derivation.
  - `v3.3.12`: Best connection dual schema support (`ENDC` and `EN-DC`).
  - `v3.4.0`: Dynamic radio and band data metrics verified.
  - `v3.4.5`: Introduced Neighbor Cells sensor with detailed attribute data.

---

## 3. Configuration & Entity Control

### Router-Learned Network Mode Selection

- **Purpose**: Sets cellular network preferences (5G NSA/SA, LTE only, auto) based strictly on supported router capabilities rather than hardcoded lists.
- **Entities & Interfaces**: `select.<name>_signal_net_select`.
- **Technical Guarantees**:
  - Mode options mined directly from device configuration files, preventing "Unknown" states and invalid write submissions.
  - Stateful write rebuilding re-authenticates and retries once if initial write is rejected.
- **Lifecycle Timeline**:
  - `v3.2.0`: Added initial Network Mode Select entity with static options.
  - `v3.4.4`: Implemented router-learned network mode selection from device configuration files.

### APN Profile & Dial Mode Management

- **Purpose**: Programmatically configures active APN profiles and switches between automatic and manual APN selection.
- **Entities & Interfaces**:
  - `select.<name>_signal_apn_profile`
  - `select.<name>_signal_apn_mode`
- **Technical Guarantees**:
  - Dropdown displays active profile in manual APN mode while clearing to blank state in auto mode.
  - Writes verified via immediate single-read confirmation to ensure router accepted parameters.
- **Lifecycle Timeline**:
  - `v3.2.0`: Introduced APN profile and APN selection mode controls.
  - `v3.3.2`: Aligned manual/auto profile display behaviors.
  - `v3.3.4`: Hardened APN selection mode toggling with verified state updates.

### Cumulative Traffic Counters & Data Limits

- **Purpose**: Monitors long-term cellular bandwidth consumption and applies traffic caps across billing periods.
- **Entities & Interfaces**:
  - `sensor.<name>_data_total_rx_bytes`
  - `sensor.<name>_data_total_tx_bytes`
  - `sensor.<name>_data_total_data_bytes`
  - `switch.<name>_data_data_limit_switch`
  - `sensor.<name>_data_data_projection`
- **Technical Guarantees**:
  - Raw counter stored in integer bytes; formatted and displayed in gigabytes (GB).
  - Form aliases (including `flux_` parameters) ensure reliable writes on newer firmware schemas.
  - Forecasts end-of-cycle consumption based on observed daily run rates with confidence scoring.
- **Lifecycle Timeline**:
  - `v1.4.0`: Initial data usage monitoring.
  - `v3.0.0`: Monthly data in native bytes with long-term statistics (`total_increasing`).
  - `v3.2.0`: Added Data Limit Control switch.
  - `v3.3.2`: Billing cycle tracking and Projected Cycle Usage forecasting.
  - `v3.3.7`: Added `flux_` parameter aliases for data volume limit settings form.
  - `v3.4.3`: Added cumulative total byte counters.
  - `v3.4.4`: Total data and limit switch enabled by default on new setups.

### Entity Configuration Management & Reset Action

- **Purpose**: Reconciles and resets enabled/disabled entities to factory defaults or model-tailored presets.
- **Entities & Interfaces**: `zte_router_5g_monitor.reset_entities` action.
- **Technical Guarantees**:
  - Safely modifies entity registry enablement flags without re-adding or deleting integration entries.
  - Dry-run preview mode allows auditing changes prior to applying them.
- **Lifecycle Timeline**:
  - `v3.3.10`: Introduced `reset_entities` service action and per-model default overlays.
  - `v3.4.0`: Entity configuration management stabilized with snapshot save/restore.

### Interactive Re-Authentication & Repairs Integration

- **Purpose**: Guides users through configuration and credential updates through native Home Assistant Repair flows.
- **Entities & Interfaces**: Home Assistant Repairs dashboard, `binary_sensor.<name>_system_integration_health`.
- **Technical Guarantees**:
  - Actionable repair raised when router password fails, providing a direct form dialog to update credentials.
  - Non-actionable schema shifts mapped to Integration Health `drift` attributes rather than noisy repair cards.
- **Lifecycle Timeline**:
  - `v3.0.0`: Initial re-authentication flow on invalid credentials.
  - `v3.1.0`: Added SMS Storage Full repair.
  - `v3.3.2`: Added Router Unreachable repair.
  - `v3.3.4`: Interactive re-authentication repair flow added; non-actionable repairs mapped to health sensor.
  - `v3.4.0`: Repairs integration aligned with HA Quality Scale criteria.

---

## 4. SMS Platform & Messaging Operations

### Multi-Bank SMS Management & Verification

- **Purpose**: Provides full SMS inbox management across both device and SIM storage with guaranteed deletion verification and accurate timestamps.
- **Entities & Interfaces**:
  - `binary_sensor.<name>_sms_storage_full`
  - `sensor.<name>_sms_msg_recent`
  - `sensor.<name>_sms_msg_total`
  - `sensor.<name>_sms_sms_unread_num`
  - Services: `zte_router_5g_monitor.send_sms`, `zte_router_5g_monitor.delete_sms`, `zte_router_5g_monitor.delete_all_sms`, `zte_router_5g_monitor.get_sms_list`
  - Event: `zte_router_5g_sms_received`
- **Technical Guarantees**:
  - Combined storage bank polling (`mem_store="2"`) targets both device flash and SIM memory.
  - Read-back verification polls until message indices are purged (up to 15s) before reporting success.
  - Multi-part message support up to 765 ASCII or 335 Unicode characters.
  - Delivery verification checks counter deltas (`sms_nv_send_total` vs `sms_nv_draftbox_total`) to prevent drafts from reporting as sent.
  - Timezone-aware timestamp parser incorporates quarter-hour router offsets for precise local ordering.
- **Lifecycle Timeline**:
  - `v1.4.2`: Initial SMS capacity monitoring and latest message content sensor.
  - `v3.1.0`: Introduced `send_sms`, `delete_sms`, `delete_all_sms`, `get_sms_list` actions and `zte_router_5g_sms_received` event.
  - `v3.3.2`: Multi-part SMS character length expansion.
  - `v3.3.3`: SMS emoji decoding and polling resilience.
  - `v3.3.4`: SMS Storage Full binary sensor added; sender phone numbers redacted from standard logs.
  - `v3.3.11`: Timezone-aware timestamp parsing with router offset; verified multi-bank deletion.
  - `v3.3.14`: Persistent SMS deletion failure tracking across restarts.
  - `v3.3.22`: Browser-aligned URL-encoded message ID terminators (`%3B`) and `notCallback=true`.
  - `v3.3.24`: Asynchronous 15-second storage settle polling and draft delivery misclassification guard.
  - `v3.4.0`: SMS platform hardening complete; manual delete probe decommissioned.

---

## 5. Hardware Support & Compatibility

### Dynamic Profile Architecture & Multi-Model Support

- **Purpose**: Automatically accommodates distinct ZTE hardware families (MC7010, MC888, MC888 Pro, MC889) without hardcoded branching.
- **Entities & Interfaces**: Internal Profile Discovery subsystem (`device_profile.py`, `web_sources.py`).
- **Technical Guarantees**:
  - Web client scripts parsed in the background to learn model-specific security tokens and parameter naming.
  - Discovers parameter spelling variations, token hashing routines (MD5 / SHA-256), and cookie schemes (`zsidn` / `stok`) dynamically.
  - Automated alias resolution handles key variations (`5g_`, `z5g_`, `nr5g_`, `flux_`).
- **Lifecycle Timeline**:
  - `v1.3.6`: Initial custom component release for ZTE MC7010.
  - `v1.9.4`: Model number reading from device.
  - `v3.0.0`: Hardware IMEI adopted as immutable device unique identifier across IP changes.
  - `v3.3.2`: Multi-model parameter key alias recognition for alternative `goform` routers.
  - `v3.3.7`: Added support for MC888 Pro dynamic cookie authentication (`zsidn`).
  - `v3.3.9`: Added `network_` and `flux_` parameter aliases for MC888-series.
  - `v3.3.10`: Expanded MC888 compatibility (generic RSSI/SINR, 5G band locks, SIM lock state).
  - `v3.3.21`: MC888 Pro write token formula identified: `hash(hash(wa_inner_version + cr_version) + RD)`.
  - `v3.3.25`: Dynamic profile discovery system introduced, replacing static probing heuristics.
  - `v3.4.0`: Verified ZTE MC888 Pro compatibility milestone released.
  - `v3.4.4`: Expanded parameter spelling alias rules (`5g_`, `z5g_`, `nr5g_`, `flux_`).

---

## 6. Platform, Tooling & Diagnostics Infrastructure

### Live Diagnostics Download & Value-Based Redaction

- **Purpose**: Captures comprehensive device data and firmware parameters for troubleshooting while safeguarding sensitive user data.
- **Entities & Interfaces**: Home Assistant Diagnostics download.
- **Technical Guarantees**:
  - Deep-query sweep polls disabled entity parameters prior to capture.
  - Redaction engine tokenizes passwords, SSIDs, and national/international phone numbers by value shape across all fields.
  - Sanitized SMS metadata, data transfer rates, and firmware asset manifests included for developer analysis.
- **Lifecycle Timeline**:
  - `v3.0.0`: Initial support for Home Assistant diagnostic download export.
  - `v3.3.5`: Diagnostic capture on setup failures retaining sanitized responses.
  - `v3.3.7`: Startup parameter candidate discovery added to diagnostic exports.
  - `v3.3.8`: Automated web UI JavaScript parameter mining integrated into diagnostic downloads.
  - `v3.3.9`: Expanded candidate probe to 758 parameters with active canary tracking; cycle time reduced 60s → 6s.
  - `v3.3.11`: Sanitized SMS bank metadata and average data usage transfer rates added.
  - `v3.3.25`: Transitive RequireJS module asset manifest and script capture metadata included.
  - `v3.4.0`: Enhanced diagnostics download capture and sanitization engine released.
  - `v3.4.4`: Value-based telephone number sanitization added across all payload keys.
  - `v3.4.5`: Restored IP pass-through and Wi-Fi client count visibility with complete disabled-entity polling.

### Automated Testing & Complexity Baselines

- **Purpose**: Enforces 100% test coverage and complexity invariants across all integration subsystems.
- **Entities & Interfaces**: Test suite in `tests/`, project complexity tracking in `docs/project_complexity.md`.
- **Technical Guarantees**:
  - Full pytest test suite with 2,125 tests executing at 100% line and branch coverage.
  - Zero danger routines ($\ge 20$ McCabe complexity); Max McCabe complexity $V(G) \le 17$.
  - Mypy strict compliance with zero `# type: ignore` suppressions.
- **Lifecycle Timeline**:
  - `v2.2.1`: Initial automated testing infrastructure and test suite.
  - `v3.0.0`: Extended test coverage for native async architecture and coordinator migration.
  - `v3.2.1`: Migration to shared CI validation infrastructure.
  - `v3.3.15`: Automated McCabe cyclomatic complexity tracking integrated into workbench tasks.
  - `v3.3.16`: Project Complexity & Health Scorecard formal baseline established.
  - `v3.4.6-dev1`: Test baseline maintained at 2,125 tests, 100% coverage, and Mypy strict pass.

---

*Capabilities dossier audited against codebase and changelogs up to `v3.4.6-dev1` on 2026-10-13. Maintained via `capabilities_build.md`.*
