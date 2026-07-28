# ZTE Router Model Compatibility & Scope Guide 📟

Created 2026-07-28

This document details hardware compatibility, API protocol families, and integration scope for **ZTE Router 5G Monitor (ZRM)** (`zte_router_5g`).

---

## 🎯 Core Scope & Design Philosophy

ZRM is designed specifically as a **cellular WAN, signal, data usage, and SMS telemetry monitor** for ZTE 5G/4G CPE routers (optimized for outdoor or indoor bridge-mode deployments).

> [!IMPORTANT] **What ZRM does NOT do:** ZRM deliberately **excludes LAN/Wi-Fi client device tracking**. In bridge mode (e.g. MC7010 connected to a downstream UniFi, OPNSense, or pfSense firewall), DHCP and client tracking are handled by the primary router. Excluding client tracking keeps ZRM lightweight, prevents API polling collisions, and maintains compliance with Home Assistant architectural standards.

---

## 🟢 Fully Tested Hardware

| Router Model | Category | Firmware Version | Verification Status |
| :-- | :-- | :-- | :-- |
| **ZTE MC7010** | 5G Outdoor CPE | `V1.0.0B01` and later | **Fully Tested** on live physical hardware |

_The ZTE MC7010 is currently the ONLY device verified on physical hardware by the integration maintainers._

---

## 🟡 Expected Compatible Hardware (`goform` API Family)

The following ZTE 5G and 4G CPE models use the **ZTE `goform` HTTP API** (`goform_get_cmd_process`, `goform_set_cmd_process`). Protocol support and model-dependent security handlers are built into ZRM's API client (`api.py`), so these devices are expected to work but remain unverified on live equipment:

### 1. 5G Indoor & Outdoor CPEs

- **ZTE MC801 / MC801A** (5G Indoor CPE) — Shares the single-user `LOGIN` challenge form and `goform` multi-data batch polling.
- **ZTE MC888 / MC888A / MC888 Ultra** (5G Wi-Fi 6 Indoor CPE) — Shares `goform` batch queries. Utilizes SHA-256 for `AD` write token calculation (supported in `api.py:get_ad()`).
- **ZTE MC889 / MC889A** (5G Outdoor CPE — successor to MC7010) — Shares the `goform` batch API and SHA-256 `AD` token calculation.

### 2. 4G LTE CPEs & Modems

- **ZTE MF266** (LTE Outdoor CPE)
- **ZTE MF286 / MF286D / MF289F** (LTE Indoor Routers)
- Other ZTE 4G/5G CPE modems using the `goform` web interface.

#### Why these are expected compatible

1. **Shared Batch Endpoint**: They respond to `GET goform_get_cmd_process?multi_data=1&cmd=...` with flat JSON objects.
2. **Identical Login Challenge**: They utilize the `LD` token salt challenge + double SHA-256 password hash + `stok` cookie.
3. **Built-in `AD` Token branching**: ZRM automatically switches between MD5 (MC7010/MC801) and SHA-256 (MC888/MC889) based on the router's firmware version string.

---

## 🔴 Incompatible Router Families & Recommended Alternatives

ZRM will **NOT** work with the following router families because they use fundamentally different API backends or serve a different operational scope:

### 1. ZTE Next-Gen G5-Series CPEs (`ubus` API Engine)

- **Incompatible Models**: **ZTE G5TC**, **ZTE G5TS**, **ZTE G5C**, **ZTE G5 Max**, **ZTE G5 Ultra** (new firmware revisions).
- **Reason for Incompatibility**: These routers run an OpenWrt-derived backend. They do not expose `/goform/goform_get_cmd_process`; instead, they listen at `/ubus/?t={timestamp}` using JSON-RPC POST requests to the `zwrt_web` service.
- **Recommended Integration**: Use **[`rosenrot00/ha-zte-ng-router`](https://github.com/rosenrot00/ha-zte-ng-router)** by @rosenrot00.

### 2. ZTE Landline Broadband / Fiber ONTs / DSL Routers (`_type=` Lua/XML API)

- **Incompatible Models**:
  - **ZTE F-Series**: `F6640`, `F6645P`, `F680`, `F6600P`, `F8748`
  - **ZTE H-Series**: `H169A`, `H2640`, `H288A`, `H388X`, `H3600P`, `H3640`, `H6645P`
  - **Other Landline Models**: `AX3000`, `E2631`, `SR7410`, `ZTE FIBRA6S` (Orange Spain Livebox 6s)
- **Reason for Incompatibility**:
  1. **Different API Protocol**: These devices use ZTE's legacy web console (`?_type=menuData` or `?_type=hiddenData`), calling internal Lua scripts (`accessdev_landevs_lua.lua`, `wan_internetstatus_lua.lua`) returning XML or JSON responses.
  2. **Lack of Cellular Telemetry**: Landline fiber/DSL ONTs do not expose 5G/LTE cellular signal metrics (RSRP, RSRQ, SNR, EARFCN/ARFCN, carrier aggregation).
  3. **LAN Device Focus**: These integrations focus heavily on Wi-Fi/LAN client tracking and mesh node topology discovery, which ZRM explicitly excludes.
- **Recommended Integrations**:
  - For general ZTE landline/fiber routers & mesh topology: Use **[`juacas/zte_tracker`](https://github.com/juacas/zte_tracker)** by @juacas.
  - For Orange Spain Livebox 6s (`FIBRA6S`): Use **[`AldenDana/ha-zte-fibra`](https://github.com/AldenDana/ha-zte-fibra)** by @AldenDana.

### 3. Non-ZTE Router Hardware

- ZRM does not support non-ZTE hardware.

---

## 📊 Summary Protocol Comparison

| Router Family | Representative Models | API Protocol | Primary Focus | ZRM Compatibility | Alternative Integration |
| :-- | :-- | :-- | :-- | :-- | :-- |
| **ZTE 5G/4G CPE (MC Series)** | MC7010, MC801A, MC888, MC889 | `goform` HTTP API | 5G/LTE Signal, WAN Telemetry, SMS | ✅ **Supported** (MC7010 tested) | **ZRM** (`zte_router_5g`) |
| **ZTE Next-Gen 5G CPE (G5 Series)** | G5TC, G5TS, G5C, G5 Max | `ubus` JSON-RPC API | 5G Signal & Router Status | ❌ Incompatible | [`ha-zte-ng-router`](https://github.com/rosenrot00/ha-zte-ng-router) |
| **ZTE Landline Broadband / Fiber ONTs** | F6640, F680, H288A, H388X, FIBRA6S | `_type=` Lua / XML API | LAN Device Tracking & Mesh Topology | ❌ Incompatible | [`zte_tracker`](https://github.com/juacas/zte_tracker) / [`ha-zte-fibra`](https://github.com/AldenDana/ha-zte-fibra) |

---

## 📚 Related Documents

- [`zte_how_to_access.md`](zte_how_to_access.md) — Technical reference for the ZTE `goform` HTTP API, login challenge, and `AD` tokens.
- [`all_sensors.md`](all_sensors.md) — Complete inventory of the 76 entities provided by ZRM.
- [`DEVELOPMENT.md`](DEVELOPMENT.md) — Architecture, devcontainer setup, and DataUpdateCoordinator resilience rules.
- [`.notes/info/other_zte_projects/analysis_and_learnings.md`](../.notes/info/other_zte_projects/analysis_and_learnings.md) — In-depth comparative research across open-source ZTE Home Assistant projects.
- [`.notes/info/other_zte_projects/additional_zte_resources.md`](../.notes/info/other_zte_projects/additional_zte_resources.md) — Ecosystem map of additional ZTE custom components, Python CLI tools, and reverse-engineering resources.
