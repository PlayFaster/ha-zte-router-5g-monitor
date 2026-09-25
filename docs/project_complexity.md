# Project Complexity & Health: ha-zte-router-5g-monitor

**Last Measured:** 2026-09-25T21:48:09.017961+00:00 · **Release:** `3.4.4` · **Dev Version:** `3.4.4-dev2`

## 1. Executive Summary

| Metric | Value | Verdict / Evaluation |
| :-- | :-: | :-- |
| **PlayFaster Health Index** | **`70` / 100** | `WARNING` ($\ge 90$ Excellent · $\ge 80$ Good · $\ge 70$ Warning) |
| **Max McCabe Complexity ($V(G)$)** | **17** | `PASS (<20)` in `crawl` ($< 20$ Pass · $20–23$ Warn · $\ge 24$ Fail) |
| **Mean Complexity per Routine** | **2.89** | Across 466 routines (Ideal $< 4.0$ per routine) |
| **Danger Routines ($\ge 20$)** | **0** | Zero tolerance (refactor or decompose) |
| **Elevated Routines ($10–19$)** | **11** | Monitor closely; candidate for cleanup |
| **Mean Routine Length** | **15.0 code lines** | Target $\le 15$ code lines ideal |
| **Largest Routine Length** | **139 code lines** | `async_get_config_entry_diagnostics` in `diagnostics.py` (Target $\le 40$ ideal, $> 80$ warn, $> 150$ fail) |
| **Routines > 80 Code Lines** | **4** | Candidate for functional decomposition |
| **Largest Module** | **2,686 code lines** | `api.py` (Warn $> 1,500$ code lines module bloat) |
| **Modules > 1,500 Code Lines** | **3** | Candidate for module decomposition |
| **Code Suppressions (`# noqa`)** | **32** | Zero preferred; review regularly |
| **Type Suppressions (`# type: ignore`)** | **0** | Mypy strict compliance |
| **Source Python SLOC** | **11,552** | Across 22 files in custom_components/ (code statements) |
| **Docstring Volume** | **3,527 lines** | Interface and contract documentation |
| **Comment Density** | **26.2%** | 3,032 inline comment lines (Advisory: > 25% inspect for procedural narration) |
| **Platform Declarations SLOC** | **3,289 lines** | Across 6 platform files |
| **Core Engine / Driver SLOC** | **8,263 lines** | Across 16 coordinator/API/helper files |
| **Static Entities** | **130 entities** | Scale indicator (`all_sensors.md`) |
| **Platform SLOC / Entity** | **25.3 lines/entity** | Target 20 – 45 lines/entity declarative efficiency |
| **Test-to-Source Ratio** | **1.63×** | 18,850 test lines ($\ge 1.5×$ recommended) |
| **Pytest Coverage** | **100%** | 2067 tests executed |
| **Pytest Duration** | **642.66s** | Full test suite wall-clock execution time |

## 2. High Complexity Routines ($\ge 10$)

| Score | Routine Symbol | Location | Status |
| :-: | :-- | :-- | :-- |
| **17** | `crawl` | `web_sources.py:221` | `ELEVATED` |
| **15** | `_async_update_data_locked` | `coordinator.py:932` | `ELEVATED` |
| **14** | `parse_token` | `device_profile.py:194` | `ELEVATED` |
| **13** | `_resolve` | `web_sources.py:138` | `ELEVATED` |
| **12** | `_login_unlocked` | `api.py:2888` | `ELEVATED` |
| **12** | `_async_outage_check` | `coordinator.py:661` | `ELEVATED` |
| **11** | `probe_names` | `api.py:3516` | `ELEVATED` |
| **11** | `parse_profile` | `device_profile.py:641` | `ELEVATED` |
| **10** | `_literal_keys` | `device_profile.py:351` | `ELEVATED` |
| **10** | `_get_current_apn_profile` | `select.py:76` | `ELEVATED` |
| **10** | `extra_state_attributes` | `sensor.py:2467` | `ELEVATED` |

## 3. Active Code Suppressions (`custom_components/`)

| Line | Rule Bypassed | File |
| :-: | :-- | :-- |
| 219 | `BLE001` | `__init__.py` |
| 1503 | `BLE001` | `api.py` |
| 2177 | `BLE001` | `api.py` |
| 3452 | `BLE001` | `api.py` |
| 3489 | `BLE001` | `api.py` |
| 3512 | `BLE001` | `api.py` |
| 3746 | `BLE001` | `api.py` |
| 3973 | `BLE001` | `api.py` |
| 4015 | `BLE001` | `api.py` |
| 4246 | `BLE001` | `api.py` |
| 4718 | `BLE001` | `api.py` |
| 5120 | `S324` | `api.py` |
| 5258 | `BLE001` | `api.py` |
| 813 | `BLE001` | `coordinator.py` |
| 998 | `BLE001` | `coordinator.py` |
| 1791 | `BLE001` | `coordinator.py` |
| 2019 | `BLE001` | `coordinator.py` |
| 2086 | `BLE001` | `coordinator.py` |
| 2103 | `BLE001` | `coordinator.py` |
| 2140 | `BLE001` | `coordinator.py` |
| 2162 | `BLE001` | `coordinator.py` |
| 97 | `S324` | `device_profile.py` |
| 588 | `BLE001` | `diagnostics.py` |
| 603 | `BLE001` | `diagnostics.py` |
| 628 | `BLE001` | `diagnostics.py` |
| 177 | `BLE001, S112` | `observations.py` |
| 228 | `BLE001` | `observations.py` |
| 490 | `BLE001` | `observations.py` |
| 183 | `BLE001` | `poll_plan.py` |
| 398 | `BLE001` | `switch.py` |
| 480 | `BLE001` | `switch.py` |
| 134 | `BLE001` | `web_sources.py` |

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
| `coordinator.py:1202` | 22 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2424` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:676` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:702` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:60` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:234` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:888` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:576` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2785` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:974` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:306` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:365` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:853` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:77` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:624` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:198` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3655` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:38` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:518` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4169` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:441` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:55` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2349` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1885` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3802` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4086` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4476` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:5026` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:165` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1687` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2227` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:54` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1359` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3025` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3787` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:31` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:99` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:793` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `reset_entities.py:213` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:256` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2199` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3588` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:17` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:45` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:257` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:93` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1583` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:309` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:937` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3310` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:186` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:207` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:510` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:69` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:181` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `observations.py:59` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:383` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:618` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2764` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3938` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:153` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:122` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:275` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:327` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:145` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:200` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:233` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:489` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:731` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1253` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1612` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4052` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:5482` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `binary_sensor.py:155` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:223` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:272` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:322` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `device_profile.py:57` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:229` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:814` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1943` | 9 lines | Long procedural block; consider moving architecture notes to docs |

### 4.3 Routines with Comments Exceeding Code Lines

| Routine | Location | Comments / Code | Advisory |
| :-- | :-- | :-: | :-- |
| `__init__` | `api.py:1149` | 129 comm / 62 code | Comments exceed code statements; verify against procedural narration |
| `session_witnesses` | `api.py:1862` | 24 comm / 21 code | Comments exceed code statements; verify against procedural narration |
| `get_params` | `api.py:4140` | 15 comm / 13 code | Comments exceed code statements; verify against procedural narration |
