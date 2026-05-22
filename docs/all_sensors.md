# ZTE Router 5G Integration - Entity Manifest

This document provides a comprehensive list of all 64 entities currently implemented in the ZTE Router 5G integration. It serves as a master reference for debugging, maintenance, and future development.

## Summary

| Sub-Device | Entity Count | Description |
| :-- | :-- | :-- |
| **System** | 15 | Core router info and global integration settings. |
| **Signal** | 35 | Cellular connectivity, signal strength (LTE/5G), and network info. |
| **Data** | 10 | Monthly and session traffic volume (Bytes and GB). |
| **SMS** | 4 | Message counts and recent message content. |
| **Total** | **64** |  |

---

## 1. System Sub-Device (15 Entities)

_Group: `system`_

| Name | Key | Type | Source (Raw Key) | Unit | Category | Notes |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Model Name | `model_name` | Sensor | `model_name` | - | Diagnostic |  |
| Firmware Version | `wa_inner_version` | Sensor | `wa_inner_version` | - | Diagnostic |  |
| WAN IP Address | `wan_ipaddr` | Sensor | `wan_ipaddr` | - | Diagnostic |  |
| LAN IP Address | `lan_ipaddr` | Sensor | `lan_ipaddr` | - | Diagnostic |  |
| Uptime | `device_uptime` | Sensor | `realtime_time` | Timestamp | Sensor | Calculated as `now() - uptime_seconds`. |
| Uptime Duration | `realtime_time` | Sensor | `realtime_time` | s | Sensor | **Disabled by default.** Raw uptime duration in seconds. |
| Last Updated | `last_updated` | Sensor | `coordinator.last_update_success_time` | Timestamp | Sensor | Internal tracking of last successful poll. |
| IMEI | `imei` | Sensor | `imei` | - | Diagnostic | **Disabled by default (sensitive).** Hardware-bound modem identifier. |
| Hardware Version | `hardware_version` | Sensor | `hardware_version` | - | Diagnostic | e.g. `MC7010-1`. |
| Battery | `battery_value` | Sensor | `battery_value` | % | Sensor | **Disabled by default.** Full when plugged in. |
| SIM IMSI | `sim_imsi` | Sensor | `sim_imsi` | - | Diagnostic | **Disabled by default (sensitive).** SIM network identity. |
| SIM ICCID | `sim_iccid` | Sensor | `sim_iccid` | - | Diagnostic | **Disabled by default (sensitive).** SIM card serial number. |
| Reboot | `reboot` | Button | API Call: `REBOOT_DEVICE` | - | Control |  |
| Pause Polling | `pause_polling` | Switch | Options: `stop_polling` | - | Config | State persists in `ConfigEntry.options`. |
| Polling Interval | `polling_interval` | Number | Options: `scan_interval` | s | Config | Range: 30s - 3600s. Persists in options. |

---

## 2. Signal Sub-Device (35 Entities)

_Group: `signal`_

| Name | Key | Type | Source (Raw Key) | Unit | Category | Notes |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Connection Status | `wan_connect_status` | Sensor | `wan_connect_status` | - | Diagnostic |  |
| Network APN | `wan_apn` | Sensor | `wan_apn` | - | Diagnostic |  |
| Network Type | `network_type` | Sensor | `network_type` | - | Sensor | e.g., LTE, ENDC, NR5G. |
| Signal Bars | `signalbar` | Sensor | `signalbar` | - | Sensor | 0-5 scale. |
| Network Provider | `network_provider` | Sensor | `network_provider` | - | Diagnostic |  |
| MDM MCC | `mdm_mcc` | Sensor | `mdm_mcc` | - | Diagnostic |  |
| MDM MNC | `mdm_mnc` | Sensor | `mdm_mnc` | - | Diagnostic |  |
| Roaming MCC | `rmcc` | Sensor | `rmcc` | - | Diagnostic | **Disabled by default.** |
| Roaming MNC | `rmnc` | Sensor | `rmnc` | - | Diagnostic | **Disabled by default.** |
| LTE RSRP | `lte_rsrp` | Sensor | `lte_rsrp` | dBm | Sensor | Range: -140 to -30. |
| LTE RSRQ | `lte_rsrq` | Sensor | `lte_rsrq` | dB | Sensor | Range: -40 to 0. |
| LTE RSSI | `lte_rssi` | Sensor | `lte_rssi` | dBm | Sensor | Range: -120 to -20. |
| LTE SNR | `lte_snr` | Sensor | `lte_snr` | dB | Sensor | Range: -20 to 50. |
| LTE PCI | `lte_pci` | Sensor | `lte_pci` | - | Diagnostic |  |
| Cell ID | `cell_id` | Sensor | `cell_id` | - | Diagnostic |  |
| Carrier Aggregation | `wan_lte_ca` | Sensor | `wan_lte_ca` | - | Sensor |  |
| LTE Primary Band | `lte_ca_pcell_band` | Sensor | `lte_ca_pcell_band` | - | Diagnostic |  |
| LTE Primary Bandwidth | `lte_ca_pcell_bandwidth` | Sensor | `lte_ca_pcell_bandwidth` | MHz | Diagnostic |  |
| LTE Secondary Band | `lte_ca_scell_band` | Sensor | `lte_ca_scell_band` | - | Diagnostic | **Disabled by default.** Data may not be available in all configurations. |
| LTE Secondary Bandwidth | `lte_ca_scell_bandwidth` | Sensor | `lte_ca_scell_bandwidth` | MHz | Diagnostic | **Disabled by default.** Data may not be available in all configurations. |
| LTE Active Band | `wan_active_band` | Sensor | `wan_active_band` | - | Diagnostic |  |
| LTE Active Channel | `wan_active_channel` | Sensor | `wan_active_channel` | - | Diagnostic |  |
| 5G RSRP | `z5g_rsrp` | Sensor | `Z5g_rsrp` | dBm | Sensor | Range: -140 to -30. |
| 5G RSRQ | `z5g_rsrq` | Sensor | `Z5g_rsrq` | dB | Sensor | Range: -40 to 0. |
| 5G RSSI | `z5g_rssi` | Sensor | `Z5g_rssi` | dBm | Sensor | Range: -120 to -20. |
| 5G SNR | `z5g_sinr` | Sensor | `Z5g_SINR` | dB | Sensor | Range: -20 to 50. |
| 5G PCI | `nr5g_pci` | Sensor | `nr5g_pci` | - | Diagnostic |  |
| 5G Active Band | `nr5g_action_band` | Sensor | `nr5g_action_band` | - | Diagnostic |  |
| 5G Active Channel | `nr5g_action_channel` | Sensor | `nr5g_action_channel` | - | Diagnostic |  |
| Legacy RSSI | `rssi` | Sensor | `rssi` | dBm | Sensor | **Disabled by default.** Data may not be available in all configurations. |
| Legacy RSCP | `rscp` | Sensor | `rscp` | dBm | Sensor | **Disabled by default.** Data may not be available in all configurations. |
| eNodeB ID | `enodeb_id` | Sensor | `enodeb_id` | - | Diagnostic | Serving cell tower identifier (hex string). |
| Network Mode | `net_select` | Sensor | `net_select` | - | Diagnostic | Configured mode, e.g. `LTE_AND_5G`, `LTE_ONLY`. |
| Bridge Mode | `ppp_status` | Sensor | `ppp_status` | - | Diagnostic | PPP layer state, e.g. `ppp_connected`. |
| Best Connection | `best_connection` | Binary | Logic: `ENDC` + `ca_activated` | - | Sensor | ON if 5G and LTE-CA are both active. |

---

## 3. Data Sub-Device (10 Entities)

_Group: `data`_

| Name | Key | Type | Source (Raw Key) | Unit | Category | Notes |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Monthly Sent | `monthly_tx_bytes_raw` | Sensor | `monthly_tx_bytes` | Bytes | Sensor | Native Byte sensor for UI conversion. Other display units may be used (e.g. GiB). |
| Monthly Received | `monthly_rx_bytes_raw` | Sensor | `monthly_rx_bytes` | Bytes | Sensor | Native Byte sensor for UI conversion. Other display units may be used (e.g. GiB). |
| Monthly Total | `monthly_total_bytes_raw` | Sensor | `TX + RX` | Bytes | Sensor | Native Byte sensor for UI conversion. Other display units may be used (e.g. GB). |
| Monthly Sent GB | `monthly_tx_bytes` | Sensor | `monthly_tx_bytes / 10^9` | GB | Sensor | **Disabled by default (Legacy).** |
| Monthly Received GB | `monthly_rx_bytes` | Sensor | `monthly_rx_bytes / 10^9` | GB | Sensor | **Disabled by default (Legacy).** |
| Monthly Total GB | `monthly_total_bytes` | Sensor | `(TX+RX) / 10^9` | GB | Sensor | **Disabled by default (Legacy).** |
| Upload Speed | `realtime_tx_thrpt` | Sensor | `realtime_tx_thrpt` | B/s | Sensor | Instantaneous TX throughput. |
| Download Speed | `realtime_rx_thrpt` | Sensor | `realtime_rx_thrpt` | B/s | Sensor | Instantaneous RX throughput. |
| Session Sent | `realtime_tx_bytes` | Sensor | `realtime_tx_bytes` | Bytes | Sensor | Cumulative bytes since last connection. Resets on reconnect (`TOTAL_INCREASING`). |
| Session Received | `realtime_rx_bytes` | Sensor | `realtime_rx_bytes` | Bytes | Sensor | Cumulative bytes since last connection. Resets on reconnect (`TOTAL_INCREASING`). |

---

## 4. SMS Sub-Device (4 Entities)

_Group: `sms`_

| Name | Key | Type | Source (Raw Key) | Unit | Category | Notes |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Unread Msg | `sms_unread_num` | Sensor | `sms_unread_num` | - | Sensor |  |
| Total Msg | `msg_total` | Sensor | Sum of all NV/SIM banks | - | Sensor | Includes attributes for each bank. |
| Recent Msg | `msg_recent` | Sensor | `last_sms` content | - | Sensor | Content is hex-decoded from router. |
| Delete All Msg | `delete_all` | Button | API Call: `DELETE_SMS` (batch) | - | Control |  |

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

---

## Version Control

- **v1.0.0** (2026-05-07) - Initial versioned snapshot. Entity count updated 51 → 63. Added 12 new sensors (System: IMEI, Hardware Version, Battery, SIM IMSI, SIM ICCID; Signal: eNodeB ID, Network Mode, PPP Status; Data: Upload Speed, Download Speed, Session Sent, Session Received). Identity strategy updated from MAC to IMEI. \
- **v3.0.0-dev23** (2026-05-08) - Updated categories for Uptime, Last Updated, Best Connection, and WAN Connect Status. Renamed PPP Status to Bridge Mode. Set Battery to disabled by default.\
- **v3.0.1-dev5** (2026-05-10) - Migrated to hierarchical translation keys across all 63 entities.\
- **v3.0.2-dev3** (2026-05-22) - Added `system_uptime_duration` sensor and corrected legacy GB sensors to use base-10 (10^9) calculation.\
