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
  - [🏠 Use Cases](#-use-cases)
  - [✅ Features](#-features)
  - [🔍 What You Get](#-what-you-get)
  - [💡 Example Automations](#-example-automations)
  - [📸 Screenshots](#-screenshots)
  - [📥 Installation](#-installation)
  - [🔧 Configuration](#-configuration)
  - [🔩 Under the Hood - Technical Architecture](#-under-the-hood---technical-architecture)
  - [❓ FAQ \& Troubleshooting](#-faq--troubleshooting)
  - [❌ Removal](#-removal)
  - [❗ Known Limitations /❔ What's Missing?](#-known-limitations--whats-missing)
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

## 🏠 Use Cases

- **Signal Monitoring**: Near-real-time and historical 5G/LTE signal data enable the monitoring of router performance.
  - **Best Signal**: Use signal diagnostics (RSRP, SNR) to optimize the physical placement or orientation of your router.
  - **Performance Tracking**: Use signal history to check whether the performance from your 5G/LTE ISP is stable or changing.
  - **Connection Quality**: Know if your router has dropped to a lower capability 4G/LTE only connection.
- **Data Cap Management**: Create automations to get notified when you reach 80% or 90% of your monthly data limit to avoid unexpected overage charges on limited 5G plans.
- **Smart SMS Gateway**: Use your router as a notification bridge; for example, forward home security alerts to your phone via SMS if your primary internet connection goes down.
  - **Obligatory Warning**: It is _**YOUR**_ responsibility to understand whether having your Router send SMS messages is going to incur an extra charge from your ISP.

## ✅ Features

### 📡 Advanced 5G/LTE Diagnostics

- **Detailed Signal Metrics**: RSRP, RSRQ, RSSI, and SNR for both the 5G NR and the LTE anchor cell.
- **Cell Tower Info**: Monitor Cell ID, eNodeB ID, PCI, and active frequency bands/channels.
- **Connection Type**: Track Carrier Aggregation and ENDC status plus LTE and 5G bands in use.

### 📉 Data Usage Tracking

- **Monthly Data Usage**: Track your monthly download, upload and total data usage.
- **Session Usage**: Track your download and upload for this session (i.e. since last router restart).
- **Download & Upload Speed**: Track your upload and download speeds. Note: This is valid, but only at the instant data was fetched from the router.

### 📋 Essential Router Management

- **Router Management**: Reboot the device directly from the HA UI.
- **100% Local**: No cloud account or internet access required.

### 🔄 Dynamic Polling

This integration features **dynamic polling**, the ability to pause polling completely or to change the polling interval.

- **Pause Polling**: Switch to halt polling when you need uninterrupted access to the router's web UI (ZTE only allows a single active login session).
- **Configurable Update Interval**: Dynamically adjust the scan interval (30s to 1 hour) via a number entity or automation.

> [!TIP]
>
> **Polling Interval can be controlled dynamically, via automation**
>
> - Set it to 30 seconds during periods of heavy use, to examine connection quality or when you need to receive new SMS messages quickly, and set it higher afterwards, to avoid taxing the router and your Home Assistant database.

### 💬 SMS Management Actions

Provides unread SMS count and latest message content sensors, a one-click **Delete All** button, a `zte_router_5g_sms_received` event for automation triggers, and four service actions for full programmatic control.

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
| `entry_id` | No | The router to use. Optional if only one router is configured. |
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
| `entry_id` | No | — | — | The router to use. Optional if only one router is configured. |
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
| `entry_id` | No | — | — | The router to use. Optional if only one router is configured. |
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

This integration provides **70+ entities** (depending on your firmware) organized into four logical devices: **System**, **Signal**, **Data**, and **SMS**.

> [!NOTE]
>
> Entity Visibility: To keep your Home Assistant UI clean, some entities are disabled by default. You can enable them via the Entities tab in the device settings.

| Sub-Device | Entity Types (+disabled) | Key Metrics | Disabled by Default |
| :-- | :-- | :-- | :-- |
| ⚙️ **System** | 9 Sensors, 3 Binary Sensors, 2 Switches, 2 Buttons, 1 Number (+5) | Firmware, IP Addresses, Uptime, Refresh Now, Reboot, Polling Controls, Reboot Schedule, UPnP, SIP ALG, SNTP Server | Uptime Duration, IMEI, Battery, SIM IMSI, SIM ICCID, ODU LED Switch, Reboot Schedule, UPnP Enabled, SIP ALG Enabled |
| 📶 **Signal** | 33 Sensors, 1 Binary Sensor, 3 Selects (+7) | RSRP, RSRQ, SINR, PCI, Cell ID, Primary/Secondary Bands, APN Profile, APN Mode, Network Mode Selection | RMCC, RMNC, LTE Secondary Band & Bandwidth, RSSI (legacy), RSCP (legacy), LTE Band Lock Mask |
| 📈 **Data** | 11 Sensors, 1 Switch (+4) | Monthly Usage, Near-real-time Speed, Session Data, Data Limit Switch, Data Volume Alert | Monthly Upload/Download/Total (Legacy GB sensors), Data Limit Switch, Data Volume Alert % |
| ✉️ **SMS Entities** | 3 Sensors, 1 Button | Unread Count, Total Msg, Recent Msg, Delete All (one-click) | None |
| 🛠️ **SMS Actions** | 4 Actions | Send, Delete, and List SMS | — |

> [!TIP]
>
> **Clean up your UI: Disable Unnecessary Devices or Entities**
>
> - If you never use the Router's SMS, you may not need the SMS sub-device.
> - Devices and their entities can be disabled from the main device page: (⋮ menu) > **Disable Device**.
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

## 💡 Example Automations

Entity IDs below use the default prefix zte_5g. If you set a custom name during setup, or have renamed since, replace zte_5g with your configured prefix.

### 💬 SMS Examples

#### 📨 Forward Incoming SMS to Mobile

This automation fires when a new SMS is detected and forwards the content to your mobile phone.

```yaml
alias: "SMS: Forward to Mobile"
triggers:
  - trigger: event
    event_type: zte_router_5g_sms_received
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: "New SMS from {{ trigger.event.data.phone }}"
      message: "{{ trigger.event.data.content }}"
```

#### 🧹 Automated Inbox Maintenance

Keep your router's SMS storage clean by automatically deleting old messages while keeping the most recent ones for safety.

```yaml
alias: "SMS: Weekly Inbox Cleanup"
triggers:
  - trigger: time
    at: "03:00:00"
conditions:
  - condition: time
    weekday:
      - sun
actions:
  - action: zte_router_5g.delete_all_sms
    data:
      entry_id: <your_config_entry_id> # This is GUI selectable in the Automation Editor.
      keep_last: 5
```

#### 📜 Fetch and Process Inbox via Automation

Example of using the `get_sms_list` action response in an automation to count messages from a specific sender.

```yaml
alias: "SMS: Count OTP Messages"
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
  - action: notify.persistent_notification
    data:
      message: |
        You have {{ inbox.messages | selectattr('phone', 'search', 'MY_BANK') |
        list | count }} messages from your bank in the inbox.
```

### 📡 APN & Network Selection Examples

#### 🔄 APN Failover

Automatically switch to a backup APN profile if the primary connection goes offline.

```yaml
alias: "APN: Switch Profile on Network Failure"
description: "Switch to a backup APN profile if the primary WAN connection drops."
triggers:
  - trigger: state
    entity_id: sensor.zte_5g_signal_wan_connect_status
    to: "disconnected"
    for: "00:05:00"
conditions:
  - condition: state
    entity_id: select.zte_5g_signal_apn_profile
    state: "primary_apn"
actions:
  - action: select.select_option
    target:
      entity_id: select.zte_5g_signal_apn_profile
    data:
      option: "backup_apn"
```

### 🚨 Data Usage Alert

Monitor your data consumption and get notified when you approach your monthly limit. If you change the display unit of data sensors (e.g. from Bytes to GB), you must change the numbers below as well.

```yaml
alias: "ZTE: High Data Usage Alert"
triggers:
  - trigger: numeric_state
    entity_id: sensor.zte_5g_data_monthly_total
    above: 500000000000 # 500 GB (in bytes)
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: "ZTE Data Alert"
      message: "Monthly data usage has exceeded 500GB."
```

### 📶 Signal Quality Alert

Monitor for poor connection quality based on 5G status and signal metrics.

```yaml
alias: "Signal: Poor Quality Connection Alert"
triggers:
  - trigger: state
    entity_id:
      - binary_sensor.zte_5g_signal_best_connection
    to: "off"
    for: "00:05:00"
  - trigger: state
    entity_id:
      - sensor.zte_5g_signal_network_type
    not_to: "ENDC"
    for: "00:05:00"
  - trigger: state
    entity_id:
      - sensor.zte_5g_signal_carrier_aggregation
    not_to: "ca_activated"
    for: "00:05:00"
  - trigger: numeric_state
    entity_id:
      - sensor.zte_5g_signal_signal_bars
    below: 4
    for: "00:05:00"
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
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: "Poor Signal Quality Detected"
      message: |
        The router connection quality is poor.
        - 5G ENDC: {{ states('sensor.zte_5g_signal_network_type') }}
        - Best Connection: {{ states('binary_sensor.zte_5g_signal_best_connection') }}
        - Signal Bars: {{ states('sensor.zte_5g_signal_signal_bars') }}
        - CA: {{ states('sensor.zte_5g_signal_carrier_aggregation') }}
```

### 🩺 System Health Alerts

#### 🚨 Router Reboot Alert

Monitor for router reboots by watching the device boot timestamp sensor.

```yaml
alias: "ZTE: Router Reboot Alert"
triggers:
  - trigger: template
    value_template: |
      {% set uptime = states('sensor.zte_5g_system_device_uptime') | as_datetime %}
      {{ uptime is not none and (now() - uptime).total_seconds() < 120 }}
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: "ZTE Router Rebooted"
      message: "The router has rebooted. Boot Time: {{ states('sensor.zte_5g_system_device_uptime') }}"
```

### 🔁 Auto-Resume Polling

Ensure polling is turned back on automatically if someone forgets to resume it after managing the router.

```yaml
alias: "ZTE: Auto-Resume Polling"
description: "Turn polling back on after 1 hour if it was manually paused."
triggers:
  - trigger: state
    entity_id: switch.zte_5g_system_pause_polling
    to: "on"
    for: "01:00:00"
actions:
  - action: switch.turn_off
    target:
      entity_id: switch.zte_5g_system_pause_polling
```

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

### 🔘 Runtime Controls & Settings (Entities)

Rather than hiding settings in configuration menus, several configuration parameters are exposed directly as Home Assistant control entities, allowing you to monitor and control them from dashboards or automations:

#### 📡 APN & Network Settings (Signal Device)

- **APN Profile** (`select.zte_5g_signal_apn_profile`): Switch the active default APN profile dynamically.
- **APN Selection Mode** (`select.zte_5g_signal_apn_selection_mode`): Toggle between `auto` and `manual` APN mode.
- **Network Mode Selection** (`select.zte_5g_signal_network_mode_selection`): Select the preferred connection type: `4G_AND_5G` (Auto), `LTE_AND_5G` (5G NSA), `Only_5G` (5G SA), or `Only_LTE` (4G Only).
- **LTE Band Lock Mask** (`sensor.zte_5g_signal_lte_band_lock_mask`): Displays the current hex mask configuration locking the active LTE bands.

#### 🔧 Router Administration & Security (System Device)

- **ODU LED Switch** (`switch.zte_5g_system_odu_led_switch`): Turn the physical status LEDs of the outdoor unit on or off (disabled by default).
- **Reboot Schedule** (`binary_sensor.zte_5g_system_reboot_schedule`): Indicates whether a scheduled reboot window is configured and active.
- **UPnP Enabled** / **SIP ALG Enabled** (`binary_sensor.zte_5g_system_upnp_enabled` / `binary_sensor.zte_5g_system_sip_alg_enabled`): Monitor firewall settings status.
- **Time Server (SNTP)** (`sensor.zte_5g_system_time_server_sntp`): Displays the active server used by the router for time synchronization.

#### 📈 Billing & Data Controls (Data Device)

- **Data Limit Switch** (`switch.zte_5g_data_data_limit_switch`): Enable/disable the router's data limit settings.
- **Data Volume Alert** (`sensor.zte_5g_data_data_volume_alert`): Displays the alarm warning percentage configured on the router (e.g., 90%).

## 🔩 Under the Hood - Technical Architecture

### 🔄 Data Polling & 3-Strike Resilience 🩹

The integration uses a custom `DataUpdateCoordinator` designed for high stability:

- **Polling Loop**: Fetches all diagnostic and SMS data in a single optimized request.
- **Triggered Refresh**: Actions like **Reboot**, **Delete SMS**, or **Change Config** trigger an immediate API refresh to provide instant feedback.
- **3-Strike Logic**: To avoid "Unavailable" flickers during momentary router congestion or signal loss:
  1. **First Failure**: Logs a warning; retries immediately.
  2. **Second Failure**: Logs a warning; retries again.
  3. **Third Failure**: Marks all entities as `Unavailable` and logs an error.
- **Auto-Recovery**: Once the router is back online, the integration restores all entities automatically.

### 🆔 Identity & Stable Entities

- **IMEI-Based Identity**: The integration uses the router's unique hardware IMEI as the primary key. This ensures that even if your router's IP address changes (DHCP), Home Assistant will track the same device and preserve your history and automations.
- **Reconfiguration**: If you change your router's IP or password, use the **Reconfigure** button on the integration card to update settings without losing any data.
- **Data Validation**: Router values are checked for validity against defined guard limits. Out-of-range sensor values (e.g., impossible signal metrics) are ignored or marked as unknown to ensure data integrity.

### 🔄 Dynamic Polling & Standard System Options

- **Both Available**: The integration provides dynamic polling controls, to pause polling or change polling interval. It also functions normally with the standard Home Assistant **System options** > **Enable polling for changes** toggle.

## ❓ FAQ & Troubleshooting

### 🔌 Connection & Authentication

#### **"Failed to connect to router" Error**

- Verify the IP address is correct.
- Confirm the username and password are correct (ZTE default is usually `admin`).
  - The username and password are the same as you use to login to the router via its webUI.
  - Username can be changed in the webUI, as well as password, so ensure you are using the current version of both.
- Ensure the router is powered on and reachable from your Home Assistant instance.

#### **Why can't I access the router web UI while this is connected?**

- ZTE routers typically only allow **one simultaneous login session**.
- Use the **Pause Polling** switch in Home Assistant to halt polling before you log into the web UI.
- Resume polling when done!

### 📊 Diagnostics & Entity Values

#### **Some sensors showing "Unknown"**

- Most sensors showing okay with some unknown **is expected behavior**.
  - The integration fetches everything it can from the router.
  - Not every metric is provided by every ISP or firmware version.
  - 5G NR sensors will show "Unknown" when the router is operating in LTE-only mode.

#### **All sensors showing "Unavailable" or "Unknown"**

- This is normal during a router reboot or if the router is temporarily unreachable.
  - The integration will automatically recover once the connection is restored.
- If sensors do not recover, perform these checks:
  - Ensure you can log into the router's web UI (confirms it is up and the password is correct).
  - Check your Home Assistant logs for specific error messages.
  - Delete and re-add the integration.

## ❌ Removal

To remove the integration from Home Assistant:

1. Go to **Settings > Devices & Services**.
2. Find the **ZTE Router 5G Monitor** card and click into it.
3. Click the **three dots** (⋮) next to the gear icon and select **Delete**.
4. Confirm deletion.

To fully uninstall (HACS):

1. Go to **HACS**.
2. Find **ZTE Router 5G Monitor** and click into it.
3. Click the **three dots** (⋮) at the top right and select **Remove**.
4. Restart Home Assistant.
5. Home Assistant automatically removes all associated entities and device entries from the registry when the integration is deleted.

## ❗ Known Limitations /❔ What's Missing?

- **Firmware Dependencies**: API feature availability varies by ISP and firmware builds.
- **Non Bridge Mode Features**: The integration was developed on and has only been tested with the MC7010 which is an outdoor bridge-mode only device without WiFi. This means the integration does not have:
  - **Client Tracking**: No tracking of connected clients.
  - **WiFi Monitoring**: There are no WiFi features.

## 📝 Maintenance Status

This is a **personal project**. Support and updates are provided on a **"best-effort"** basis only. While I use this integration daily and aim to keep it functional with the latest Home Assistant releases, I cannot guarantee immediate fixes for issues or compatibility with all router firmware versions.

## 🤝 Contributors & Acknowledgements

- 🙏 Special Thanks: This project is based on the original work done by @Kajkac on ZTE Routers. A big thanks for the heavy lifting!
- 🙏 **[huawei_lte_extended](https://github.com/william-aqn/huawei_lte_extended)** (@william-aqn): The approach to expanded SMS functionality in this integration is based on this work.
- This project was developed with the assistance of AI to ensure code quality and adherence to best practices.

## 📄 License

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

This project is licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.

---

💬 **Questions or Issues?** Visit the [GitHub repository](https://github.com/PlayFaster/ha-zte-router-5g-monitor).
