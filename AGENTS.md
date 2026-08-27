# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

> **Read the shared conventions first:** [`.shared/dev_std/agent_conventions.md`](.shared/dev_std/agent_conventions.md) — commands (tests, lint, mypy, validation), the Windows-host `docker exec` workflow, devcontainer access, HAB/MCP for interrogating the running HA instance, the post-modification SCOPE table, code conventions, and the markdown/Python rules. That file is the single source of truth for everything shared across the integration projects; this file covers only what is specific to **ha-zte-router-5g-monitor**.
>
> **[!] Note:** If you edit files inside directory junctions (`.notes/` or `.shared/`), do not run container validation on them. Validate them on the Windows host from the `shared/` folder.

---

> [!CAUTION] **Never run `git checkout`, `git restore`, `git reset`, `git stash` or `git clean`. Ask first, every time — no exceptions, whoever's changes you think they are.** Reading git (`status`, `diff`, `log`, `show`) is always fine. Full rule and the incident behind it: [`agent_conventions.md`](.shared/dev_std/agent_conventions.md).

## What This Integration Does

A Home Assistant custom integration (`zte_router_5g`) for ZTE 5G CPE routers (primarily the MC7010). It is a `local_polling` `hub` integration distributed via HACS. It talks to the router's undocumented `goform` HTTP API, exposing signal diagnostics, data usage, SMS, and reboot/polling controls. There are no external `requirements` — it relies only on `aiohttp` and Home Assistant core.

> **Entity `about` notes are listed in [`docs/about_attribute_list.md`](docs/about_attribute_list.md), which is derived from source, not authored** — the note in the entity description or `_attr_about` is the original; that file records it. Synchronize documentation automatically from code using `python .workbench/check_sensor_manifest.py --sync-docs`.
>
> **Entity and service inventory lives in [`docs/all_sensors.md`](docs/all_sensors.md)** — it is authoritative and synchronized from code descriptions via `python .workbench/check_sensor_manifest.py --sync-docs` (and validated against live HA via `--verify-ha`). This file deliberately carries no entity counts or service descriptions.

## Commands

Standard for all integration projects — see [shared conventions §2](.shared/dev_std/agent_conventions.md). Nothing about this project's commands differs.

## Architecture

Data flows in one direction: **`api.py` → `coordinator.py` → platform entities**. Entities never call the API directly for reads; they read `coordinator.data`.

- **`api.py` (`ZTERouterAPI`)** — stateless-ish async client for the `goform` API. Key behaviors that are easy to break:
  - Auth uses a chained SHA-256 hash of password + a per-session `LD` token; commands need an `AD` token derived from firmware version + `RD` (MD5 vs SHA-256 depending on model — see `get_ad`).
  - `_request` is the single choke point: it auto-detects expired sessions and transparently re-logs-in **once** (`_retry` guard prevents loops). Three signatures — an HTML redirect, unparsable JSON, or **a JSON dict in which every value is an empty string**.
  - **That last rule is "every value is empty", not "these named keys are empty" — do not narrow it.** A dead session answers `200 OK` with the requested keys echoed back blank: `{"sms_data_total":""}` for SMS, `{"network_type":"","signalbar":"",…}` for the batch poll. The rule previously named the batch-poll keys, so it could never fire on an SMS response (`.get("network_type")` is `None` there, and `None == ""` is `False`) — SMS actions silently returned an empty list on an expired session while Refresh Now recovered it. Signature table in [`docs/zte_how_to_access.md`](docs/zte_how_to_access.md).
  - `_require_contract()` is the second, independent defense: each SMS call asserts the key it must receive (`messages`, `sms_nv_total`) and raises rather than falling back to an empty default. An empty inbox returns `{"messages":[]}` — the key is present — which is what keeps "no messages" distinguishable from "no session". Never reintroduce a `.get(key, [])` fallback on these paths.
  - An inactivity check in `_request` proactively clears `stok` if the gap since the last request exceeds 150 seconds, forcing a new login.
  - **Only an authenticated call updates `last_activity`.** `LD` and `wa_inner_version` are served without a session, so letting them stamp the clock told the idle check a long-dead session was fresh. Every write calls `get_ad()` → `get_version()` first, so an action taken after a pause hit exactly that: the unauthenticated fetch reset the clock immediately before the authenticated call that needed it, the stale `stok` survived, and the write went out on a dead session reporting success. Do not move that update back outside the `if authenticated:` guard.
  - **`DATA_LIMIT_SETTING` is an all-or-nothing form.** It carries the limit switch, the cap and its unit, the alert percentage, the monthly auto-reset switch and the billing reset day, and the router answers `{"result":"failure"}` for a payload missing any of them — which is why the old single-field `set_data_limit_switch()` had never worked. Every write goes through `set_data_volume_settings()`, a read-modify-write sourcing untouched fields from the last poll and raising rather than guessing when one is absent. `traffic_clear_date` has no separate `goformId`; it is written through this form or not at all.
  - **`_require_success()` is checked on every write.** This API answers `200 OK` with `{"result":"failure"}` for a refused command, so an unchecked write reports success having done nothing — a user watched an SMS action go green with no message sent. Applied to all eight `goformId` writes. It raises only on an explicit non-success `result`; a response with no `result` key is left alone, because not every command returns one. **Reboot is not special-cased**: a connection error still propagates, since a dropped link cannot be told from a router that never received the command.
  - A GET request to `wa_inner_version` is executed inside `login()` immediately after obtaining a new `stok` to fully initialize/activate the session on the router, enabling subsequent POST commands.
  - Two exception types drive everything downstream: `ZTEAuthError` (bad credentials → reauth) vs `ZTEConnectionError` (network/transient). Raise the right one.
  - SMS content/numbers are hex-encoded on the wire; `_hex_decode` / `_parse_date` produce the `*_decoded` fields entities and services consume.
  - **`_hex_decode` decodes the whole string at once — never code unit by code unit.** `bytes.fromhex(s).decode("utf-16-be")`, not a loop of `chr(int(s[i:i+4], 16))`. The loop form is correct only inside the Basic Multilingual Plane: every emoji arrives as a UTF-16 **surrogate pair**, and taking each half separately yields two lone surrogates. The result is not merely wrong text — **it cannot be encoded to UTF-8 at all**, so the recorder, a webhook or a log handler raises `UnicodeEncodeError` on a message the user cannot identify. `get_sms_list` is a **response service**, which is the sharpest way this presents: HA fails to serialize the payload and the whole action dies rather than showing mangled text. Verified on hardware 2026-08-07 — before the fix, two emoji messages made the action fail outright. An odd-length payload is a decode failure, not a partial message.
  - **`send_sms` picks `encode_type` per message** — `GSM7_default` when `helpers.is_gsm7()` says the text is entirely within the GSM 03.38 alphabet, `UNICODE` otherwise. **`MessageBody` stays UTF-16BE hex for both.** `encode_type` selects the router's DCS and segment accounting; it is not an instruction to change the client-side encoding. Verified against two independent implementations (`Kajkac/pygsm7.py::encodeMessage()`, `rosenrot00/zte_api.py::_encode_sms_message()`), which both hex-encode UTF-16 code units regardless of the type they declare. Do not "fix" a GSM-7 send by packing 7-bit septets.
  - **The message length limit therefore depends on content, not just length.** `SMS_MAX_CHARS_GSM7` (765 = 5 x 153) and `SMS_MAX_CHARS_UNICODE` (335 = 5 x 67) in `const.py`; enforced by `_validate_sms_length()` in `__init__.py`, **not** by the service schema, because which limit applies is only knowable from the message itself. The schema carries the absolute ceiling alone. A flat limit is wrong in both directions — too small for plain text, and large enough to let a Unicode message become several separately-charged segments unannounced. Segment arithmetic and the hardware confirmation are in [`docs/zte_how_to_access.md`](docs/zte_how_to_access.md).
  - **`login()` tries one alternate form on failure.** `_attempt_login()` posts a single `goformId` and returns a `_LoginAttempt`; `login()` retries once with the other form (`LOGIN` ↔ `LOGIN_MULTI_USER`) when the first yields no session. It deliberately does **not** retry a credentials rejection — a wrong password is wrong on either form, and a second attempt only counts against routers that lock out. Real transport failures raise straight out rather than triggering a pointless retry.
  - **The batch poll is two requests, split by criticality.** The router bounds a GET at ~2048 characters — a **URL-length budget, not a name count** — and a single list had reached 1,889 characters with ~160 to spare. `_CORE_PARAMS` (mandatory, `get_all_data`) carries everything feeding an enabled-by-default entity, the contract keys and the device identity; `_EXTENDED_PARAMS` (optional, `get_extended_data`) carries diagnostics, disabled-by-default entities, router settings and the thermal keys. The extended half runs through `_fetch_optional`, so it holds last-good values for three cycles and then marks **only its own** entities unavailable — entities fed from it set `source=ENDPOINT_EXTENDED`. **Do not move a key feeding an enabled-by-default entity into the extended batch**, and note that cross-model aliases stay in core for exactly that reason: they feed enabled sensors on other models. `test_batch_poll_urls_stay_within_the_router_budget` guards both halves.
  - `get_all_data()` requests a block of cross-model keys the MC7010 does not populate. This is safe: an unknown `cmd` name is simply **absent** from the response rather than an error, and an absent key cannot trip the "every value is empty" rule above. **Keep that block in step with the alias tuples in `sensor.py`** — `test_get_all_data_requests_every_aliased_key` fails if an alias names a key that is never requested.
  - Full interface reference — every `cmd` and `goformId`, the auth and `AD` chains, and the failure modes of this API: [`docs/zte_how_to_access.md`](docs/zte_how_to_access.md).
  - `logout()` ends the router session on unload. It **must** send an `AD` token like every other state-changing command — without one the router answers `{"result":"failure"}` and leaves the session live. It is best-effort: it swallows its own errors and always clears local state, because an unreachable router must never block unload.

- **`coordinator.py` (`ZTERouterDataUpdateCoordinator`)** — polling + resilience layer.
  - **Failure resilience**: on timeout/auth/generic errors it holds the last known values for up to `FETCH_STRIKE_LIMIT` (3, in `const.py`) consecutive failures before marking entities unavailable (`UpdateFailed`). After 3 auth failures it triggers reauth via `ConfigEntryAuthFailed`.
  - **Per-endpoint resilience**: `_fetch_optional()` gives each optional endpoint (the two SMS calls) its own last-good payload and strike count; entities fed by one consult `endpoint_available(source)` in their `available` property. `get_all_data` is mandatory and stays on the global path. `ZTEAuthError` is re-raised rather than absorbed so reauth still fires.
  - **Dynamic polling**: `CONF_STOP_POLLING` returns cached data without hitting the router (the router allows only one login session, so pausing frees the web UI); `CONF_SCAN_INTERVAL` sets the interval.
  - **Force refresh**: `async_force_refresh()` sets a one-shot flag consumed **before** the pause check, so explicit user actions fetch even while paused. Every write action and the Refresh Now button route through it — never `async_request_refresh()` directly, which the pause short-circuit swallows.
  - **Self-diagnosis**: `health_snapshot` is a coordinator attribute (deliberately **not** in `coordinator.data`, which is `None` before first success and frozen during an outage) written on both the success and failure paths. It reports total outage (first failure at cold start, 3rd at runtime), degraded endpoints, and contract drift — a successful response containing none of `CORE_KEYS`. Drift publishes on this sensor only: it raised a repair until the 2026-08-25 repair-set alignment, and does not any more, because a schema change is not something the user can act on.
  - Detects new SMS by timestamp + per-message hash and fires the `zte_router_5g_sms_received` bus event. `_check_sms_storage` runs **before** the health snapshot so the repair state it reflects is current.
  - **Two repair issues**, with ids scoped to the config entry (`{entry_id}_{name}`) and cleared on both unload and removal — `REPAIR_NAMES` in `coordinator.py` is the list, and `async_remove_entry` exists solely to stop a raised repair outliving the integration as permanent unfixable litter. `conn_error` (`UNREACHABLE_STRIKE_LIMIT` = **10** consecutive failures — deliberately far above the 3-strike unavailability threshold, so a router reboot never raises it; auto-clearing), and `auth_failed` (the router **rejected** the credentials — not a lapsed session, which is the integration's problem; `is_fixable=True`, `is_persistent=True`, and it does not auto-clear because a wrong password stays wrong). A Repair requires **persistence plus agency**: the condition must have stopped resolving itself _and_ there must be something the user can do. Adding a third needs that test applied, not just a `translation_key`. Set by `x_project/repair_set_alignment.md` §2, which is family-wide — do not add one here alone.
  - **`auth_failed` is fixable, so `repairs.py` must exist.** Home Assistant substitutes `ConfirmRepairFlow` for a fixable issue whose integration ships no `repairs` platform, and that flow's Fix button shows an empty confirm box and **deletes the card without touching the credentials**. `tests/test_repairs.py::test_the_fix_flow_is_ours_not_the_confirm_fallback` fails if the module is removed.
  - **`RETIRED_REPAIR_NAMES` is not dead code.** `firmware_contract_drift`, `sms_storage_full` and `router_unreachable` were retired or renamed on 2026-08-25. `ir.async_delete_issue` looks up by id, so a card still live under a retired id has no route out — `clear_legacy_repairs()` deletes them at every setup, which is what makes retiring one safe. Deleting an entry from that tuple strands any card still showing under it.
  - Persists a stable `boot_time` into `entry.data` so the uptime timestamp doesn't jitter. The boot instant is latched once and only re-derived when the router's uptime counter drops by more than `UPTIME_REBOOT_MARGIN` (a genuine reboot); missing/garbage uptime readings leave the latched value untouched. `last_uptime` is persisted alongside `boot_time` as the reboot-detection anchor.

- **`__init__.py`** — entry setup forwards platforms **immediately**, then runs login + first refresh in a background task (`async_create_background_task`) so HA startup isn't blocked. Also registers the SMS services at domain level. The coordinator is stored on `entry.runtime_data`, not `hass.data`. `async_unload_entry` calls `api.logout()` after unloading platforms.
  - **Options listener**: `_async_options_updated` diffs `entry.options` against `coordinator.reload_signature` (options minus `LIVE_OPTION_KEYS`). Anything outside the allow-list — host, username, password — schedules a reload; `scan_interval` and `stop_polling` live-apply. Reload is the default; adding a new option means deciding which side it falls on, and connection or entity-topology settings must always reload.

- **`helpers.py`** — besides `build_device_info` and the `ZTEAboutEntity` mixin, carries two cross-model utilities with no HA dependency: `is_gsm7()` (GSM 03.38 alphabet, for the SMS encoding choice above) and `earfcn_to_band()` / `arfcn_to_band()` (3GPP channel-to-band lookup, for routers that report a channel number but no band name). **The NR ranges genuinely overlap** — n78 sits inside n77 — so `arfcn_to_band()` resolves ties by a documented table order and is best-effort by design. A band name the router reports always wins over it. All three return `None` rather than guessing on unparsable or out-of-range input.

- **Platforms** (`sensor`, `binary_sensor`, `button`, `number`, `switch`, `select`) — read `coordinator.data` and attach to sub-devices via `helpers.build_device_info`.
  - **`sensor.py` key aliasing**: `_get_first(data, keys)` returns the first spelling the router populated, treating present-but-empty as absent. Alias tuples are named constants (`_ALIAS_5G_RSRP` etc.) so the set is checkable against `api.py`. It nests **inside** the existing converters — `_safe_float(_get_first(...))`, never bare — or coercion and rounding are lost. All six monthly TX/RX call sites are aliased, including the two totals via `_monthly_total_bytes()`; aliasing only some would let the totals silently disagree with their own components on `flux_`-spelling hardware.
  - **`Projected Cycle Usage` carries two deliberate non-defaults.** It has **no `state_class`**, so it never reaches long-term statistics — it is an estimate of where the cycle ends up, and the usage it derives from is already recorded by `Monthly Total`; `test_projection_has_no_state_class` guards it, because "a numeric sensor with no state class" looks like an oversight. And it **falls back to the calendar month** when the router reports no reset day, publishing `cycle_source: calendar_assumed` rather than going `unknown` — an unexplained blank that never clears is worse than a stated assumption. Its `prior_rate` hook in `helpers.project_cycle_usage()` is always `None` today; the cycle-history store behind it is declined, see `DEVELOPMENT.md` §7.
  - **Thermal sensors are a defined set, not a subset.** The five `pm_*` entities are the thermal keys the sibling `goform` project polls with °C units. `test_thermal_sensor_set_matches_the_descriptions` fails if one is added without a test or vice versa. No model is yet confirmed to populate any of them — all are disabled by default, and the MC7010 returns `""` for every one. Two exceptions read elsewhere: `ZTEIntegrationHealthSensor` reads `coordinator.health_snapshot` and overrides `available` to `True` unconditionally, and sensors with a `source` on their description gate `available` on `endpoint_available()`.

- **`diagnostics.py`** — sanitizes rather than key-redacts. `coordinator.data` is the vendor payload verbatim, so it blanks credentials/subscriber IDs/carrier identity, pseudonymizes IPs, cell IDs and SMS senders to stable tokens, summarizes `APN_config*` to its shape, and sweeps everything else for IP/MAC-shaped strings. Identifiers are matched by shape and position only — **never** seed it with real values. Verify changes against a regenerated download with an SMS present, not by reading the code.

### Device Identity Model ("Flat Identity")

Hardware metadata (`model`, `sw_version`, `imei`) is read once and stored in `entry.data`, so device info is stable from boot before the first poll completes. Entities are grouped into sub-devices (System / Signal / Data / SMS) all linked to a `{prefix}_system` root, where `prefix` is the IMEI (or `host_{host}` fallback). The System device is registered early in `async_setup_entry` to avoid parent-link warnings.

This is the **System-as-root** topology, and it is conformant — `dev_standards` §3 (Standard Version 1.15.0) ranks a stable non-MAC hardware identifier such as IMEI **equal** to a MAC, and names both System-as-root and hardware-as-root as valid. The `goform` API never exposes a MAC. Do not "fix" this to an IP-keyed root; the earlier ladder implied that and was wrong.

**Version compatibility (`_compat.py`).** Parent links and registry lookups go through feature-detected shims — `via_device_link` and `device_by_identifier` — emitting `via_device_id` on HA 2026.8+ and the legacy `via_device` tuple on ≤2026.7, with **no version floor**. `owning_entry_ids` is deliberately absent: this integration never reads `device.config_entries`, and an unused shim is dead code against a 100% coverage bar. Family-wide analysis and the 2026.8.0 re-verification checklist: `.shared/issues/x_project/device_registry_2026_08.md`.

### Config Entry Data vs. Options

This integration intentionally splits config entry storage:

- **`entry.options`** holds the live, user-editable connection settings: `CONF_HOST`, `CONF_USERNAME`, `CONF_PASSWORD`, plus `scan_interval` / `stop_polling`.
- **`entry.data`** holds discovered hardware metadata: `model`, `sw_version`, `imei`, `boot_time`, `last_uptime`.

Read credentials from `entry.options`, not `entry.data`. The config flow is `VERSION = 2` and supports user / reconfigure / reauth / options steps.

There is **no** `async_migrate_entry`, which is safe only because the first public release (2.0.1) already shipped the v2 schema — no v1 entry exists in the wild. Bumping `VERSION` to 3 makes a migration handler mandatory. In tests, `MockConfigEntry` defaults to `version=1`, so pass `version=2` explicitly or setup fails with "Migration handler not found".

## Key Patterns & Conventions

Shared conventions (ruff/mypy strictness, `_LOGGER` prefixing, `PARALLEL_UPDATES`, `translation_key`, icons, exception tuple syntax, markdown emoji rules) are in [shared conventions §4–5](.shared/dev_std/agent_conventions.md). Nothing in this project deviates.

### Entity naming — do not repeat the sub-device word

Home Assistant prefixes the **device** name to the entity name, and this integration's devices are `ZTE 5G System` / `Signal` / `Data` / `SMS`. So an entity in the `data` group named "Data Reset Day" becomes **"ZTE 5G Data Data Reset Day"** and `sensor.zte_5g_data_data_reset_day`.

**Name the entity for what it is within its group, not including the group.** `Reset Day`, `Allowance`, `Alert Threshold` — never `Data Reset Day`, `Data Allowance`, `Data Volume Alert`.

Two released entities already carry the doubling and are **deliberately left alone**:

- `sensor.zte_5g_signal_signal_bars`
- `switch.zte_5g_data_data_limit_switch`

Renaming them would fix nothing. **Home Assistant never renames an existing `entity_id`** — the registry keeps whatever was assigned at creation — so every current install keeps the doubled ID regardless, while anyone referencing the friendly name in a dashboard or template gets a silent break. The only beneficiary is a new install, which is not worth the breakage. Fix the convention going forward; do not retrofit.

The corollary matters when adding an entity: **get the name right before it ships**, because after that only new installs see the correction. `Reset Day`, `Allowance` and `Alert Threshold` were all renamed within hours of being added, for exactly this reason.

### Raising user-facing exceptions

Every raise that can reach a user must be translated — no f-string messages:

```python
raise HomeAssistantError(
    translation_domain=DOMAIN,
    translation_key="send_sms_failed",
    translation_placeholders={"error": str(err)},
) from err
```

- Add a matching entry to the `exceptions` block in **both** `strings.json` and `translations/en.json`.
- Pick the type deliberately: **`ServiceValidationError`** when the caller got the call wrong and can fix it (no `entry_id` given when several routers exist); **`HomeAssistantError`** when the operation failed (the router rejected a reboot).
- `test_every_raised_exception_has_translated_text` walks every raise in the component and fails on an untranslated one or a key missing from either file.
- **Testing gotcha:** a translated exception resolves its message through `hass` at `str()` time, so `pytest.raises(..., match="some text")` fails under this suite's mocked hass with `async_get_hass called from the wrong thread`. Assert on `err.value.translation_key` instead.

### Editing `quality_scale.yaml`

Comments are plain multi-line block scalars, so a `": "` sequence in prose is parsed as a mapping and breaks the file. Write `X — because Y`, not `X: because Y`. Check with `grep -nE '^      .*: ' custom_components/zte_router_5g/quality_scale.yaml` before committing.

## Tests that will stop you, and why they exist

This project has **more sweep tests than any other in the family** — a consequence of §2.1, §2.2, §2.5, §12 and §22 all landing here first. A sweep asserts that every member of a **set** is covered, so it fails when the set _grows_, not when a known member breaks. The failure therefore looks unrelated to whatever you just changed, and the reflex is to suppress it.

**If one of these fails, it has found something. The allow-list is the last resort, not the first move.**

**Add a row when you add a sweep.** This table went stale within one session of being written — three sweeps were added and none reached it — which is the same drift the sweeps themselves exist to catch.

| Add or change this | This fails | Do this |
| :-- | :-- | :-- |
| A sensor with a unit or `state_class` | `test_every_numeric_sensor_has_a_guard_band` | Declare `min_limit` / `max_limit`, or add the key to the unguarded allow-list **with a reason**. Then update `docs/value_min_max.md` — §6 requires it to match the code in both directions. `test_unguarded_allowlist_has_no_dead_entries` fails if an exemption outlives its sensor. |
| Any sensor at all | `test_no_sensor_uses_the_total_state_class` | Use `TOTAL_INCREASING`. `ALLOWED_TOTAL_STATE_CLASS` is deliberately **empty**, so adding an entry is a reviewable act rather than a typo. Plain `TOTAL` walks long-term statistics backwards on every billing rollover. |
| Any entity | `test_every_live_entity_has_an_icon_or_a_device_class` | Add an `icons.json` entry **under that entity's own platform**, unless it carries a `device_class`. A live sweep, because descriptions live in a mix of tuples and module-level singletons. |
| Any action | the action half of `test_entity_hygiene.py` | Add a `services` entry in the nested `{"service": "mdi:..."}` form. Checked in both directions — every action has an icon, every icon names a real action. |
| An entity attribute | `test_no_entity_publishes_a_recorded_attribute` | Add the key to that class's `_unrecorded_attributes`. **Repeat `"about"` if the class declares its own set** — HA does not merge this across the class hierarchy, so a subclass assignment shadows the mixin's entirely. |
| A raised exception, or a repair | `test_every_raised_exception_has_translated_text`; for repairs, the step-8 sweeps in `tests/test_health_contract.py` | Add the key to the `exceptions` / `issues` block in **both** `strings.json` and `translations/en.json`. **A repair takes a `title`, then _exactly one_ of `description` or `fix_flow`** — `hassfest`'s issues schema declares them `vol.Exclusive`, because a fixable issue renders its prose in the flow's step rather than on the card. Supplying both fails `hassfest` locally and in CI. |
| A new API method | `test_every_public_method_is_covered_by_the_sweep` | Add it to `_CALLS` in `test_dead_session_sweep.py`. The property it must satisfy: **a method either does the thing or raises — it may never return a success-shaped result having done nothing.** |
| A new write command | `test_every_write_command_is_in_the_refusal_sweep`, `test_every_write_is_classified`, `test_every_classification_carries_a_reason` | Add it to `scripts/write_classification.py` as `SAFE`, `ATTENDED` or `NEVER_AUTOMATED`, **with a written reason**. If you classify it `SAFE`, `test_every_safe_write_is_exercised_by_the_hardware_check` also requires `scripts/hardware_check.py` to actually send it. |
| A write payload | `test_every_write_command_has_a_locked_shape` | The shape is pinned. `DATA_LIMIT_SETTING` is all-or-nothing: the router answers `{"result":"failure"}` for a payload missing any field. |
| A key in the batch poll | `test_every_batch_carries_both_classes`, `test_batch_poll_urls_stay_within_the_router_budget` | Every batch needs one authenticated and one unauthenticated key, or the dead-session rule cannot fire on it. And the URL is bounded at ~2048 characters — a **length** budget, not a name count. |
| A sensor key alias | `test_every_aliased_key_is_requested_by_the_batch_poll` | Add the spelling to the cross-model block in `api.py`, or the alias names a key never requested. |
| A thermal sensor | `test_thermal_sensor_set_matches_the_descriptions` | The five `pm_*` entities are a defined set, not a subset. Add the test and the description together. |
| A sensor fed from the extended poll | `test_no_sensor_declares_a_source_its_data_does_not_come_from` | Only set `source=ENDPOINT_EXTENDED` if the keys really are in `_EXTENDED_PARAMS`. `Allowance` and `Alert Threshold` declared it while their keys sat in `_CORE_PARAMS`, so both went unavailable holding data the mandatory poll had just refreshed. The sweep resolves keys through lambdas, helper functions and alias tuples — its first version scanned description text only, found nothing for `data_allowance`, and passed with the defect deliberately restored. |
| A sensor description | `test_every_sensor_carries_a_stable_unique_id` | Every description needs a `key` that yields a distinct `unique_id`. HA silently declines to register an entity without one: it still appears and still reports a value, while every user customization is discarded on restart. |
| A config-flow field | `test_no_field_leaks_the_stored_secret`, `test_stored_secrets_are_never_pre_filled` | Never pre-fill a stored secret — not as a `default`, not as a `suggested_value`, and not into a non-secret field. A masked value still reaches the browser and the eye icon reveals it. Both schema builders are fed a sentinel secret that must appear nowhere in the rendered schema. |
| A key in the router payload | `test_no_identifier_survives_anywhere_in_the_output` | Diagnostics is asserted as a property over the whole rendered file, not per key — a leak is by definition somewhere the key list did not reach. Sanitize by **shape and position**, never by seeding real values, and keep the diagnostic substance. Over-redaction fails the companion test. |
| A `DATA_LIMIT_SETTING` field | `test_every_data_volume_field_is_polled` | The form is all-or-nothing and is built read-modify-write from the last poll, so every field it carries must be in `_CORE_PARAMS`. A field the poll does not fetch cannot be echoed back, and the router answers `{"result":"failure"}` for a payload missing any of them. |
| A switch fed from the extended poll | `test_no_switch_reads_from_a_degradable_endpoint` | Move the key to `_CORE_PARAMS`. §22: a stale diagnostic is cosmetic, a stale **control** position invites a write composed from a reading that is no longer true. |
| A repair issue | `REPAIR_NAMES` in `coordinator.py`, and the step-8 sweeps in `tests/test_health_contract.py` | Add it there, or unload and removal will not clear it and it becomes permanent unfixable litter in the Repairs panel. Registry ids carry the entry id; `translation_key` stays bare. The set is fixed family-wide by `x_project/repair_set_alignment.md` §2, so a third one is a cross-project decision. **Never rename or retire a live `issue_id` without adding it to `RETIRED_REPAIR_NAMES`** — `ir.async_delete_issue` looks up by id, so the old id orphans a raised repair with no UI path out. |
| A condition only ever exercised one way | `Pytest: Check Test Coverage` reports a partial branch (`123->126` in the `Missing` column) | **Write the test.** All eleven found here were missing tests; none was dead code, matching WiFi's 12 of 12. Delete a guard only where the type system or the immediate caller already prevents the case — never in code consuming held or stored state, where the "impossible" shape arrives exactly when something upstream has already failed. `# pragma: no cover` changes the denominator, so it raises the percentage without testing anything. |
| A test that runs code without checking it | `Tests: Assertion Audit` | Assert the **observable outcome**. Where "this must not raise" is the real contract, assert what that implies — nothing cancelled, no task created, exactly one event on the bus. Adding a trivial assertion to clear the count is a defect, not a fix. Last resort: `tests/zero_assertion_allowlist.txt`, with a reason. |

- **Mutation testing is scoped by `.validate/mutmut_modules.txt`** — currently `*/helpers.py`, `*/diagnostics.py`, `*/sensor.py`, chosen by measurement because their tests exercise real code. `api.py`, `coordinator.py`, `switch.py` and `select.py` are excluded: their tests mock the thing being mutated, so every mutation of a call into that mock survives and none is a findable defect. Run it with the **Tests: Mutation Check** task — not part of `Validate All`, because survivors need judging rather than counting. **Never delete `mutants/`**: it is the incremental cache _and_ the results store, and changing the module list does not require it.

- **`only_mutate` must be an indented newline list.** The comma-separated form shown in the mutmut docs silently generates **zero mutants and reports no error** — a run configured that way passes completely and proves nothing.

## Remaining Work (Future — Separate Session)

**Forward work lives in [docs/ROADMAP.md](docs/ROADMAP.md)** — refer there for planned items, revisit parameters, and declined design decisions. Keep it there rather than here, so there is one place to look.

---

## Development Environment

Standard for all integration projects — see [shared conventions §3](.shared/dev_std/agent_conventions.md). Nothing about this project's environment differs.

## Known Open Issues

**Nothing is recorded here, and nothing should be.** This project's open work lives in `.notes/todo.md`, `.notes/tasks/`, the cross-project chore register, the cross-project queue and [`docs/ROADMAP.md`](docs/ROADMAP.md). One command reads all of them, from `dev-workbench/`:

```bash
uv run python scripts/check_queue_format.py --open ha-zte-router-5g-monitor
```

**Which one a new item belongs in, and how to add, check and close it, is [`issue_tracking_workflow.md`](.shared/issues/issue_tracking_workflow.md)** — authoritative, with the summary at [shared conventions §8](.shared/dev_std/agent_conventions.md).
