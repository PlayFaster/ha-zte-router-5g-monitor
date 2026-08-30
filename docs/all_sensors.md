# ZTE Router 5G Integration - Entity Manifest

A complete list of the static entities and service actions provided by the integration, grouped by sub-device.

<!-- GENERATED:start -->

## Summary

| Sub-Device | Entity Count | Description            |
| :--------- | :----------- | :--------------------- |
| **Data**   | 15           | Data entities.         |
| **SMS**    | 5            | SMS entities.          |
| **Signal** | 40           | Signal entities.       |
| **System** | 33           | System entities.       |
| **Total**  | **93**       | Total static entities. |

## Data Sub-Device (15 Entities)

| Name | Key | Type | Unit | Category | Notes |
| :-- | :-- | :-- | :-- | :-- | :-- |
| Allowance | `data_allowance` | Sensor | B | Diagnostic | - |
| Reset Day | `data_clear_day` | Sensor | - | Diagnostic | - |
| Projected Cycle Usage | `data_projection` | Sensor | B | - | - |
| Alert Threshold | `data_volume_alert_percent` | Sensor | % | Diagnostic | - |
| Monthly Received GB | `monthly_rx_bytes` | Sensor | GB | - | **Disabled by default.** LTS: `total_increasing` |
| Monthly Received | `monthly_rx_bytes_raw` | Sensor | B | - | LTS: `total_increasing` |
| Monthly Total GB | `monthly_total_bytes` | Sensor | GB | - | **Disabled by default.** LTS: `total_increasing` |
| Monthly Total | `monthly_total_bytes_raw` | Sensor | B | - | LTS: `total_increasing` |
| Monthly Sent GB | `monthly_tx_bytes` | Sensor | GB | - | **Disabled by default.** LTS: `total_increasing` |
| Monthly Sent | `monthly_tx_bytes_raw` | Sensor | B | - | LTS: `total_increasing` |
| Session Received | `realtime_rx_bytes` | Sensor | B | - | - |
| Download Speed | `realtime_rx_thrpt` | Sensor | B/s | - | - |
| Session Sent | `realtime_tx_bytes` | Sensor | B | - | - |
| Upload Speed | `realtime_tx_thrpt` | Sensor | B/s | - | - |
| Data Limit Switch | `data_limit_switch` | Switch | - | Config | **Disabled by default.** |

## SMS Sub-Device (5 Entities)

| Name | Key | Type | Unit | Category | Notes |
| :-- | :-- | :-- | :-- | :-- | :-- |
| SMS Storage Full | `sms_storage_full` | Binary Sensor | - | Diagnostic | - |
| Delete All | `delete_all` | Button | - | - | - |
| Recent Msg | `msg_recent` | Sensor | - | - | - |
| Total Msg | `msg_total` | Sensor | - | - | LTS: `measurement` |
| Unread Msg | `sms_unread_num` | Sensor | - | - | LTS: `measurement` |

## Signal Sub-Device (40 Entities)

| Name | Key | Type | Unit | Category | Notes |
| :-- | :-- | :-- | :-- | :-- | :-- |
| Best Connection | `best_connection` | Binary Sensor | - | - | - |
| APN Selection Mode | `apn_mode` | Select | - | Config | - |
| APN Profile | `apn_profile` | Select | - | Config | - |
| Network Mode Selection | `net_select` | Select | - | Config | - |
| Cell ID | `cell_id` | Sensor | - | Diagnostic | - |
| eNodeB ID | `enodeb_id` | Sensor | - | Diagnostic | - |
| LTE Band Lock Mask | `lte_band_lock` | Sensor | - | Diagnostic | **Disabled by default.** |
| LTE Primary Band | `lte_ca_pcell_band` | Sensor | - | Diagnostic | - |
| LTE Primary Bandwidth | `lte_ca_pcell_bandwidth` | Sensor | MHz | Diagnostic | - |
| LTE Secondary Band | `lte_ca_scell_band` | Sensor | - | Diagnostic | **Disabled by default.** |
| LTE Secondary Bandwidth | `lte_ca_scell_bandwidth` | Sensor | MHz | Diagnostic | **Disabled by default.** |
| Carrier Aggregation Secondary Cells | `lte_multi_ca_scell_info` | Sensor | - | Diagnostic | **Disabled by default.** |
| LTE PCI | `lte_pci` | Sensor | - | Diagnostic | - |
| LTE RSRP | `lte_rsrp` | Sensor | dBm | - | LTS: `measurement` |
| LTE RSRQ | `lte_rsrq` | Sensor | dB | - | LTS: `measurement` |
| LTE RSSI | `lte_rssi` | Sensor | dBm | - | LTS: `measurement` |
| LTE SNR | `lte_snr` | Sensor | dB | - | LTS: `measurement` |
| MDM MCC | `mdm_mcc` | Sensor | - | Diagnostic | **Disabled by default.** |
| MDM MNC | `mdm_mnc` | Sensor | - | Diagnostic | **Disabled by default.** |
| Network Mode | `net_select` | Sensor | - | Diagnostic | - |
| Network Provider | `network_provider` | Sensor | - | Diagnostic | - |
| Network Type | `network_type` | Sensor | - | - | - |
| 5G Active Band | `nr5g_action_band` | Sensor | - | Diagnostic | - |
| 5G Active Channel | `nr5g_action_channel` | Sensor | - | Diagnostic | - |
| 5G PCI | `nr5g_pci` | Sensor | - | Diagnostic | - |
| Bridge Mode | `ppp_status` | Sensor | - | Diagnostic | - |
| Roaming MCC | `rmcc` | Sensor | - | Diagnostic | **Disabled by default.** |
| Roaming MNC | `rmnc` | Sensor | - | Diagnostic | **Disabled by default.** |
| Legacy RSCP | `rscp` | Sensor | dBm | - | **Disabled by default.** |
| Legacy RSSI | `rssi` | Sensor | dBm | - | **Disabled by default.** |
| Signal Bars | `signalbar` | Sensor | - | - | LTS: `measurement` |
| LTE Active Band | `wan_active_band` | Sensor | - | Diagnostic | - |
| LTE Active Channel | `wan_active_channel` | Sensor | - | Diagnostic | - |
| Network APN | `wan_apn` | Sensor | - | Diagnostic | - |
| WAN Connect Status | `wan_connect_status` | Sensor | - | Diagnostic | - |
| Carrier Aggregation | `wan_lte_ca` | Sensor | - | - | - |
| 5G RSRP | `z5g_rsrp` | Sensor | dBm | - | LTS: `measurement` |
| 5G RSRQ | `z5g_rsrq` | Sensor | dB | - | LTS: `measurement` |
| 5G RSSI | `z5g_rssi` | Sensor | dBm | - | LTS: `measurement` |
| 5G SNR | `z5g_sinr` | Sensor | dB | - | LTS: `measurement` |

## System Sub-Device (33 Entities)

| Name | Key | Type | Unit | Category | Notes |
| :-- | :-- | :-- | :-- | :-- | :-- |
| Integration Health | `integration_health` | Binary Sensor | - | Diagnostic | - |
| Reboot Schedule | `reboot_schedule` | Binary Sensor | - | Diagnostic | **Disabled by default.** |
| SIP ALG Enabled | `sip_alg_enabled` | Binary Sensor | - | Diagnostic | **Disabled by default.** |
| UPnP Enabled | `upnp_enabled` | Binary Sensor | - | Diagnostic | **Disabled by default.** |
| Web Page Sleep | `web_sleep` | Binary Sensor | - | Diagnostic | **Disabled by default.** |
| Web Page Auto-Wake | `web_wake` | Binary Sensor | - | Diagnostic | **Disabled by default.** |
| Reboot | `reboot` | Button | - | - | - |
| Refresh Now | `refresh` | Button | - | Config | - |
| Polling Interval | `polling_interval` | Number | s | Config | - |
| APN Interface Version | `apn_interface_version` | Sensor | - | Diagnostic | **Disabled by default.** |
| Battery | `battery_value` | Sensor | % | - | **Disabled by default.** |
| Device Uptime | `device_uptime` | Sensor | - | - | - |
| Hardware Version | `hardware_version` | Sensor | - | Diagnostic | - |
| IMEI | `imei` | Sensor | - | Diagnostic | **Disabled by default.** |
| LAN IP Address | `lan_ipaddr` | Sensor | - | Diagnostic | - |
| Last Updated | `last_updated` | Sensor | - | - | - |
| Model Name | `model_name` | Sensor | - | Diagnostic | - |
| WAN Fallback Mode | `opms_wan_auto_mode` | Sensor | - | Diagnostic | **Disabled by default.** |
| WAN Operating Mode | `opms_wan_mode` | Sensor | - | Diagnostic | **Disabled by default.** |
| 5G Modem Temperature | `pm_modem_5g` | Sensor | °C | Diagnostic | **Disabled by default.** LTS: `measurement` |
| 5G Radio Temperature | `pm_sensor_5g` | Sensor | °C | Diagnostic | **Disabled by default.** LTS: `measurement` |
| Ambient Modem Temperature | `pm_sensor_ambient` | Sensor | °C | Diagnostic | **Disabled by default.** LTS: `measurement` |
| Modem Temperature | `pm_sensor_mdm` | Sensor | °C | Diagnostic | **Disabled by default.** LTS: `measurement` |
| Power Amplifier Temperature | `pm_sensor_pa1` | Sensor | °C | Diagnostic | **Disabled by default.** LTS: `measurement` |
| Uptime Duration | `realtime_time` | Sensor | s | - | **Disabled by default.** |
| SIM ICCID | `sim_iccid` | Sensor | - | Diagnostic | **Disabled by default.** |
| SIM IMSI | `sim_imsi` | Sensor | - | Diagnostic | **Disabled by default.** |
| Time Server (SNTP) | `sntp_server` | Sensor | - | Diagnostic | **Disabled by default.** |
| Router Timezone | `sntp_timezone` | Sensor | - | Diagnostic | **Disabled by default.** |
| Firmware Version | `wa_inner_version` | Sensor | - | Diagnostic | - |
| WAN IP Address | `wan_ipaddr` | Sensor | - | Diagnostic | - |
| ODU LED Switch | `odu_led_switch` | Switch | - | Config | **Disabled by default.** |
| Pause Polling | `pause_polling` | Switch | - | Config | - |

<!-- GENERATED:end -->

---

## Debugging & Maintenance Reference

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

## Services

The integration registers several custom Home Assistant services for advanced SMS management:

### `send_sms`

Send an SMS message via the router.

- **Fields:**
  - `entry_id` (optional): The router config entry ID to use (optional if only one exists).
  - `target` (required): List of phone numbers/targets to send the message to.
  - `message` (required): Message content. Up to **765** characters of standard text, or **335** if it contains an emoji or other special character - the encoding is chosen per message.

### `delete_sms`

Delete a specific SMS message by its index.

- **Fields:**
  - `entry_id` (optional): The router config entry ID (optional if only one exists).
  - `index` (required): The index of the message to delete.

### `delete_all_sms`

Delete all SMS messages from the router inbox.

- **Fields:**
  - `entry_id` (optional): The router config entry ID (optional if only one exists).
  - `keep_last` (optional): Number of most recent messages to keep (default: 0, which deletes all; range 0-50).

### `get_sms_list`

Fetch a list of SMS messages from the router. This service returns a response payload.

- **Fields:**
  - `entry_id` (optional): The router config entry ID (optional if only one exists).
  - `page` (optional): Page number (default: 1; range 1-100).
  - `count` (optional): Messages per page (default: 20; range 1-50).
  - `box_type` (optional): Box to read from. **Default 0 = All Boxes.** Other options: 1=Local Inbox, 2=Local Sent, 3=Local Draft, 5=SIM Inbox, 6=SIM Sent, 7=SIM Draft, 8=Mix Inbox, 9=Mix Sent, 10=Mix Draft. The schema rejects any other value.
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
- **v3.4.0** (2026-07-30) — Live reconciliation via `sensor_review` (SOURCE=Via_HAB, SCOPE=Full) against all 92 entities, with the 34 disabled ones temporarily enabled. Counts 82 → 92 across the session: five discovery-report diagnostics, two web-power binary sensors, `Reset Day`, `Projected Cycle Usage`, `Allowance` and `Alert Threshold`. Renamed the uptime row `Uptime` → **`Device Uptime`** to match `strings.json` and the live instance — the only inventory discrepancy the review found. Platform counts now match live and `README.md` exactly at 75 / 7 / 3 / 3 / 3 / 1.
