# Project Complexity & Health: ha-zte-router-5g-monitor

**Last Measured:** 2026-09-29T21:21:23.830238+00:00 · **Release:** `3.4.5` · **Dev Version:** `3.4.5-dev2`

## 1. Executive Summary

| Metric | Value | Verdict / Evaluation |
| :-- | :-: | :-- |
| **PlayFaster Health Index** | **`70` / 100** | `WARNING` ($\ge 90$ Excellent · $\ge 80$ Good · $\ge 70$ Warning) |
| **Max McCabe Complexity ($V(G)$)** | **17** | `PASS (<20)` in `crawl` ($< 20$ Pass · $20–23$ Warn · $\ge 24$ Fail) |
| **Mean Complexity per Routine** | **2.90** | Across 475 routines (Ideal $< 4.0$ per routine) |
| **Danger Routines ($\ge 20$)** | **0** | Zero tolerance (refactor or decompose) |
| **Elevated Routines ($10–19$)** | **11** | Monitor closely; candidate for cleanup |
| **Mean Routine Length** | **14.9 code lines** | Target $\le 15$ code lines ideal |
| **Largest Routine Length** | **139 code lines** | `async_get_config_entry_diagnostics` in `diagnostics.py` (Target $\le 40$ ideal, $> 80$ warn, $> 150$ fail) |
| **Routines > 80 Code Lines** | **4** | Candidate for functional decomposition |
| **Largest Module** | **2,721 code lines** | `api.py` (Warn $> 1,500$ code lines module bloat) |
| **Modules > 1,500 Code Lines** | **3** | Candidate for module decomposition |
| **Code Suppressions (`# noqa`)** | **32** | Zero preferred; review regularly |
| **Type Suppressions (`# type: ignore`)** | **0** | Mypy strict compliance |
| **Source Python SLOC** | **11,723** | Across 22 files in custom_components/ (code statements) |
| **Docstring Volume** | **3,574 lines** | Interface and contract documentation |
| **Comment Density** | **26.2%** | 3,071 inline comment lines (Advisory: > 25% inspect for procedural narration) |
| **Platform Declarations SLOC** | **3,346 lines** | Across 6 platform files |
| **Core Engine / Driver SLOC** | **8,377 lines** | Across 16 coordinator/API/helper files |
| **Static Entities** | **132 entities** | Scale indicator (`all_sensors.md`) |
| **Platform SLOC / Entity** | **25.3 lines/entity** | Target 20 – 45 lines/entity declarative efficiency |
| **Test-to-Source Ratio** | **1.64×** | 19,169 test lines ($\ge 1.5×$ recommended) |
| **Pytest Coverage** | **100%** | 2125 tests executed |
| **Pytest Duration** | **823.76s** | Full test suite wall-clock execution time |

## 2. High Complexity Routines ($\ge 10$)

| Score | Routine Symbol | Location | Status |
| :-: | :-- | :-- | :-- |
| **17** | `crawl` | `web_sources.py:221` | `ELEVATED` |
| **15** | `_async_update_data_locked` | `coordinator.py:945` | `ELEVATED` |
| **14** | `parse_token` | `device_profile.py:194` | `ELEVATED` |
| **13** | `_resolve` | `web_sources.py:138` | `ELEVATED` |
| **12** | `_login_unlocked` | `api.py:2957` | `ELEVATED` |
| **12** | `_async_outage_check` | `coordinator.py:674` | `ELEVATED` |
| **12** | `extra_state_attributes` | `sensor.py:2537` | `ELEVATED` |
| **11** | `probe_names` | `api.py:3587` | `ELEVATED` |
| **11** | `parse_profile` | `device_profile.py:641` | `ELEVATED` |
| **10** | `_literal_keys` | `device_profile.py:351` | `ELEVATED` |
| **10** | `_get_current_apn_profile` | `select.py:76` | `ELEVATED` |

## 3. Active Code Suppressions (`custom_components/`)

| Line | Rule Bypassed | File |
| :-: | :-- | :-- |
| 219 | `BLE001` | `__init__.py` |
| 1551 | `BLE001` | `api.py` |
| 2225 | `BLE001` | `api.py` |
| 3523 | `BLE001` | `api.py` |
| 3560 | `BLE001` | `api.py` |
| 3583 | `BLE001` | `api.py` |
| 3817 | `BLE001` | `api.py` |
| 4044 | `BLE001` | `api.py` |
| 4086 | `BLE001` | `api.py` |
| 4317 | `BLE001` | `api.py` |
| 4789 | `BLE001` | `api.py` |
| 5191 | `S324` | `api.py` |
| 5329 | `BLE001` | `api.py` |
| 826 | `BLE001` | `coordinator.py` |
| 1011 | `BLE001` | `coordinator.py` |
| 1842 | `BLE001` | `coordinator.py` |
| 2080 | `BLE001` | `coordinator.py` |
| 2147 | `BLE001` | `coordinator.py` |
| 2164 | `BLE001` | `coordinator.py` |
| 2201 | `BLE001` | `coordinator.py` |
| 2223 | `BLE001` | `coordinator.py` |
| 97 | `S324` | `device_profile.py` |
| 593 | `BLE001` | `diagnostics.py` |
| 608 | `BLE001` | `diagnostics.py` |
| 633 | `BLE001` | `diagnostics.py` |
| 177 | `BLE001, S112` | `observations.py` |
| 228 | `BLE001` | `observations.py` |
| 490 | `BLE001` | `observations.py` |
| 196 | `BLE001` | `poll_plan.py` |
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
| `coordinator.py:1218` | 22 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2472` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:683` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:709` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:60` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:234` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:888` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:583` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2833` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:995` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:336` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:365` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:853` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:77` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:631` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:207` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3726` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:38` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:525` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4240` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:441` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:55` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2416` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1933` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3873` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4157` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4547` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:5097` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:165` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1754` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2294` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:54` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1407` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3096` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3858` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:31` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:99` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:798` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `reset_entities.py:213` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:256` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2247` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3659` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:17` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:45` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:257` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:94` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1650` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:316` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:980` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3381` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:186` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:207` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:509` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:70` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:190` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `observations.py:59` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:383` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:618` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2812` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4009` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:153` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:123` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:305` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:357` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:145` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:200` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:233` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:496` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:738` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1296` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1660` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4123` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:5553` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `binary_sensor.py:155` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:223` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:272` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:322` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `device_profile.py:57` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:259` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:864` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2010` | 9 lines | Long procedural block; consider moving architecture notes to docs |

### 4.3 Routines with Comments Exceeding Code Lines

| Routine | Location | Comments / Code | Advisory |
| :-- | :-- | :-: | :-- |
| `__init__` | `api.py:1192` | 130 comm / 66 code | Comments exceed code statements; verify against procedural narration |
| `session_witnesses` | `api.py:1910` | 24 comm / 21 code | Comments exceed code statements; verify against procedural narration |
| `get_params` | `api.py:4211` | 15 comm / 13 code | Comments exceed code statements; verify against procedural narration |
