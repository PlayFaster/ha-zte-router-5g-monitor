# About Attributes — ZTE Router 5G Monitor 💡

Most entities in this integration carry a short built-in **`about`** note — a plain-language explanation of what the entity is, and for the signal metrics, what a good value looks like.

> [!TIP]
>
> **To see one in Home Assistant:** click the entity, open the **⋮ (three-dots) menu → Details**, and look for the **`about`** attribute.

---

> [!NOTE]
>
> **These notes are never written to your database.** They are declared as _unrecorded attributes_, so Home Assistant shows them live in the entity's details but the recorder ignores them entirely — they cost nothing to carry, however often the entity updates. See `dev_standards.md` Section 14.

**80 of the 92 entities carry a note.** The other 12 deliberately do not — a note on everything trains you to ignore notes. They are listed in full at the end, so the omissions stay visible and deliberate rather than looking like gaps.

ᴰ = **disabled by default.** Enable it from the entity's settings if you want it; it is hidden to keep the default entity list manageable.

---

<!-- GENERATED:start -->

## Data (15)

| Entity | Platform | Key | Note |
| :-- | :-- | :-- | :-- |
| Allowance | Sensor | `data_allowance` | The monthly data cap configured on the router itself, matching the Data Plan figure on its Data Management page. Useful as the threshold for an automation, so it tracks the router rather than a number typed into the automation. The router counts in binary units, so a 2 TB plan shows here as about 2199 GB - the same amount, counted the way Home Assistant counts. Unavailable if no limit is set, or if the limit is set in hours rather than data. |
| Reset Day | Sensor | `data_clear_day` | The day of the month on which the router zeroes its monthly data counters. This is the router's own billing cycle, which need not start on the 1st - check it against your provider's bill. If your month is shorter than this day, the reset happens on the last day instead. |
| Projected Cycle Usage | Sensor | `data_projection` | Projected total data usage for the current billing cycle, based on average daily consumption so far. It reads low on the first day of a cycle and settles within 24 hours. |
| Alert Threshold | Sensor | `data_volume_alert_percent` | The percentage of the Allowance at which the router raises its own alert - 80% of a 2 TB plan means it warns you at 1.6 TB. This is the router's internal threshold, separate from any automation you build in Home Assistant. |
| Monthly Received GB | Sensor | `monthly_rx_bytes` | Data downloaded this billing month, as counted by the router. Treat it as a close guide rather than an exact match for your ISP's billing. |
| Monthly Received | Sensor | `monthly_rx_bytes_raw` | Monthly download total, counted by the router. Home Assistant displays it in GB while storing the exact byte count, so it is both readable on a dashboard and precise in automations. |
| Monthly Total GB | Sensor | `monthly_total_bytes` | Combined upload and download for the billing month - the figure to compare against a data cap. |
| Monthly Total | Sensor | `monthly_total_bytes_raw` | Combined monthly upload and download - the figure to compare against a data cap. Home Assistant displays it in GB while storing the exact byte count, so nothing is rounded away in automations. |
| Monthly Sent GB | Sensor | `monthly_tx_bytes` | Data uploaded this billing month, as counted by the router. This is the router's own counter, not your ISP's - it resets when the router says so and may not match your operator's billing exactly. |
| Monthly Sent | Sensor | `monthly_tx_bytes_raw` | Monthly upload total, counted by the router. Home Assistant displays it in GB while storing the exact byte count, so no separate sensor is needed for automations that want the precise figure. |
| Session Received | Sensor | `realtime_rx_bytes` | Data downloaded during the current session, reset on every router reboot. For billing, use the monthly sensors instead. |
| Download Speed | Sensor | `realtime_rx_thrpt` | Current download rate at the instant of the last poll. Because it is sampled rather than averaged, it will not reflect a short burst that happened between polls. |
| Session Sent | Sensor | `realtime_tx_bytes` | Data uploaded during the current session - since the router last restarted, not since the start of the month. It resets to zero on every reboot. |
| Upload Speed | Sensor | `realtime_tx_thrpt` | Current upload rate. This is a snapshot taken at the moment the router was last polled, not an average - brief peaks between polls are not captured. |
| Data Limit Switch | Switch | `data_limit_switch` | Turns on the router's own monthly data cap. When the limit is reached the router stops passing traffic - it does not merely warn - so leave this off unless you have set the limit deliberately. The alert percentage governs when it warns you on the way there. |

## SMS (3)

| Entity | Platform | Key | Note |
| :-- | :-- | :-- | :-- |
| SMS Storage Full | Binary sensor | `sms_storage_full` | On when message storage has no room left. A full store makes the network stop delivering new messages, and nothing else in the integration reports that - which is the whole reason this entity exists. |
| Recent Msg | Sensor | `msg_recent` | The most recently received message. Sender, date and storage index are in the attributes; the index is what the delete action needs to remove this specific message. |
| Total Msg | Sensor | `msg_total` | Total messages held across every storage area - router memory and SIM, inbox, sent and drafts. The breakdown per area is in this sensor's attributes. Storage filling up stops new messages arriving. |

## Signal (53)

| Entity | Platform | Key | Note |
| :-- | :-- | :-- | :-- |
| APN Selection Mode | Select | `apn_mode` | Whether the router picks the APN itself (auto, using the network's default) or uses the profile you chose (manual). Auto is right for almost everyone. To switch to manual, choose an APN Profile instead - that sets the mode and the profile together, which is what the router requires. |
| APN Profile | Select | `apn_profile` | Which stored APN profile to connect with. The APN is the gateway your SIM's network expects; the wrong one usually means no data at all rather than slow data. Choosing one here also switches APN Selection Mode to manual. While the mode is auto the router uses the network's default APN, which may not be in this list - the Network APN sensor is the authoritative answer to what is actually in use. Note the Default profile stores no APN, so selecting it leaves Network APN reading unknown - the router's own page shows an empty field for the same reason. New profiles are added on the router's own web page, not here. |
| Network Mode Selection | Select | `net_select` | Which mobile technologies the router may use. These are the router's own web page settings under different names: 4G_AND_5G is Auto, LTE_AND_5G is 5G NSA, Only_5G is 5G SA, Only_LTE is 4G Only. Auto lets it fall back when a signal weakens; the Only options lock it. Locking to 5G can drop the connection entirely where 5G coverage is marginal, so prefer Auto unless you are testing. |
| 5G RSRP Antenna 1 | Sensor | `5g_rsrp_antenna_1` | Reference signal strength at the first 5G receiver, in dBm. The two receivers see the same cell through different antennas, so a persistent gap between them points at placement or an obstruction rather than at the network. |
| 5G RSRP Antenna 2 | Sensor | `5g_rsrp_antenna_2` | Reference signal strength at the second 5G receiver, in dBm. Compare with the first: a steady difference is an antenna or placement effect, not a change in coverage. |
| APN Changes | Sensor | `apn_changes` | How many times the APN in use has changed. Usually zero - a change you did not make points at the operator reprovisioning the connection. |
| CA Secondary Cell RSRP | Sensor | `ca_scell_rsrp` | Reference signal strength on the aggregated secondary carrier, in dBm. Carrier aggregation adds a second band alongside the primary one; this is how strong that second band is. |
| CA Secondary Cell RSRQ | Sensor | `ca_scell_rsrq` | Reference signal quality on the aggregated secondary carrier, in dB. Typically -10 or better is good, below -15 poor. |
| CA Secondary Cell RSSI | Sensor | `ca_scell_rssi` | Total received power on the aggregated secondary carrier, in dBm - wanted signal, interference and noise together. |
| CA Secondary Cell SNR | Sensor | `ca_scell_snr` | Signal-to-noise ratio on the aggregated secondary carrier, in dB. Worth comparing against the primary: the secondary band often carries the cleaner signal, which the headline SNR does not show. |
| Cell Changes | Sensor | `cell_changes` | How many times the router has been handed to a different 4G cell. Unlike the others this moves on its own as the network balances load, so the useful reading is the rate rather than the total - a step change in handovers per day is worth looking at. |
| Cell ID | Sensor | `cell_id` | The identifier of the 4G cell currently serving the router. A change means you have been handed to a different cell, which often explains a sudden change in speed or signal. |
| eNodeB ID | Sensor | `enodeb_id` | The identifier of the 4G base station (eNodeB) serving you - the mast itself, rather than the individual sector, which is the Cell ID. A change here means you have moved to a different mast. |
| LTE Band Lock Mask | Sensor | `lte_band_lock` | Hexadecimal bitmask of the 4G bands the modem is permitted to use. Bit 0 is band 1, so bit 2 is band 3 and bit 19 is band 20 - 0x60088080045 means bands 1, 3, 7, 20, 28, 32, 42 and 43. Use it to confirm which bands a band lock has left available; locking to one the router cannot see leaves it with no service. |
| LTE Primary Band | Sensor | `lte_ca_pcell_band` | The primary 4G band carrying your connection. Lower-numbered bands generally travel further and penetrate buildings better; higher bands usually carry more capacity over shorter distances. |
| LTE Primary Bandwidth | Sensor | `lte_ca_pcell_bandwidth` | The channel width of the primary 4G band, in MHz. Wider is faster: 20 MHz carries roughly four times the data of 5 MHz, all else being equal. |
| LTE Secondary Band | Sensor | `lte_ca_scell_band` | The secondary 4G band added by Carrier Aggregation. Only present while aggregation is active. |
| LTE Secondary Bandwidth | Sensor | `lte_ca_scell_bandwidth` | Channel width of the aggregated secondary 4G band, in MHz. It adds to the primary band's capacity rather than replacing it. |
| Carrier Aggregation Secondary Cells | Sensor | `lte_multi_ca_scell_info` | Raw descriptor of the additional 4G carriers in use, one semicolon-terminated group per secondary cell. The fields are cell index, PCI, a value that varies between polls, LTE band, EARFCN and bandwidth in MHz - so '2,352,1,20,6300,10' is band 20 on EARFCN 6300 at 10 MHz. The named Carrier Aggregation sensors are friendlier for display. |
| LTE PCI | Sensor | `lte_pci` | Physical Cell Identity - a number from 0 to 503 identifying the specific 4G cell sector serving the router. Neighboring sectors reuse the range, so a change means you have moved to a different sector or mast. |
| LTE RSRP | Sensor | `lte_rsrp` | Reference Signal Received Power - the strength of the 4G signal, in dBm. This is the number to watch when aiming or siting the router; SNR is the better guide to how fast the connection will actually go. Typically: better than -80 is excellent, -80 to -90 good, -90 to -100 fair, below -100 poor. Values are negative, so closer to zero is stronger. |
| LTE RSRQ | Sensor | `lte_rsrq` | Reference Signal Received Quality - 4G signal quality rather than raw strength, in dB. It reflects how much interference and load the cell is carrying. Typically: better than -10 is excellent, -10 to -15 good, -15 to -20 fair, below -20 poor. Strong RSRP with poor RSRQ usually means a busy cell. |
| LTE RSSI | Sensor | `lte_rssi` | Received Signal Strength Indicator - total received power across the 4G channel, including noise and interference, in dBm. Less diagnostic than RSRP, because it cannot separate your cell's signal from everything else on the frequency. |
| LTE SNR | Sensor | `lte_snr` | Signal-to-Noise Ratio for 4G, in dB - how far the wanted signal rises above the background noise. This is the best predictor of achievable speed. Typically: above 20 is excellent, 13 to 20 good, 0 to 13 fair, below 0 poor. |
| MDM MCC | Sensor | `mdm_mcc` | Mobile Country Code - a three-digit code identifying the country of the network the modem is attached to (for example 272 = Ireland). |
| MDM MNC | Sensor | `mdm_mnc` | Mobile Network Code - identifies the individual operator within that country. Together with the MCC it uniquely names the network you are on. |
| Network Mode | Sensor | `net_select` | The network technology the router is currently allowed to use, as chosen by the Network Mode control. Restricting it can stabilize a connection that keeps switching between 4G and 5G. |
| Network Mode Config | Sensor | `net_select_config` | Whether the router picks its network mode itself or holds the one you chose - the Automatic or Manual setting on its own network selection page. Automatic lets it fall back as coverage changes; Manual keeps the Network Mode you set until you change it. |
| Network Provider | Sensor | `network_provider` | The mobile network the router is registered to. This can differ from the SIM's home network while roaming. |
| Network Type | Sensor | `network_type` | The connection technology in use. ENDC and LTE-NSA are both 5G non-standalone, where a 4G anchor carries the connection alongside a 5G carrier: ENDC means the 5G carrier is actually in use, LTE-NSA means the router is attached for 5G but is running on the 4G anchor alone, which is what weak 5G coverage looks like. Plain LTE means no 5G at all. |
| 5G Active Band | Sensor | `nr5g_action_band` | The active 5G NR band. Bands below 1 GHz reach furthest, mid-band (around 3.5 GHz) is the usual balance of speed and coverage, and high bands are fastest over the shortest distance. |
| 5G Active Channel | Sensor | `nr5g_action_channel` | The 5G channel number in use within the active band, expressed as an NR-ARFCN. Useful when comparing your connection against neighboring cells. |
| 5G NSA Band Lock | Sensor | `nr5g_nsa_band_lock` | The 5G bands the router may use in non-standalone mode, where 5G runs alongside a 4G anchor. The counterpart to LTE Band Lock. |
| 5G PCI | Sensor | `nr5g_pci` | Physical Cell Identity for the 5G cell, from 0 to 1007. A change means the router has been handed to a different 5G sector or mast. |
| 5G SA Band Lock | Sensor | `nr5g_sa_band_lock` | The 5G bands the router may use in standalone mode, where 5G runs without a 4G anchor. |
| Bridge Mode | Sensor | `ppp_status` | Whether the router is currently passing the connection straight through in bridge mode - connected means it is. This is the live session, not the configuration: WAN Operating Mode reports which mode the router is set to, bridge or gateway, while this reports whether that session is actually up. It can show disconnected while the radio signal is still strong, which points at an APN or account problem rather than coverage. |
| Provider Changes | Sensor | `provider_changes` | How many times the registered network operator has changed. On a fixed installation this should be zero unless you have changed SIM or the SIM has roamed. |
| Roaming MCC | Sensor | `rmcc` | Mobile Country Code of the network the router is registered to, as opposed to the modem's own view. It differs from the modem MCC while roaming. |
| Roaming MNC | Sensor | `rmnc` | Mobile Network Code of the registered network. Compare with the modem MNC to tell whether the router is roaming. |
| Roaming State | Sensor | `roaming_state` | Whether the SIM is on its home network or roaming. Roaming can carry different charges and different speed limits. |
| Legacy RSCP | Sensor | `rscp` | Received Signal Code Power, in dBm - a 3G/UMTS measurement. Only meaningful if the router has fallen back to 3G, which on a 5G CPE usually signals a coverage problem. |
| Legacy RSSI | Sensor | `rssi` | Combined signal strength across all active radio frequencies, in dBm. Technology-specific LTE and 5G RSRP metrics provide more diagnostic detail. |
| Signal Bars | Sensor | `signalbar` | The router's own signal rating, 0 to 5, the same one shown on its web page. It is a coarse summary - for anything precise use RSRP or SNR, which is what the bars are derived from. |
| SINR | Sensor | `sinr` | Signal to Noise Ratio for the cell currently serving the router, in dB - how far the wanted signal sits above the noise and interference around it. Reported by the router without saying which radio it measured, so it is separate from LTE SNR and from 5G SINR, which the router names individually. Higher is better; below about 0 dB the connection is struggling. |
| LTE Active Band | Sensor | `wan_active_band` | The frequency band currently carrying your connection. Which band you land on is decided by the network, and it affects both range and speed. |
| LTE Active Channel | Sensor | `wan_active_channel` | The specific radio channel number in use within the active band. Mainly of interest when comparing against neighboring cells or diagnosing interference. |
| Network APN | Sensor | `wan_apn` | Access Point Name - the gateway the router is actually connected with. This is the authoritative answer: while APN Selection Mode is auto the router uses the network's own default, which may not be one of your stored profiles, so the APN Profile selector can differ from this or read unknown. A wrong APN is a common cause of a router that has good signal but no working data. |
| WAN Connect Status | Sensor | `wan_connect_status` | Whether the router currently has a data connection to the mobile network. This covers the mobile side only - it can report connected while the wider internet is unreachable. |
| Carrier Aggregation | Sensor | `wan_lte_ca` | Whether Carrier Aggregation is active - the modem combining two or more frequency bands at once for extra bandwidth. When active, the secondary band appears in the SCell sensors. |
| 5G RSRP | Sensor | `z5g_rsrp` | Reference Signal Received Power for the 5G carrier, in dBm - the 5G equivalent of LTE RSRP, and the number to watch when siting the router for 5G. Typically: better than -80 is excellent, -80 to -90 good, -90 to -100 fair, below -100 poor. |
| 5G RSRQ | Sensor | `z5g_rsrq` | Reference Signal Received Quality for 5G, in dB - quality rather than strength, reflecting interference and cell load. Typically: better than -10 is excellent, -10 to -15 good, -15 to -20 fair, below -20 poor. |
| 5G RSSI | Sensor | `z5g_rssi` | Total received power across the 5G channel, in dBm, including noise and interference. Use 5G RSRP for a cleaner measure of your own cell's strength. |
| 5G SNR | Sensor | `z5g_sinr` | Signal-to-Noise Ratio for the 5G carrier, in dB - how far the wanted signal rises above everything competing with it. This is the best predictor of achievable 5G speed. Typically: above 20 is excellent, 13 to 20 good, 0 to 13 fair, below 0 poor. |

## System (35)

| Entity | Platform | Key | Note |
| :-- | :-- | :-- | :-- |
| Reboot Schedule | Binary sensor | `reboot_schedule` | Whether the router reboots itself on an internal schedule. Execution time, repeat mode (weekly/monthly), and both candidate days are in the attributes. |
| SIP ALG Enabled | Binary sensor | `sip_alg_enabled` | SIP ALG rewrites internet-telephony traffic as it passes through. It is meant to help, and frequently does the opposite: one-way audio and calls that drop after a set time are the classic symptoms. If VoIP misbehaves, this is the first thing to turn off. |
| UPnP Enabled | Binary sensor | `upnp_enabled` | Whether the router lets devices open their own inbound ports. Convenient for games and consoles, but it means any device on the network can expose itself without being asked. On a router in bridge mode this usually has no effect - your main firewall handles it. |
| Web Page Sleep | Binary sensor | `web_sleep` | Whether the router puts its web management page to sleep after inactivity. This affects browser logins only, not integration polling. |
| Web Page Auto-Wake | Binary sensor | `web_wake` | Whether the router's web management interface automatically wakes from sleep when accessed. |
| APN Interface Version | Sensor | `apn_interface_version` | Which version of the router's own APN configuration format is in use. Only of interest when an APN change is not taking effect. |
| Battery | Sensor | `battery_value` | Battery charge level for portable ZTE models. Mains-powered units lacking a battery report 100%. |
| Connection Failure Count | Sensor | `connection_failure_count` | How many times the router has failed to establish the mobile data connection since it last restarted. A rising count with the connection apparently up means it is dropping and recovering. |
| Firmware Update State | Sensor | `current_upgrade_state` | Whether a firmware update is running. The value is the router's own, reported unchanged. |
| Device Uptime | Sensor | `device_uptime` | The moment the router last booted, held steady between reboots rather than recalculated each poll. It only moves when the router's own uptime counter drops, so a genuine restart is easy to trigger automations on. |
| Firmware Changes | Sensor | `firmware_changes` | How many times the router's firmware version has changed since this integration started watching. The version sensor itself keeps no long-term history, so this is what makes an operator's silent update visible months later. The versions and dates are on the Firmware Version sensor's history attribute. |
| IMEI | Sensor | `imei` | International Mobile Equipment Identity - the modem's unique 15-digit hardware serial, used by networks to identify the device itself rather than the SIM. This integration also uses it as the stable identity for your router, so entity history survives an IP change. |
| Modem State | Sensor | `modem_state` | What the modem itself reports about its own startup, separately from whether a connection is up. Useful when the router answers but nothing is passing traffic. |
| Firmware Update Available | Sensor | `new_version_state` | Whether the router has found a firmware update. The value is the router's own, reported unchanged. |
| WAN Fallback Mode | Sensor | `opms_wan_auto_mode` | The WAN operating mode the router falls back to automatically. A difference between this and the active mode is normal. |
| WAN Operating Mode | Sensor | `opms_wan_mode` | Whether the router is passing traffic as a gateway of its own or bridging it straight through to equipment behind it. Changing this is deliberately not offered here: it alters the path this integration reaches the router over, so use the router's own web page where a mistake can still be undone. |
| 5G Modem Temperature | Sensor | `pm_modem_5g` | Temperature reported by the router's 5G modem section. Not reported by all models. |
| 5G Radio Temperature | Sensor | `pm_sensor_5g` | Temperature reported by the router's 5G radio. Not reported by all models. |
| Ambient Modem Temperature | Sensor | `pm_sensor_ambient` | Internal air temperature inside the modem, away from the radio itself. Read alongside the power amplifier temperature it indicates whether the unit as a whole is running hot or just the transmitter. Not reported by all models. |
| Modem Temperature | Sensor | `pm_sensor_mdm` | Temperature of the 4G/LTE cellular baseband module. Not reported by all models. |
| Power Amplifier Temperature | Sensor | `pm_sensor_pa1` | Temperature of the RF power amplifier driving the transmit signal, typically the warmest component in the unit. Not reported by all models. |
| Uptime Duration | Sensor | `realtime_time` | How long the router has been running since its last boot. The Device Uptime sensor expresses the same fact as a timestamp, which is usually the easier one to automate against. |
| SIM ICCID | Sensor | `sim_iccid` | Integrated Circuit Card ID - the SIM card's own serial number, printed on the card itself. Useful for identifying which SIM is in the router without opening it. |
| SIM IMSI | Sensor | `sim_imsi` | International Mobile Subscriber Identity - the unique number identifying your SIM's subscription on the network, as distinct from the IMEI which identifies the hardware. |
| SIM Lock State | Sensor | `sim_lock_state` | Whether the SIM is asking for its PIN. A SIM waiting on a PIN presents as no service, which otherwise reads as a coverage fault, and the attempt counters only say how many tries are left rather than whether one is being asked for. |
| SIM PIN Attempts Remaining | Sensor | `sim_pin_attempts` | PIN attempts left before the SIM locks and needs the PUK. A SIM that has locked presents as no service, which otherwise looks like a coverage or connection fault. |
| SIM PUK Attempts Remaining | Sensor | `sim_puk_attempts` | PUK attempts left before the SIM is permanently blocked and has to be replaced by the operator. |
| Time Server (SNTP) | Sensor | `sntp_server` | The time server the router synchronizes its clock from. An unreachable time server can make the timestamps on SMS messages and logs wrong, so it is worth checking if dates look implausible. |
| Router Timezone | Sensor | `sntp_timezone` | The router's configured base timezone and Daylight Saving Time (DST) offset - for example '0-1' represents base offset UTC+0 with DST active. |
| Firmware Update Result | Sensor | `upgrade_result` | The outcome of the router's last firmware update attempt. Reads error where an update was tried and did not complete, which the update-state entities do not show. |
| Firmware Version | Sensor | `wa_inner_version` | The router's firmware build string. Worth recording before a firmware update, so you can tell what changed if the router starts behaving differently afterwards. |
| WAN IP Changes | Sensor | `wan_ip_changes` | How many times the router's public WAN address has changed. A rising count means your operator is reassigning it, which breaks anything that relied on it staying put. |
| WAN IP Address | Sensor | `wan_ipaddr` | The address your ISP has given the router on the mobile network - what the internet sees. Often a shared carrier-grade NAT address, which is why inbound connections and port forwarding usually do not work on mobile broadband. |
| WAN Mode Changes | Sensor | `wan_mode_changes` | How many times the router has switched between bridge and gateway operation. This changes what the router does to your whole network, and an operator can change it remotely. |
| ODU LED Switch | Switch | `odu_led_switch` | Turns the status light on the outdoor unit on or off. Cosmetic only - the connection is unaffected, so switching it off is safe if the unit is visible from a window or a bedroom. The router reports the light's real state, so this reflects the unit rather than the last command sent. |

## WiFi (2)

| Entity | Platform | Key | Note |
| :-- | :-- | :-- | :-- |
| Wi-Fi Clients Connected | Sensor | `wifi_clients` | How many devices are connected to the router's Wi-Fi right now, across all its networks. Counts wireless clients only - anything on a network cable is not included. |
| Wi-Fi Enabled | Sensor | `wifi_enabled` | Whether the router's Wi-Fi radios are switched on. Reported as the router states it, so this reflects the radios rather than the last command sent to them. |

## Entities without an `about` note (13)

The following entities carry no `about` attribute (self-explanatory or intentionally unannotated):

| Entity               | Platform      | Key                    | Group  |
| :------------------- | :------------ | :--------------------- | :----- |
| Delete All           | Button        | `delete_all`           | SMS    |
| Unread Msg           | Sensor        | `sms_unread_num`       | SMS    |
| Best Connection      | Binary sensor | `best_connection`      | Signal |
| Integration Health   | Binary sensor | `integration_health`   | System |
| Operator Provisioned | Binary sensor | `operator_provisioned` | System |
| Reboot               | Button        | `reboot`               | System |
| Refresh Now          | Button        | `refresh`              | System |
| Polling Interval     | Number        | `polling_interval`     | System |
| Hardware Version     | Sensor        | `hardware_version`     | System |
| LAN IP Address       | Sensor        | `lan_ipaddr`           | System |
| Last Updated         | Sensor        | `last_updated`         | System |
| Model Name           | Sensor        | `model_name`           | System |
| Pause Polling        | Switch        | `pause_polling`        | System |

<!-- GENERATED:end -->

---

_The `about=` fields and `_attr_about` declarations in `custom_components/zte_router_5g/` are the source of truth for these notes. Edit them there — this file is regenerated from the **live** entity attributes by `sensor_review` (`SCOPE=About`), which is what proves a note actually reaches the user rather than merely being declared. Do not hand-edit the tables._

Created: 2026-07-28 Last Updated: 2026-07-30

---

## Version Control

- **v1.5.0** (2026-08-01) — Regenerated from live via `sensor_review` (SOURCE=Via_HAB, SCOPE=Full) after a Home Assistant restart, verified before the fetch by confirming `Signal Bars` published its post-edit text. Coverage unchanged at **86 of 92**; the six deliberate omissions are unchanged. Eight note texts refreshed, all of them this file lagging same-day code edits: `Signal Bars` and `5G SNR` no longer say SINR, since the integration reports what the router labels SNR and cannot verify what the modem computes; `LTE RSRP` no longer competes with SNR for "the single most useful number"; `Network APN` and `APN Profile` say `unknown` rather than "blank", which is what Home Assistant actually shows for an empty value; and three notes changed `neighbouring` to `neighboring` under the US-spelling rule. No note was found missing, and every entity declaring one publishes it — no delivery faults.
- **v1.3.0** (2026-07-30) — Regenerated from live via `sensor_review` (SOURCE=Via_HAB, SCOPE=Full) against all 92 entities with the 34 disabled ones temporarily enabled. Coverage 84 of 91 → **85 of 92**. Added `Allowance` and `Alert Threshold`; removed `Data Volume Alert`, which was **renamed in code** rather than dropped in delivery — the review confirmed separately that every entity declaring a note publishes one. Nineteen note texts updated after a rewrite pass that removed vendor-blaming and outdated display advice. The seven deliberate omissions are unchanged.
- **v1.2.0** (2026-07-29) — Added an **Entities without a note** section covering all 14, so the omissions are visible and deliberate rather than reading as gaps. Flagged APN Profile and Network Mode Selection as the only two where a wrong choice has a real cost, for a later decision. Header reworded to state coverage as 68 of 82.
- **v1.1.0** (2026-07-29) — Added the five thermal sensor notes (Power Amplifier, Ambient Modem, Modem, 5G Modem, 5G Radio Temperature), closing the deferral recorded in `[3.3.1-dev1]`. Count 63 → 68. Regenerated from the **live** entity attributes via `sensor_review` (SCOPE=About), which also confirmed no note is being dropped in delivery: 68 declared in source, 68 published live.
- **v1.0.0** (2026-07-28) — Initial document, 63 notes.
- **v1.4.0** (2026-07-31) — Reconciled against live via `sensor_review` (SOURCE=Via_HAB, SCOPE=Full) with all 34 disabled entities temporarily enabled. Coverage **85 of 92 → 86 of 92**. Four notes rewritten in code and refreshed here — the three APN/network selects and **Network APN** — after hardware testing established behavior that reads as broken without explanation: choosing a profile forces the mode to manual, the APN in use in auto mode need not appear in the profile list, and the `Default` profile stores an empty APN. **ODU LED Switch** gains a note and leaves the deliberate-omission list (7 → 6): it was self-explanatory when that list was drawn up, but it is now a control whose position is confirmed by reading the router back, which is worth saying. No delivery faults found — every documented note reaches the user.
