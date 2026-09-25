# Project Complexity & Health: ha-zte-router-5g-monitor

**Last Measured:** 2026-09-25T19:26:44.693702+00:00 · **Release:** `3.4.4` · **Dev Version:** `3.4.4-dev1`

## 1. Executive Summary

| Metric | Value | Verdict / Evaluation |
| :-- | :-: | :-- |
| **PlayFaster Health Index** | **`75` / 100** | `WARNING` ($\ge 90$ Excellent · $\ge 80$ Good · $\ge 70$ Warning) |
| **Max McCabe Complexity ($V(G)$)** | **17** | `PASS (<20)` in `crawl` ($< 20$ Pass · $20–23$ Warn · $\ge 24$ Fail) |
| **Mean Complexity per Routine** | **2.91** | Across 437 routines (Ideal $< 4.0$ per routine) |
| **Danger Routines ($\ge 20$)** | **0** | Zero tolerance (refactor or decompose) |
| **Elevated Routines ($10–19$)** | **11** | Monitor closely; candidate for cleanup |
| **Mean Routine Length** | **15.3 code lines** | Target $\le 15$ code lines ideal |
| **Largest Routine Length** | **132 code lines** | `async_get_config_entry_diagnostics` in `diagnostics.py` (Target $\le 40$ ideal, $> 80$ warn, $> 150$ fail) |
| **Routines > 80 Code Lines** | **3** | Candidate for functional decomposition |
| **Largest Module** | **2,650 code lines** | `api.py` (Warn $> 1,500$ code lines module bloat) |
| **Modules > 1,500 Code Lines** | **2** | Candidate for module decomposition |
| **Code Suppressions (`# noqa`)** | **27** | Zero preferred; review regularly |
| **Type Suppressions (`# type: ignore`)** | **0** | Mypy strict compliance |
| **Source Python SLOC** | **11,111** | Across 21 files in custom_components/ (code statements) |
| **Docstring Volume** | **3,433 lines** | Interface and contract documentation |
| **Comment Density** | **26.8%** | 2,973 inline comment lines (Advisory: > 25% inspect for procedural narration) |
| **Platform Declarations SLOC** | **3,247 lines** | Across 6 platform files |
| **Core Engine / Driver SLOC** | **7,864 lines** | Across 15 coordinator/API/helper files |
| **Static Entities** | **130 entities** | Scale indicator (`all_sensors.md`) |
| **Platform SLOC / Entity** | **25.0 lines/entity** | Target 20 – 45 lines/entity declarative efficiency |
| **Test-to-Source Ratio** | **1.65×** | 18,352 test lines ($\ge 1.5×$ recommended) |
| **Pytest Coverage** | **100%** | 2013 tests executed |
| **Pytest Duration** | **997.09s** | Full test suite wall-clock execution time |

## 2. High Complexity Routines ($\ge 10$)

| Score | Routine Symbol | Location | Status |
| :-: | :-- | :-- | :-- |
| **17** | `crawl` | `web_sources.py:221` | `ELEVATED` |
| **14** | `_async_update_data_locked` | `coordinator.py:897` | `ELEVATED` |
| **14** | `parse_token` | `device_profile.py:194` | `ELEVATED` |
| **13** | `_resolve` | `web_sources.py:138` | `ELEVATED` |
| **12** | `_login_unlocked` | `api.py:2831` | `ELEVATED` |
| **12** | `_async_outage_check` | `coordinator.py:640` | `ELEVATED` |
| **11** | `probe_names` | `api.py:3459` | `ELEVATED` |
| **11** | `parse_profile` | `device_profile.py:641` | `ELEVATED` |
| **10** | `_literal_keys` | `device_profile.py:351` | `ELEVATED` |
| **10** | `_get_current_apn_profile` | `select.py:76` | `ELEVATED` |
| **10** | `extra_state_attributes` | `sensor.py:2426` | `ELEVATED` |

## 3. Active Code Suppressions (`custom_components/`)

| Line | Rule Bypassed | File |
| :-: | :-- | :-- |
| 219 | `BLE001` | `__init__.py` |
| 1446 | `BLE001` | `api.py` |
| 2120 | `BLE001` | `api.py` |
| 3395 | `BLE001` | `api.py` |
| 3432 | `BLE001` | `api.py` |
| 3455 | `BLE001` | `api.py` |
| 3689 | `BLE001` | `api.py` |
| 3916 | `BLE001` | `api.py` |
| 3958 | `BLE001` | `api.py` |
| 4176 | `BLE001` | `api.py` |
| 4648 | `BLE001` | `api.py` |
| 5050 | `S324` | `api.py` |
| 5188 | `BLE001` | `api.py` |
| 792 | `BLE001` | `coordinator.py` |
| 1748 | `BLE001` | `coordinator.py` |
| 1946 | `BLE001` | `coordinator.py` |
| 1983 | `BLE001` | `coordinator.py` |
| 2005 | `BLE001` | `coordinator.py` |
| 97 | `S324` | `device_profile.py` |
| 584 | `BLE001` | `diagnostics.py` |
| 599 | `BLE001` | `diagnostics.py` |
| 177 | `BLE001, S112` | `observations.py` |
| 228 | `BLE001` | `observations.py` |
| 490 | `BLE001` | `observations.py` |
| 398 | `BLE001` | `switch.py` |
| 480 | `BLE001` | `switch.py` |
| 134 | `BLE001` | `web_sources.py` |

## 4. Comment Quality & Density Audits

### 4.1 High Comment Density Files (> 25% comments/code)

| Module | Rationale / Advisory |
| :-- | :-- |
| `api.py` | Inspect for commented-out dead code or procedural narration |
| `const.py` | Inspect for commented-out dead code or procedural narration |
| `coordinator.py` | Inspect for commented-out dead code or procedural narration |
| `device_profile.py` | Inspect for commented-out dead code or procedural narration |
| `diagnostics.py` | Inspect for commented-out dead code or procedural narration |
| `entity_defaults.py` | Inspect for commented-out dead code or procedural narration |

### 4.2 Contiguous Comment Blocks (> 8 lines)

| Location | Length | Advisory |
| :-- | :-: | :-- |
| `coordinator.py:1159` | 22 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2367` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:619` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:645` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:60` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:234` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:888` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:519` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2728` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:957` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:269` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:365` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:853` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:77` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:567` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:196` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3598` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:38` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:461` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4112` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:441` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:55` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2308` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1828` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3745` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4029` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4406` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4956` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:165` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1646` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2186` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:54` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1302` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2968` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3730` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:31` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:99` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:776` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `reset_entities.py:213` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:256` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2142` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3531` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:17` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:45` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:257` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:91` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1542` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:309` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:880` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3253` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:186` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:207` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:510` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:67` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:179` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `observations.py:59` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:383` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:618` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2707` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3881` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:153` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:120` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:242` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:290` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:145` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:200` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:233` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:432` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:674` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1196` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1555` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3995` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:5412` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `binary_sensor.py:155` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:223` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:272` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:322` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `device_profile.py:57` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:210` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:773` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1902` | 9 lines | Long procedural block; consider moving architecture notes to docs |

### 4.3 Routines with Comments Exceeding Code Lines

| Routine | Location | Comments / Code | Advisory |
| :-- | :-- | :-: | :-- |
| `__init__` | `api.py:1092` | 129 comm / 62 code | Comments exceed code statements; verify against procedural narration |
| `session_witnesses` | `api.py:1805` | 24 comm / 21 code | Comments exceed code statements; verify against procedural narration |
| `get_params` | `api.py:4083` | 15 comm / 13 code | Comments exceed code statements; verify against procedural narration |
