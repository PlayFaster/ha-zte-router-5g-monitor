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

| Metric Category    | Metric Name                          | Min  | Max   | Action if Out of Bounds                                                                                                                                                 |
| :----------------- | :----------------------------------- | :--- | :---- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Signal Power**   | RSRP (5G/LTE)                        | -140 | -30   | Set to `Unknown`                                                                                                                                                        |
|                    | RSRQ (5G/LTE)                        | -40  | 0     | Set to `Unknown`                                                                                                                                                        |
|                    | RSSI (5G/LTE)                        | -120 | -20   | Set to `Unknown`                                                                                                                                                        |
|                    | Legacy RSSI                          | -120 | -20   | Disabled by default. Separate entity from the LTE and 5G RSSI sensors above.                                                                                            |
|                    | Legacy RSCP                          | -120 | -20   | Disabled by default. Separate entity from the LTE and 5G RSSI sensors above.                                                                                            |
| **Signal Quality** | SNR                                  | -20  | 50    | Set to `Unknown`                                                                                                                                                        |
| **Diagnostics**    | Signal Bars                          | 0    | 5     | The router's own 0-5 rating; anything outside it is not a rating.                                                                                                       |
|                    | Uptime Duration                      | 0    | —     | Seconds since boot cannot be negative. No ceiling — a long-running router is not an error.                                                                              |
| **Data Usage**     | Monthly Download                     | 0    | —     | Byte counter cannot be negative (`TOTAL_INCREASING`). No upper bound: a ceiling on an accumulating counter silently drops legitimate data.                              |
|                    | Monthly Upload                       | 0    | —     | As above.                                                                                                                                                               |
|                    | Monthly Total                        | 0    | —     | As above.                                                                                                                                                               |
|                    | Monthly Download / Upload / Total GB | 0    | —     | Disabled-by-default legacy sensors. Same counters divided by 10⁹, so the same floor applies.                                                                            |
|                    | Upload Speed                         | 0    | —     | Prevents negative values from firmware glitches. No upper bound (5G peak varies).                                                                                       |
|                    | Download Speed                       | 0    | —     | Prevents negative values from firmware glitches. No upper bound (5G peak varies).                                                                                       |
|                    | Session Sent                         | 0    | —     | Byte counter cannot be negative. Resets on reconnect (`TOTAL_INCREASING`).                                                                                              |
|                    | Session Received                     | 0    | —     | Byte counter cannot be negative. Resets on reconnect (`TOTAL_INCREASING`).                                                                                              |
|                    | Alert Threshold                      | 0    | 100   | Percentage threshold.                                                                                                                                                   |
|                    | Allowance                            | 0    | 1 PiB | Confirmed against the router's own Data Management page (2 TiB cap, 1.6 TiB reminder), but the upper bound stays as a guard against a misparse reaching the statistics. |
|                    | Reset Day                            | 1    | 31    | Day of the month. A value outside this range is not a calendar date, whatever the router reports.                                                                       |
|                    | Projected Cycle Usage                | 0    | —     | A projection cannot be negative. No upper bound: exceeding it is the very thing the sensor exists to warn about, so a ceiling would hide the case that matters.         |
| **Device**         | Battery                              | 0    | 100   | Physical percentage bounds.                                                                                                                                             |
|                    | Power Amplifier Temperature          | -40  | 125   | Silicon operating range; rejects the sentinel values some firmware emits when the sensor is absent.                                                                     |
|                    | Ambient Modem Temperature            | -40  | 125   | Silicon operating range; rejects the sentinel values some firmware emits when the sensor is absent.                                                                     |
|                    | Modem Temperature                    | -40  | 125   | Silicon operating range; rejects the sentinel values some firmware emits when the sensor is absent.                                                                     |
|                    | 5G Modem Temperature                 | -40  | 125   | Silicon operating range; rejects the sentinel values some firmware emits when the sensor is absent.                                                                     |
|                    | 5G Radio Temperature                 | -40  | 125   | Silicon operating range; rejects the sentinel values some firmware emits when the sensor is absent.                                                                     |
| **SMS**            | Total Msg                            | 0    | 1000  | Sum across all NV and SIM banks. A count cannot be negative.                                                                                                            |
|                    | Unread Msg                           | 0    | 1000  | A count cannot be negative.                                                                                                                                             |

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

| Sensor                   | Why it is safe without one                                                                 |
| :----------------------- | :----------------------------------------------------------------------------------------- |
| `lte_ca_pcell_bandwidth` | Channel width the network chose. No state class, so it never reaches long-term statistics. |
| `lte_ca_scell_bandwidth` | As above.                                                                                  |

Adding a numeric sensor without bounds is therefore a deliberate act with a stated reason, not something that can happen by omission.

**This document cannot be trusted on its own.** A guard band is a property of the entity description in `sensor.py`, invisible to Home Assistant and to any live query — so `sensor_review` cannot see one. Until 2026-08-01 this file documented bounds for five sensors that the code did not apply, and nothing detected it. The test above is what makes the two agree; treat this table as a description of the code, never as a substitute for reading it.

---

## Version Control

- **v1.5.0** (2026-08-01) — Reconciled against the code for the first time. Five documented bands did not exist (`Signal Bar`, `Monthly Download/Upload/Total`, `Total Count`) and two real ones were undocumented (`Legacy RSSI`, `Legacy RSCP`). Rather than delete the five rows, the guard bands were added to the code: the six monthly byte counters gained `min_limit=0`, matching the session counters, which had carried it since the start — a negative value on a `TOTAL_INCREASING` sensor is written to long-term statistics and stays there. Upper bounds on those counters were dropped as unsafe: a ceiling on an accumulating counter silently discards legitimate data. `Signal Bars`, `Total Msg`, `Unread Msg` and `Uptime Duration` also gained bands. Two row names were wrong and now match the entities (`Total Count` → `Total Msg`, `Signal Bar` → `Signal Bars`). Added the Coverage section and the test that keeps this file honest.
- **v1.1.0** (2026-05-07) - Initial versioned snapshot. Added guard bands for Battery (0–100 %), Upload Speed (min 0 B/s), Download Speed (min 0 B/s), Session Sent (min 0 bytes), Session Received (min 0 bytes), and Device Battery category.
- **v1.2.0** (2026-05-27) - Added guard band for Data Volume Alert percentage (0-100%).
- **v1.3.0** (2026-07-29) - Added guard bands for the five thermal sensors: Power Amplifier, Ambient Modem, Modem, 5G Modem and 5G Radio temperatures (-40 to 125 degrees C), covering the silicon operating range and rejecting the sentinel values some firmware emits when the sensor is absent.
- **v1.4.0** (2026-07-30) — Added guard bands for `Reset Day` (1–31, a day of the month), `Projected Cycle Usage` (min 0, no ceiling — exceeding it is the very thing the sensor exists to warn about) and `Allowance` (0 to 1 PiB, an upper bound against a misparse of the router's `<value>_<multiplier>` encoding reaching the statistics). Renamed `Data Volume Alert` → **`Alert Threshold`** after the entity was renamed to avoid a doubled entity ID.
