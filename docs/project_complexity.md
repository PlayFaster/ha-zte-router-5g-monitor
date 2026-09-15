# Project Complexity & Health: ha-zte-router-5g-monitor

**Last Measured:** 2026-09-15T01:54:37.149822+00:00 · **Release:** `3.3.25` · **Dev Version:** `3.3.25-dev8`

## 1. Executive Summary

| Metric | Value | Verdict / Evaluation |
| :-- | :-: | :-- |
| **PlayFaster Health Index** | **`75` / 100** | `WARNING` ($\ge 90$ Excellent · $\ge 80$ Good · $\ge 70$ Warning) |
| **Max McCabe Complexity ($V(G)$)** | **16** | `PASS (<20)` in `crawl` ($< 20$ Pass · $20–23$ Warn · $\ge 24$ Fail) |
| **Mean Complexity per Routine** | **2.88** | Across 346 routines (Ideal $< 4.0$ per routine) |
| **Danger Routines ($\ge 20$)** | **0** | Zero tolerance (refactor or decompose) |
| **Elevated Routines ($10–19$)** | **7** | Monitor closely; candidate for cleanup |
| **Mean Routine Length** | **15.5 code lines** | Target $\le 15$ code lines ideal |
| **Largest Routine Length** | **123 code lines** | `async_get_config_entry_diagnostics` in `diagnostics.py` (Target $\le 40$ ideal, $> 80$ warn, $> 150$ fail) |
| **Routines > 80 Code Lines** | **3** | Candidate for functional decomposition |
| **Largest Module** | **2,319 code lines** | `api.py` (Warn $> 1,500$ code lines module bloat) |
| **Modules > 1,500 Code Lines** | **2** | Candidate for module decomposition |
| **Code Suppressions (`# noqa`)** | **22** | Zero preferred; review regularly |
| **Type Suppressions (`# type: ignore`)** | **0** | Mypy strict compliance |
| **Source Python SLOC** | **9,436** | Across 20 files in custom_components/ (code statements) |
| **Docstring Volume** | **2,794 lines** | Interface and contract documentation |
| **Comment Density** | **26.7%** | 2,524 inline comment lines (Advisory: > 25% inspect for procedural narration) |
| **Platform Declarations SLOC** | **3,003 lines** | Across 6 platform files |
| **Core Engine / Driver SLOC** | **6,433 lines** | Across 14 coordinator/API/helper files |
| **Static Entities** | **121 entities** | Scale indicator (`all_sensors.md`) |
| **Platform SLOC / Entity** | **24.8 lines/entity** | Target 20 – 45 lines/entity declarative efficiency |
| **Test-to-Source Ratio** | **1.61×** | 15,208 test lines ($\ge 1.5×$ recommended) |
| **Pytest Coverage** | **100%** | 1663 tests executed |
| **Pytest Duration** | **176.18s** | Full test suite wall-clock execution time |

## 2. High Complexity Routines ($\ge 10$)

| Score | Routine Symbol | Location | Status |
| :-: | :-- | :-- | :-- |
| **16** | `crawl` | `web_sources.py:205` | `ELEVATED` |
| **13** | `_async_update_data_locked` | `coordinator.py:562` | `ELEVATED` |
| **13** | `_resolve` | `web_sources.py:122` | `ELEVATED` |
| **11** | `login` | `api.py:2606` | `ELEVATED` |
| **11** | `probe_names` | `api.py:3222` | `ELEVATED` |
| **10** | `_get_current_apn_profile` | `select.py:73` | `ELEVATED` |
| **10** | `extra_state_attributes` | `sensor.py:2287` | `ELEVATED` |

## 3. Active Code Suppressions (`custom_components/`)

| Line | Rule Bypassed | File |
| :-: | :-- | :-- |
| 212 | `BLE001` | `__init__.py` |
| 1276 | `BLE001` | `api.py` |
| 1916 | `BLE001` | `api.py` |
| 3158 | `BLE001` | `api.py` |
| 3195 | `BLE001` | `api.py` |
| 3218 | `BLE001` | `api.py` |
| 3452 | `BLE001` | `api.py` |
| 3663 | `BLE001` | `api.py` |
| 3705 | `BLE001` | `api.py` |
| 3925 | `BLE001` | `api.py` |
| 4285 | `BLE001` | `api.py` |
| 4425 | `S324` | `api.py` |
| 4517 | `BLE001` | `api.py` |
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
| `const.py:224` | 30 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:598` | 22 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2153` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:60` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:779` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:572` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:256` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:71` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:495` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2513` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:911` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:266` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:543` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:311` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:834` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:179` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3361` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:869` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:437` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3861` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:52` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2169` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1658` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3508` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3776` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4058` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:166` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1573` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2046` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:48` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1132` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2728` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3493` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:31` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:100` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:38` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `reset_entities.py:213` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:250` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1048` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1933` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3294` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:17` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:45` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:279` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:75` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1469` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:297` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:734` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3013` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:187` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:208` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:439` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:51` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:162` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `observations.py:54` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:367` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:592` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2493` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3628` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:154` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:104` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:239` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:287` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:140` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:195` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:227` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:408` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:629` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:963` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1061` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1385` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3742` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4387` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `binary_sensor.py:155` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:207` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:700` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1817` | 9 lines | Long procedural block; consider moving architecture notes to docs |

### 4.3 Routines with Comments Exceeding Code Lines

| Routine | Location | Comments / Code | Advisory |
| :-- | :-- | :-: | :-- |
| `__init__` | `api.py:942` | 116 comm / 55 code | Comments exceed code statements; verify against procedural narration |
| `get_ad` | `api.py:4366` | 22 comm / 18 code | Comments exceed code statements; verify against procedural narration |
| `session_witnesses` | `api.py:1635` | 24 comm / 21 code | Comments exceed code statements; verify against procedural narration |
| `get_params` | `api.py:3832` | 15 comm / 13 code | Comments exceed code statements; verify against procedural narration |
