# Signal Metric Guard Bands

To ensure the Home Assistant UI remains clean and professional, we apply "Guard Bands" to incoming router data. If a value falls outside these realistic physical limits, the sensor reads `Unknown` to prevent misleading spikes or "ghost" zeros.

## Guard Band Strategy (Option C)

We use a **Declarative Validation** approach. Limits are defined directly within the `EntityDescription` for each sensor. The base sensor class automatically enforces these bounds before passing the value to Home Assistant.

### Why this approach?

- **Readability**: Limits are visible next to the sensor definition.
- **Maintainability**: Changing a limit requires updating only one number, not complex logic.
- **Stability**: Prevents impossible values (e.g., 200dBm signal) from polluting long-term statistics and database storage.

---

## Validated Signal Limits

<!-- GENERATED:start -->

| Sub-device | Sensor key                  |    Min |                Max | Unit |
| :--------- | :-------------------------- | -----: | -----------------: | :--- |
| Data       | `data_allowance`            |    `0` | `1125899906842624` | B    |
| Data       | `data_clear_day`            |    `1` |               `31` | —    |
| Data       | `data_projection`           |    `0` |                  — | B    |
| Data       | `data_volume_alert_percent` |    `0` |              `100` | %    |
| Data       | `monthly_rx_bytes`          |    `0` |                  — | GB   |
| Data       | `monthly_rx_bytes_raw`      |    `0` |                  — | B    |
| Data       | `monthly_total_bytes`       |    `0` |                  — | GB   |
| Data       | `monthly_total_bytes_raw`   |    `0` |                  — | B    |
| Data       | `monthly_tx_bytes`          |    `0` |                  — | GB   |
| Data       | `monthly_tx_bytes_raw`      |    `0` |                  — | B    |
| Data       | `realtime_rx_bytes`         |    `0` |                  — | B    |
| Data       | `realtime_rx_thrpt`         |    `0` |                  — | B/s  |
| Data       | `realtime_tx_bytes`         |    `0` |                  — | B    |
| Data       | `realtime_tx_thrpt`         |    `0` |                  — | B/s  |
| SMS        | `msg_total`                 |    `0` |             `1000` | —    |
| SMS        | `sms_unread_num`            |    `0` |             `1000` | —    |
| Signal     | `5g_rsrp_antenna_1`         | `-140` |              `-40` | dBm  |
| Signal     | `5g_rsrp_antenna_2`         | `-140` |              `-40` | dBm  |
| Signal     | `ca_scell_rsrp`             | `-140` |              `-40` | dBm  |
| Signal     | `ca_scell_rsrq`             |  `-40` |                `0` | dB   |
| Signal     | `ca_scell_rssi`             | `-120` |              `-20` | dBm  |
| Signal     | `ca_scell_snr`              |  `-20` |               `50` | dB   |
| Signal     | `lte_rsrp`                  | `-140` |              `-30` | dBm  |
| Signal     | `lte_rsrq`                  |  `-40` |                `0` | dB   |
| Signal     | `lte_rssi`                  | `-120` |              `-20` | dBm  |
| Signal     | `lte_snr`                   |  `-20` |               `50` | dB   |
| Signal     | `rscp`                      | `-120` |              `-20` | dBm  |
| Signal     | `rssi`                      | `-120` |              `-20` | dBm  |
| Signal     | `signalbar`                 |    `0` |                `5` | —    |
| Signal     | `sinr`                      |  `-20` |               `50` | dB   |
| Signal     | `z5g_rsrp`                  | `-140` |              `-30` | dBm  |
| Signal     | `z5g_rsrq`                  |  `-40` |                `0` | dB   |
| Signal     | `z5g_rssi`                  | `-120` |              `-20` | dBm  |
| Signal     | `z5g_sinr`                  |  `-20` |               `50` | dB   |
| System     | `battery_value`             |    `0` |              `100` | %    |
| System     | `connection_failure_count`  |    `0` |            `10000` | —    |
| System     | `pm_modem_5g`               |  `-40` |              `125` | °C   |
| System     | `pm_sensor_5g`              |  `-40` |              `125` | °C   |
| System     | `pm_sensor_ambient`         |  `-40` |              `125` | °C   |
| System     | `pm_sensor_mdm`             |  `-40` |              `125` | °C   |
| System     | `pm_sensor_pa1`             |  `-40` |              `125` | °C   |
| System     | `realtime_time`             |    `0` |                  — | s    |
| System     | `sim_pin_attempts`          |    `0` |               `10` | —    |
| System     | `sim_puk_attempts`          |    `0` |               `10` | —    |
| WiFi       | `wifi_clients`              |    `0` |              `256` | —    |

<!-- GENERATED:end -->

---

## Implementation Details

The `ZTESensorEntityDescription` data-class includes:

- `min_limit`: The lowest physically possible value.
- `max_limit`: The highest physically possible value.

The `native_value` property in the sensor class performs the following check:

```python
try:
    val = self.entity_description.value_fn(self.coordinator.data)
    if val is not None:
        num_val = float(val)
        if min_limit is not None and num_val < min_limit:
            return None
        if max_limit is not None and num_val > max_limit:
            return None
    return val
except (ValueError, TypeError):
    return val
```

---

## Coverage

**Every numeric sensor carries a guard band, and a test enforces it.** `test_every_numeric_sensor_has_a_guard_band` fails if a sensor with a unit or a state class ships without bounds.

Two are exempt by name, in `_UNGUARDED_BY_DESIGN`:

| Sensor | Why it is safe without one |
| :-- | :-- |
| `lte_ca_pcell_bandwidth` | Channel width the network chose. No state class, so it never reaches long-term statistics and a bad reading cannot corrupt history — which is the whole of the exemption. Adding one would end it, and the sensor would then need bounds. |
| `lte_ca_scell_bandwidth` | As above. |

Adding a numeric sensor without bounds is therefore a deliberate act with a stated reason, not something that can happen by omission.

**This document cannot be trusted on its own.** A guard band is a property of the entity description in `sensor.py`, invisible to Home Assistant and to any live query — so `sensor_review` cannot see one. Until 2026-08-01 this file documented bounds for five sensors that the code did not apply, and nothing detected it. The test above is what makes the two agree; treat this table as a description of the code, never as a substitute for reading it.

---

## Version Control

- **v1.5.0** (2026-08-01) — Reconciled against the code for the first time. Five documented bands did not exist (`Signal Bar`, `Monthly Download/Upload/Total`, `Total Count`) and two real ones were undocumented (`Legacy RSSI`, `Legacy RSCP`). Rather than delete the five rows, the guard bands were added to the code: the six monthly byte counters gained `min_limit=0`, matching the session counters, which had carried it since the start — a negative value on a `TOTAL_INCREASING` sensor is written to long-term statistics and stays there. Upper bounds on those counters were dropped as unsafe: a ceiling on an accumulating counter silently discards legitimate data. `Signal Bars`, `Total Msg`, `Unread Msg` and `Uptime Duration` also gained bands. Two row names were wrong and now match the entities (`Total Count` → `Total Msg`, `Signal Bar` → `Signal Bars`). Added the Coverage section and the test that keeps this file honest.
- **v1.1.0** (2026-05-07) - Initial versioned snapshot. Added guard bands for Battery (0–100 %), Upload Speed (min 0 B/s), Download Speed (min 0 B/s), Session Sent (min 0 bytes), Session Received (min 0 bytes), and Device Battery category.
- **v1.2.0** (2026-05-27) - Added guard band for Data Volume Alert percentage (0-100%).
- **v1.3.0** (2026-07-29) - Added guard bands for the five thermal sensors: Power Amplifier, Ambient Modem, Modem, 5G Modem and 5G Radio temperatures (-40 to 125 degrees C), covering the silicon operating range and rejecting the sentinel values some firmware emits when the sensor is absent.
- **v1.4.0** (2026-07-30) — Added guard bands for `Reset Day` (1–31, a day of the month), `Projected Cycle Usage` (min 0, no ceiling — exceeding it is the very thing the sensor exists to warn about) and `Allowance` (0 to 1 PiB, an upper bound against a misparse of the router's `<value>_<multiplier>` encoding reaching the statistics). Renamed `Data Volume Alert` → **`Alert Threshold`** after the entity was renamed to avoid a doubled entity ID.
