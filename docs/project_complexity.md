# Project Complexity & Health: ha-zte-router-5g-monitor

**Last Measured:** 2026-09-12T14:24:23.087672+00:00 · **Release:** `3.3.22` · **Dev Version:** `3.3.22-dev4`

## 1. Executive Summary

| Metric | Value | Verdict / Evaluation |
| :-- | :-: | :-- |
| **PlayFaster Health Index** | **`59` / 100** | `ACTION REQUIRED` ($\ge 90$ Excellent · $\ge 80$ Good · $\ge 70$ Warning) |
| **Max McCabe Complexity ($V(G)$)** | **19** | `PASS (<20)` in `_request` ($< 20$ Pass · $20–23$ Warn · $\ge 24$ Fail) |
| **Mean Complexity per Routine** | **3.02** | Across 386 routines (Ideal $< 4.0$ per routine) |
| **Danger Routines ($\ge 20$)** | **0** | Zero tolerance (refactor or decompose) |
| **Elevated Routines ($10–19$)** | **16** | Monitor closely; candidate for cleanup |
| **Mean Routine Length** | **17.7 code lines** | Target $\le 15$ code lines ideal |
| **Largest Routine Length** | **145 code lines** | `_run_rungs` in `sms_delete_probe.py` (Target $\le 40$ ideal, $> 80$ warn, $> 150$ fail) |
| **Routines > 80 Code Lines** | **11** | Candidate for functional decomposition |
| **Largest Module** | **1,931 code lines** | `sensor.py` (Warn $> 1,500$ code lines module bloat) |
| **Modules > 1,500 Code Lines** | **3** | Candidate for module decomposition |
| **Code Suppressions (`# noqa`)** | **38** | Zero preferred; review regularly |
| **Type Suppressions (`# type: ignore`)** | **0** | Mypy strict compliance |
| **Source Python SLOC** | **10,708** | Across 20 files in custom_components/ (code statements) |
| **Docstring Volume** | **2,692 lines** | Interface and contract documentation |
| **Comment Density** | **25.7%** | 2,752 inline comment lines (Advisory: > 25% inspect for procedural narration) |
| **Platform Declarations SLOC** | **3,003 lines** | Across 6 platform files |
| **Core Engine / Driver SLOC** | **7,705 lines** | Across 14 coordinator/API/helper files |
| **Static Entities** | **121 entities** | Scale indicator (`all_sensors.md`) |
| **Platform SLOC / Entity** | **24.8 lines/entity** | Target 20 – 45 lines/entity declarative efficiency |
| **Test-to-Source Ratio** | **1.39×** | 14,865 test lines ($\ge 1.5×$ recommended) |
| **Pytest Coverage** | **100%** | 1656 tests executed |
| **Pytest Duration** | **253.84s** | Full test suite wall-clock execution time |

## 2. High Complexity Routines ($\ge 10$)

| Score  | Routine Symbol              | Location                   | Status     |
| :----: | :-------------------------- | :------------------------- | :--------- |
| **19** | `_request`                  | `api.py:1600`              | `ELEVATED` |
| **19** | `_attempt`                  | `sms_delete_probe.py:1213` | `ELEVATED` |
| **17** | `_run_rungs`                | `sms_delete_probe.py:1729` | `ELEVATED` |
| **16** | `_crawl`                    | `sms_delete_probe.py:605`  | `ELEVATED` |
| **15** | `_fields_for`               | `sms_delete_probe.py:721`  | `ELEVATED` |
| **15** | `_web_ui_rungs`             | `sms_delete_probe.py:2682` | `ELEVATED` |
| **13** | `_async_update_data_locked` | `coordinator.py:569`       | `ELEVATED` |
| **13** | `_resolve`                  | `sms_delete_probe.py:522`  | `ELEVATED` |
| **12** | `_candidate_rungs`          | `sms_delete_probe.py:2196` | `ELEVATED` |
| **12** | `_transport_rungs`          | `sms_delete_probe.py:2461` | `ELEVATED` |
| **11** | `login`                     | `api.py:1831`              | `ELEVATED` |
| **11** | `probe_names`               | `api.py:2474`              | `ELEVATED` |
| **10** | `_get_current_apn_profile`  | `select.py:73`             | `ELEVATED` |
| **10** | `extra_state_attributes`    | `sensor.py:2287`           | `ELEVATED` |
| **10** | `_try_login`                | `sms_delete_probe.py:286`  | `ELEVATED` |
| **10** | `_web_ui_write_rungs`       | `sms_delete_probe.py:2840` | `ELEVATED` |

## 3. Active Code Suppressions (`custom_components/`)

| Line | Rule Bypassed  | File                  |
| :--: | :------------- | :-------------------- |
| 223  | `BLE001`       | `__init__.py`         |
| 2310 | `BLE001`       | `api.py`              |
| 2370 | `BLE001`       | `api.py`              |
| 2407 | `BLE001`       | `api.py`              |
| 2430 | `BLE001`       | `api.py`              |
| 2455 | `BLE001`       | `api.py`              |
| 2704 | `BLE001`       | `api.py`              |
| 2909 | `BLE001`       | `api.py`              |
| 2951 | `BLE001`       | `api.py`              |
| 3138 | `BLE001`       | `api.py`              |
| 3453 | `S324`         | `api.py`              |
| 3541 | `BLE001`       | `api.py`              |
| 461  | `BLE001`       | `coordinator.py`      |
| 900  | `BLE001`       | `coordinator.py`      |
| 558  | `BLE001`       | `diagnostics.py`      |
| 573  | `BLE001`       | `diagnostics.py`      |
| 128  | `BLE001, S112` | `observations.py`     |
| 166  | `BLE001`       | `observations.py`     |
| 312  | `BLE001`       | `observations.py`     |
| 306  | `SLF001`       | `sms_delete_probe.py` |
| 319  | `SLF001`       | `sms_delete_probe.py` |
| 338  | `SLF001`       | `sms_delete_probe.py` |
| 437  | `BLE001`       | `sms_delete_probe.py` |
| 815  | `SLF001`       | `sms_delete_probe.py` |
| 819  | `BLE001`       | `sms_delete_probe.py` |
| 848  | `S324`         | `sms_delete_probe.py` |
| 1028 | `BLE001`       | `sms_delete_probe.py` |
| 1360 | `SLF001`       | `sms_delete_probe.py` |
| 1606 | `BLE001`       | `sms_delete_probe.py` |
| 1710 | `SLF001`       | `sms_delete_probe.py` |
| 1752 | `SLF001`       | `sms_delete_probe.py` |
| 1811 | `SLF001`       | `sms_delete_probe.py` |
| 1823 | `SLF001`       | `sms_delete_probe.py` |
| 1862 | `SLF001`       | `sms_delete_probe.py` |
| 2542 | `SLF001`       | `sms_delete_probe.py` |
| 3029 | `SLF001`       | `sms_delete_probe.py` |
| 3038 | `SLF001`       | `sms_delete_probe.py` |
| 345  | `BLE001`       | `switch.py`           |

## 4. Comment Quality & Density Audits

### 4.1 High Comment Density Files (> 25% comments/code)

| Module                | Rationale / Advisory                                        |
| :-------------------- | :---------------------------------------------------------- |
| `api.py`              | Inspect for commented-out dead code or procedural narration |
| `const.py`            | Inspect for commented-out dead code or procedural narration |
| `coordinator.py`      | Inspect for commented-out dead code or procedural narration |
| `diagnostics.py`      | Inspect for commented-out dead code or procedural narration |
| `entity_defaults.py`  | Inspect for commented-out dead code or procedural narration |
| `sms_delete_probe.py` | Inspect for commented-out dead code or procedural narration |

### 4.2 Contiguous Comment Blocks (> 8 lines)

| Location | Length | Advisory |
| :-- | :-: | :-- |
| `const.py:170` | 30 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:851` | 24 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1494` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:786` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:545` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:60` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1631` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:859` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:266` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:516` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:219` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:834` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1120` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:179` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2613` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:869` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:426` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3076` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:52` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2169` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1286` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2756` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3018` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3202` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:112` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1573` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2046` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:98` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1949` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:37` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1951` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2741` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:31` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:46` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:38` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `reset_entities.py:213` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1844` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:239` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2546` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:17` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:75` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1469` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:286` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:646` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2236` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:133` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:154` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:347` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:51` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:162` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `observations.py:54` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1767` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:378` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:616` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2874` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:100` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:104` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:239` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:287` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:373` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1093` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:129` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:184` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:216` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:397` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:817` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1780` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2988` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:3415` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `binary_sensor.py:155` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:207` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:700` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1817` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:457` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:2967` | 9 lines | Long procedural block; consider moving architecture notes to docs |

### 4.3 Routines with Comments Exceeding Code Lines

| Routine | Location | Comments / Code | Advisory |
| :-- | :-- | :-: | :-- |
| `__init__` | `api.py:796` | 64 comm / 40 code | Comments exceed code statements; verify against procedural narration |
| `get_ad` | `api.py:3394` | 22 comm / 18 code | Comments exceed code statements; verify against procedural narration |
| `session_witnesses` | `api.py:1263` | 24 comm / 21 code | Comments exceed code statements; verify against procedural narration |
| `get_params` | `api.py:3047` | 15 comm / 13 code | Comments exceed code statements; verify against procedural narration |
| `async_run_discovery` | `coordinator.py:1487` | 6 comm / 5 code | Comments exceed code statements; verify against procedural narration |
