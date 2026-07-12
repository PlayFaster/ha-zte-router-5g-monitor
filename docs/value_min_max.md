# Signal Metric Guard Bands

To ensure the Home Assistant UI remains clean and professional, we apply "Guard Bands" to incoming router data. If a value falls outside these realistic physical limits, the sensor is marked as `Unavailable` to prevent misleading spikes or "ghost" zeros.

## Guard Band Strategy (Option C)

We use a **Declarative Validation** approach. Limits are defined directly within the `EntityDescription` for each sensor. The base sensor class automatically enforces these bounds before passing the value to Home Assistant.

### Why this approach?

- **Readability**: Limits are visible next to the sensor definition.
- **Maintainability**: Changing a limit requires updating only one number, not complex logic.
- **Stability**: Prevents impossible values (e.g., 200dBm signal) from polluting long-term statistics and database storage.

---

## Validated Signal Limits

| Metric Category | Metric Name | Min | Max | Action if Out of Bounds |
| :-- | :-- | :-- | :-- | :-- |
| **Signal Power** | RSRP (5G/LTE) | -140 | -30 | Set to `Unavailable` |
|  | RSRQ (5G/LTE) | -40 | 0 | Set to `Unavailable` |
|  | RSSI (5G/LTE) | -120 | -20 | Set to `Unavailable` |
| **Signal Quality** | SNR / SINR | -20 | 50 | Set to `Unavailable` |
| **Diagnostics** | Signal Bar | 0 | 5 | Set to `Unavailable` |
| **Data Usage** | Monthly Download | 0 | 100TB | Set to `Unavailable` |
|  | Monthly Upload | 0 | 100TB | Set to `Unavailable` |
|  | Monthly Total | 0 | 100TB | Set to `Unavailable` |
|  | Upload Speed | 0 | — | Prevents negative values from firmware glitches. No upper bound (5G peak varies). |
|  | Download Speed | 0 | — | Prevents negative values from firmware glitches. No upper bound (5G peak varies). |
|  | Session Sent | 0 | — | Byte counter cannot be negative. Resets on reconnect (`TOTAL_INCREASING`). |
|  | Session Received | 0 | — | Byte counter cannot be negative. Resets on reconnect (`TOTAL_INCREASING`). |
|  | Data Volume Alert | 0 | 100 | Percentage threshold. |
| **Device** | Battery | 0 | 100 | Physical percentage bounds. |
| **SMS** | Total Count | 0 | 1000 | Set to `Unavailable` |

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

## Version Control

- **v1.1.0** (2026-05-07) - Initial versioned snapshot. Added guard bands for Battery (0–100 %), Upload Speed (min 0 B/s), Download Speed (min 0 B/s), Session Sent (min 0 bytes), Session Received (min 0 bytes), and Device Battery category.
- **v1.2.0** (2026-05-27) - Added guard band for Data Volume Alert percentage (0-100%).
