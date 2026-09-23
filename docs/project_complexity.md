# Project Complexity & Health: ha-zte-router-5g-monitor

**Last Measured:** 2026-09-23T06:28:34.722678+00:00 · **Release:** `3.4.0` · **Dev Version:** `3.4.1-dev2`

## 1. Executive Summary

| Metric | Value | Verdict / Evaluation |
| :-- | :-: | :-- |
| **PlayFaster Health Index** | **`75` / 100** | `WARNING` ($\ge 90$ Excellent · $\ge 80$ Good · $\ge 70$ Warning) |
| **Max McCabe Complexity ($V(G)$)** | **16** | `PASS (<20)` in `crawl` ($< 20$ Pass · $20–23$ Warn · $\ge 24$ Fail) |
| **Mean Complexity per Routine** | **2.94** | Across 396 routines (Ideal $< 4.0$ per routine) |
| **Danger Routines ($\ge 20$)** | **0** | Zero tolerance (refactor or decompose) |
| **Elevated Routines ($10–19$)** | **10** | Monitor closely; candidate for cleanup |
| **Mean Routine Length** | **15.4 code lines** | Target $\le 15$ code lines ideal |
| **Largest Routine Length** | **130 code lines** | `async_get_config_entry_diagnostics` in `diagnostics.py` (Target $\le 40$ ideal, $> 80$ warn, $> 150$ fail) |
| **Routines > 80 Code Lines** | **3** | Candidate for functional decomposition |
| **Largest Module** | **2,582 code lines** | `api.py` (Warn $> 1,500$ code lines module bloat) |
| **Modules > 1,500 Code Lines** | **2** | Candidate for module decomposition |
| **Code Suppressions (`# noqa`)** | **27** | Zero preferred; review regularly |
| **Type Suppressions (`# type: ignore`)** | **0** | Mypy strict compliance |
| **Source Python SLOC** | **10,333** | Across 21 files in custom_components/ (code statements) |
| **Docstring Volume** | **3,175 lines** | Interface and contract documentation |
| **Comment Density** | **26.8%** | 2,772 inline comment lines (Advisory: > 25% inspect for procedural narration) |
| **Platform Declarations SLOC** | **3,103 lines** | Across 6 platform files |
| **Core Engine / Driver SLOC** | **7,230 lines** | Across 15 coordinator/API/helper files |
| **Static Entities** | **123 entities** | Scale indicator (`all_sensors.md`) |
| **Platform SLOC / Entity** | **25.2 lines/entity** | Target 20 – 45 lines/entity declarative efficiency |
| **Test-to-Source Ratio** | **1.63×** | 16,810 test lines ($\ge 1.5×$ recommended) |
| **Pytest Coverage** | **100%** | 1853 tests executed |
| **Pytest Duration** | **159.65s** | Full test suite wall-clock execution time |

## 2. High Complexity Routines ($\ge 10$)

| Score | Routine Symbol | Location | Status |
| :-: | :-- | :-- | :-- |
| **16** | `crawl` | `web_sources.py:208` | `ELEVATED` |
| **14** | `_async_update_data_locked` | `coordinator.py:653` | `ELEVATED` |
| **14** | `parse_token` | `device_profile.py:190` | `ELEVATED` |
| **13** | `_resolve` | `web_sources.py:125` | `ELEVATED` |
| **12** | `login` | `api.py:2735` | `ELEVATED` |
| **11** | `probe_names` | `api.py:3363` | `ELEVATED` |
| **10** | `_literal_keys` | `device_profile.py:347` | `ELEVATED` |
| **10** | `parse_profile` | `device_profile.py:557` | `ELEVATED` |
| **10** | `_get_current_apn_profile` | `select.py:75` | `ELEVATED` |
| **10** | `extra_state_attributes` | `sensor.py:2298` | `ELEVATED` |

## 3. Active Code Suppressions (`custom_components/`)

| Line | Rule Bypassed | File |
| :-: | :-- | :-- |
| 219 | `BLE001` | `__init__.py` |
| 1367 | `BLE001` | `api.py` |
| 2039 | `BLE001` | `api.py` |
| 3299 | `BLE001` | `api.py` |
| 3336 | `BLE001` | `api.py` |
| 3359 | `BLE001` | `api.py` |
| 3593 | `BLE001` | `api.py` |
| 3804 | `BLE001` | `api.py` |
| 3846 | `BLE001` | `api.py` |
| 4064 | `BLE001` | `api.py` |
| 4527 | `BLE001` | `api.py` |
| 4901 | `S324` | `api.py` |
| 5039 | `BLE001` | `api.py` |
| 548 | `BLE001` | `coordinator.py` |
| 1020 | `BLE001` | `coordinator.py` |
| 1057 | `BLE001` | `coordinator.py` |
| 1074 | `BLE001` | `coordinator.py` |
| 1095 | `BLE001` | `coordinator.py` |
| 93 | `S324` | `device_profile.py` |
| 571 | `BLE001` | `diagnostics.py` |
| 586 | `BLE001` | `diagnostics.py` |
| 133 | `BLE001, S112` | `observations.py` |
| 180 | `BLE001` | `observations.py` |
| 388 | `BLE001` | `observations.py` |
| 393 | `BLE001` | `switch.py` |
| 461 | `BLE001` | `switch.py` |
| 121 | `BLE001` | `web_sources.py` |

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
| `api.py:2280` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:889` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:604` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:630` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:60` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:234` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:504` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2641` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:938` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:266` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:311` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:834` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:76` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:552` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:184` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3502` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:38` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:869` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:446` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4000` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:387` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:55` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2180` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1747` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3649` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3917` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4285` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4807` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:165` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1573` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2058` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:53` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1223` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2872` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3634` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:31` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:99` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `reset_entities.py:213` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:253` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2061` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3435` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:17` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:45` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:257` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:79` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1469` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:306` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:813` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3157` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:186` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:207` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:456` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:55` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:167` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:763` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `observations.py:59` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:383` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:618` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2620` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3769` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:153` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:108` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:239` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:287` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:143` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:198` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:230` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:417` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:659` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1129` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1476` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3883` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:5259` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `binary_sensor.py:155` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:223` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:272` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `device_profile.py:53` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:207` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:700` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1829` | 9 lines | Long procedural block; consider moving architecture notes to docs |

### 4.3 Routines with Comments Exceeding Code Lines

| Routine | Location | Comments / Code | Advisory |
| :-- | :-- | :-: | :-- |
| `__init__` | `api.py:1025` | 120 comm / 59 code | Comments exceed code statements; verify against procedural narration |
| `session_witnesses` | `api.py:1724` | 24 comm / 21 code | Comments exceed code statements; verify against procedural narration |
| `get_params` | `api.py:3971` | 15 comm / 13 code | Comments exceed code statements; verify against procedural narration |
