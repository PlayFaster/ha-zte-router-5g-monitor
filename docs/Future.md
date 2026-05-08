# Future Roadmap: ZTE Router 5G Integration

This document outlines strategic opportunities for future development of the `ha-zte-router-5g-monitor` integration. Given the current architectural stability and parity with the PlayFaster standards, future efforts should focus on transition from **monitoring** to **active management**.

## 1. High Priority: SMS Automation

The single largest feature gap compared to the TP-Link suite is the inability to send outbound SMS.

- **Objective**: Implement a `zte_router_5g.send_sms` service.
- **Technical Path**:
  - Utilize the `SEND_SMS` goform ID.
  - Requires hex-encoding for the `MessageBody`.
  - Requires a timestamped `sms_time` parameter in the payload.
- **Value**: Enables Home Assistant to interact with carrier-side services (e.g., checking data balances via text) and provides a non-IP-based emergency alert channel.

## 2. Medium Priority: Advanced Cellular Diagnostics

For users operating in **Bridge Mode**, the integration's primary value is monitoring the health of the 5G link.

- **Objective**: Expose Carrier Aggregation (CA) and MIMO metrics.
- **Proposed Sensors**:
  - `lte_ca_pcell_bandwidth` / `lte_ca_scell_bandwidth` (in MHz).
  - `wan_lte_ca` (Binary Sensor for "CA Active" state).
  - `nr5g_action_channel` (ARFCN for 5G).
- **Value**: Provides deeper insights for antenna alignment and identifying carrier-side throttling.

## 3. Medium Priority: Architectural Refinements

Improve the "snappiness" of the integration and reduce load on the router's processor.

- **Token Persistence**: Store the `stok` (Session Token) in `ConfigEntry` data or a local cache. This prevents a full login cycle on every Home Assistant restart.
- **Coordinator "Fast-Path"**: Update the `reboot` and `delete_sms` actions to trigger an immediate `coordinator.async_request_refresh()` for instant UI feedback.

## 4. Low Priority: Administrative Controls

Unlock "Power User" features currently restricted to the router's hidden WebUI menus.

- **Band Locking**: Implement a `select` entity to force the router onto specific LTE/5G bands (e.g., Force N78 or B20).
- **Cell Locking**: Allow locking to a specific PCI (Physical Cell ID).
- **Safety Requirement**: These features must include a "Reset to Auto" toggle to prevent permanent loss of connectivity.

---

## Roadmap Summary

| Phase           | Task                                 | Effort | Value      |
| :-------------- | :----------------------------------- | :----- | :--------- |
| **Short Term**  | **Implement `send_sms` service**     | Medium | ⭐⭐⭐⭐⭐ |
| **Short Term**  | **Add Carrier Aggregation sensors**  | Low    | ⭐⭐⭐     |
| **Medium Term** | **Token Persistence** (Stok storage) | Medium | ⭐⭐       |
| **Long Term**   | **Band Selection UI** (Experimental) | High   | ⭐⭐⭐⭐   |

**Current Status**: The integration is 100% compliant with PlayFaster v1.2 standards and provides exhaustive monitoring for Bridge Mode deployments.
