# ZTE Router Model Compatibility & Scope Guide 📟

Created 2026-07-28

This document details hardware compatibility, API protocol families, and integration scope for **ZTE Router 5G Monitor (ZRM)** (`zte_router_5g`).

---

## 🎯 Core Scope & Design Philosophy

ZRM is designed specifically as a **cellular WAN, signal, data usage, and SMS monitor** for ZTE 5G/4G CPE routers (optimized for outdoor or indoor bridge-mode deployments).

> [!IMPORTANT] **What ZRM does NOT do:** ZRM deliberately **excludes LAN/Wi-Fi client device tracking**. It reports a WiFi _client count_ on models that supply one, which is a single number from the router's own status page and creates no per-device entities. In bridge mode (e.g. MC7010 connected to a downstream UniFi, OPNSense, or pfSense firewall), DHCP and client tracking are handled by the primary router. Excluding client tracking keeps ZRM lightweight, prevents API polling collisions, and maintains compliance with Home Assistant architectural standards.

---

## 🟢 Fully Tested Hardware

| Router Model | Category | Firmware Version | Verification Status |
| :-- | :-- | :-- | :-- |
| **ZTE MC7010** | 5G Outdoor CPE | `V1.0.0B01` and later | **Fully Tested** on live physical hardware |

_The ZTE MC7010 is currently the ONLY device verified on physical hardware by the integration maintainers._

The MC7010 works the same in bridge mode and router mode. Compared on 2026-09-24, both modes answer the same keys, and no entity changes meaning. The only differences are the WAN mode reading and the WAN address. Switching mode reboots the router, which Device Uptime records as a reboot.

On the MC7010, Device Uptime reads the router's own uptime, `system_uptime`. A router that does not answer that key falls back to the data session's counter, so its Device Uptime moves at each data reconnect, the same as Connection Uptime. On the MC888 Pro, which answers no uptime key, Device Uptime is disabled by default on new installs, as Uptime Duration is on every model. Turning the **Data Connection** switch off or on takes the MC7010 offline for up to about 40 s, and other controls are refused until it answers again.

---

## 🟡 Expected Compatible Hardware (`goform` API Family)

The following ZTE 5G and 4G CPE models use the **ZTE `goform` HTTP API** (`goform_get_cmd_process`, `goform_set_cmd_process`). Protocol support and model-dependent security handlers are built into ZRM's API client (`api.py`), so these devices are expected to work but remain unverified on live equipment:

### 1. 5G Indoor & Outdoor CPEs

- **ZTE MC801 / MC801A** (5G Indoor CPE) — Shares the single-user `LOGIN` challenge form and `goform` multi-data batch polling.
- **ZTE MC888 / MC888A / MC888 Ultra** (5G Wi-Fi 6 Indoor CPE) — Shares `goform` batch queries. Utilizes SHA-256 for `AD` write token calculation (supported in `api.py:get_ad()`).
- **ZTE MC889 / MC889A** (5G Outdoor CPE — successor to MC7010) — Shares the `goform` batch API and SHA-256 `AD` token calculation.

### 2. 4G LTE CPEs & Modems

- **ZTE MF266** (LTE Outdoor CPE) — an alternative dedicated integration also exists: [`teixeluis/zte-lte-modem`](https://github.com/teixeluis/zte-lte-modem).
- **ZTE MF286 / MF286D / MF289F** (LTE Indoor Routers)
- Other ZTE 4G/5G CPE modems using the `goform` web interface.

#### Why these are expected compatible

1. **Shared Batch Endpoint**: They respond to `GET goform_get_cmd_process?multi_data=1&cmd=...` with flat JSON objects.
2. **Identical Login Challenge**: They utilize the `LD` token salt challenge + double SHA-256 password hash + `stok` cookie.
3. **The `AD` token recipe is read from the device**: since `[3.3.25-dev10]` ZRM parses the router's own `js/service.js` for the function its token expression names, and resolves that name to a digest. The token is `hash(hash(wa_inner_version + cr_version) + RD)`; a device that does not answer `cr_version`, the MC7010 among them, contributes an empty second operand. Confirmed against a token an MC888 Pro accepted, 2026-09-11.

   The model string — MD5 for MC7010/MC801, SHA-256 for MC888/MC889 — is now the fallback for a firmware whose pages cannot be read. It was the only mechanism until `[3.3.25-dev10]`, and it is wrong in principle: `js/config/config.js` is effectively identical between the MC7010 and the MC888 Pro on every flag that could plausibly select a digest, including `WEB_ATTR_IF_SUPPORT_SHA256`, which reads `2` on both. Only the function the script names distinguishes them.

   **The sources disagree on more than the digest.** `teixeluis/zte-lte-modem` documents the MF266 as `MD5(MD5(cr + wa) + RD).upper()` — the operand order reversed and an uppercased MD5, against the MC7010's `wa + cr` lowercase. Operand order comes from the `rd_params` mapping in the device's own service layer, and the case travels with the digest name, so an MF266 gets both from itself rather than from a list it is not on.
4. **Per-model entity defaults**: which entities start enabled is resolved per router model, because models answer different subsets of the parameter set. The MC888 Pro reports its signal quality under `network_`-prefixed names an MC7010 does not use, so **RSSI** and **SINR** start enabled there and the five LTE and 5G sensors it cannot fill start disabled; the MC7010 has no WiFi of its own, so the two WiFi sensors start disabled there and enabled everywhere else. An unrecognised model gets the standard set. Curated from diagnostics captures, never measured at runtime — see `entity_defaults.MODEL_OVERLAY`. `check_sensor_manifest.py --verify-ha` reads the same overlay and resolves against it, so an entity the overlay disables for the connected model reading `unknown` is the expected result and is reported as a note rather than a finding. Only the disabling half is honoured there: the overlay also enables **RSSI** and **SINR** on the MC888 Pro, and acting on that would subject them to a liveness check on hardware the tool has never run against.
5. **Cross-model parameter spellings**: 36 alternate spellings resolve to the same entities, so a router using the `network_` or `flux_` vocabulary populates sensors named for the bare one.

#### What ZRM does to accommodate them (added 3.3.1)

- **Alternative field names**: the same measurement is spelled differently across firmware releases. Signal and data-usage sensors try each known spelling in turn and take whichever the router populated — `Z5g_rsrp` / `5g_rsrp` / `nr5g_rsrp`, `Z5g_SINR` / `Z5g_snr`, `nr5g_pci` / `Z5g_CELL_ID`, `monthly_*_bytes` / `flux_monthly_*_bytes`. The MC7010 spelling is always tried first, so its behavior is unchanged.
- **Login form fallback**: which form a `goform` router accepts is a per-model quirk. If the first form yields no session, ZRM retries once with the other (`LOGIN` ↔ `LOGIN_MULTI_USER`). A credentials rejection is **not** retried — a wrong password is wrong on either form, and a second attempt only counts against routers that lock out.

  Since `[3.3.25-dev11]` the device's own login form narrows the first choice: ZRM reads whether that form carries a `username` field, and a form carrying none selects `LOGIN`. Only that direction is used — the MC7010 carries a username and still uses `LOGIN`, so reading the flag symmetrically would move it onto a form it does not accept. The model-string branch remains behind it. `teixeluis/zte-lte-modem` documents the MF266 as `LOGIN_MULTI_USER` with `user=admin`, which the fallback already reaches.
- **Band name from channel number**: where a router reports `wan_active_channel` / `nr5g_action_channel` but leaves the band name blank, ZRM derives it from the 3GPP EARFCN/NR-ARFCN tables. A band name the router reports always wins. NR ranges overlap (n78 sits inside n77), so the derived NR band is best-effort.
- **Optional thermal sensors**: five temperature sensors (`pm_sensor_pa1`, `pm_sensor_ambient`, `pm_sensor_mdm`, `pm_modem_5g`, `pm_sensor_5g`), all **disabled by default**. The MC7010 returns an empty value for every one and no model is yet confirmed to populate them.
- **Carrier aggregation reports three states, not two.** `wan_lte_ca` has been observed as `ca_activated`, `ca_deconfigured` and `ca_deactivated` across 22 diagnostics downloads from two models. `ca_deactivated` was seen once, on an MC888 Pro on 2026-09-07, alongside a configured secondary cell (`network_lte_ca_scell_band = 3`, 20 MHz) and populated secondary-cell signal data — aggregation set up but not carrying traffic, which `ca_deconfigured` (no secondary cell at all) does not describe. The **Best Connection** binary sensor requires `ca_activated` exactly, so the third state reads as off, which is correct.
- **Secondary-cell signal data appears only while a secondary carrier exists.** `lte_multi_ca_scell_sig_info` is populated on both tested models when one is configured, and is empty or absent otherwise — absent rather than empty when the poll did not request it, since it is a discovery-mined name rather than a core-poll one. Its field order (RSRP, RSRQ, SNR, RSSI) was derived on hardware; see `_scell_field` in `sensor.py` for the derivation.

> [!NOTE] **Most of the above is not verified on hardware.** The fallbacks are derived from other open-source `goform` projects and from published 3GPP tables. The exceptions are the entries that state a measurement — the thermal sensors, the carrier-aggregation states and the secondary-cell signal data — which are recorded from diagnostics downloads and name the model and date. Every path tries the MC7010 behavior first, so the realistic failure mode on an untested model is that a fallback quietly does nothing — not that anything regresses on a tested one. Reports from other models are welcome.

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
  2. **Lack of Cellular Metrics**: Landline fiber/DSL ONTs do not expose 5G/LTE cellular signal metrics (RSRP, RSRQ, SNR, EARFCN/ARFCN, carrier aggregation).
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
| **ZTE 5G/4G CPE (MC Series)** | MC7010, MC801A, MC888, MC889 | `goform` HTTP API | 5G/LTE Signal, WAN Status, SMS | ✅ **Supported** (MC7010 tested on hardware; MC888 Pro verified from diagnostics captures) | **ZRM** (`zte_router_5g`) |
| **ZTE Next-Gen 5G CPE (G5 Series)** | G5TC, G5TS, G5C, G5 Max | `ubus` JSON-RPC API | 5G Signal & Router Status | ❌ Incompatible | [`ha-zte-ng-router`](https://github.com/rosenrot00/ha-zte-ng-router) |
| **ZTE Landline Broadband / Fiber ONTs** | F6640, F680, H288A, H388X, FIBRA6S | `_type=` Lua / XML API | LAN Device Tracking & Mesh Topology | ❌ Incompatible | [`zte_tracker`](https://github.com/juacas/zte_tracker) / [`ha-zte-fibra`](https://github.com/AldenDana/ha-zte-fibra) |

**Reads and writes are different questions.** Reads are expected to work broadly: discovery builds entities from the names a device actually answers, so a name an unknown model does not report is absent rather than an error. Writes depend on the device's own token and request form, and are confirmed on two models only.

|  | MC7010 | MC888 Pro |
| :-- | :-- | :-- |
| Reads | Tested on hardware | Confirmed from downloads, 97 names populated |
| Data-limit switch | Works | Works, from `[3.3.22]` |
| SMS delete | Works, effectively synchronous | Works, but completes after the integration's check looks |
| SMS send | Works, message received | Accepted and stored as a draft; nothing transmitted, and the router's own web interface fails to send too |
| APN, bearer, LED, reboot | Works | Untested |

A control that appears to do nothing is the reason a diagnostics download is asked for first: this API answers `200 OK` with `{"result":"success"}` for writes it does not perform, so a silent refusal cannot be told from a completed write any other way.

---

## 📚 Related Documents

- [`zte_how_to_access.md`](zte_how_to_access.md) — Technical reference for the ZTE `goform` HTTP API, login challenge, and `AD` tokens.
- [`all_sensors.md`](all_sensors.md) — Complete inventory of the entities provided by ZRM, and the authoritative source for the count.
- [`DEVELOPMENT.md`](DEVELOPMENT.md) — Architecture, devcontainer setup, and DataUpdateCoordinator resilience rules.
