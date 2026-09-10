# Project Complexity & Health: ha-zte-router-5g-monitor

**Last Measured:** 2026-09-10T13:20:38.236021+00:00 · **Release:** `3.3.17` · **Dev Version:** `3.3.17`

## 1. Executive Summary

| Metric | Value | Verdict / Evaluation |
| :-- | :-: | :-- |
| **PlayFaster Health Index** | **`64` / 100** | `ACTION REQUIRED` ($\ge 90$ Excellent · $\ge 80$ Good · $\ge 70$ Warning) |
| **Max McCabe Complexity ($V(G)$)** | **19** | `PASS (<20)` in `_request` ($< 20$ Pass · $20–23$ Warn · $\ge 24$ Fail) |
| **Mean Complexity per Routine** | **2.93** | Across 346 routines (Ideal $< 4.0$ per routine) |
| **Danger Routines ($\ge 20$)** | **0** | Zero tolerance (refactor or decompose) |
| **Elevated Routines ($10–19$)** | **11** | Monitor closely; candidate for cleanup |
| **Mean Routine Length** | **17.2 code lines** | Target $\le 15$ code lines ideal |
| **Largest Routine Length** | **174 code lines** | `_run_rungs` in `sms_delete_probe.py` (Target $\le 40$ ideal, $> 80$ warn, $> 150$ fail) |
| **Routines > 80 Code Lines** | **9** | Candidate for functional decomposition |
| **Largest Module** | **1,931 code lines** | `sensor.py` (Warn $> 1,500$ code lines module bloat) |
| **Modules > 1,500 Code Lines** | **2** | Candidate for module decomposition |
| **Code Suppressions (`# noqa`)** | **36** | Zero preferred; review regularly |
| **Type Suppressions (`# type: ignore`)** | **0** | Mypy strict compliance |
| **Source Python SLOC** | **9,925** | Across 20 files in custom_components/ (code statements) |
| **Docstring Volume** | **2,406 lines** | Interface and contract documentation |
| **Comment Density** | **25.2%** | 2,506 inline comment lines (Advisory: > 25% inspect for procedural narration) |
| **Platform Declarations SLOC** | **3,003 lines** | Across 6 platform files |
| **Core Engine / Driver SLOC** | **6,922 lines** | Across 14 coordinator/API/helper files |
| **Static Entities** | **121 entities** | Scale indicator (`all_sensors.md`) |
| **Platform SLOC / Entity** | **24.8 lines/entity** | Target 20 – 45 lines/entity declarative efficiency |
| **Test-to-Source Ratio** | **1.42×** | 14,137 test lines ($\ge 1.5×$ recommended) |
| **Pytest Coverage** | **100%** | 1571 tests executed |
| **Pytest Duration** | **227.29s** | Full test suite wall-clock execution time |

## 2. High Complexity Routines ($\ge 10$)

| Score  | Routine Symbol              | Location                   | Status     |
| :----: | :-------------------------- | :------------------------- | :--------- |
| **19** | `_request`                  | `api.py:1342`              | `ELEVATED` |
| **19** | `_attempt`                  | `sms_delete_probe.py:771`  | `ELEVATED` |
| **17** | `_run_rungs`                | `sms_delete_probe.py:1170` | `ELEVATED` |
| **13** | `_async_update_data_locked` | `coordinator.py:569`       | `ELEVATED` |
| **12** | `_candidate_rungs`          | `sms_delete_probe.py:1581` | `ELEVATED` |
| **12** | `_transport_rungs`          | `sms_delete_probe.py:1846` | `ELEVATED` |
| **11** | `login`                     | `api.py:1552`              | `ELEVATED` |
| **11** | `probe_names`               | `api.py:2195`              | `ELEVATED` |
| **10** | `_get_current_apn_profile`  | `select.py:73`             | `ELEVATED` |
| **10** | `extra_state_attributes`    | `sensor.py:2287`           | `ELEVATED` |
| **10** | `_try_login`                | `sms_delete_probe.py:271`  | `ELEVATED` |

## 3. Active Code Suppressions (`custom_components/`)

| Line | Rule Bypassed  | File                  |
| :--: | :------------- | :-------------------- |
| 220  | `BLE001`       | `__init__.py`         |
| 2031 | `BLE001`       | `api.py`              |
| 2091 | `BLE001`       | `api.py`              |
| 2128 | `BLE001`       | `api.py`              |
| 2151 | `BLE001`       | `api.py`              |
| 2176 | `BLE001`       | `api.py`              |
| 2425 | `BLE001`       | `api.py`              |
| 2630 | `BLE001`       | `api.py`              |
| 2672 | `BLE001`       | `api.py`              |
| 2847 | `BLE001`       | `api.py`              |
| 3139 | `S324`         | `api.py`              |
| 3185 | `BLE001`       | `api.py`              |
| 461  | `BLE001`       | `coordinator.py`      |
| 900  | `BLE001`       | `coordinator.py`      |
| 513  | `BLE001`       | `diagnostics.py`      |
| 528  | `BLE001`       | `diagnostics.py`      |
| 128  | `BLE001, S112` | `observations.py`     |
| 166  | `BLE001`       | `observations.py`     |
| 312  | `BLE001`       | `observations.py`     |
| 291  | `SLF001`       | `sms_delete_probe.py` |
| 304  | `SLF001`       | `sms_delete_probe.py` |
| 323  | `SLF001`       | `sms_delete_probe.py` |
| 378  | `SLF001`       | `sms_delete_probe.py` |
| 382  | `BLE001`       | `sms_delete_probe.py` |
| 411  | `S324`         | `sms_delete_probe.py` |
| 591  | `BLE001`       | `sms_delete_probe.py` |
| 902  | `SLF001`       | `sms_delete_probe.py` |
| 1139 | `BLE001`       | `sms_delete_probe.py` |
| 1177 | `SLF001`       | `sms_delete_probe.py` |
| 1222 | `SLF001`       | `sms_delete_probe.py` |
| 1234 | `SLF001`       | `sms_delete_probe.py` |
| 1273 | `SLF001`       | `sms_delete_probe.py` |
| 1927 | `SLF001`       | `sms_delete_probe.py` |
| 2084 | `SLF001`       | `sms_delete_probe.py` |
| 2093 | `SLF001`       | `sms_delete_probe.py` |
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
| `sms_delete_probe.py:414` | 24 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1236` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:786` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:545` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:60` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:803` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:266` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:516` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:219` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:834` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:683` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:179` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2334` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:869` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:426` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:52` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2169` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2477` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2739` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:112` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1573` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2046` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:83` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1356` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:37` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1672` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2462` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:31` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:46` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:38` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `reset_entities.py:213` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1255` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:239` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2267` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:17` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:75` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1469` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:1177` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:286` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:646` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1957` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:133` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:154` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:335` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:51` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:162` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `observations.py:54` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:375` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:610` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2595` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2793` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:100` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:104` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:239` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:287` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:656` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:129` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:184` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:216` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:397` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:817` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1501` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2709` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `binary_sensor.py:155` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:207` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:700` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1817` | 9 lines | Long procedural block; consider moving architecture notes to docs |

### 4.3 Routines with Comments Exceeding Code Lines

| Routine | Location | Comments / Code | Advisory |
| :-- | :-- | :-: | :-- |
| `__init__` | `api.py:796` | 56 comm / 37 code | Comments exceed code statements; verify against procedural narration |
| `async_run_discovery` | `coordinator.py:1487` | 6 comm / 5 code | Comments exceed code statements; verify against procedural narration |
