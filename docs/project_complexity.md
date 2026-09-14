# Project Complexity & Health: ha-zte-router-5g-monitor

**Last Measured:** 2026-09-14T22:55:28.277068+00:00 · **Release:** `3.3.25` · **Dev Version:** `3.3.25-dev7`

## 1. Executive Summary

| Metric | Value | Verdict / Evaluation |
| :-- | :-: | :-- |
| **PlayFaster Health Index** | **`75` / 100** | `WARNING` ($\ge 90$ Excellent · $\ge 80$ Good · $\ge 70$ Warning) |
| **Max McCabe Complexity ($V(G)$)** | **16** | `PASS (<20)` in `crawl` ($< 20$ Pass · $20–23$ Warn · $\ge 24$ Fail) |
| **Mean Complexity per Routine** | **2.88** | Across 346 routines (Ideal $< 4.0$ per routine) |
| **Danger Routines ($\ge 20$)** | **0** | Zero tolerance (refactor or decompose) |
| **Elevated Routines ($10–19$)** | **7** | Monitor closely; candidate for cleanup |
| **Mean Routine Length** | **15.4 code lines** | Target $\le 15$ code lines ideal |
| **Largest Routine Length** | **120 code lines** | `async_get_config_entry_diagnostics` in `diagnostics.py` (Target $\le 40$ ideal, $> 80$ warn, $> 150$ fail) |
| **Routines > 80 Code Lines** | **3** | Candidate for functional decomposition |
| **Largest Module** | **2,310 code lines** | `api.py` (Warn $> 1,500$ code lines module bloat) |
| **Modules > 1,500 Code Lines** | **2** | Candidate for module decomposition |
| **Code Suppressions (`# noqa`)** | **24** | Zero preferred; review regularly |
| **Type Suppressions (`# type: ignore`)** | **0** | Mypy strict compliance |
| **Source Python SLOC** | **9,417** | Across 20 files in custom_components/ (code statements) |
| **Docstring Volume** | **2,760 lines** | Interface and contract documentation |
| **Comment Density** | **26.5%** | 2,498 inline comment lines (Advisory: > 25% inspect for procedural narration) |
| **Platform Declarations SLOC** | **3,003 lines** | Across 6 platform files |
| **Core Engine / Driver SLOC** | **6,414 lines** | Across 14 coordinator/API/helper files |
| **Static Entities** | **121 entities** | Scale indicator (`all_sensors.md`) |
| **Platform SLOC / Entity** | **24.8 lines/entity** | Target 20 – 45 lines/entity declarative efficiency |
| **Test-to-Source Ratio** | **1.59×** | 15,003 test lines ($\ge 1.5×$ recommended) |
| **Pytest Coverage** | **100%** | 1646 tests executed |
| **Pytest Duration** | **213.02s** | Full test suite wall-clock execution time |

## 2. High Complexity Routines ($\ge 10$)

| Score | Routine Symbol | Location | Status |
| :-: | :-- | :-- | :-- |
| **16** | `crawl` | `web_sources.py:205` | `ELEVATED` |
| **13** | `_async_update_data_locked` | `coordinator.py:562` | `ELEVATED` |
| **13** | `_resolve` | `web_sources.py:122` | `ELEVATED` |
| **11** | `login` | `api.py:2570` | `ELEVATED` |
| **11** | `probe_names` | `api.py:3215` | `ELEVATED` |
| **10** | `_get_current_apn_profile` | `select.py:73` | `ELEVATED` |
| **10** | `extra_state_attributes` | `sensor.py:2287` | `ELEVATED` |

## 3. Active Code Suppressions (`custom_components/`)

| Line | Rule Bypassed | File |
| :-: | :-- | :-- |
| 212 | `BLE001` | `__init__.py` |
| 1264 | `BLE001` | `api.py` |
| 1904 | `BLE001` | `api.py` |
| 3051 | `BLE001` | `api.py` |
| 3111 | `BLE001` | `api.py` |
| 3148 | `BLE001` | `api.py` |
| 3171 | `BLE001` | `api.py` |
| 3196 | `BLE001` | `api.py` |
| 3445 | `BLE001` | `api.py` |
| 3650 | `BLE001` | `api.py` |
| 3692 | `BLE001` | `api.py` |
| 3879 | `BLE001` | `api.py` |
| 4239 | `BLE001` | `api.py` |
| 4379 | `S324` | `api.py` |
| 4471 | `BLE001` | `api.py` |
| 454 | `BLE001` | `coordinator.py` |
| 906 | `BLE001` | `coordinator.py` |
| 566 | `BLE001` | `diagnostics.py` |
| 581 | `BLE001` | `diagnostics.py` |
| 128 | `BLE001, S112` | `observations.py` |
| 166 | `BLE001` | `observations.py` |
| 337 | `BLE001` | `observations.py` |
| 345 | `BLE001` | `switch.py` |
| 118 | `BLE001` | `web_sources.py` |

## 4. Comment Quality & Density Audits

### 4.1 High Comment Density Files (> 25% comments/code)

| Module | Rationale / Advisory |
| :-- | :-- |
| `api.py` | Inspect for commented-out dead code or procedural narration |
| `const.py` | Inspect for commented-out dead code or procedural narration |
| `coordinator.py` | Inspect for commented-out dead code or procedural narration |
| `diagnostics.py` | Inspect for commented-out dead code or procedural narration |
| `entity_defaults.py` | Inspect for commented-out dead code or procedural narration |

### 4.2 Contiguous Comment Blocks (> 8 lines)

| Location | Length | Advisory |
| :-- | :-: | :-- |
| `const.py:210` | 30 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:597` | 22 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2141` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:46` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:779` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:571` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:242` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:70` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:494` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2501` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:906` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:266` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:542` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:297` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:834` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:179` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3354` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:869` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:436` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3817` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:52` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2169` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1646` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3497` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3759` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4012` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:152` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1573` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2046` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:47` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1120` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2692` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3482` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:31` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:86` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:38` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `reset_entities.py:213` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:249` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1047` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1921` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3287` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:17` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:265` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:75` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1469` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:296` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:733` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2977` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:173` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:194` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:425` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:51` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:162` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `observations.py:54` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:367` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:592` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2481` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3615` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:140` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:104` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:239` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:287` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:139` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:194` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:226` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:407` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:628` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:962` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1060` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1373` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3729` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4341` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `binary_sensor.py:155` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:207` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:700` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1817` | 9 lines | Long procedural block; consider moving architecture notes to docs |

### 4.3 Routines with Comments Exceeding Code Lines

| Routine | Location | Comments / Code | Advisory |
| :-- | :-- | :-: | :-- |
| `__init__` | `api.py:941` | 107 comm / 53 code | Comments exceed code statements; verify against procedural narration |
| `_perform` | `api.py:2495` | 19 comm / 7 code | Comments exceed code statements; verify against procedural narration |
| `get_ad` | `api.py:4320` | 22 comm / 18 code | Comments exceed code statements; verify against procedural narration |
| `session_witnesses` | `api.py:1623` | 24 comm / 21 code | Comments exceed code statements; verify against procedural narration |
| `get_params` | `api.py:3788` | 15 comm / 13 code | Comments exceed code statements; verify against procedural narration |
| `async_run_discovery` | `coordinator.py:1477` | 6 comm / 5 code | Comments exceed code statements; verify against procedural narration |
