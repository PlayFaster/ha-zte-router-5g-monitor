# ZTE Router 5G Integration - Entity Manifest

This document provides a comprehensive list of all 91 entities currently implemented in the ZTE Router 5G integration. It serves as a master reference for debugging, maintenance, and future development.

## Summary

| Sub-Device | Entity Count | Description |
| :-- | :-- | :-- |
| **System** | 32 | Core router info and global integration settings. |
| **Signal** | 40 | Cellular connectivity, signal strength (LTE/5G), and network info. |
| **Data** | 14 | Monthly and session traffic volume (Bytes and GB). |
| **SMS** | 4 | Message counts and recent message content. |
| **Total** | **91** |  |

---

## 1. System Sub-Device (32 Entities)

_Group: `system`_

| Name | Key | Type | Source (Raw Key) | Unit | Category | Notes | About |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-: |
| Model Name | `model_name` | Sensor | `model_name` | - | Diagnostic |  | — |
| Firmware Version | `wa_inner_version` | Sensor | `wa_inner_version` | - | Diagnostic |  | ✔ |
| WAN IP Address | `wan_ipaddr` | Sensor | `wan_ipaddr` | - | Diagnostic |  | ✔ |
| LAN IP Address | `lan_ipaddr` | Sensor | `lan_ipaddr` | - | Diagnostic |  | — |
| Uptime | `device_uptime` | Sensor | `realtime_time` | Timestamp | Sensor | Calculated as `now() - uptime_seconds`. | ✔ |
| Uptime Duration | `realtime_time` | Sensor | `realtime_time` | h | Sensor | **Disabled by default.** Raw uptime duration. Other display units may be used (e.g. h). | ✔ |
| Last Updated | `last_updated` | Sensor | `coordinator.last_update_success_time` | Timestamp | Sensor | Internal tracking of last successful poll. | — |
| IMEI | `imei` | Sensor | `imei` | - | Diagnostic | **Disabled by default (sensitive).** Hardware-bound modem identifier. | ✔ |
| Hardware Version | `hardware_version` | Sensor | `hardware_version` | - | Diagnostic | e.g. `MC7010-1`. | — |
| Battery | `battery_value` | Sensor | `battery_value` | % | Sensor | **Disabled by default.** Full when plugged in. | ✔ |
| Power Amplifier Temperature | `pm_sensor_pa1` | Sensor | `pm_sensor_pa1` | °C | Diagnostic | **Disabled by default.** Not populated by the MC7010, which returns an empty value. | ✔ |
| Ambient Modem Temperature | `pm_sensor_ambient` | Sensor | `pm_sensor_ambient` | °C | Diagnostic | **Disabled by default.** Not populated by the MC7010, which returns an empty value. | ✔ |
| Modem Temperature | `pm_sensor_mdm` | Sensor | `pm_sensor_mdm` | °C | Diagnostic | **Disabled by default.** Not populated by the MC7010, which returns an empty value. | ✔ |
| 5G Modem Temperature | `pm_modem_5g` | Sensor | `pm_modem_5g` | °C | Diagnostic | **Disabled by default.** Not populated by the MC7010, which returns an empty value. | ✔ |
| 5G Radio Temperature | `pm_sensor_5g` | Sensor | `pm_sensor_5g` | °C | Diagnostic | **Disabled by default.** Not populated by the MC7010, which returns an empty value. | ✔ |
| SIM IMSI | `sim_imsi` | Sensor | `sim_imsi` | - | Diagnostic | **Disabled by default (sensitive).** SIM network identity. | ✔ |
| SIM ICCID | `sim_iccid` | Sensor | `sim_iccid` | - | Diagnostic | **Disabled by default (sensitive).** SIM card serial number. | ✔ |
| Refresh Now | `refresh` | Button | `coordinator.async_request_refresh()` | - | Config | Forces an immediate poll cycle. Complements Pause Polling and the polling interval. | ✔ |
| Reboot | `reboot` | Button | API Call: `REBOOT_DEVICE` | - | Control |  | ✔ |
| Pause Polling | `pause_polling` | Switch | Options: `stop_polling` | - | Config | State persists in `ConfigEntry.options`. | ✔ |
| Polling Interval | `polling_interval` | Number | Options: `scan_interval` | s | Config | Range: 30s - 3600s. Persists in options. | ✔ |
| Integration Health | `integration_health` | Binary | `coordinator.health_snapshot` | - | Diagnostic | ON when the integration detects a problem, including a poll that succeeds but returns nothing usable. Stays available during an outage, when other entities do not. Attributes carry the detail. | ✔ |
| Reboot Schedule | `reboot_schedule` | Binary | `reboot_schedule_enable` | - | Diagnostic | **Disabled by default.** Scheduled reboot active status. Extra attributes: hour, minute, schedule mode, day of week, day of month - the last three raw, as the mode-to-day mapping is unconfirmed. | ✔ |
| UPnP Enabled | `upnp_enabled` | Binary | `upnp_enable` | - | Diagnostic | **Disabled by default.** UPnP active status. | ✔ |
| SIP ALG Enabled | `sip_alg_enabled` | Binary | `alg_sip_enable` | - | Diagnostic | **Disabled by default.** SIP ALG active status. | ✔ |
| ODU LED Switch | `odu_led_switch` | Switch | `ODU_led_switch` | - | Config | **Disabled by default.** Toggle router outdoor unit LED light. | — |
| Time Server (SNTP) | `sntp_server` | Sensor | `sntp_server` | - | Diagnostic | **Disabled by default.** Configuration time server. | ✔ |
| Router Timezone | `sntp_timezone` | Sensor | `sntp_timezone` | - | Diagnostic | **Disabled by default.** Vendor-format timezone string (e.g. `0-1`), shown raw rather than interpreted. | ✔ |
| WAN Operating Mode | `opms_wan_mode` | Sensor | `opms_wan_mode` | - | Diagnostic | **Disabled by default.** e.g. `LTE_BRIDGE`. Read-only by design - changing it alters the path the integration reaches the router over. | ✔ |
| WAN Fallback Mode | `opms_wan_auto_mode` | Sensor | `opms_wan_auto_mode` | - | Diagnostic | **Disabled by default.** e.g. `AUTO_LTE_GATEWAY`. Differing from the active mode is normal. | ✔ |
| APN Interface Version | `apn_interface_version` | Sensor | `apn_interface_version` | - | Diagnostic | **Disabled by default.** Router APN configuration schema version. | ✔ |
| Web Page Sleep | `web_sleep` | Binary | `web_sleep_switch` | - | Diagnostic | **Disabled by default.** Read-only: no write command was found for it. | ✔ |
| Web Page Auto-Wake | `web_wake` | Binary | `web_wake_switch` | - | Diagnostic | **Disabled by default.** Read-only for the same reason. | ✔ |

---

## 2. Signal Sub-Device (39 Entities)

_Group: `signal`_

| Name | Key | Type | Source (Raw Key) | Unit | Category | Notes | About |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-: |
| WAN Connect Status | `wan_connect_status` | Sensor | `wan_connect_status` | - | Diagnostic |  | ✔ |
| Network APN | `wan_apn` | Sensor | `wan_apn` | - | Diagnostic | Data may not be available in all configurations. | ✔ |
| Network Type | `network_type` | Sensor | `network_type` | - | Sensor | e.g., LTE, ENDC, NR5G. | ✔ |
| Signal Bars | `signalbar` | Sensor | `signalbar` | - | Sensor | 0-5 scale. | ✔ |
| Network Provider | `network_provider` | Sensor | `network_provider` | - | Diagnostic |  | ✔ |
| MDM MCC | `mdm_mcc` | Sensor | `mdm_mcc` | - | Diagnostic |  | ✔ |
| MDM MNC | `mdm_mnc` | Sensor | `mdm_mnc` | - | Diagnostic |  | ✔ |
| Roaming MCC | `rmcc` | Sensor | `rmcc` | - | Diagnostic | **Disabled by default.** | ✔ |
| Roaming MNC | `rmnc` | Sensor | `rmnc` | - | Diagnostic | **Disabled by default.** | ✔ |
| LTE RSRP | `lte_rsrp` | Sensor | `lte_rsrp` | dBm | Sensor | Range: -140 to -30. | ✔ |
| LTE RSRQ | `lte_rsrq` | Sensor | `lte_rsrq` | dB | Sensor | Range: -40 to 0. | ✔ |
| LTE RSSI | `lte_rssi` | Sensor | `lte_rssi` | dBm | Sensor | Range: -120 to -20. | ✔ |
| LTE SNR | `lte_snr` | Sensor | `lte_snr` | dB | Sensor | Range: -20 to 50. | ✔ |
| LTE PCI | `lte_pci` | Sensor | `lte_pci` | - | Diagnostic |  | ✔ |
| Cell ID | `cell_id` | Sensor | `cell_id` | - | Diagnostic |  | ✔ |
| Carrier Aggregation | `wan_lte_ca` | Sensor | `wan_lte_ca` | - | Sensor |  | ✔ |
| LTE Primary Band | `lte_ca_pcell_band` | Sensor | `lte_ca_pcell_band` | - | Diagnostic |  | ✔ |
| LTE Primary Bandwidth | `lte_ca_pcell_bandwidth` | Sensor | `lte_ca_pcell_bandwidth` | MHz | Diagnostic |  | ✔ |
| LTE Secondary Band | `lte_ca_scell_band` | Sensor | `lte_ca_scell_band` | - | Diagnostic | **Disabled by default.** Data may not be available in all configurations. | ✔ |
| LTE Secondary Bandwidth | `lte_ca_scell_bandwidth` | Sensor | `lte_ca_scell_bandwidth` | MHz | Diagnostic | **Disabled by default.** Data may not be available in all configurations. | ✔ |
| LTE Active Band | `wan_active_band` | Sensor | `wan_active_band` | - | Diagnostic |  | ✔ |
| LTE Active Channel | `wan_active_channel` | Sensor | `wan_active_channel` | - | Diagnostic |  | ✔ |
| 5G RSRP | `z5g_rsrp` | Sensor | `Z5g_rsrp` | dBm | Sensor | Range: -140 to -30. Data may not be available in all configurations (no 5G attachment reports empty 5G metrics). | ✔ |
| 5G RSRQ | `z5g_rsrq` | Sensor | `Z5g_rsrq` | dB | Sensor | Range: -40 to 0. Data may not be available in all configurations (no 5G attachment reports empty 5G metrics). | ✔ |
| 5G RSSI | `z5g_rssi` | Sensor | `Z5g_rssi` | dBm | Sensor | Range: -120 to -20. Data may not be available in all configurations (no 5G attachment reports empty 5G metrics). | ✔ |
| 5G SNR | `z5g_sinr` | Sensor | `Z5g_SINR` | dB | Sensor | Range: -20 to 50. Data may not be available in all configurations (no 5G attachment reports empty 5G metrics). | ✔ |
| 5G PCI | `nr5g_pci` | Sensor | `nr5g_pci` | - | Diagnostic | Data may not be available in all configurations (no 5G attachment reports empty 5G metrics). | ✔ |
| 5G Active Band | `nr5g_action_band` | Sensor | `nr5g_action_band` | - | Diagnostic | Data may not be available in all configurations (no 5G attachment reports empty 5G metrics). | ✔ |
| 5G Active Channel | `nr5g_action_channel` | Sensor | `nr5g_action_channel` | - | Diagnostic | Data may not be available in all configurations (no 5G attachment reports empty 5G metrics). | ✔ |
| Legacy RSSI | `rssi` | Sensor | `rssi` | dBm | Sensor | **Disabled by default.** Data may not be available in all configurations. | ✔ |
| Legacy RSCP | `rscp` | Sensor | `rscp` | dBm | Sensor | **Disabled by default.** Data may not be available in all configurations. | ✔ |
| eNodeB ID | `enodeb_id` | Sensor | `enodeb_id` | - | Diagnostic | Serving cell tower identifier (hex string). | ✔ |
| Network Mode | `net_select` | Sensor | `net_select` | - | Diagnostic | Configured mode, e.g. `LTE_AND_5G`, `LTE_ONLY`. | ✔ |
| Bridge Mode | `ppp_status` | Sensor | `ppp_status` | - | Diagnostic | PPP layer state, e.g. `ppp_connected`. | ✔ |
| Best Connection | `best_connection` | Binary | Logic: `ENDC` + `ca_activated` | - | Sensor | ON if 5G and LTE-CA are both active. | ✔ |
| APN Profile | `apn_profile` | Select | `apn_index` + `APN_config0..19` | - | Config | Switch default/active APN profile index. | ✔ |
| APN Selection Mode | `apn_mode` | Select | `apn_mode` | - | Config | Switch between Automatic and Manual APN selection modes. | ✔ |
| Network Mode Selection | `net_select_mode` | Select | `BearerPreference` | - | Config | Choose network bearer preference (Auto, 5G NSA, 5G SA, 4G Only). | ✔ |
| LTE Band Lock Mask | `lte_band_lock` | Sensor | `lte_band_lock` | - | Diagnostic | **Disabled by default.** LTE band lock configuration mask. | ✔ |
| Carrier Aggregation Secondary Cells | `lte_multi_ca_scell_info` | Sensor | `lte_multi_ca_scell_info` | - | Diagnostic | **Disabled by default.** Raw descriptor, one comma-separated group per secondary cell (e.g. `2,352,2,20,6300,10;`). | ✔ |

---

## 3. Data Sub-Device (14 Entities)

_Group: `data`_

| Name | Key | Type | Source (Raw Key) | Unit | Category | Notes | About |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-: |
| Monthly Sent | `monthly_tx_bytes_raw` | Sensor | `monthly_tx_bytes` | Bytes | Sensor | Native Byte sensor for UI conversion. Other display units may be used (e.g. GB). | ✔ |
| Monthly Received | `monthly_rx_bytes_raw` | Sensor | `monthly_rx_bytes` | Bytes | Sensor | Native Byte sensor for UI conversion. Other display units may be used (e.g. GB). | ✔ |
| Monthly Total | `monthly_total_bytes_raw` | Sensor | `TX + RX` | Bytes | Sensor | Native Byte sensor for UI conversion. Other display units may be used (e.g. GB). | ✔ |
| Monthly Sent GB | `monthly_tx_bytes` | Sensor | `monthly_tx_bytes / 10^9` | GB | Sensor | **Disabled by default (Legacy).** | ✔ |
| Monthly Received GB | `monthly_rx_bytes` | Sensor | `monthly_rx_bytes / 10^9` | GB | Sensor | **Disabled by default (Legacy).** | ✔ |
| Monthly Total GB | `monthly_total_bytes` | Sensor | `(TX+RX) / 10^9` | GB | Sensor | **Disabled by default (Legacy).** | ✔ |
| Upload Speed | `realtime_tx_thrpt` | Sensor | `realtime_tx_thrpt` | B/s | Sensor | Instantaneous TX throughput. Other display units may be used (e.g. Mbit/s). | ✔ |
| Download Speed | `realtime_rx_thrpt` | Sensor | `realtime_rx_thrpt` | B/s | Sensor | Instantaneous RX throughput. Other display units may be used (e.g. Mbit/s). | ✔ |
| Session Sent | `realtime_tx_bytes` | Sensor | `realtime_tx_bytes` | Bytes | Sensor | Cumulative bytes since last connection. Resets on reconnect. No LTS. Other display units may be used (e.g. GB). | ✔ |
| Session Received | `realtime_rx_bytes` | Sensor | `realtime_rx_bytes` | Bytes | Sensor | Cumulative bytes since last connection. Resets on reconnect. No LTS. Other display units may be used (e.g. GB). | ✔ |
| Data Limit Switch | `data_limit_switch` | Switch | `data_volume_limit_switch` | - | Config | **Disabled by default.** Control data volume limit switch. | ✔ |
| Data Volume Alert | `data_volume_alert_percent` | Sensor | `data_volume_alert_percent` | % | Sensor | **Disabled by default.** Alert threshold percentage of limit. | ✔ |
| Reset Day | `data_clear_day` | Sensor | `traffic_clear_date` | - | Diagnostic | Day of month the router zeroes its monthly counters. Aliased across three spellings; guard band 1-31. | ✔ |
| Projected Cycle Usage | `data_projection` | Sensor | `TX + RX` vs cycle elapsed | Bytes | Sensor | Estimated end-of-cycle total. `measurement` state class, not `total`. Attributes: confidence, basis, cycle day, cycle start. Other display units may be used (e.g. GB). | ✔ |

---

## 4. SMS Sub-Device (4 Entities)

_Group: `sms`_

| Name | Key | Type | Source (Raw Key) | Unit | Category | Notes | About |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-: |
| Unread Msg | `sms_unread_num` | Sensor | `sms_unread_num` | - | Sensor |  | — |
| Total Msg | `msg_total` | Sensor | Sum of all NV/SIM banks | - | Sensor | Includes attributes for each bank. | ✔ |
| Recent Msg | `msg_recent` | Sensor | `last_sms` content | - | Sensor | Content is hex-decoded from router. | ✔ |
| Delete All | `delete_all` | Button | API Call: `DELETE_SMS` (batch) | - | Control |  | — |
| Send Sms | `send_sms` | Service | — | — | — | Send an SMS message via the router. | — |
| Delete Sms | `delete_sms` | Service | — | — | — | Delete an SMS message by its index. | — |
| Delete All Sms | `delete_all_sms` | Service | — | — | — | Delete all SMS messages from the router inbox. | — |
| Get Sms List | `get_sms_list` | Service | — | — | — | Fetch a list of SMS messages from the router. | — |

---

## 5. Debugging & Maintenance Reference

### Identity Strategy

- **Base Unique ID**: The IMEI of the router modem (preferred) or `host_{IP}` (fallback for firmware that does not expose IMEI).
- **Entity Unique ID**: `{{base_id}}_{{key}}`.
- **Device Identifiers**: `{{DOMAIN}}_{{base_id}}_{{group}}` (e.g., `zte_router_5g_864155042229309_signal`).

### Missing Elements Troubleshooting

If an entity disappears, check:

1. **Raw Key Mapping**: Ensure the router is returning the key in `get_all_data`. Some firmware versions omit specific signal keys (e.g., `rscp`).
2. **Sub-device Linking**: All non-system sub-devices must have a `via_device` link to the `system` sub-device.
3. **Internal Key Stability**: All keys used in `unique_id` are lowercase (e.g., `z5g_rsrp`). Do not change these to PascalCase even if the router's raw data changes, as it will break the entity registry.

### SMS Attributes

The `Total Msg` sensor contains detailed attributes for storage analysis:

- `sms_nv_total`, `sms_sim_total`
- `sms_nv_rev_total`, `sms_nv_send_total`, `sms_nv_draftbox_total`
- `sms_sim_rev_total`, `sms_sim_send_total`, `sms_sim_draftbox_total`

The `Recent Msg` sensor contains:

- `id`: Internal router message ID.
- `number`: Hex-decoded sender number.
- `date`: Formatted ISO timestamp from router's comma-separated format.

### Suggested Display Units & Precision

Sensors are stored in their canonical **native** unit (so long-term statistics and guard bands are stable) but carry a display hint via `suggested_unit_of_measurement` / `suggested_display_precision`. The value shown in the UI can still be overridden per-entity.

| Sensors | Native | Suggested display | Precision |
| :-- | :-- | :-- | :-- |
| `monthly_tx_bytes_raw`, `monthly_rx_bytes_raw`, `monthly_total_bytes_raw` | Bytes | GB | 1 |
| `realtime_tx_bytes`, `realtime_rx_bytes` (session) | Bytes | GB | 2 |
| `realtime_tx_thrpt`, `realtime_rx_thrpt` | B/s | Mbit/s | 2 |
| `realtime_time` (Uptime Duration) | s | h | 1 |
| `lte_ca_pcell_bandwidth`, `lte_ca_scell_bandwidth` | MHz | MHz (unchanged) | 0 |
| `lte_rsrp`, `lte_rssi`, `z5g_rsrp`, `z5g_rssi`, `rssi`, `rscp` | dBm | dBm (unchanged) | 0 |

> The legacy GB sensors (`monthly_tx_bytes`, `monthly_rx_bytes`, `monthly_total_bytes`) already report GB (disabled by default) and are intentionally left unchanged.

---

## 6. Services

The integration registers several custom Home Assistant services for advanced SMS management:

### `send_sms`

Send an SMS message via the router.

- **Fields:**
  - `entry_id` (optional): The router config entry ID to use (optional if only one exists).
  - `target` (required): List of phone numbers/targets to send the message to.
  - `message` (required): Message content (up to 160 characters).

### `delete_sms`

Delete a specific SMS message by its index.

- **Fields:**
  - `entry_id` (required): The router config entry ID.
  - `index` (required): The index of the message to delete.

### `delete_all_sms`

Delete all SMS messages from the router inbox.

- **Fields:**
  - `entry_id` (required): The router config entry ID.
  - `keep_last` (optional): Number of most recent messages to keep (default: 0, which deletes all).

### `get_sms_list`

Fetch a list of SMS messages from the router. This service returns a response payload.

- **Fields:**
  - `entry_id` (required): The router config entry ID.
  - `page` (optional): Page number (default: 1).
  - `count` (optional): Messages per page (default: 20).
  - `box_type` (optional): Box to read from (default: 1 = Local Inbox. Other options: 2=Local Sent, 3=Local Draft, 4=Local Trash, 5=SIM Inbox, 6=SIM Sent, 7=SIM Draft, 8=Mix Inbox, 9=Mix Sent, 10=Mix Draft).
- **Response Schema:**
  - Returns a dictionary containing a list of `messages` with `index`, `phone`, `content`, `date`, and `read` status.

---

## Version Control

- **v1.0.0** (2026-05-07) - Initial versioned snapshot. Entity count updated 51 → 63. Added 12 new sensors (System: IMEI, Hardware Version, Battery, SIM IMSI, SIM ICCID; Signal: eNodeB ID, Network Mode, PPP Status; Data: Upload Speed, Download Speed, Session Sent, Session Received). Identity strategy updated from MAC to IMEI.
- **v3.0.0-dev23** (2026-05-08) - Updated categories for Uptime, Last Updated, Best Connection, and WAN Connect Status. Renamed PPP Status to Bridge Mode. Set Battery to disabled by default.
- **v3.0.1-dev5** (2026-05-10) - Migrated to hierarchical translation keys across all 63 entities.
- **v3.0.2-dev3** (2026-05-22) - Added `system_uptime_duration` sensor and corrected legacy GB sensors to use base-10 (10^9) calculation.
- **v3.0.2-dev6** (2026-05-23) - Added documentation for the custom SMS services (`send_sms`, `delete_sms`, `delete_all_sms`, `get_sms_list`).
- **v3.0.2-dev7** (2026-05-23) - Documented custom SMS services and verified setup.
- **v3.1.1-dev5** (2026-05-25) - Updated Session Sent/Received notes to reflect removal of state_class (no LTS).
- **v3.2.0** (2026-05-27) — Added 11 new entities (APN Profile, APN Selection Mode, Network Mode Selection, ODU LED Switch, Data Limit Switch, Reboot Schedule, UPnP Enabled, SIP ALG Enabled, LTE Band Lock Mask, Data Volume Alert %, SNTP Time Server) raising total count from 64 to 75.
- **v3.2.5-dev7** (2026-07-02) — Added the "Refresh Now" button (System sub-device) for on-demand coordinator refresh, raising total count from 75 to 76.
- **v3.2.5-dev8** (2026-07-02) — Added suggested display units/precision to 16 sensors (data size → GB, data rate → Mbit/s, uptime duration → hours, bandwidth and dBm → 0 dp). No entity count change. Added the "Suggested Display Units & Precision" reference table.
- **v3.2.5-dev9** (2026-07-03) — Documented unit displays for Data sub-device and System Uptime Duration; added SMS service definitions to the SMS sub-device table.
- **v3.3.3** (2026-07-29) — `About` column refreshed after six control entities gained notes (APN Profile, APN Selection Mode, Network Mode Selection, UPnP Enabled, SIP ALG Enabled, Data Limit Switch); coverage 68 → 74 of 82.
- **v3.3.2** (2026-07-29) — Added an `About` column (✔ / —) marking which entities carry an unrecorded `about` note; 68 of 82 do. The note text itself stays in `about_attribute_list.md` and is deliberately not duplicated here — it is 1-3 sentences per entity and would make this table unreadable. Reconciled against the live instance by `sensor_review` (SCOPE=About).
- **v3.3.1** (2026-07-29) — Live reconciliation against the running instance via `sensor_review` (82 entities). Added the **Integration Health** binary sensor, which had never been documented. Renamed two rows to match HA: Connection Status -> WAN Connect Status, Delete All Msg -> Delete All. Corrected System 26 -> 27 and total 81 -> 82. Annotated the seven 5G signal metrics and Network APN as legitimately unavailable without a 5G attachment.
- **v3.3.1** (2026-07-29) — Added five thermal diagnostic sensors (Power Amplifier, Ambient Modem, Modem, 5G Modem, 5G Radio temperatures), all disabled by default because the MC7010 does not populate any of them. System count 21 to 26, total 76 to 81.
