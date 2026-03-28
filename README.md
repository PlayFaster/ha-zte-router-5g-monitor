# ZTE Router Monitor for Home Assistant

Home Assistant integration for ZTE MC7010 5G Routers that provides detailed signal statistics, data usage tracking, and SMS management.

## Features

- **Works with ZTE 7010**: This works with, and has only been tested with, ZTE 7010 5G Outdoor CPE Router. It may work with other similiar ZTE devices.
  
- **Categorized Devices**: Separate devices for Router Stats, Data Usage, and SMS Services.
  
- **Signal Monitoring**: Real-time RSRP, RSRQ, RSSI, and SNR for both LTE and 5G.
  
- **Data Tracking**: Monthly download, upload, and total usage (GB).
  
- **SMS Management**: View recent messages and delete the mailbox directly from HA.
  
- **Resilient Polling**: Includes a hybrid retry logic (30s retry) and stale-data grace periods to prevent "Unavailable" flickers during router reboots.
  
## Installation

### Manual

1. Copy the `custom_components/zte_router` folder to your Home Assistant `custom_components` directory.
  
2. Restart Home Assistant.
  
3. Go to **Settings > Devices & Services > Add Integration** and search for "ZTE Router Monitor".
  
### HACS

1. Add this URL as a **Custom Repository** in HACS.
  
2. Click Download.
  
3. Restart Home Assistant and add via the UI.
  
## Configuration

Setup is handled entirely via the UI. You will need:

- Router IP Address (e.g., 192.168.0.1)
- Router Username
- Admin Password
