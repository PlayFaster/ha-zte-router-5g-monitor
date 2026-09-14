# Project Complexity & Health: ha-zte-router-5g-monitor

**Last Measured:** 2026-09-14T19:00:16.068322+00:00 · **Release:** `3.3.25` · **Dev Version:** `3.3.25-dev7`

## 1. Executive Summary

| Metric | Value | Verdict / Evaluation |
| :-- | :-: | :-- |
| **PlayFaster Health Index** | **`60` / 100** | `ACTION REQUIRED` ($\ge 90$ Excellent · $\ge 80$ Good · $\ge 70$ Warning) |
| **Max McCabe Complexity ($V(G)$)** | **19** | `PASS (<20)` in `_attempt` ($< 20$ Pass · $20–23$ Warn · $\ge 24$ Fail) |
| **Mean Complexity per Routine** | **3.00** | Across 415 routines (Ideal $< 4.0$ per routine) |
| **Danger Routines ($\ge 20$)** | **0** | Zero tolerance (refactor or decompose) |
| **Elevated Routines ($10–19$)** | **15** | Monitor closely; candidate for cleanup |
| **Mean Routine Length** | **17.4 code lines** | Target $\le 15$ code lines ideal |
| **Largest Routine Length** | **145 code lines** | `_run_rungs` in `sms_delete_probe.py` (Target $\le 40$ ideal, $> 80$ warn, $> 150$ fail) |
| **Routines > 80 Code Lines** | **10** | Candidate for functional decomposition |
| **Largest Module** | **2,287 code lines** | `api.py` (Warn $> 1,500$ code lines module bloat) |
| **Modules > 1,500 Code Lines** | **3** | Candidate for module decomposition |
| **Code Suppressions (`# noqa`)** | **41** | Zero preferred; review regularly |
| **Type Suppressions (`# type: ignore`)** | **0** | Mypy strict compliance |
| **Source Python SLOC** | **11,115** | Across 20 files in custom_components/ (code statements) |
| **Docstring Volume** | **3,051 lines** | Interface and contract documentation |
| **Comment Density** | **26.7%** | 2,969 inline comment lines (Advisory: > 25% inspect for procedural narration) |
| **Platform Declarations SLOC** | **3,003 lines** | Across 6 platform files |
| **Core Engine / Driver SLOC** | **8,112 lines** | Across 14 coordinator/API/helper files |
| **Static Entities** | **121 entities** | Scale indicator (`all_sensors.md`) |
| **Platform SLOC / Entity** | **24.8 lines/entity** | Target 20 – 45 lines/entity declarative efficiency |
| **Test-to-Source Ratio** | **1.43×** | 15,911 test lines ($\ge 1.5×$ recommended) |
| **Pytest Coverage** | **100%** | 1738 tests executed |
| **Pytest Duration** | **329.09s** | Full test suite wall-clock execution time |

## 2. High Complexity Routines ($\ge 10$)

| Score | Routine Symbol | Location | Status |
| :-: | :-- | :-- | :-- |
| **19** | `_attempt` | `sms_delete_probe.py:1213` | `ELEVATED` |
| **17** | `_run_rungs` | `sms_delete_probe.py:1729` | `ELEVATED` |
| **16** | `_crawl` | `sms_delete_probe.py:605` | `ELEVATED` |
| **15** | `_fields_for` | `sms_delete_probe.py:721` | `ELEVATED` |
| **15** | `_web_ui_rungs` | `sms_delete_probe.py:2682` | `ELEVATED` |
| **13** | `_async_update_data_locked` | `coordinator.py:569` | `ELEVATED` |
| **13** | `_resolve` | `sms_delete_probe.py:522` | `ELEVATED` |
| **12** | `_candidate_rungs` | `sms_delete_probe.py:2196` | `ELEVATED` |
| **12** | `_transport_rungs` | `sms_delete_probe.py:2461` | `ELEVATED` |
| **11** | `login` | `api.py:2508` | `ELEVATED` |
| **11** | `probe_names` | `api.py:3153` | `ELEVATED` |
| **10** | `_get_current_apn_profile` | `select.py:73` | `ELEVATED` |
| **10** | `extra_state_attributes` | `sensor.py:2287` | `ELEVATED` |
| **10** | `_try_login` | `sms_delete_probe.py:286` | `ELEVATED` |
| **10** | `_web_ui_write_rungs` | `sms_delete_probe.py:2840` | `ELEVATED` |

## 3. Active Code Suppressions (`custom_components/`)

| Line | Rule Bypassed | File |
| :-: | :-- | :-- |
| 223 | `BLE001` | `__init__.py` |
| 1221 | `BLE001` | `api.py` |
| 1849 | `BLE001` | `api.py` |
| 2989 | `BLE001` | `api.py` |
| 3049 | `BLE001` | `api.py` |
| 3086 | `BLE001` | `api.py` |
| 3109 | `BLE001` | `api.py` |
| 3134 | `BLE001` | `api.py` |
| 3383 | `BLE001` | `api.py` |
| 3588 | `BLE001` | `api.py` |
| 3630 | `BLE001` | `api.py` |
| 3817 | `BLE001` | `api.py` |
| 4177 | `BLE001` | `api.py` |
| 4317 | `S324` | `api.py` |
| 4405 | `BLE001` | `api.py` |
| 461 | `BLE001` | `coordinator.py` |
| 913 | `BLE001` | `coordinator.py` |
| 565 | `BLE001` | `diagnostics.py` |
| 580 | `BLE001` | `diagnostics.py` |
| 128 | `BLE001, S112` | `observations.py` |
| 166 | `BLE001` | `observations.py` |
| 337 | `BLE001` | `observations.py` |
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
| `const.py:210` | 30 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:851` | 24 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:581` | 22 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2086` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:46` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:786` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:555` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:242` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:70` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2446` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:899` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:266` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:526` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:297` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:834` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1120` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:179` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3292` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:869` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:436` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3755` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:52` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2169` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1591` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3435` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3697` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3950` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:152` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1573` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2046` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:98` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1949` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:47` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2630` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3420` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:31` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:86` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:38` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `reset_entities.py:213` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1844` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:249` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1015` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1866` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3225` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:17` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:265` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:75` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1469` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:296` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:701` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2915` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:173` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:194` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:425` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:51` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:162` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `observations.py:54` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1767` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:378` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:621` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2426` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3553` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:140` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:104` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:239` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:287` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:373` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1093` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:139` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:194` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:226` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:407` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:612` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:930` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1028` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3667` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4279` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `binary_sensor.py:155` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:207` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:700` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1817` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:457` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:2967` | 9 lines | Long procedural block; consider moving architecture notes to docs |

### 4.3 Routines with Comments Exceeding Code Lines

| Routine | Location | Comments / Code | Advisory |
| :-- | :-- | :-: | :-- |
| `__init__` | `api.py:909` | 109 comm / 54 code | Comments exceed code statements; verify against procedural narration |
| `_perform` | `api.py:2440` | 19 comm / 7 code | Comments exceed code statements; verify against procedural narration |
| `get_ad` | `api.py:4258` | 22 comm / 18 code | Comments exceed code statements; verify against procedural narration |
| `session_witnesses` | `api.py:1568` | 24 comm / 21 code | Comments exceed code statements; verify against procedural narration |
| `get_params` | `api.py:3726` | 15 comm / 13 code | Comments exceed code statements; verify against procedural narration |
| `async_run_discovery` | `coordinator.py:1500` | 6 comm / 5 code | Comments exceed code statements; verify against procedural narration |
