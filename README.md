<!-- markdownlint-disable MD033 -->

# ZTE Router 5G Monitor for Home Assistant

[![HACS Integration](https://img.shields.io/badge/HACS-Integration-orange.svg)](https://hacs.xyz/) [![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5?logo=homeassistant&logoColor=white)](https://hacs.xyz/docs/faq/custom_repositories) [![Latest Release](https://img.shields.io/github/v/release/PlayFaster/ha-zte-router-5g-monitor?label=Release&logo=github)](https://github.com/PlayFaster/ha-zte-router-5g-monitor/releases) [![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0) [![Validate](https://github.com/PlayFaster/ha-zte-router-5g-monitor/actions/workflows/validate.yaml/badge.svg)](https://github.com/PlayFaster/ha-zte-router-5g-monitor/actions/workflows/validate.yaml) ![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/PlayFaster/0376d580e72d0abc493665a80396f701/raw/coverage.json) [![Last Commit](https://img.shields.io/github/last-commit/PlayFaster/ha-zte-router-5g-monitor?label=Last%20commit)](https://github.com/PlayFaster/ha-zte-router-5g-monitor/commits/main)

A Home Assistant integration for **ZTE 5G CPE Routers** providing Signal Stats, Data Usage & SMS Management.

> [!NOTE]
>
> **Is this the right integration for you?**
>
> - **If you own a ZTE MC7010** and want to monitor your 5G/LTE connection quality, data usage, and manage SMS messages directly from Home Assistant, then **yes**.
> - **This integration is for you if** you want:
>   - **Advanced Signal Diagnostics** — Near-real-time tracking of RSRP, RSRQ, RSSI, and SNR for both LTE and 5G.
>   - **Polling Control** — Pause polling and adjust the scan interval dynamically from the HA UI or via automation.
>   - **SMS Management** — View the most recently received message content and attributes directly in HA.
>
> This project is optimized for the ZTE MC7010 5G Outdoor CPE but may work with other similar ZTE devices.

## 📋 Table of Contents

- [ZTE Router 5G Monitor for Home Assistant](#zte-router-5g-monitor-for-home-assistant)
  - [📋 Table of Contents](#-table-of-contents)
  - [🔧 Compatibility \& Tested Devices](#-compatibility--tested-devices)
  - [🎯 Use Cases](#-use-cases)
  - [✅ Features](#-features)
  - [🔍 What You Get](#-what-you-get)
  - [📸 Screenshots](#-screenshots)
  - [🔘 Controls \& Settings](#-controls--settings)
  - [💡 Example Automations](#-example-automations)
  - [📥 Installation](#-installation)
  - [🔧 Configuration](#-configuration)
  - [🔩 Under the Hood - Technical Architecture](#-under-the-hood---technical-architecture)
  - [❓ FAQ \& Troubleshooting](#-faq--troubleshooting)
  - [❗ Known Limitations /❔ What's Missing?](#-known-limitations--whats-missing)
  - [❌ Removal](#-removal)
  - [📝 Maintenance Status](#-maintenance-status)
  - [🤝 Contributors \& Acknowledgements](#-contributors--acknowledgements)
  - [📄 License](#-license)

## 🔧 Compatibility & Tested Devices

**📟 Router Hardware:**

- **Fully Tested**:
  - **ZTE MC7010** (5G Outdoor CPE) — tested firmware: `V1.0.0B01` and later
- **Expected Compatible**: Other ZTE 5G CPE devices (e.g., MC801A) may work but are currently untested.
- **Not Supported**: Non-ZTE hardware.

**🌐 Network:**

- Local network access to the router is required.

**🏠 Home Assistant Version:**

- Minimum: Home Assistant **2024.8.0**
- Minimum Python: **3.12+** (this is built into and handled by HA, but relevant for non-standard installs).

## 🎯 Use Cases

- **Signal Monitoring**: Near-real-time and historical 5G/LTE signal data enable the monitoring of router performance.
  - **Best Signal**: Use signal diagnostics (RSRP, SNR) to optimize the physical placement or orientation of your router. → [Morning Signal Report](#-force-a-fresh-reading-before-reporting) example.
  - **Performance Tracking**: Use signal history to check whether the performance from your 5G/LTE ISP is stable or changing. → [Cell Tower Change Alert](#-cell-tower-change-alert) example.
  - **Connection Quality**: Know if your router has dropped to a lower-capability 4G/LTE only connection. → [Signal Quality Alert](#-signal-quality-alert) example.
- **Data Cap Management**: Create automations to get notified when your usage crosses a threshold you set (for example, as you approach your monthly data limit) to avoid unexpected overage charges on limited 5G plans. → [Data Usage Alert](#-data-usage-alert) example.
- **Unattended Recovery**: Fail over to a backup APN, or restart the router, when the connection stops recovering on its own. → [APN Failover](#-apn-failover--network-selection) and [Auto-Reboot on a Prolonged Outage](#-auto-reboot-on-a-prolonged-outage) examples.
- **Smart SMS Gateway**: Use your router as a notification bridge; for example, forward home security alerts to your phone via SMS if your primary internet connection goes down. → [Forward Incoming SMS](#-forward-incoming-sms-to-mobile) example.
  - **Obligatory Warning**: It is _**YOUR**_ responsibility to understand whether having your Router send SMS messages is going to incur an extra charge from your ISP.
- **Knowing When the Integration Itself Is Wrong**: A firmware update can rename the fields this integration reads, leaving sensors blank with no obvious error. The Integration Health sensor reports that case directly. → [Integration Health Problem Alert](#-integration-health-problem-alert) and [Firmware Change Notification](#-firmware-change-notification) examples.

## ✅ Features

### 📡 Advanced 5G/LTE Diagnostics

- **Detailed Signal Metrics**: RSRP, RSRQ, RSSI, and SNR for both the 5G NR and the LTE anchor cell.
- **Cell Tower Info**: Monitor Cell ID, eNodeB ID, PCI, and active frequency bands/channels. See the [Cell Tower Change Alert](#-cell-tower-change-alert) example.
- **Connection Type**: Track Carrier Aggregation and ENDC status plus LTE and 5G bands in use. See the [Signal Quality Alert](#-signal-quality-alert) example.

### 📉 Data Usage Tracking

- **Monthly Data Usage**: Track your monthly download, upload and total data usage. See the [Data Usage Alert](#-data-usage-alert) example.
- **Session Usage**: Track your download and upload for this session (i.e. since last router restart).
- **Download & Upload Speed**: Track your upload and download speeds. Note: This is valid, but only at the instant data was fetched from the router.

### 📋 Essential Router Management

- **Router Management**: Reboot the device directly from the HA UI, by hand or from an automation. See the [Auto-Reboot on a Prolonged Outage](#-auto-reboot-on-a-prolonged-outage) example.
- **Self-Diagnosis**: An **Integration Health** binary sensor reports the integration's own degradation — including a poll that _succeeded_ but returned nothing usable. See [Self-Diagnosis](#-self-diagnosis) and the [Integration Health Problem Alert](#-integration-health-problem-alert) example.
- **100% Local**: No cloud account or internet access required.

### 🔄 Dynamic Polling

This integration features **dynamic polling**, the ability to pause polling completely or to change the polling interval.

- **Pause Polling**: Switch to halt polling when you need uninterrupted access to the router's web UI (ZTE only allows a single active login session). See the [Auto-Resume Polling](#-auto-resume-polling) example.
- **Configurable Update Interval**: Dynamically adjust the scan interval (30s to 1 hour, default 180s) via a number entity or automation. See the [Dynamic Polling Interval](#-dynamic-polling-interval) example.
- **Explicit Actions Always Fetch**: **Refresh Now**, a settings change or an SMS action fetches immediately **even while paused** — only scheduled polls are suppressed. See the [Force a Fresh Reading](#-force-a-fresh-reading-before-reporting) example.

> [!TIP]
>
> **Polling Interval can be controlled dynamically, via automation**
>
> - Set it to 30 seconds during periods of heavy use, to examine connection quality or when you need to receive new SMS messages quickly, and set it higher afterwards, to avoid taxing the router and your Home Assistant database.

### 💬 SMS Management Actions

Provides unread SMS count and latest message content sensors, a one-click **Delete All** button, a `zte_router_5g_sms_received` event for automation triggers ([example](#-forward-incoming-sms-to-mobile)), and four service actions for full programmatic control ([inbox cleanup](#-automated-inbox-maintenance) and [on-demand query](#-fetch-and-process-inbox-via-automation) examples).

- The `Recent Msg` sensor displays the most recent message received **OR** _sent_.
- In the examples below, the `entry_id:` of your router, where required, is drop-down menu selectable from the editor GUI.

> The **Delete All** button entity is a simple one-click UI control with no parameters. The `delete_all_sms` service action below is the programmable equivalent and accepts a `keep_last` parameter to preserve recent messages.

#### `zte_router_5g.send_sms`

Send an SMS message via the router.

| Parameter | Required | Description |
| :-- | :-- | :-- |
| `entry_id` | No | The router to use. Optional if only one router is configured. |
| `target` | **Yes** | Recipient phone number(s) (e.g. `+353871234567`). |
| `message` | **Yes** | Message content. |

```yaml
action: zte_router_5g.send_sms
data:
  target: "+1234567891011"
  message: "Hello from Home Assistant!"
```

#### `zte_router_5g.delete_sms`

Delete a single SMS by its storage index. Use the `index` field from `get_sms_list` or from the `zte_router_5g_sms_received` event.

| Parameter | Required | Description |
| :-- | :-- | :-- |
| `entry_id` | No | The router to use. Defaults to your only router; required if more than one is configured. |
| `index` | **Yes** | Storage index of the message to delete (integer ≥ 0). |

```yaml
action: zte_router_5g.delete_sms
data:
  entry_id: <your_config_entry_id>
  index: 3
```

#### `zte_router_5g.delete_all_sms`

Bulk delete SMS messages from the router inbox.

| Parameter | Required | Default | Range | Description |
| :-- | :-- | :-- | :-- | :-- |
| `entry_id` | No | — | — | The router to use. Defaults to your only router; required if more than one is configured. |
| `keep_last` | No | `0` | 0–50 | Number of most recent messages to preserve. `0` deletes all. |

```yaml
action: zte_router_5g.delete_all_sms
data:
  entry_id: <your_config_entry_id>
  keep_last: 5
```

#### `zte_router_5g.get_sms_list`

Fetch a list of SMS messages. Supports **Action Responses** — use the output directly in automations and scripts.

| Parameter | Required | Default | Range | Description |
| :-- | :-- | :-- | :-- | :-- |
| `entry_id` | No | — | — | The router to use. Defaults to your only router; required if more than one is configured. |
| `page` | No | `1` | 1–100 | Page number for pagination. |
| `count` | No | `20` | 1–50 | Messages per page. |
| `box_type` | No | `1` | See below | Mailbox to read from. |

**`box_type` values:** `1` Local Inbox · `2` Local Sent · `3` Local Draft · `4` Local Trash · `5` SIM Inbox · `6` SIM Sent · `7` SIM Draft · `8` Mix Inbox · `9` Mix Sent · `10` Mix Draft

**Response — each message in `messages`:**

| Field     | Type    | Description                                                  |
| :-------- | :------ | :----------------------------------------------------------- |
| `index`   | Integer | Storage index — pass to `delete_sms` to delete this message. |
| `phone`   | Text    | Sender's phone number.                                       |
| `content` | Text    | Message body.                                                |
| `date`    | Text    | Date/time string.                                            |
| `read`    | Boolean | `true` if read, `false` if unread.                           |

```yaml
action: zte_router_5g.get_sms_list
data:
  entry_id: <your_config_entry_id>
  count: 50
  box_type: 1
response_variable: inbox
```

#### `zte_router_5g_sms_received` Event

Fires automatically when a new incoming SMS is detected. Use as an automation trigger.

| Field | Type | Description |
| :-- | :-- | :-- |
| `entry_id` | Text | Config entry ID of the router that received the message. |
| `phone` | Text | Sender's phone number. |
| `content` | Text | Message body. |
| `date` | Text | Date/time of the message. |
| `index` | Integer | Storage index — pass directly to `delete_sms` to delete after processing. |

## 🔍 What You Get

This integration provides **75+ entities** (depending on your firmware) organized into four logical devices: **System**, **Signal**, **Data**, and **SMS**.

> [!NOTE]
>
> Entity Visibility: To keep your Home Assistant UI clean, some entities are disabled by default. You can enable them via the Entities tab in the device settings.

| Sub-Device | Entity Types (+disabled) | Key Metrics | Disabled by Default |
| :-- | :-- | :-- | :-- |
| ⚙️ **System** | 13 Sensors, 4 Binary Sensors, 2 Switches, 2 Buttons, 1 Number (+10) | Firmware, IP Addresses, Uptime, **Integration Health**, Refresh Now, Reboot, Polling Controls, Reboot Schedule, UPnP, SIP ALG, SNTP Server | Uptime Duration, IMEI, Battery, SIM IMSI, SIM ICCID, Time Server (SNTP), ODU LED Switch, Reboot Schedule, UPnP Enabled, SIP ALG Enabled |
| 📶 **Signal** | 35 Sensors, 1 Binary Sensor, 3 Selects (+7) | RSRP, RSRQ, SINR, PCI, Cell ID, Primary/Secondary Bands, APN Profile, APN Mode, Network Mode Selection | RMCC, RMNC, LTE Secondary Band & Bandwidth, RSSI (legacy), RSCP (legacy), LTE Band Lock Mask |
| 📈 **Data** | 11 Sensors, 1 Switch (+5) | Monthly Usage, Near-real-time Speed, Session Data, Data Limit Switch, Data Volume Alert | Monthly Upload/Download/Total (Legacy GB sensors), Data Limit Switch, Data Volume Alert % |
| ✉️ **SMS Entities** | 3 Sensors, 1 Button | Unread Count, Total Msg, Recent Msg, Delete All (one-click) | None |
| 🛠️ **SMS Actions** | 4 Actions | Send, Delete, and List SMS | — |

> [!TIP]
>
> **Clean up your UI: Disable Unnecessary Devices or Entities**
>
> - If you never use the Router's SMS, you may not need the SMS sub-device.
> - Devices can be disabled from the main device page: (⋮ menu) > **Disable Device** which also disables all the device entities.
> - Individual entities can be disabled via their properties, or in bulk on the entities list page.

### 📊 Long Term Statistics (LTS)

Home Assistant stores Long Term Statistics for numeric sensors that have a `state_class` set. This integration enables LTS only for sensors where long-term trend data is genuinely useful:

| Sensors with LTS enabled | Why |
| :-- | :-- |
| LTE & 5G signal metrics (RSRP, RSRQ, RSSI, SNR) | Track connection quality trends over time |
| Monthly data usage (Sent, Received, Total) | Monitor data consumption month-over-month |
| SMS counts (Unread, Total) | Track message volume over time |
| Signal Bars | Coarse signal summary over time |

The following sensors have **no LTS** to avoid unnecessary database growth:

| Sensor | Reason |
| :-- | :-- |
| Upload / Download Speed | Instantaneous readings — history at poll intervals has limited analytical value |
| Session Sent / Received | Resets on every reconnect — not meaningful for long-term trends |
| Uptime Duration | Resets on reboot; predictable pattern adds no insight |
| Battery | Always 100% when plugged in |
| Legacy RSSI / RSCP (disabled) | Legacy metrics disabled by default |
| Data Volume Alert % (disabled) | Configuration setting; historical trend holds no analytical value |
| LTE Band Lock Mask (disabled) | Text string diagnostic sensor |
| Time Server (SNTP) (disabled) | Text string configuration sensor |

> [!TIP]
>
> **Want to add a sensor to Long Term Statistics?**
>
> Add a `state_class` override via [Manual Customization](https://www.home-assistant.io/integrations/homeassistant/#manual-customization) in your `configuration.yaml`. For example, to track Upload Speed in LTS:
>
> ```yaml
> homeassistant:
>   customize:
>     sensor.zte_5g_data_upload_speed:
>       state_class: measurement
> ```
>
> Restart Home Assistant after saving. The sensor will begin accumulating LTS from that point forward.

## 📸 Screenshots

### Integration Overview

![Integration](.github/images/zte_5g_integration_screen.png)

| Signal | System |
| :-: | :-: |
| ![Signal](.github/images/zte_5g_signal_screen_mini1.png) | ![System](.github/images/zte_5g_sensor_control_info_mini.png) |

| Data | SMS |
| :-: | :-: |
| ![Data](.github/images/zte_5g_data_screen_mini.png) | ![SMS](.github/images/zte_5g_sms_info.png) |

### Setup

![Setup](.github/images/zte_5g_setup_info.png)

## 🔘 Controls & Settings

Rather than hiding settings in configuration menus, several configuration parameters are exposed directly as Home Assistant control entities, allowing you to monitor and control them from dashboards or automations:

### 📡 APN & Network Settings (Signal Device)

- **APN Profile** (`select.zte_5g_signal_apn_profile`): Switch the active default APN profile dynamically.
- **APN Selection Mode** (`select.zte_5g_signal_apn_selection_mode`): Toggle between `auto` and `manual` APN mode.
- **Network Mode Selection** (`select.zte_5g_signal_network_mode_selection`): Select the preferred connection type: `4G_AND_5G` (Auto), `LTE_AND_5G` (5G NSA), `Only_5G` (5G SA), or `Only_LTE` (4G Only).
- **Disabled by Default**: These are disabled by default but can be enabled
  - **LTE Band Lock Mask** (`sensor.zte_5g_signal_lte_band_lock_mask`): Displays the current hex mask configuration locking the active LTE bands.

### 🔧 Router Administration & Polling (System Device)

- **Pause Polling** (`switch.zte_5g_system_pause_polling`): Halt all polling when you need exclusive access to the router's web UI.
- **Polling Interval** (`number.zte_5g_system_polling_interval`): Adjust the scan interval slider (30s to 1 hour, default `180` seconds).
- **Refresh Now** (`button.zte_5g_system_refresh_now`): Trigger an immediate refresh (data fetch).
- **Disabled by Default**: These are disabled by default but can be enabled
  - **ODU LED Switch** (`switch.zte_5g_system_odu_led_switch`): Turn the physical status LEDs of the outdoor unit on or off.
  - **Reboot Schedule** (`binary_sensor.zte_5g_system_reboot_schedule`): Indicates whether a scheduled reboot window is configured and active.
  - **UPnP Enabled** / **SIP ALG Enabled** (`binary_sensor.zte_5g_system_upnp_enabled` / `binary_sensor.zte_5g_system_sip_alg_enabled`): Monitor firewall settings status.
  - **Time Server (SNTP)** (`sensor.zte_5g_system_time_server_sntp`): Displays the active server used by the router for time synchronization.

### 📈 Billing & Data Controls (Data Device)

- **Disabled by Default**: These are disabled by default but can be enabled
  - **Data Limit Switch** (`switch.zte_5g_data_data_limit_switch`): Enable/disable the router's data limit settings.
  - **Data Volume Alert** (`sensor.zte_5g_data_data_volume_alert`): Displays the alarm warning percentage configured on the router (e.g., 90%).

## 💡 Example Automations

Entity IDs below use the default prefix zte_5g. If you set a custom name during setup, or have renamed since, replace zte_5g with your configured prefix.

### 💬 SMS Examples

#### 📨 Forward Incoming SMS to Mobile

<details>

<summary> &nbsp; &nbsp; This automation fires when a new SMS is detected and forwards the content to your mobile phone.<br>
&nbsp; &nbsp; &nbsp; &nbsp; ➕ &nbsp; Click to Expand for Automation Detail:
</summary><br>

```yaml
alias: "ZTE SMS: Forward to Mobile"
description: "Forwards the content of any newly received SMS to a notification"
mode: queued
max: 10
triggers:
  - trigger: event
    event_type: zte_router_5g_sms_received
    note: |
      Fires once per genuinely new message. Messages already on the router when Home
      Assistant starts are recorded silently as a baseline, so a restart never replays
      your whole inbox into this automation.
actions:
  - action: persistent_notification.create
    data:
      title: "New SMS from {{ trigger.event.data.phone }}"
      message: "{{ trigger.event.data.content }}"
    note: |
      The event payload carries phone, content, date and index. Use index with the
      delete_sms action if you want to remove the message after handling it.
```

> [!NOTE] `mode: queued` matters here — several messages can arrive in one poll cycle, and the default `single` mode would silently drop all but the first.

---

</details>

#### 🧹 Automated Inbox Maintenance

<details>

<summary> &nbsp; &nbsp; Keep your router's SMS storage clean by automatically deleting old messages while keeping the most recent ones for safety.<br>
&nbsp; &nbsp; &nbsp; &nbsp; ➕ &nbsp; Click to Expand for Automation Detail:
</summary><br>

```yaml
alias: "ZTE SMS: Weekly Inbox Cleanup"
description: "Deletes stored SMS weekly, keeping the five most recent"
mode: single
triggers:
  - trigger: time
    at: "03:00:00"
    note: Overnight, so the deletion never competes with a poll you are watching.
conditions:
  - condition: time
    weekday:
      - sun
    note: Weekly is usually enough; raise the frequency if your router fills up faster.
actions:
  - action: zte_router_5g.delete_all_sms
    data:
      entry_id: <your_config_entry_id> # This is GUI selectable in the Automation Editor.
      keep_last: 5
    note: |
      keep_last preserves the newest N messages. Set it to 0 to clear the inbox
      entirely. The action refreshes the coordinator afterwards, so the SMS counters
      update immediately rather than at the next scheduled poll - and it does so even
      if Pause Polling is on.
```

---

</details>

#### 📜 Fetch and Process Inbox via Automation

<details>

<summary> &nbsp; &nbsp; Example of using the `get_sms_list` action response in an automation to count messages from a specific sender.<br>
&nbsp; &nbsp; &nbsp; &nbsp; ➕ &nbsp; Click to Expand for Automation Detail:
</summary><br>

```yaml
alias: "ZTE SMS: Count OTP Messages"
description: "Queries the inbox on demand and counts messages from one sender"
mode: single
triggers:
  - trigger: time
    at: "09:00:00"
    weekday:
      - mon
      - wed
      - fri
actions:
  - action: zte_router_5g.get_sms_list
    data:
      entry_id: <your_config_entry_id> # This is GUI selectable in the Automation Editor.
      count: 50
    response_variable: inbox
    note: |
      This action performs its own fetch rather than reading the Recent Msg sensor, so
      it keeps working even if the SMS entities are disabled - and it returns the full
      message list, which is far too bulky to hold as a sensor attribute.
  - action: notify.persistent_notification
    data:
      message: |
        You have {{ inbox.messages | selectattr('phone', 'search', 'MY_BANK') |
        list | count }} messages from your bank in the inbox.
    note: |
      Each entry in inbox.messages has index, phone, content, date and read. Filter on
      any of them; use index to feed the delete_sms action.
```

---

</details>

### 📡 Connection, Data & Signal Automations

#### 📡 APN Failover & Network Selection

<details>

<summary> &nbsp; &nbsp; Automatically switch to a backup APN profile if the primary connection goes offline.<br>
&nbsp; &nbsp; &nbsp; &nbsp; ➕ &nbsp; Click to Expand for Automation Detail:
</summary><br>

```yaml
alias: "ZTE APN: Switch Profile on Network Failure"
description: "Switch to a backup APN profile if the primary WAN connection drops."
mode: single
triggers:
  - trigger: state
    entity_id: sensor.zte_5g_signal_wan_connect_status
    to: "disconnected"
    for: "00:05:00"
    note: |
      The 5 minute hold matters. The integration already holds last-known values for
      three consecutive failed polls before reporting anything, so a value that has
      stayed "disconnected" for five minutes is a real outage rather than a blip.
conditions:
  - condition: state
    entity_id: select.zte_5g_signal_apn_profile
    state: "primary_apn"
    note: |
      Only fail over from the primary. Without this the automation would flap back and
      forth every time the backup APN also dropped.
actions:
  - action: select.select_option
    target:
      entity_id: select.zte_5g_signal_apn_profile
    data:
      option: "backup_apn"
    note: |
      Replace both profile names with values from your own router - the options come
      from the APN profiles it actually has configured. Selecting an option forces an
      immediate poll, so the change is reflected in Home Assistant right away.
```

---

</details>

#### 🚨 Data Usage Alert

<details>

<summary> &nbsp; &nbsp; Monitor your data consumption and get notified when you approach your monthly limit. The example below assumes the data sensors display in **GB**. If your sensors are not in GB, check their unit and adjust the thresholds and templates accordingly.<br>
&nbsp; &nbsp; &nbsp; &nbsp; ➕ &nbsp; Click to Expand for Automation Detail:
</summary><br>

```yaml
alias: "ZTE Data: High Data Usage Alert"
description: "Warns once when monthly data crosses a threshold"
mode: single
triggers:
  - trigger: numeric_state
    entity_id: sensor.zte_5g_data_monthly_total
    above: 500 # 500 GB - use 500000000000 if the sensor displays Bytes (B)
    note: |
      The sensor stores bytes and displays gigabytes. A numeric_state trigger compares
      against the DISPLAYED value, so 500 means 500 GB here. Check the unit shown on
      the entity before setting the number - see the note under this example.
actions:
  - action: persistent_notification.create
    data:
      title: "ZTE Data Alert"
      message: |
        Monthly data usage has reached
        {{ states('sensor.zte_5g_data_monthly_total') }}
        {{ state_attr('sensor.zte_5g_data_monthly_total', 'unit_of_measurement') }}.
    note: |
      Reading the unit from the entity keeps the message correct whether you are
      displaying GB, MB or bytes. A numeric_state trigger fires only on the crossing,
      so this notifies once rather than on every poll above the threshold.
```

---

</details>

#### 📶 Signal Quality Alert

<details>

<summary> &nbsp; &nbsp; Monitor for poor connection quality based on 5G status and signal metrics.<br>
&nbsp; &nbsp; &nbsp; &nbsp; ➕ &nbsp; Click to Expand for Automation Detail:
</summary><br>

```yaml
alias: "ZTE Signal: Poor Quality Connection Alert"
description: "Notifies when connection quality degrades on any of four measures"
mode: single
triggers:
  - trigger: state
    entity_id:
      - binary_sensor.zte_5g_signal_best_connection
    to: "off"
    for: "00:05:00"
    note: |
      Best Connection is on only when the router has BOTH 5G ENDC and LTE carrier
      aggregation active. It reports unknown rather than off before the first poll
      completes, so a restart does not fire this.
  - trigger: state
    entity_id:
      - sensor.zte_5g_signal_network_type
    not_to: "ENDC"
    for: "00:05:00"
    note: Dropped off 5G NSA entirely - usually the most noticeable of the four.
  - trigger: state
    entity_id:
      - sensor.zte_5g_signal_carrier_aggregation
    not_to: "ca_activated"
    for: "00:05:00"
    note: Lost LTE carrier aggregation, which usually shows up as reduced throughput.
  - trigger: numeric_state
    entity_id:
      - sensor.zte_5g_signal_signal_bars
    below: 4
    for: "00:05:00"
    note: |
      Signal bars is the router's own 0-5 summary. Prefer RSRP or SINR if you want a
      physically meaningful threshold; bars is coarse but matches what the router's
      own UI shows.
conditions:
  - condition: or
    conditions:
      - condition: numeric_state
        entity_id: sensor.zte_5g_signal_signal_bars
        below: 4
      - condition: state
        entity_id: binary_sensor.zte_5g_signal_best_connection
        state:
          - "off"
      - condition: not
        conditions:
          - condition: state
            entity_id: sensor.zte_5g_signal_carrier_aggregation
            state:
              - ca_activated
      - condition: not
        conditions:
          - condition: state
            entity_id: sensor.zte_5g_signal_network_type
            state:
              - ENDC
    note: |
      Re-checking the same four measures as conditions means the notification only
      fires if the degradation is still true when the action runs, not merely when
      one of them briefly flickered.
actions:
  - action: persistent_notification.create
    data:
      title: "Poor Signal Quality Detected"
      message: |
        The router connection quality is poor.
        - 5G ENDC: {{ states('sensor.zte_5g_signal_network_type') }}
        - Best Connection: {{ states('binary_sensor.zte_5g_signal_best_connection') }}
        - Signal Bars: {{ states('sensor.zte_5g_signal_signal_bars') }}
        - CA: {{ states('sensor.zte_5g_signal_carrier_aggregation') }}
    note: |
      Reporting all four values together tells you which one actually degraded, which
      is what you need to decide whether to reposition the router or just wait it out.
```

---

</details>

### 🩺 System Health & Connectivity Alerts

#### 🩺 Integration Health Problem Alert

<details>

<summary> &nbsp; &nbsp; Be told when the integration detects a fault in its own data.<br>
&nbsp; &nbsp; &nbsp; &nbsp; ➕ &nbsp; Click to Expand for Automation Detail:
</summary><br>

The **Integration Health** binary sensor turns on when the integration's self-checks find a problem — the router unreachable for several consecutive polls, an SMS endpoint that has stopped responding, or a poll that _succeeded_ but returned none of the fields the integration expects (typically a firmware update renaming them). It stays **available even when every other entity has gone unavailable**, so it can report the fault that made the others unreliable.

```yaml
alias: "ZTE Health: Integration Health Problem"
description: "Notifies when the integration's self-checks detect a problem"
mode: single
triggers:
  - trigger: state
    entity_id: binary_sensor.zte_5g_system_integration_health
    to: "on"
    for:
      minutes: 10
    note: |
      The 10 minute duration is deliberate. A brief outage can set the sensor and clear
      it on the next cycle; this reports only problems that persist. Shorten it if you
      would rather hear about transient faults too.
actions:
  - action: persistent_notification.create
    data:
      title: ZTE Router 5G Monitor needs attention
      message: |
        {{ state_attr('binary_sensor.zte_5g_system_integration_health', 'issues')
           | join(', ') }}
        Last good update: {{ state_attr('binary_sensor.zte_5g_system_integration_health', 'last_good_update') }}
    note: |
      issues is a list of human-readable problem descriptions. The sensor also carries
      severity (ok / degraded / warning / error), degraded_capabilities (names of failed
      endpoints), repairs (the repair issues currently raised), and consecutive_failures.
```

> [!TIP] To alert only on the serious cases and ignore ordinary connectivity blips, add a condition on the `severity` attribute: `{{ state_attr('binary_sensor.zte_5g_system_integration_health', 'severity') == 'warning' }}` fires only for a suspected firmware API change, which is the condition that also raises a Repair.

---

</details>

#### 🔄 Router Reboot Alert

<details>

<summary> &nbsp; &nbsp; Monitor for router reboots by watching the device boot timestamp sensor.<br>
&nbsp; &nbsp; &nbsp; &nbsp; ➕ &nbsp; Click to Expand for Automation Detail:
</summary><br>

```yaml
alias: "ZTE Reboot: Router Reboot Alert"
description: "Notifies when the router's boot timestamp moves, indicating a restart"
mode: single
triggers:
  - trigger: template
    value_template: |
      {% set uptime = states('sensor.zte_5g_system_device_uptime') | as_datetime %}
      {{ uptime is not none and (now() - uptime).total_seconds() < 120 }}
    note: |
      Device Uptime is a timestamp of when the router booted, not a counter. The
      integration latches that instant and only re-derives it when the router's uptime
      counter genuinely drops, so it does not drift between reboots - which is what
      makes this template reliable rather than noisy.
actions:
  - action: persistent_notification.create
    data:
      title: "ZTE Router Rebooted"
      message: "The router has rebooted. Boot Time: {{ states('sensor.zte_5g_system_device_uptime') }}"
    note: Swap in notify.mobile_app_your_phone to get this on your phone instead.
```

---

</details>

#### 🔁 Auto-Reboot on a Prolonged Outage

<details>

<summary> &nbsp; &nbsp; Recover automatically from a wedged connection by restarting the router.<br>
&nbsp; &nbsp; &nbsp; &nbsp; ➕ &nbsp; Click to Expand for Automation Detail:
</summary><br>

> [!WARNING] This reboots your router unattended. Keep the trigger duration generous and `mode: single`, or a flapping connection can put the router into a reboot loop that stops it recovering on its own.

```yaml
alias: "ZTE Reboot: Auto-Reboot on Prolonged Outage"
description: "Reboots the router after a sustained WAN outage"
mode: single
max_exceeded: silent
triggers:
  - trigger: state
    entity_id: sensor.zte_5g_signal_wan_connect_status
    to: "disconnected"
    for:
      minutes: 30
    note: |
      Deliberately long. Mobile networks drop and re-establish routinely, and a reboot
      costs several minutes of downtime - so this should only fire for an outage that
      has clearly stopped resolving itself.
conditions:
  - condition: state
    entity_id: binary_sensor.zte_5g_system_integration_health
    state: "off"
    note: |
      Cross-check against the integration's own health verdict. Health being off means
      polling is succeeding, so "disconnected" is trustworthy live data rather than a
      stale value being held while fetches fail - in which case rebooting would be
      treating the wrong problem.
actions:
  - action: button.press
    target:
      entity_id: button.zte_5g_system_reboot
    note: The router drops off the network for a few minutes; entities go unavailable.
  - delay:
      minutes: 10
    note: |
      Holding the automation open for 10 minutes with mode:single means it cannot
      re-trigger while the router is still coming back up.
  - action: persistent_notification.create
    data:
      title: "ZTE Router Rebooted Automatically"
      message: |
        The WAN was disconnected for 30 minutes, so the router was rebooted.
        Status is now: {{ states('sensor.zte_5g_signal_wan_connect_status') }}
```

---

</details>

#### 📻 Cell Tower Change Alert

<details>

<summary> &nbsp; &nbsp; Be told when the router re-homes to a different cell, which often explains a sudden change in speed or signal.<br>
&nbsp; &nbsp; &nbsp; &nbsp; ➕ &nbsp; Click to Expand for Automation Detail:
</summary><br>

```yaml
alias: "ZTE Tower: Serving Cell Changed"
description: "Notifies when the router attaches to a different cell tower"
mode: single
triggers:
  - trigger: state
    entity_id: sensor.zte_5g_signal_cell_id
    note: |
      No to: or from: - any change fires this, and Cell ID only changes when the
      serving cell actually changes.
conditions:
  - condition: template
    value_template: "{{ trigger.from_state.state not in ['unknown', 'unavailable', none] }}"
    note: |
      Suppresses the first reading after a restart, which would otherwise look like a
      tower change every time Home Assistant boots.
actions:
  - action: persistent_notification.create
    data:
      title: "ZTE: Serving Cell Changed"
      message: |
        Cell ID {{ trigger.from_state.state }} → {{ trigger.to_state.state }}
        Band: {{ states('sensor.zte_5g_signal_lte_active_band') }}
        RSRP: {{ states('sensor.zte_5g_signal_lte_rsrp') }} dBm
    note: |
      Reporting the new band and signal alongside the change is what makes this useful
      - a tower change with worse RSRP is the usual explanation for a sudden slowdown.
```

---

</details>

#### 🧩 Firmware Change Notification

<details>

<summary> &nbsp; &nbsp; Know when the router updates itself. A firmware change is the most likely cause of the integration's data shape shifting underneath it.<br>
&nbsp; &nbsp; &nbsp; &nbsp; ➕ &nbsp; Click to Expand for Automation Detail:
</summary><br>

```yaml
alias: "ZTE Firmware: Firmware Version Changed"
description: "Notifies when the router reports a different firmware version"
mode: single
triggers:
  - trigger: state
    entity_id: sensor.zte_5g_system_firmware_version
    note: |
      ZTE CPEs can update firmware without warning. Worth knowing about, because a
      firmware change can rename the API fields the integration reads - exactly the
      condition the Integration Health sensor watches for.
conditions:
  - condition: template
    value_template: "{{ trigger.from_state.state not in ['unknown', 'unavailable', none] }}"
    note: Ignores the first reading after a restart.
actions:
  - action: persistent_notification.create
    data:
      title: "ZTE Router Firmware Changed"
      message: |
        {{ trigger.from_state.state }} → {{ trigger.to_state.state }}

        If sensors start showing Unknown after this, check Integration Health and open
        an issue quoting both version numbers.
    note: |
      If the update did break the API, Integration Health turns on and raises a Repair
      within a few poll cycles.
```

---

</details>

### 🔄 Polling Control Automations

#### 🔁 Auto-Resume Polling

<details>

<summary> &nbsp; &nbsp; Ensure polling is turned back on automatically if someone forgets to resume it after managing the router.<br>
&nbsp; &nbsp; &nbsp; &nbsp; ➕ &nbsp; Click to Expand for Automation Detail:
</summary><br>

```yaml
alias: "ZTE Polling: Auto-Resume Polling"
description: "Turn polling back on after 1 hour if it was manually paused."
mode: single
triggers:
  - trigger: state
    entity_id: switch.zte_5g_system_pause_polling
    to: "on"
    for: "01:00:00"
    note: |
      Pausing frees the router's single login session so you can use its web UI. This
      is the safety net for forgetting to switch it back.
actions:
  - action: switch.turn_off
    target:
      entity_id: switch.zte_5g_system_pause_polling
    note: |
      Resuming triggers an immediate fetch, so the entities catch up straight away
      rather than waiting for the next scheduled poll.
```

---

</details>

#### 🔄 Dynamic Polling Interval

<details>

<summary> &nbsp; &nbsp; Poll frequently when you are watching, and back off overnight to reduce load on the router and the recorder database.<br>
&nbsp; &nbsp; &nbsp; &nbsp; ➕ &nbsp; Click to Expand for Automation Detail:
</summary><br>

```yaml
alias: "ZTE Polling: Set Polling Interval by Time of Day"
description: "Tightens the poll interval during the day and relaxes it overnight"
mode: single
triggers:
  - trigger: time
    at: "07:00:00"
    id: "day"
    note: Switch to the responsive daytime cadence.
  - trigger: time
    at: "23:00:00"
    id: "night"
    note: Back off overnight.
actions:
  - choose:
      - conditions:
          - condition: trigger
            id: "day"
        sequence:
          - action: number.set_value
            target:
              entity_id: number.zte_5g_system_polling_interval
            data:
              value: 60
            note: |
              Poll every 60 seconds. Changing the interval applies immediately without
              reloading the integration, so no entity becomes briefly unavailable - and
              it also forces one fetch straight away.
      - conditions:
          - condition: trigger
            id: "night"
        sequence:
          - action: number.set_value
            target:
              entity_id: number.zte_5g_system_polling_interval
            data:
              value: 900
            note: |
              Poll every 15 minutes. Use the Pause Polling switch instead if you want
              no polling at all rather than less of it.
```

---

</details>

#### 🔍 Force a Fresh Reading Before Reporting

<details>

<summary> &nbsp; &nbsp; Read genuinely current values in a report or dashboard refresh, rather than whatever the last scheduled poll happened to leave behind.<br>
&nbsp; &nbsp; &nbsp; &nbsp; ➕ &nbsp; Click to Expand for Automation Detail:
</summary><br>

```yaml
alias: "ZTE Signal: Morning Signal Report"
description: "Forces a fresh poll, then reports current signal quality"
mode: single
triggers:
  - trigger: time
    at: "08:00:00"
actions:
  - action: button.press
    target:
      entity_id: button.zte_5g_system_refresh_now
    note: |
      Refresh Now fetches immediately even if Pause Polling is on - explicit user
      actions always reach the router, only scheduled polls respect the pause.
  - delay:
      seconds: 15
    note: |
      Give the fetch time to complete and the entities time to update before reading
      them. 15s is comfortable; the coordinator's own timeout is 30s.
  - action: persistent_notification.create
    data:
      title: "ZTE Morning Signal Report"
      message: |
        Network: {{ states('sensor.zte_5g_signal_network_type') }}
        Bars: {{ states('sensor.zte_5g_signal_signal_bars') }}/5
        LTE RSRP: {{ states('sensor.zte_5g_signal_lte_rsrp') }} dBm
        5G RSRP: {{ states('sensor.zte_5g_signal_5g_rsrp') }} dBm
        Monthly data: {{ states('sensor.zte_5g_data_monthly_total') }}
        Reading taken: {{ states('sensor.zte_5g_system_last_updated') }}
    note: |
      Including Last Updated proves the report is fresh - if it does not move, the
      forced fetch did not land and the numbers above are stale.
```

---

</details>

## 📥 Installation

### ✨ HACS (Recommended)

1. Add this [repository](https://github.com/PlayFaster/ha-zte-router-5g-monitor) as a **Custom Repository** in HACS:
   - Open HACS in Home Assistant
   - Click **Custom repositories** (⋮ menu)
   - Add repository URL and Type: `Integration`
2. Search for "ZTE Router 5G Monitor" and click **Download**
3. Restart Home Assistant
4. Go to **Settings > Devices & Services > Add Integration** and search for "ZTE Router 5G Monitor"

### 💾 Manual Installation

1. Download the [latest release](https://github.com/PlayFaster/ha-zte-router-5g-monitor/releases).
2. Copy the `custom_components/zte_router_5g` folder to your Home Assistant `custom_components` directory
3. Restart Home Assistant
4. Go to **Settings > Devices & Services > Add Integration** and search for "ZTE Router 5G Monitor"

## 🔧 Configuration

### 🔧 Initial Setup

Setup is handled entirely via the UI. You will need the same details that you use for the router's web UI:

- **Host** — Router IP Address (e.g., 192.168.0.1)
- **Username** — Router login username (default: admin)
- **Password** — Admin password for the router web interface
- **Name** — Custom prefix for all devices and entities (default: `ZTE 5G`). This determines entity IDs — e.g. the default produces `sensor.zte_5g_data_monthly_total`. Change this if you have multiple routers or prefer a different naming scheme.

### 🔨 Runtime Options

After installation, open **Settings > Devices & Services > ZTE Router 5G Monitor > Configure** to adjust:

#### Connection Settings

| Option   | Description                                                |
| -------- | ---------------------------------------------------------- |
| Host     | Router IP address (change if the router's LAN IP changes). |
| Username | Router login username.                                     |
| Password | Admin password (update if changed on the router).          |

## 🔩 Under the Hood - Technical Architecture

### 🔄 Data Polling & 3-Strike Resilience 🩹

The integration uses a custom `DataUpdateCoordinator` designed for high stability:

- **Polling Loop**: Fetches all diagnostic and SMS data in a single optimized request.
- **Triggered Refresh**: Actions like **Reboot**, **Delete SMS**, or **Change Config** trigger an immediate API refresh to provide instant feedback.
- **3-Strike Logic**: To avoid "Unavailable" flickers during momentary router congestion or signal loss:
  1. **First Failure**: Logs a warning; retries immediately.
  2. **Second Failure**: Logs a warning; retries again.
  3. **Third Failure**: Marks all entities as `Unavailable` and logs an error.
- **Per-Endpoint Resilience**: The SMS endpoints carry their **own** strike budget. If SMS stops responding while the main data fetch keeps working, only the SMS entities are affected — Signal and Data keep updating.
- **Auto-Recovery**: Once the router is back online, the integration restores all entities automatically.
- **Forced Refresh Always Fetches**: Every explicit action — **Refresh Now**, changing a setting, deleting an SMS — fetches immediately **even while Pause Polling is on**. Only scheduled polls respect the pause.

### 🩺 Self-Diagnosis

Connection failures are visible already: entities go `Unavailable`. The gap this fills is the failure Home Assistant **cannot** see — a poll that _succeeds_ while the data is wrong.

The **Integration Health** binary sensor (System device) reports:

- **Total outage** — the router unreachable. Flagged on the **first** failure at startup (there are no held values, so waiting would leave you with no explanation), or on the **third** consecutive failure at runtime. A success clears it in the same cycle.
- **Degraded capability** — an optional endpoint that has exhausted its own strike budget.
- **Contract drift** — a successful response containing none of the fields the integration expects, which usually means a firmware update renamed them.

It is deliberately **available at all times**, including when every other entity has gone unavailable — a health sensor that disappears during an outage cannot explain the silence. See the [example automation](#-integration-health-problem-alert).

#### 🔨 Repairs

Some problems need you to do something, so they are also raised in Home Assistant's **Repairs** panel rather than only on a sensor. All three clear themselves automatically once the condition passes.

| Repair | Raised when | Why it is a Repair |
| :-- | :-- | :-- |
| **Router is not responding** | 10 consecutive failed fetches | Ten failures in a row means the problem is not clearing on its own. The text lists what to check — power-cycle, whether the IP changed, whether the password changed, the network path. |
| **Firmware may have changed its API** | 3 consecutive polls succeed but contain none of the expected fields | Nothing looks broken from the outside, but sensors will be blank. Needs reporting so the integration can be updated. |
| **SMS storage is full** | The router's message store is at capacity | New messages will be rejected until some are deleted. |

> [!NOTE] A brief outage — a router reboot, a passing network glitch — deliberately does **not** raise a Repair. Entities go unavailable after three failed polls, and Integration Health turns on, but the Repairs panel stays quiet until a problem has clearly stopped fixing itself.

### 🔐 Session Handling

The router permits only **one login session at a time**. The integration releases its session when the config entry is unloaded, reloaded or removed, so the router's web UI is available again immediately rather than after the session times out.

### 🆔 Identity & Stable Entities

- **IMEI-Based Identity**: The integration uses the router's unique hardware IMEI as the primary key. This ensures that even if your router's IP address changes (DHCP), Home Assistant will track the same device and preserve your history and automations.
- **Reconfiguration**: If you change your router's IP or password, use the **Reconfigure** button on the integration card to update settings without losing any data.
- **Data Validation**: Router values are checked for validity against defined guard limits. Out-of-range sensor values (e.g., impossible signal metrics) are ignored or marked as unknown to ensure data integrity.

### 🔄 Dynamic Polling & Standard System Options

- **Both Available**: The integration provides dynamic polling controls, to pause polling or change polling interval. It also functions normally with the standard Home Assistant **System options** > **Enable polling for changes** toggle.

## ❓ FAQ & Troubleshooting

### 🔌 Connection & Authentication

#### **"Failed to connect to router" Error**

<details>

<summary>
&nbsp; &nbsp; ➕ &nbsp; &nbsp; Click to Expand for Details:
</summary><br>

- Verify the IP address is correct.
- Confirm the username and password are correct (ZTE default is usually `admin`).
  - The username and password are the same as you use to login to the router via its webUI.
  - Username can be changed in the webUI, as well as password, so ensure you are using the current version of both.
- Ensure the router is powered on and reachable from your Home Assistant instance.

---

</details>

#### 🔒 **Why can't I access the router web UI while this integration is running?**

<details>

<summary>
&nbsp; &nbsp; ➕ &nbsp; &nbsp; Click to Expand for Details:
</summary><br>

- ZTE routers typically only allow **one simultaneous login session**.
- Use the **Pause Polling** switch in Home Assistant to halt polling before you log into the web UI.
- Resume polling when done!
- **Note:** logging into the web UI evicts the integration's session. The integration re-authenticates on its next poll, so this is harmless — but it is also why pausing is the tidier approach.
- Disabling or reloading the integration releases its session immediately, so you do not have to wait for it to time out.

---

</details>

### 📊 Diagnostics & Entity Values

#### ❔ **Some sensors showing "Unknown"**

<details>

<summary>
&nbsp; &nbsp; ➕ &nbsp; &nbsp; Click to Expand for Details:
</summary><br>

- Most sensors showing okay with some unknown **is expected behavior**.
  - The integration fetches everything it can from the router.
  - Not every metric is provided by every ISP or firmware version.
  - 5G NR sensors will show "Unknown" when the router is operating in LTE-only mode.

---

</details>

#### 🔨 **A "Router is not responding" Repair has appeared**

<details>

<summary>
&nbsp; &nbsp; ➕ &nbsp; &nbsp; Click to Expand for Details:
</summary><br>

- This means the integration failed to reach the router **10 times in a row**, so the problem is not resolving on its own. A reboot or a brief glitch will never raise it.
- Work through the checks in the Repair itself, in order: power-cycle the router; check whether its IP address has changed (the Repair names the address currently configured, so you can compare); check whether the router's password was changed; check the network path between Home Assistant and the router.
- If the address or the password has changed, use **Reconfigure** on the integration to update it. A static DHCP reservation for the router prevents the address changing again.
- The Repair clears itself as soon as the router answers.

---

</details>

#### 🛑 **All sensors showing "Unavailable" or "Unknown"**

<details>

<summary>
&nbsp; &nbsp; ➕ &nbsp; &nbsp; Click to Expand for Details:
</summary><br>

- This is normal during a router reboot or if the router is temporarily unreachable.
  - The integration will automatically recover once the connection is restored.
- If sensors do not recover, perform these checks:
  - Ensure you can log into the router's web UI (confirms it is up and the password is correct).
  - Check your Home Assistant logs for specific error messages.
  - Delete and re-add the integration.

---

</details>

## ❗ Known Limitations /❔ What's Missing?

- **Firmware Dependencies**: API feature availability varies by ISP and firmware builds.
- **Non-Bridge-Mode Features**: The integration was developed on and has only been tested with the MC7010 which is an outdoor bridge-mode only device without WiFi. This means the integration does not have:
  - **Client Tracking**: No tracking of connected clients.
  - **WiFi Monitoring**: There are no WiFi features.

## ❌ Removal

To remove the integration from Home Assistant:

<details>

<summary>
&nbsp; &nbsp; ➕ &nbsp; &nbsp; Click to Expand for Details:
</summary><br>

1. Go to **Settings > Devices & Services**.
2. Find the **ZTE Router 5G Monitor** card and click into it.
3. Click the **three dots** (⋮) next to the gear icon and select **Delete**.
4. Confirm deletion.

> [!NOTE]
>
> This integration writes **no files** of its own to `config/.storage` — the only things it stores are the config entry itself (host, credentials, and the discovered model / firmware / IMEI) and its entities and devices, all of which Home Assistant removes for you when the entry is deleted.
>
> Home Assistant keeps recorded history and entity customizations independently of the integration, so re-adding later picks up much where it left off.

---

</details>

<br>

To fully uninstall (HACS):

<details>

<summary>
&nbsp; &nbsp; ➕ &nbsp; &nbsp; Click to Expand for Details:
</summary><br>

1. Go to **HACS**.
2. Find **ZTE Router 5G Monitor** and click into it.
3. Click the **three dots** (⋮) at the top right and select **Remove**.
4. Restart Home Assistant.
5. Home Assistant automatically removes all associated entities and device entries from the registry when the integration is deleted.

---

</details>

## 📝 Maintenance Status

This is a **personal project**. Support and updates are provided on a **"best-effort"** basis only. While I use this integration daily and aim to keep it functional with the latest Home Assistant releases, I cannot guarantee immediate fixes for issues or compatibility with all router firmware versions.

---

## 🤝 Contributors & Acknowledgements

- 🙏 Special Thanks: This project is based on the original work done by @Kajkac on ZTE Routers. A big thanks for the heavy lifting!
- 🙏 **[huawei_lte_extended](https://github.com/william-aqn/huawei_lte_extended)** (@william-aqn): The approach to expanded SMS functionality in this integration is based on this work.
- This project was developed with the assistance of AI to ensure code quality and adherence to best practices.

---

## 📄 License

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

This project is licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.

---

💬 **Questions or Issues?** Visit the [GitHub repository](https://github.com/PlayFaster/ha-zte-router-5g-monitor).
