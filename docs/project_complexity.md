# Project Complexity & Health: ha-zte-router-5g-monitor

**Last Measured:** 2026-09-09T01:42:59.743454+00:00 · **Release:** `3.3.16` · **Dev Version:** `3.3.16`

## 1. Executive Summary

| Metric | Value | Verdict / Evaluation |
| :-- | :-: | :-- |
| **PlayFaster Health Index** | **`71` / 100** | `WARNING` ($\ge 90$ Excellent · $\ge 80$ Good · $\ge 70$ Warning) |
| **Max McCabe Complexity ($V(G)$)** | **19** | `PASS (<20)` in `_request` ($< 20$ Pass · $20–23$ Warn · $\ge 24$ Fail) |
| **Mean Complexity per Routine** | **2.80** | Across 323 routines (Ideal $< 4.0$ per routine) |
| **Danger Routines ($\ge 20$)** | **0** | Zero tolerance (refactor or decompose) |
| **Elevated Routines ($10–19$)** | **8** | Monitor closely; candidate for cleanup |
| **Mean Routine Length** | **15.9 code lines** | Target $\le 15$ code lines ideal |
| **Largest Routine Length** | **169 code lines** | `_run_rungs` in `sms_delete_probe.py` (Target $\le 40$ ideal, $> 80$ warn, $> 150$ fail) |
| **Routines > 80 Code Lines** | **5** | Candidate for functional decomposition |
| **Largest Module** | **1,931 code lines** | `sensor.py` (Warn $> 1,500$ code lines module bloat) |
| **Modules > 1,500 Code Lines** | **2** | Candidate for module decomposition |
| **Code Suppressions (`# noqa`)** | **32** | Zero preferred; review regularly |
| **Type Suppressions (`# type: ignore`)** | **0** | Mypy strict compliance |
| **Source Python SLOC** | **9,125** | Across 20 files in custom_components/ (code statements) |
| **Docstring Volume** | **2,266 lines** | Interface and contract documentation |
| **Comment Density** | **24.5%** | 2,235 inline comment lines (Healthy implementation rationale) |
| **Platform Declarations SLOC** | **3,003 lines** | Across 6 platform files |
| **Core Engine / Driver SLOC** | **6,122 lines** | Across 14 coordinator/API/helper files |
| **Static Entities** | **121 entities** | Scale indicator (`all_sensors.md`) |
| **Platform SLOC / Entity** | **24.8 lines/entity** | Target 20 – 45 lines/entity declarative efficiency |
| **Test-to-Source Ratio** | **1.51×** | 13,780 test lines ($\ge 1.5×$ recommended) |
| **Pytest Coverage** | **100%** | 1528 tests executed |
| **Pytest Duration** | **140.83s** | Full test suite wall-clock execution time |

## 2. High Complexity Routines ($\ge 10$)

| Score  | Routine Symbol              | Location                  | Status     |
| :----: | :-------------------------- | :------------------------ | :--------- |
| **19** | `_request`                  | `api.py:1335`             | `ELEVATED` |
| **17** | `_run_rungs`                | `sms_delete_probe.py:454` | `ELEVATED` |
| **13** | `_async_update_data_locked` | `coordinator.py:569`      | `ELEVATED` |
| **12** | `_candidate_rungs`          | `sms_delete_probe.py:726` | `ELEVATED` |
| **11** | `login`                     | `api.py:1544`             | `ELEVATED` |
| **11** | `probe_names`               | `api.py:2187`             | `ELEVATED` |
| **10** | `_get_current_apn_profile`  | `select.py:73`            | `ELEVATED` |
| **10** | `extra_state_attributes`    | `sensor.py:2287`          | `ELEVATED` |

## 3. Active Code Suppressions (`custom_components/`)

| Line | Rule Bypassed  | File                  |
| :--: | :------------- | :-------------------- |
| 220  | `BLE001`       | `__init__.py`         |
| 2023 | `BLE001`       | `api.py`              |
| 2083 | `BLE001`       | `api.py`              |
| 2120 | `BLE001`       | `api.py`              |
| 2143 | `BLE001`       | `api.py`              |
| 2168 | `BLE001`       | `api.py`              |
| 2417 | `BLE001`       | `api.py`              |
| 2622 | `BLE001`       | `api.py`              |
| 2664 | `BLE001`       | `api.py`              |
| 2839 | `BLE001`       | `api.py`              |
| 3131 | `S324`         | `api.py`              |
| 3177 | `BLE001`       | `api.py`              |
| 461  | `BLE001`       | `coordinator.py`      |
| 900  | `BLE001`       | `coordinator.py`      |
| 513  | `BLE001`       | `diagnostics.py`      |
| 528  | `BLE001`       | `diagnostics.py`      |
| 128  | `BLE001, S112` | `observations.py`     |
| 166  | `BLE001`       | `observations.py`     |
| 312  | `BLE001`       | `observations.py`     |
| 118  | `SLF001`       | `sms_delete_probe.py` |
| 122  | `BLE001`       | `sms_delete_probe.py` |
| 145  | `S324`         | `sms_delete_probe.py` |
| 208  | `SLF001`       | `sms_delete_probe.py` |
| 230  | `BLE001`       | `sms_delete_probe.py` |
| 293  | `SLF001`       | `sms_delete_probe.py` |
| 375  | `SLF001`       | `sms_delete_probe.py` |
| 444  | `BLE001`       | `sms_delete_probe.py` |
| 461  | `SLF001`       | `sms_delete_probe.py` |
| 493  | `SLF001`       | `sms_delete_probe.py` |
| 505  | `SLF001`       | `sms_delete_probe.py` |
| 544  | `SLF001`       | `sms_delete_probe.py` |
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
| `api.py:1229` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:786` | 21 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:545` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:148` | 20 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:60` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `diagnostics.py:803` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:266` | 19 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:516` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:219` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:834` | 18 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:179` | 17 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2326` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `known_names.py:869` | 16 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:426` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:52` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2169` | 15 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2469` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2731` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:112` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1573` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:2046` | 14 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:37` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1664` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2454` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:31` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:46` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `entity_defaults.py:38` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `reset_entities.py:213` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `sms_delete_probe.py:526` | 13 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:239` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2259` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:17` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:75` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1469` | 12 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:286` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:646` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1949` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:133` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:154` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:335` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:51` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:162` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `observations.py:54` | 11 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:375` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `__init__.py:610` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2587` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2785` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `const.py:100` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `coordinator.py:104` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:239` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:287` | 10 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:129` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:184` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:216` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:397` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:817` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:1493` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `api.py:2701` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `binary_sensor.py:155` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:207` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:700` | 9 lines | Long procedural block; consider moving architecture notes to docs |
| `sensor.py:1817` | 9 lines | Long procedural block; consider moving architecture notes to docs |

### 4.3 Routines with Comments Exceeding Code Lines

| Routine | Location | Comments / Code | Advisory |
| :-- | :-- | :-: | :-- |
| `__init__` | `api.py:796` | 50 comm / 36 code | Comments exceed code statements; verify against procedural narration |
| `async_run_discovery` | `coordinator.py:1487` | 6 comm / 5 code | Comments exceed code statements; verify against procedural narration |
