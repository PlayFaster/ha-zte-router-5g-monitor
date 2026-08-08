# About Attributes — ZTE Router 5G Monitor 💡

Most entities in this integration carry a short built-in **`about`** note — a plain-language explanation of what the entity is, and for the signal metrics, what a good value looks like.

> [!TIP]
>
> **To see one in Home Assistant:** click the entity, open the **⋮ (three-dots) menu → Details**, and look for the **`about`** attribute.

---

> [!NOTE]
>
> **These notes are never written to your database.** They are declared as _unrecorded attributes_, so Home Assistant shows them live in the entity's details but the recorder ignores them entirely — they cost nothing to carry, however often the entity updates. See `dev_standards.md` Section 14.

**86 of the 92 entities carry a note.** The other 6 deliberately do not — a note on everything trains you to ignore notes. They are listed in full at the end, so the omissions stay visible and deliberate rather than looking like gaps.

ᴰ = **disabled by default.** Enable it from the entity's settings if you want it; it is hidden to keep the default entity list manageable.

---

## Contents

- [🔧 System](#-system) — 29 entities
- [📡 Signal](#-signal) — 40 entities
- [📉 Data](#-data) — 15 entities
- [💬 SMS](#-sms) — 2 entities
- [🚫 Entities without a note](#-entities-without-a-note) — 6 entities

---

## 🔧 System

Router identity, firmware, uptime and the controls.

| Entity | About |
| :-- | :-- |
| **5G Modem Temperature** ᴰ | Temperature reported by the router's 5G modem section. Not reported by all models. |
| **5G Radio Temperature** ᴰ | Temperature reported by the router's 5G radio. Not reported by all models. |
| **Ambient Modem Temperature** ᴰ | Internal air temperature inside the modem, away from the radio itself. Read alongside the power amplifier temperature it indicates whether the unit as a whole is running hot or just the transmitter. Not reported by all models. |
| **APN Interface Version** ᴰ | Which version of the router's own APN configuration format is in use. Only of interest when an APN change is not taking effect. |
| **Battery** ᴰ | Battery charge level for portable ZTE models. Mains-powered units lacking a battery report 100%. |
| **Device Uptime** | The moment the router last booted, held steady between reboots rather than recalculated each poll. It only moves when the router's own uptime counter drops, so a genuine restart is easy to trigger automations on. |
| **Firmware Version** | The router's firmware build string. Worth recording before a firmware update, so you can tell what changed if the router starts behaving differently afterwards. |
| **IMEI** ᴰ | International Mobile Equipment Identity - the modem's unique 15-digit hardware serial, used by networks to identify the device itself rather than the SIM. This integration also uses it as the stable identity for your router, so entity history survives an IP change. |
| **Integration Health** | On when the integration detects a problem with itself, including the case where a fetch succeeds but returns nothing usable - which nothing else catches. The attributes carry the detail. It stays available even when every other entity has gone unavailable, because that is exactly when it has something to say. |
| **Modem Temperature** ᴰ | Temperature of the 4G/LTE cellular baseband module. Not reported by all models. |
| **ODU LED Switch** ᴰ | Turns the status light on the outdoor unit on or off. Cosmetic only - the connection is unaffected, so switching it off is safe if the unit is visible from a window or a bedroom. The router reports the light's real state, so this reflects the unit rather than the last command sent. |
| **Pause Polling** | Stops scheduled polling without removing the integration. Useful when you need the router's own web page, since it allows only one login session at a time. Entities hold their last known values, and explicit actions such as Refresh Now still fetch. |
| **Polling Interval** | How often the integration fetches from the router, from 30 seconds to 1 hour. The router permits only one login session at a time, so polling less often leaves its web page free for longer. |
| **Power Amplifier Temperature** ᴰ | Temperature of the RF power amplifier driving the transmit signal, typically the warmest component in the unit. Not reported by all models. |
| **Reboot** | Restarts the router. The connection drops for a minute or two, and session data counters reset to zero. Monthly counters are unaffected. |
| **Reboot Schedule** ᴰ | Whether the router reboots itself on an internal schedule. Execution time, repeat mode (weekly/monthly), and both candidate days are in the attributes. |
| **Refresh Now** | Fetches from the router immediately, without waiting for the next scheduled poll. It works even while polling is paused - explicit actions always fetch. |
| **Router Timezone** ᴰ | The router's configured base timezone and Daylight Saving Time (DST) offset - for example '0-1' represents base offset UTC+0 with DST active. |
| **SIM ICCID** ᴰ | Integrated Circuit Card ID - the SIM card's own serial number, printed on the card itself. Useful for identifying which SIM is in the router without opening it. |
| **SIM IMSI** ᴰ | International Mobile Subscriber Identity - the unique number identifying your SIM's subscription on the network, as distinct from the IMEI which identifies the hardware. |
| **SIP ALG Enabled** ᴰ | SIP ALG rewrites internet-telephony traffic as it passes through. It is meant to help, and frequently does the opposite: one-way audio and calls that drop after a set time are the classic symptoms. If VoIP misbehaves, this is the first thing to turn off. |
| **Time Server (SNTP)** ᴰ | The time server the router synchronies its clock from. An unreachable time server can make the timestamps on SMS messages and logs wrong, so it is worth checking if dates look implausible. |
| **UPnP Enabled** ᴰ | Whether the router lets devices open their own inbound ports. Convenient for games and consoles, but it means any device on the network can expose itself without being asked. On a router in bridge mode this usually has no effect - your main firewall handles it. |
| **Uptime Duration** ᴰ | How long the router has been running since its last boot. The Device Uptime sensor expresses the same fact as a timestamp, which is usually the easier one to automate against. |
| **WAN Fallback Mode** ᴰ | The WAN operating mode the router falls back to automatically. A difference between this and the active mode is normal. |
| **WAN IP Address** | The address your ISP has given the router on the mobile network - what the internet sees. Often a shared carrier-grade NAT address, which is why inbound connections and port forwarding usually do not work on mobile broadband. |
| **WAN Operating Mode** ᴰ | Whether the router is passing traffic as a gateway of its own or bridging it straight through to equipment behind it. Changing this is deliberately not offered here: it alters the path this integration reaches the router over, so use the router's own web page where a mistake can still be undone. |
| **Web Page Auto-Wake** ᴰ | Whether the router's web management interface automatically wakes from sleep when accessed. |
| **Web Page Sleep** ᴰ | Whether the router puts its web management page to sleep after inactivity. This affects browser logins only, not integration polling. |

## 📡 Signal

Cellular connectivity and radio measurements.

| Entity | About |
| :-- | :-- |
| **5G Active Band** | The active 5G NR band. Bands below 1 GHz reach furthest, mid-band (around 3.5 GHz) is the usual balance of speed and coverage, and high bands are fastest over the shortest distance. |
| **5G Active Channel** | The 5G channel number in use within the active band, expressed as an NR-ARFCN. Useful when comparing your connection against neighboring cells. |
| **5G PCI** | Physical Cell Identity for the 5G cell, from 0 to 1007. A change means the router has been handed to a different 5G sector or mast. |
| **5G RSRP** | Reference Signal Received Power for the 5G carrier, in dBm - the 5G equivalent of LTE RSRP, and the number to watch when siting the router for 5G. Typically: better than -80 is excellent, -80 to -90 good, -90 to -100 fair, below -100 poor. |
| **5G RSRQ** | Reference Signal Received Quality for 5G, in dB - quality rather than strength, reflecting interference and cell load. Typically: better than -10 is excellent, -10 to -15 good, -15 to -20 fair, below -20 poor. |
| **5G RSSI** | Total received power across the 5G channel, in dBm, including noise and interference. Use 5G RSRP for a cleaner measure of your own cell's strength. |
| **5G SNR** | Signal-to-Noise Ratio for the 5G carrier, in dB - how far the wanted signal rises above everything competing with it. This is the best predictor of achievable 5G speed. Typically: above 20 is excellent, 13 to 20 good, 0 to 13 fair, below 0 poor. |
| **APN Profile** | Which stored APN profile to connect with. The APN is the gateway your SIM's network expects; the wrong one usually means no data at all rather than slow data. Choosing one here also switches APN Selection Mode to manual. While the mode is auto the router uses the network's default APN, which may not be in this list - the Network APN sensor is the authoritative answer to what is actually in use. Note the Default profile stores no APN, so selecting it leaves Network APN reading unknown - the router's own page shows an empty field for the same reason. New profiles are added on the router's own web page, not here. |
| **APN Selection Mode** | Whether the router picks the APN itself (auto, using the network's default) or uses the profile you chose (manual). Auto is right for almost everyone. To switch to manual, choose an APN Profile instead - that sets the mode and the profile together, which is what the router requires. |
| **Best Connection** | On when the router has the best connection type it can get - a 5G carrier aggregated with the 4G anchor. Off does not mean a fault; it usually means 5G coverage is unavailable where the router is sited. |
| **Bridge Mode** | Whether the router is currently passing the connection straight through in bridge mode - connected means it is. This is the live session, not the configuration: WAN Operating Mode reports which mode the router is set to, bridge or gateway, while this reports whether that session is actually up. It can show disconnected while the radio signal is still strong, which points at an APN or account problem rather than coverage. |
| **Carrier Aggregation** | Whether Carrier Aggregation is active - the modem combining two or more frequency bands at once for extra bandwidth. When active, the secondary band appears in the SCell sensors. |
| **Carrier Aggregation Secondary Cells** ᴰ | Raw descriptor of the additional 4G carriers in use, one semicolon-terminated group per secondary cell. The fields are cell index, PCI, a value that varies between polls, LTE band, EARFCN and bandwidth in MHz - so '2,352,1,20,6300,10' is band 20 on EARFCN 6300 at 10 MHz. The named Carrier Aggregation sensors are friendlier for display. |
| **Cell ID** | The identifier of the 4G cell currently serving the router. A change means you have been handed to a different cell, which often explains a sudden change in speed or signal. |
| **eNodeB ID** | The identifier of the 4G base station (eNodeB) serving you - the mast itself, rather than the individual sector, which is the Cell ID. A change here means you have moved to a different mast. |
| **Legacy RSCP** ᴰ | Received Signal Code Power, in dBm - a 3G/UMTS measurement. Only meaningful if the router has fallen back to 3G, which on a 5G CPE usually signals a coverage problem. |
| **Legacy RSSI** ᴰ | Combined signal strength across all active radio frequencies, in dBm. Technology-specific LTE and 5G RSRP metrics provide more diagnostic detail. |
| **LTE Active Band** | The frequency band currently carrying your connection. Which band you land on is decided by the network, and it affects both range and speed. |
| **LTE Active Channel** | The specific radio channel number in use within the active band. Mainly of interest when comparing against neighboring cells or diagnosing interference. |
| **LTE Band Lock Mask** ᴰ | Hexadecimal bitmask of the 4G bands the modem is permitted to use. Bit 0 is band 1, so bit 2 is band 3 and bit 19 is band 20 - 0x60088080045 means bands 1, 3, 7, 20, 28, 32, 42 and 43. Use it to confirm which bands a band lock has left available; locking to one the router cannot see leaves it with no service. |
| **LTE PCI** | Physical Cell Identity - a number from 0 to 503 identifying the specific 4G cell sector serving the router. Neighboring sectors reuse the range, so a change means you have moved to a different sector or mast. |
| **LTE Primary Band** | The primary 4G band carrying your connection. Lower-numbered bands generally travel further and penetrate buildings better; higher bands usually carry more capacity over shorter distances. |
| **LTE Primary Bandwidth** | The channel width of the primary 4G band, in MHz. Wider is faster: 20 MHz carries roughly four times the data of 5 MHz, all else being equal. |
| **LTE RSRP** | Reference Signal Received Power - the strength of the 4G signal, in dBm. This is the number to watch when aiming or siting the router; SNR is the better guide to how fast the connection will actually go. Typically: better than -80 is excellent, -80 to -90 good, -90 to -100 fair, below -100 poor. Values are negative, so closer to zero is stronger. |
| **LTE RSRQ** | Reference Signal Received Quality - 4G signal quality rather than raw strength, in dB. It reflects how much interference and load the cell is carrying. Typically: better than -10 is excellent, -10 to -15 good, -15 to -20 fair, below -20 poor. Strong RSRP with poor RSRQ usually means a busy cell. |
| **LTE RSSI** | Received Signal Strength Indicator - total received power across the 4G channel, including noise and interference, in dBm. Less diagnostic than RSRP, because it cannot separate your cell's signal from everything else on the frequency. |
| **LTE Secondary Band** ᴰ | The secondary 4G band added by Carrier Aggregation. Only present while aggregation is active. |
| **LTE Secondary Bandwidth** ᴰ | Channel width of the aggregated secondary 4G band, in MHz. It adds to the primary band's capacity rather than replacing it. |
| **LTE SNR** | Signal-to-Noise Ratio for 4G, in dB - how far the wanted signal rises above the background noise. This is the best predictor of achievable speed. Typically: above 20 is excellent, 13 to 20 good, 0 to 13 fair, below 0 poor. |
| **MDM MCC** | Mobile Country Code - a three-digit code identifying the country of the network the modem is attached to (for example 272 = Ireland). |
| **MDM MNC** | Mobile Network Code - identifies the individual operator within that country. Together with the MCC it uniquely names the network you are on. |
| **Network APN** | Access Point Name - the gateway the router is actually connected with. This is the authoritative answer: while APN Selection Mode is auto the router uses the network's own default, which may not be one of your stored profiles, so the APN Profile selector can differ from this or read unknown. A wrong APN is a common cause of a router that has good signal but no working data. |
| **Network Mode** | The network technology the router is currently allowed to use, as chosen by the Network Mode control. Restricting it can stabilize a connection that keeps switching between 4G and 5G. |
| **Network Mode Selection** | Which mobile technologies the router may use. These are the router's own web page settings under different names: 4G_AND_5G is Auto, LTE_AND_5G is 5G NSA, Only_5G is 5G SA, Only_LTE is 4G Only. Auto lets it fall back when a signal weakens; the Only options lock it. Locking to 5G can drop the connection entirely where 5G coverage is marginal, so prefer Auto unless you are testing. |
| **Network Provider** | The mobile network the router is registered to. This can differ from the SIM's home network while roaming. |
| **Network Type** | The connection technology in use. ENDC and LTE-NSA are both 5G non-standalone, where a 4G anchor carries the connection alongside a 5G carrier: ENDC means the 5G carrier is actually in use, LTE-NSA means the router is attached for 5G but is running on the 4G anchor alone, which is what weak 5G coverage looks like. Plain LTE means no 5G at all. |
| **Roaming MCC** ᴰ | Mobile Country Code of the network the router is registered to, as opposed to the modem's own view. It differs from the modem MCC while roaming. |
| **Roaming MNC** ᴰ | Mobile Network Code of the registered network. Compare with the modem MNC to tell whether the router is roaming. |
| **Signal Bars** | The router's own signal rating, 0 to 5, the same one shown on its web page. It is a coarse summary - for anything precise use RSRP or SNR, which is what the bars are derived from. |
| **WAN Connect Status** | Whether the router currently has a data connection to the mobile network. This covers the mobile side only - it can report connected while the wider internet is unreachable. |

## 📉 Data

Usage counters and throughput.

| Entity | About |
| :-- | :-- |
| **Alert Threshold** | The percentage of the Allowance at which the router raises its own alert - 80% of a 2 TB plan means it warns you at 1.6 TB. This is the router's internal threshold, separate from any automation you build in Home Assistant. |
| **Allowance** ᴰ | The monthly data cap configured on the router itself, matching the Data Plan figure on its Data Management page. Useful as the threshold for an automation, so it tracks the router rather than a number typed into the automation. The router counts in binary units, so a 2 TB plan shows here as about 2199 GB - the same amount, counted the way Home Assistant counts. Unavailable if no limit is set, or if the limit is set in hours rather than data. |
| **Data Limit Switch** ᴰ | Turns on the router's own monthly data cap. When the limit is reached the router stops passing traffic - it does not merely warn - so leave this off unless you have set the limit deliberately. The alert percentage governs when it warns you on the way there. |
| **Download Speed** | Current download rate at the instant of the last poll. Because it is sampled rather than averaged, it will not reflect a short burst that happened between polls. |
| **Monthly Received** | Monthly download total, counted by the router. Home Assistant displays it in GB while storing the exact byte count, so it is both readable on a dashboard and precise in automations. |
| **Monthly Received GB** ᴰ | Data downloaded this billing month, as counted by the router. Treat it as a close guide rather than an exact match for your ISP's billing. |
| **Monthly Sent** | Monthly upload total, counted by the router. Home Assistant displays it in GB while storing the exact byte count, so no separate sensor is needed for automations that want the precise figure. |
| **Monthly Sent GB** ᴰ | Data uploaded this billing month, as counted by the router. This is the router's own counter, not your ISP's - it resets when the router says so and may not match your operator's billing exactly. |
| **Monthly Total** | Combined monthly upload and download - the figure to compare against a data cap. Home Assistant displays it in GB while storing the exact byte count, so nothing is rounded away in automations. |
| **Monthly Total GB** ᴰ | Combined upload and download for the billing month - the figure to compare against a data cap. |
| **Projected Cycle Usage** | Projected total data usage for the current billing cycle, based on average daily consumption so far. It reads low on the first day of a cycle and settles within 24 hours. |
| **Reset Day** | The day of the month on which the router zeroes its monthly data counters. This is the router's own billing cycle, which need not start on the 1st - check it against your provider's bill. If your month is shorter than this day, the reset happens on the last day instead. |
| **Session Received** | Data downloaded during the current session, reset on every router reboot. For billing, use the monthly sensors instead. |
| **Session Sent** | Data uploaded during the current session - since the router last restarted, not since the start of the month. It resets to zero on every reboot. |
| **Upload Speed** | Current upload rate. This is a snapshot taken at the moment the router was last polled, not an average - brief peaks between polls are not captured. |

## 💬 SMS

Message counts and content.

| Entity | About |
| :-- | :-- |
| **Recent Msg** | The most recently received message. Sender, date and storage index are in the attributes; the index is what the delete action needs to remove this specific message. |
| **Total Msg** | Total messages held across every storage area - router memory and SIM, inbox, sent and drafts. The breakdown per area is in this sensor's attributes. Storage filling up stops new messages arriving, which the Integration Health sensor flags. |

## 🚫 Entities without a note

These 6 entities carry no attribute. That is a decision, not an oversight: where the entity's name already answers the question, a note adds noise and teaches you to skip reading them.

| Entity | Group | Why no note |
| :-- | :-- | :-- |
| **Hardware Version** | System | The value is the answer. |
| **LAN IP Address** | System | Self-describing. |
| **Last Updated** | System | Self-describing. |
| **Model Name** | System | The value is the answer. |
| **Delete All** | SMS | The button label is the whole function, and it asks for confirmation. |
| **Unread Msg** | SMS | A count of unread SMS. |

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
