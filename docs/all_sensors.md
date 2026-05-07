# ZTE Router 5G Integration - Entity Manifest

This document provides a comprehensive list of all 51 entities currently implemented in the ZTE Router 5G integration. It serves as a master reference for debugging, maintenance, and future development.

## Summary

| Sub-Device | Entity Count | Description |
| :-- | :-- | :-- |
| **System** | 9 | Core router info and global integration settings. |
| **Signal** | 32 | Cellular connectivity, signal strength (LTE/5G), and network info. |
| **Data** | 6 | Monthly traffic volume (Bytes and GB). |
| **SMS** | 4 | Message counts and recent message content. |
| **Total** | **51** |  |

---

## 1. System Sub-Device (9 Entities)

_Group: `system`_

| Name | Key | Type | Source (Raw Key) | Unit | Category | Notes |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Model Name | `model_name` | Sensor | `model_name` | - | Diagnostic |  |
| Firmware Version | `wa_inner_version` | Sensor | `wa_inner_version` | - | Diagnostic |  |
| WAN IP Address | `wan_ipaddr` | Sensor | `wan_ipaddr` | - | Diagnostic |  |
| LAN IP Address | `lan_ipaddr` | Sensor | `lan_ipaddr` | - | Diagnostic |  |
| Uptime | `device_uptime` | Sensor | `realtime_time` | Timestamp | Diagnostic | Calculated as `now() - uptime_seconds`. |
| Last Updated | `last_updated` | Sensor | `coordinator.last_update_success_time` | Timestamp | Diagnostic | Internal tracking of last successful poll. |
| Reboot | `reboot` | Button | API Call: `REBOOT_DEVICE` | - | Control |  |
| Pause Polling | `pause_polling` | Switch | Options: `stop_polling` | - | Config | State persists in `ConfigEntry.options`. |
| Polling Interval | `polling_interval` | Number | Options: `scan_interval` | s | Config | Range: 30s - 3600s. Persists in options. |

---

## 2. Signal Sub-Device (32 Entities)

_Group: `signal`_

| Name | Key | Type | Source (Raw Key) | Unit | Category | Notes |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Connection Status | `wan_connect_status` | Sensor | `wan_connect_status` | - | Sensor |  |
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
| LTE Secondary Band | `lte_ca_scell_band` | Sensor | `lte_ca_scell_band` | - | Diagnostic | **Disabled by default.** |
| LTE Secondary Bandwidth | `lte_ca_scell_bandwidth` | Sensor | `lte_ca_scell_bandwidth` | MHz | Diagnostic | **Disabled by default.** |
| LTE Active Band | `wan_active_band` | Sensor | `wan_active_band` | - | Diagnostic |  |
| LTE Active Channel | `wan_active_channel` | Sensor | `wan_active_channel` | - | Diagnostic |  |
| 5G RSRP | `z5g_rsrp` | Sensor | `Z5g_rsrp` | dBm | Sensor | Range: -140 to -30. |
| 5G RSRQ | `z5g_rsrq` | Sensor | `Z5g_rsrq` | dB | Sensor | Range: -40 to 0. |
| 5G RSSI | `z5g_rssi` | Sensor | `Z5g_rssi` | dBm | Sensor | Range: -120 to -20. |
| 5G SNR | `z5g_sinr` | Sensor | `Z5g_SINR` | dB | Sensor | Range: -20 to 50. |
| 5G PCI | `nr5g_pci` | Sensor | `nr5g_pci` | - | Diagnostic |  |
| 5G Active Band | `nr5g_action_band` | Sensor | `nr5g_action_band` | - | Diagnostic |  |
| 5G Active Channel | `nr5g_action_channel` | Sensor | `nr5g_action_channel` | - | Diagnostic |  |
| Legacy RSSI | `rssi` | Sensor | `rssi` | dBm | Sensor | **Disabled by default.** |
| Legacy RSCP | `rscp` | Sensor | `rscp` | dBm | Sensor | **Disabled by default.** |
| Best Connection | `best_connection` | Binary | Logic: `ENDC` + `ca_activated` | - | Diagnostic | ON if 5G and LTE-CA are both active. |

---

## 3. Data Sub-Device (6 Entities)

_Group: `data`_

| Name | Key | Type | Source (Raw Key) | Unit | Category | Notes |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Monthly Sent | `monthly_tx_bytes_raw` | Sensor | `monthly_tx_bytes` | Bytes | Sensor | Native Byte sensor for UI conversion. |
| Monthly Received | `monthly_rx_bytes_raw` | Sensor | `monthly_rx_bytes` | Bytes | Sensor | Native Byte sensor for UI conversion. |
| Monthly Total | `monthly_total_bytes_raw` | Sensor | `TX + RX` | Bytes | Sensor | Native Byte sensor for UI conversion. |
| Monthly Sent GB | `monthly_tx_bytes` | Sensor | `monthly_tx_bytes / 1024^3` | GB | Sensor | **Disabled by default (Legacy).** |
| Monthly Received GB | `monthly_rx_bytes` | Sensor | `monthly_rx_bytes / 1024^3` | GB | Sensor | **Disabled by default (Legacy).** |
| Monthly Total GB | `monthly_total_bytes` | Sensor | `(TX+RX) / 1024^3` | GB | Sensor | **Disabled by default (Legacy).** |

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

- **Base Unique ID**: The MAC address of the router (preferred) or `host_{IP}` (fallback).
- **Entity Unique ID**: `{{base_id}}_{{key}}`.
- **Device Identifiers**: `{{DOMAIN}}_{{base_id}}_{{group}}` (e.g., `zte_router_5g_001122334455_signal`).

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
