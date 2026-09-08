# Project Complexity & Health: ha-zte-router-5g-monitor

**Last Measured:** 2026-09-08T17:27:47.844682+00:00 · **Release:** `3.3.16` · **Dev Version:** `3.3.16-dev1`

## 1. Executive Summary

| Metric | Value | Verdict / Evaluation |
| :--- | :---: | :--- |
| **PlayFaster Health Index** | **`63` / 100** | `ACTION REQUIRED` ($\ge 90$ Excellent · $\ge 80$ Good · $\ge 70$ Warning) |
| **Max McCabe Complexity ($V(G)$)** | **19** | `PASS (<20)` in `_request` ($< 20$ Pass · $20–23$ Warn · $\ge 24$ Fail) |
| **Mean Complexity per Routine** | **3.93** | Across 198 routines (Ideal $< 4.0$ per routine) |
| **Danger Routines ($\ge 20$)** | **0** | Zero tolerance (refactor or decompose) |
| **Elevated Routines ($10–19$)** | **8** | Monitor closely; candidate for cleanup |
| **Mean Routine Length** | **26.4 lines** | Target $\le 20$ lines ideal, $> 30$ warning |
| **Largest Routine Length** | **254 lines** | `_run_rungs` in `sms_delete_probe.py` (Target $\le 60$ ideal, $> 100$ warn, $> 200$ fail) |
| **Routines > 100 Lines** | **9** | Candidate for functional decomposition |
| **Largest Module** | **3,453 lines** | `api.py` (Warn $> 2,000$ lines module bloat) |
| **Modules > 2,000 Lines** | **2** | Candidate for module decomposition |
| **Code Suppressions (`# noqa`)** | **31** | Zero preferred; review regularly |
| **Type Suppressions (`# type: ignore`)** | **0** | Mypy strict compliance |
| **Source Python SLOC** | **14,756** | Across 20 files in custom_components/ |
| **Platform Declarations SLOC** | **3,976 lines** | Across 6 platform files |
| **Core Engine / Driver SLOC** | **10,780 lines** | Across 14 coordinator/API/helper files |
| **Static Entities** | **121 entities** | Scale indicator (`all_sensors.md`) |
| **Platform SLOC / Entity** | **32.9 lines/entity** | Target 20 – 45 lines/entity declarative efficiency |
| **Test-to-Source Ratio** | **1.56×** | 23,029 test lines ($\ge 1.5×$ recommended) |
| **Pytest Coverage** | **100%** | 1524 tests executed |
| **Pytest Duration** | **195.22s** | Full test suite wall-clock execution time |

## 2. High Complexity Routines ($\ge 10$)

| Score | Routine Symbol | Location | Status |
| :---: | :--- | :--- | :--- |
| **19** | `_request` | `api.py:1335` | `ELEVATED` |
| **17** | `_run_rungs` | `sms_delete_probe.py:430` | `ELEVATED` |
| **13** | `_async_update_data_locked` | `coordinator.py:569` | `ELEVATED` |
| **12** | `_candidate_rungs` | `sms_delete_probe.py:686` | `ELEVATED` |
| **11** | `login` | `api.py:1544` | `ELEVATED` |
| **11** | `probe_names` | `api.py:2187` | `ELEVATED` |
| **10** | `_get_current_apn_profile` | `select.py:73` | `ELEVATED` |
| **10** | `extra_state_attributes` | `sensor.py:2287` | `ELEVATED` |

## 3. Active Code Suppressions (`custom_components/`)

| Line | Rule Bypassed | File |
| :---: | :--- | :--- |
| 220 | `BLE001` | `__init__.py` |
| 2023 | `BLE001` | `api.py` |
| 2083 | `BLE001` | `api.py` |
| 2120 | `BLE001` | `api.py` |
| 2143 | `BLE001` | `api.py` |
| 2168 | `BLE001` | `api.py` |
| 2417 | `BLE001` | `api.py` |
| 2622 | `BLE001` | `api.py` |
| 2664 | `BLE001` | `api.py` |
| 2839 | `BLE001` | `api.py` |
| 3131 | `S324` | `api.py` |
| 3177 | `BLE001` | `api.py` |
| 461 | `BLE001` | `coordinator.py` |
| 900 | `BLE001` | `coordinator.py` |
| 513 | `BLE001` | `diagnostics.py` |
| 528 | `BLE001` | `diagnostics.py` |
| 128 | `BLE001, S112` | `observations.py` |
| 166 | `BLE001` | `observations.py` |
| 312 | `BLE001` | `observations.py` |
| 118 | `SLF001` | `sms_delete_probe.py` |
| 122 | `BLE001` | `sms_delete_probe.py` |
| 145 | `S324` | `sms_delete_probe.py` |
| 206 | `BLE001` | `sms_delete_probe.py` |
| 269 | `SLF001` | `sms_delete_probe.py` |
| 351 | `SLF001` | `sms_delete_probe.py` |
| 420 | `BLE001` | `sms_delete_probe.py` |
| 437 | `SLF001` | `sms_delete_probe.py` |
| 469 | `SLF001` | `sms_delete_probe.py` |
| 481 | `SLF001` | `sms_delete_probe.py` |
| 520 | `SLF001` | `sms_delete_probe.py` |
| 345 | `BLE001` | `switch.py` |
