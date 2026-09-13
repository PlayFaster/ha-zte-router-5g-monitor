# Project Complexity & Health: ha-zte-router-5g-monitor

**Last Measured:** 2026-09-13T20:06:30.676621+00:00 · **Release:** `3.3.23` · **Dev Version:** `3.3.23`

## 1. Executive Summary

| Metric | Value | Verdict / Evaluation |
| :-- | :-: | :-- |
| **PlayFaster Health Index** | **`60` / 100** | `ACTION REQUIRED` ($\ge 90$ Excellent · $\ge 80$ Good · $\ge 70$ Warning) |
| **Max McCabe Complexity ($V(G)$)** | **19** | `PASS (<20)` in `_request` ($< 20$ Pass · $20–23$ Warn · $\ge 24$ Fail) |
| **Mean Complexity per Routine** | **3.03** | Across 390 routines (Ideal $< 4.0$ per routine) |
| **Danger Routines ($\ge 20$)** | **0** | Zero tolerance (refactor or decompose) |
| **Elevated Routines ($10–19$)** | **16** | Monitor closely; candidate for cleanup |
| **Mean Routine Length** | **17.8 code lines** | Target $\le 15$ code lines ideal |
| **Largest Routine Length** | **145 code lines** | `_run_rungs` in `sms_delete_probe.py` (Target $\le 40$ ideal, $> 80$ warn, $> 150$ fail) |
| **Routines > 80 Code Lines** | **11** | Candidate for functional decomposition |
| **Largest Module** | **2,013 code lines** | `api.py` (Warn $> 1,500$ code lines module bloat) |
| **Modules > 1,500 Code Lines** | **3** | Candidate for module decomposition |
| **Code Suppressions (`# noqa`)** | **40** | Zero preferred; review regularly |
| **Type Suppressions (`# type: ignore`)** | **0** | Mypy strict compliance |
| **Source Python SLOC** | **10,801** | Across 20 files in custom_components/ (code statements) |
| **Docstring Volume** | **2,780 lines** | Interface and contract documentation |
| **Comment Density** | **25.8%** | 2,783 inline comment lines (Advisory: > 25% inspect for procedural narration) |
| **Platform Declarations SLOC** | **3,003 lines** | Across 6 platform files |
| **Core Engine / Driver SLOC** | **7,798 lines** | Across 14 coordinator/API/helper files |
| **Static Entities** | **121 entities** | Scale indicator (`all_sensors.md`) |
| **Platform SLOC / Entity** | **24.8 lines/entity** | Target 20 – 45 lines/entity declarative efficiency |
| **Test-to-Source Ratio** | **1.39×** | 15,056 test lines ($\ge 1.5×$ recommended) |
| **Pytest Coverage** | **100%** | 1671 tests executed |
| **Pytest Duration** | **344.04s** | Full test suite wall-clock execution time |

## 2. High Complexity Routines ($\ge 10$)

| Score | Routine Symbol | Location | Status |
| :-: | :-- | :-- | :-- |
| **19** | `_request` | `api.py:1673` | `ELEVATED` |
| **19** | `_attempt` | `sms_delete_probe.py:1213` | `ELEVATED` |
| **17** | `_run_rungs` | `sms_delete_probe.py:1729` | `ELEVATED` |
| **16** | `_crawl` | `sms_delete_probe.py:605` | `ELEVATED` |
| **15** | `_fields_for` | `sms_delete_probe.py:721` | `ELEVATED` |
| **15** | `_web_ui_rungs` | `sms_delete_probe.py:2682` | `ELEVATED` |
| **13** | `_async_update_data_locked` | `coordinator.py:569` | `ELEVATED` |
| **13** | `_resolve` | `sms_delete_probe.py:522` | `ELEVATED` |
| **12** | `_candidate_rungs` | `sms_delete_probe.py:2196` | `ELEVATED` |
| **12** | `_transport_rungs` | `sms_delete_probe.py:2461` | `ELEVATED` |
| **11** | `login` | `api.py:1905` | `ELEVATED` |
| **11** | `probe_names` | `api.py:2548` | `ELEVATED` |
| **10** | `_get_current_apn_profile` | `select.py:73` | `ELEVATED` |
| **10** | `extra_state_attributes` | `sensor.py:2287` | `ELEVATED` |
| **10** | `_try_login` | `sms_delete_probe.py:286` | `ELEVATED` |
| **10** | `_web_ui_write_rungs` | `sms_delete_probe.py:2840` | `ELEVATED` |

## 3. Active Code Suppressions (`custom_components/`)

| Line | Rule Bypassed | File |
| :-: | :-- | :-- |
| 223 | `BLE001` | `__init__.py` |
| 1053 | `BLE001` | `api.py` |
| 2384 | `BLE001` | `api.py` |
| 2444 | `BLE001` | `api.py` |
| 2481 | `BLE001` | `api.py` |
| 2504 | `BLE001` | `api.py` |
| 2529 | `BLE001` | `api.py` |
| 2778 | `BLE001` | `api.py` |
| 2983 | `BLE001` | `api.py` |
| 3025 | `BLE001` | `api.py` |
| 3212 | `BLE001` | `api.py` |
| 3502 | `BLE001` | `api.py` |
| 3642 | `S324` | `api.py` |
| 3730 | `BLE001` | `api.py` |
| 461 | `BLE001` | `coordinator.py` |
| 900 | `BLE001` | `coordinator.py` |
| 565 | `BLE001` | `diagnostics.py` |
| 580 | `BLE001` | `diagnostics.py` |
| 128 | `BLE001, S112` | `observations.py` |
| 166 | `BLE001` | `observations.py` |
| 312 | `BLE001` | `observations.py` |
| 306 | `SLF001` | `sms_delete_probe.py` |
| 319 | `SLF001` | `sms_delete_probe.py` |
| 338 | `SLF001` | `sms_delete_probe.py` |
| 437 | `BLE001` | `sms_delete_probe.py` |
| 815 | `SLF001` | `sms_delete_probe.py` |
| 819 | `BLE001` | `sms_delete_probe.py` |
| 848 | `S324` | `sms_delete_probe.py` |
| 1028 | `BLE001` | `sms_delete_probe.py` |
| 1360 | `SLF001` | `sms_delete_probe.py` |
| 1606 | `BLE001` | `sms_delete_probe.py` |
| 1710 | `SLF001` | `sms_delete_probe.py` |
| 1752 | `SLF001` | `sms_delete_probe.py` |
| 1811 | `SLF001` | `sms_delete_probe.py` |
| 1823 | `SLF001` | `sms_delete_probe.py` |
| 1862 | `SLF001` | `sms_delete_probe.py` |
| 2542 | `SLF001` | `sms_delete_probe.py` |
| 3029 | `SLF001` | `sms_delete_probe.py` |
| 3038 | `SLF001` | `sms_delete_probe.py` |
| 345 | `BLE001` | `switch.py` |

## 4. Comment Quality & Density Audits

### 4.1 High Comment Density Files (> 25% comments/code)

| Module | Rationale / Advisory |
| :-- | :-- |
| `api.py` | Inspect for commented-out dead code or procedural narration |
| `const.py` | Inspect for commented-out dead code or procedural narration |
| `coordinator.py` | Inspect for commented-out dead code or procedural narration |
| `diagnostics.py` | Inspect for commented-out dead code or procedural narration |
| `entity_defaults.py` | Inspect for commented-out dead code or procedural narration |
| `sms_delete_probe.py` | Inspect for commented-out dead code or procedural narration |

### 4.2 Contiguous Comment Blocks (> 8 lines)

| Location | Length | Advisory |
| :-- | :-: | :-- |
| `const.py:170` | 30 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:851` | 24 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1567` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:786` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:548` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1704` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:202` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:63` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:866` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:266` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:519` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:242` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:834` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1120` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:179` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2687` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:869` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:429` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3150` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:52` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2169` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1355` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2830` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3092` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3276` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:112` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1573` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2046` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:98` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1949` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:40` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2025` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2815` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:31` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:46` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:38` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `reset_entities.py:213` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1844` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:242` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2620` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:17` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:75` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1469` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:289` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:649` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2310` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:133` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:154` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:370` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:51` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:162` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `observations.py:54` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1767` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:378` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:616` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2948` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:100` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:104` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:239` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:287` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:373` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1093` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:132` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:187` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:219` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:400` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:820` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1854` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3062` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3604` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `binary_sensor.py:155` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:207` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:700` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1817` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:457` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:2967` | 9 lines | Long procedural block; consider moving architecture notes to docs |

### 4.3 Routines with Comments Exceeding Code Lines

| Routine | Location | Comments / Code | Advisory |
| :-- | :-- | :-: | :-- |
| `__init__` | `api.py:799` | 67 comm / 41 code | Comments exceed code statements; verify against procedural narration |
| `get_ad` | `api.py:3583` | 22 comm / 18 code | Comments exceed code statements; verify against procedural narration |
| `session_witnesses` | `api.py:1332` | 24 comm / 21 code | Comments exceed code statements; verify against procedural narration |
| `get_params` | `api.py:3121` | 15 comm / 13 code | Comments exceed code statements; verify against procedural narration |
| `async_run_discovery` | `coordinator.py:1487` | 6 comm / 5 code | Comments exceed code statements; verify against procedural narration |
