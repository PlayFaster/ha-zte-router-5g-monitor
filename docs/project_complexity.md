# Project Complexity & Health: ha-zte-router-5g-monitor

**Last Measured:** 2026-09-24T13:56:39.581979+00:00 · **Release:** `3.4.3` · **Dev Version:** `3.4.3-dev1`

## 1. Executive Summary

| Metric | Value | Verdict / Evaluation |
| :-- | :-: | :-- |
| **PlayFaster Health Index** | **`74` / 100** | `WARNING` ($\ge 90$ Excellent · $\ge 80$ Good · $\ge 70$ Warning) |
| **Max McCabe Complexity ($V(G)$)** | **16** | `PASS (<20)` in `crawl` ($< 20$ Pass · $20–23$ Warn · $\ge 24$ Fail) |
| **Mean Complexity per Routine** | **2.90** | Across 425 routines (Ideal $< 4.0$ per routine) |
| **Danger Routines ($\ge 20$)** | **0** | Zero tolerance (refactor or decompose) |
| **Elevated Routines ($10–19$)** | **11** | Monitor closely; candidate for cleanup |
| **Mean Routine Length** | **15.3 code lines** | Target $\le 15$ code lines ideal |
| **Largest Routine Length** | **132 code lines** | `async_get_config_entry_diagnostics` in `diagnostics.py` (Target $\le 40$ ideal, $> 80$ warn, $> 150$ fail) |
| **Routines > 80 Code Lines** | **3** | Candidate for functional decomposition |
| **Largest Module** | **2,594 code lines** | `api.py` (Warn $> 1,500$ code lines module bloat) |
| **Modules > 1,500 Code Lines** | **2** | Candidate for module decomposition |
| **Code Suppressions (`# noqa`)** | **27** | Zero preferred; review regularly |
| **Type Suppressions (`# type: ignore`)** | **0** | Mypy strict compliance |
| **Source Python SLOC** | **10,907** | Across 21 files in custom_components/ (code statements) |
| **Docstring Volume** | **3,362 lines** | Interface and contract documentation |
| **Comment Density** | **26.6%** | 2,896 inline comment lines (Advisory: > 25% inspect for procedural narration) |
| **Platform Declarations SLOC** | **3,219 lines** | Across 6 platform files |
| **Core Engine / Driver SLOC** | **7,688 lines** | Across 15 coordinator/API/helper files |
| **Static Entities** | **130 entities** | Scale indicator (`all_sensors.md`) |
| **Platform SLOC / Entity** | **24.8 lines/entity** | Target 20 – 45 lines/entity declarative efficiency |
| **Test-to-Source Ratio** | **1.63×** | 17,758 test lines ($\ge 1.5×$ recommended) |
| **Pytest Coverage** | **100%** | 1942 tests executed |
| **Pytest Duration** | **213.19s** | Full test suite wall-clock execution time |

## 2. High Complexity Routines ($\ge 10$)

| Score | Routine Symbol | Location | Status |
| :-: | :-- | :-- | :-- |
| **16** | `crawl` | `web_sources.py:208` | `ELEVATED` |
| **14** | `_async_update_data_locked` | `coordinator.py:897` | `ELEVATED` |
| **14** | `parse_token` | `device_profile.py:190` | `ELEVATED` |
| **13** | `_resolve` | `web_sources.py:125` | `ELEVATED` |
| **12** | `login` | `api.py:2749` | `ELEVATED` |
| **12** | `_async_outage_check` | `coordinator.py:640` | `ELEVATED` |
| **11** | `probe_names` | `api.py:3377` | `ELEVATED` |
| **10** | `_literal_keys` | `device_profile.py:347` | `ELEVATED` |
| **10** | `parse_profile` | `device_profile.py:557` | `ELEVATED` |
| **10** | `_get_current_apn_profile` | `select.py:70` | `ELEVATED` |
| **10** | `extra_state_attributes` | `sensor.py:2432` | `ELEVATED` |

## 3. Active Code Suppressions (`custom_components/`)

| Line | Rule Bypassed | File |
| :-: | :-- | :-- |
| 219 | `BLE001` | `__init__.py` |
| 1381 | `BLE001` | `api.py` |
| 2053 | `BLE001` | `api.py` |
| 3313 | `BLE001` | `api.py` |
| 3350 | `BLE001` | `api.py` |
| 3373 | `BLE001` | `api.py` |
| 3607 | `BLE001` | `api.py` |
| 3818 | `BLE001` | `api.py` |
| 3860 | `BLE001` | `api.py` |
| 4078 | `BLE001` | `api.py` |
| 4546 | `BLE001` | `api.py` |
| 4929 | `S324` | `api.py` |
| 5067 | `BLE001` | `api.py` |
| 792 | `BLE001` | `coordinator.py` |
| 1748 | `BLE001` | `coordinator.py` |
| 1946 | `BLE001` | `coordinator.py` |
| 1983 | `BLE001` | `coordinator.py` |
| 2000 | `BLE001` | `coordinator.py` |
| 93 | `S324` | `device_profile.py` |
| 571 | `BLE001` | `diagnostics.py` |
| 586 | `BLE001` | `diagnostics.py` |
| 177 | `BLE001, S112` | `observations.py` |
| 228 | `BLE001` | `observations.py` |
| 490 | `BLE001` | `observations.py` |
| 399 | `BLE001` | `switch.py` |
| 481 | `BLE001` | `switch.py` |
| 121 | `BLE001` | `web_sources.py` |

## 4. Comment Quality & Density Audits

### 4.1 High Comment Density Files (> 25% comments/code)

| Module | Rationale / Advisory |
| :-- | :-- |
| `api.py` | Inspect for commented-out dead code or procedural narration |
| `const.py` | Inspect for commented-out dead code or procedural narration |
| `device_profile.py` | Inspect for commented-out dead code or procedural narration |
| `diagnostics.py` | Inspect for commented-out dead code or procedural narration |
| `entity_defaults.py` | Inspect for commented-out dead code or procedural narration |

### 4.2 Contiguous Comment Blocks (> 8 lines)

| Location | Length | Advisory |
| :-- | :-: | :-- |
| `coordinator.py:1159` | 22 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2294` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:618` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:644` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:60` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:234` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:879` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:518` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2655` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:942` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:269` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:365` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:844` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:76` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:566` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:196` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3516` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:38` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:460` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4014` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:441` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:55` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2314` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1761` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3663` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3931` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4304` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4835` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:165` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1651` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2192` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:53` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1237` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2886` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3648` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:31` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:99` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:763` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `reset_entities.py:213` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:255` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2075` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3449` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:17` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:45` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:257` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:91` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1547` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:308` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:827` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3171` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:186` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:207` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:510` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:67` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:179` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `observations.py:59` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:383` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:618` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2634` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3783` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:153` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:120` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:242` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:290` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:144` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:199` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:232` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:431` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:673` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1143` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1490` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3897` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:5287` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `binary_sensor.py:155` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:223` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:272` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:322` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `device_profile.py:53` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:210` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:778` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1907` | 9 lines | Long procedural block; consider moving architecture notes to docs |

### 4.3 Routines with Comments Exceeding Code Lines

| Routine | Location | Comments / Code | Advisory |
| :-- | :-- | :-: | :-- |
| `__init__` | `api.py:1039` | 120 comm / 59 code | Comments exceed code statements; verify against procedural narration |
| `session_witnesses` | `api.py:1738` | 24 comm / 21 code | Comments exceed code statements; verify against procedural narration |
| `get_params` | `api.py:3985` | 15 comm / 13 code | Comments exceed code statements; verify against procedural narration |
