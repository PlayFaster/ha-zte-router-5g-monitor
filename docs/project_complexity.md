# Project Complexity & Health: ha-zte-router-5g-monitor

**Last Measured:** 2026-09-17T13:02:17.836981+00:00 · **Release:** `3.4.0` · **Dev Version:** `3.4.0-dev1`

## 1. Executive Summary

| Metric | Value | Verdict / Evaluation |
| :-- | :-: | :-- |
| **PlayFaster Health Index** | **`74` / 100** | `WARNING` ($\ge 90$ Excellent · $\ge 80$ Good · $\ge 70$ Warning) |
| **Max McCabe Complexity ($V(G)$)** | **16** | `PASS (<20)` in `crawl` ($< 20$ Pass · $20–23$ Warn · $\ge 24$ Fail) |
| **Mean Complexity per Routine** | **2.98** | Across 375 routines (Ideal $< 4.0$ per routine) |
| **Danger Routines ($\ge 20$)** | **0** | Zero tolerance (refactor or decompose) |
| **Elevated Routines ($10–19$)** | **10** | Monitor closely; candidate for cleanup |
| **Mean Routine Length** | **15.7 code lines** | Target $\le 15$ code lines ideal |
| **Largest Routine Length** | **127 code lines** | `async_get_config_entry_diagnostics` in `diagnostics.py` (Target $\le 40$ ideal, $> 80$ warn, $> 150$ fail) |
| **Routines > 80 Code Lines** | **3** | Candidate for functional decomposition |
| **Largest Module** | **2,498 code lines** | `api.py` (Warn $> 1,500$ code lines module bloat) |
| **Modules > 1,500 Code Lines** | **2** | Candidate for module decomposition |
| **Code Suppressions (`# noqa`)** | **26** | Zero preferred; review regularly |
| **Type Suppressions (`# type: ignore`)** | **0** | Mypy strict compliance |
| **Source Python SLOC** | **10,041** | Across 21 files in custom_components/ (code statements) |
| **Docstring Volume** | **3,089 lines** | Interface and contract documentation |
| **Comment Density** | **26.9%** | 2,706 inline comment lines (Advisory: > 25% inspect for procedural narration) |
| **Platform Declarations SLOC** | **3,003 lines** | Across 6 platform files |
| **Core Engine / Driver SLOC** | **7,038 lines** | Across 15 coordinator/API/helper files |
| **Static Entities** | **121 entities** | Scale indicator (`all_sensors.md`) |
| **Platform SLOC / Entity** | **24.8 lines/entity** | Target 20 – 45 lines/entity declarative efficiency |
| **Test-to-Source Ratio** | **1.61×** | 16,149 test lines ($\ge 1.5×$ recommended) |
| **Pytest Coverage** | **100%** | 1776 tests executed |
| **Pytest Duration** | **154.71s** | Full test suite wall-clock execution time |

## 2. High Complexity Routines ($\ge 10$)

| Score | Routine Symbol | Location | Status |
| :-: | :-- | :-- | :-- |
| **16** | `crawl` | `web_sources.py:205` | `ELEVATED` |
| **14** | `parse_token` | `device_profile.py:190` | `ELEVATED` |
| **13** | `_async_update_data_locked` | `coordinator.py:562` | `ELEVATED` |
| **13** | `_resolve` | `web_sources.py:122` | `ELEVATED` |
| **12** | `login` | `api.py:2669` | `ELEVATED` |
| **11** | `probe_names` | `api.py:3294` | `ELEVATED` |
| **10** | `_literal_keys` | `device_profile.py:347` | `ELEVATED` |
| **10** | `parse_profile` | `device_profile.py:557` | `ELEVATED` |
| **10** | `_get_current_apn_profile` | `select.py:73` | `ELEVATED` |
| **10** | `extra_state_attributes` | `sensor.py:2287` | `ELEVATED` |

## 3. Active Code Suppressions (`custom_components/`)

| Line | Rule Bypassed | File |
| :-: | :-- | :-- |
| 213 | `BLE001` | `__init__.py` |
| 1303 | `BLE001` | `api.py` |
| 1975 | `BLE001` | `api.py` |
| 3230 | `BLE001` | `api.py` |
| 3267 | `BLE001` | `api.py` |
| 3290 | `BLE001` | `api.py` |
| 3524 | `BLE001` | `api.py` |
| 3735 | `BLE001` | `api.py` |
| 3777 | `BLE001` | `api.py` |
| 3995 | `BLE001` | `api.py` |
| 4370 | `BLE001` | `api.py` |
| 4744 | `S324` | `api.py` |
| 4882 | `BLE001` | `api.py` |
| 457 | `BLE001` | `coordinator.py` |
| 910 | `BLE001` | `coordinator.py` |
| 947 | `BLE001` | `coordinator.py` |
| 964 | `BLE001` | `coordinator.py` |
| 985 | `BLE001` | `coordinator.py` |
| 93 | `S324` | `device_profile.py` |
| 571 | `BLE001` | `diagnostics.py` |
| 586 | `BLE001` | `diagnostics.py` |
| 133 | `BLE001, S112` | `observations.py` |
| 180 | `BLE001` | `observations.py` |
| 388 | `BLE001` | `observations.py` |
| 345 | `BLE001` | `switch.py` |
| 118 | `BLE001` | `web_sources.py` |

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
| `api.py:2216` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:779` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:594` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:620` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:60` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:234` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:494` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2576` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:931` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:266` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:289` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:834` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:72` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:542` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:181` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3433` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:38` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:869` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:436` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3931` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:365` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:55` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2169` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1683` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3580` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3848` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4128` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:4650` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:165` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1573` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2046` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:49` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1159` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2803` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3565` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:31` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:99` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `reset_entities.py:213` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:249` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1997` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3366` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:17` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:45` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:257` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:76` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1469` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:296` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:756` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3088` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:186` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:207` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:435` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:52` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:164` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `observations.py:59` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:368` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:601` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2556` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3700` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:153` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:105` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:239` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:287` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:139` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:194` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:226` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:407` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:649` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1068` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1412` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3814` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:5102` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `binary_sensor.py:155` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:223` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `device_profile.py:53` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:207` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:700` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1817` | 9 lines | Long procedural block; consider moving architecture notes to docs |

### 4.3 Routines with Comments Exceeding Code Lines

| Routine | Location | Comments / Code | Advisory |
| :-- | :-- | :-: | :-- |
| `__init__` | `api.py:964` | 118 comm / 58 code | Comments exceed code statements; verify against procedural narration |
| `session_witnesses` | `api.py:1660` | 24 comm / 21 code | Comments exceed code statements; verify against procedural narration |
| `get_params` | `api.py:3902` | 15 comm / 13 code | Comments exceed code statements; verify against procedural narration |
