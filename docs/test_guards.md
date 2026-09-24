# Test Guards: ZTE Router 5G Monitor

Rationale for the guard tests listed under _Tests that will stop you_ in [`AGENTS.md`](../AGENTS.md). `AGENTS.md` states what fails and what to do; this file records why each guard exists. When a guard test is added, its row goes in `AGENTS.md` and its rationale here.

---

## Guards Moved From `AGENTS.md` (2026-09-23)

Each entry is the rationale column of the former `AGENTS.md` table, copied verbatim.

### An entity class of any kind

**Tests:** `test_every_live_entity_belongs_to_a_device`, `test_device_info_is_declared_once`

Inherit `helpers.ZTEDeviceEntity`. Never write your own `device_info`

### A binary sensor or switch

**Tests:** `test_every_boolean_entity_declares_the_keys_it_reads`

Declare `state_keys`. A boolean value function answers `False` for an empty payload, so it cannot say whether the router replied

### An entry in `MODEL_OVERLAY`

**Tests:** `test_every_overlay_key_names_a_real_entity`, `test_no_overlay_entry_repeats_the_description_default`

Name a real entity key, and only where the model differs from the shipped default

### A sensor with a unit or `state_class`

**Tests:** `test_every_numeric_sensor_has_a_guard_band`

Declare `min_limit` / `max_limit`, or add the key to the unguarded allow-list **with a reason**. Then update `docs/value_min_max.md` — §6 requires it to match the code in both directions. `test_unguarded_allowlist_has_no_dead_entries` fails if an exemption outlives its sensor.

### Any sensor at all

**Tests:** `test_no_sensor_uses_the_total_state_class`

Use `TOTAL_INCREASING`. `ALLOWED_TOTAL_STATE_CLASS` is deliberately **empty**, so adding an entry is a reviewable act rather than a typo. Plain `TOTAL` walks long-term statistics backwards on every billing rollover.

### Any entity

**Tests:** `test_every_live_entity_has_an_icon_or_a_device_class`

Add an `icons.json` entry **under that entity's own platform**, unless it carries a `device_class`. A live sweep, because descriptions live in a mix of tuples and module-level singletons.

### Any action

**Tests:** the action half of `test_entity_hygiene.py`

Add a `services` entry in the nested `{"service": "mdi:..."}` form. Checked in both directions — every action has an icon, every icon names a real action.

### An entity attribute

**Tests:** `test_no_entity_publishes_a_recorded_attribute`

Add the key to that class's `_unrecorded_attributes`. **Repeat `"about"` if the class declares its own set** — HA does not merge this across the class hierarchy, so a subclass assignment shadows the mixin's entirely.

### A raised exception, or a repair

**Tests:** `test_every_raised_exception_has_translated_text`; for repairs, the step-8 sweeps in `tests/test_health_contract.py`

Add the key to the `exceptions` / `issues` block in **both** `strings.json` and `translations/en.json`. **A repair takes a `title`, then _exactly one_ of `description` or `fix_flow`** — `hassfest`'s issues schema declares them `vol.Exclusive`, because a fixable issue renders its prose in the flow's step rather than on the card. Supplying both fails `hassfest` locally and in CI.

### A new API method

**Tests:** `test_every_public_method_is_covered_by_the_sweep`

Add it to `_CALLS` in `test_dead_session_sweep.py`. The property it must satisfy: **a method either does the thing or raises — it may never return a success-shaped result having done nothing.**

### A new write command

**Tests:** `test_every_write_command_is_in_the_refusal_sweep`, `test_every_write_is_classified`, `test_every_classification_carries_a_reason`

Add it to `scripts/write_classification.py` as `SAFE`, `ATTENDED` or `NEVER_AUTOMATED`, **with a written reason**. If you classify it `SAFE`, `test_every_safe_write_is_exercised_by_the_hardware_check` also requires `scripts/hardware_check.py` to actually send it.

### A write payload

**Tests:** `test_every_write_command_has_a_locked_shape`

The shape is pinned. `DATA_LIMIT_SETTING` is all-or-nothing: the router answers `{"result":"failure"}` for a payload missing any field.

### A key the poll requests

**Tests:** `test_at_least_one_chunk_per_batch_can_be_classified`, `test_a_verdict_is_only_drawn_where_it_could_mean_something`

The batch is split by URL length, and `_batch_get` draws a session verdict only on a chunk holding a sentinel or an unauthenticated key. A chunk of names a device does not support answers every one empty, which is the shape of an expired session — measured when the MC888 aliases pushed the core list into two requests and every poll returned nothing. Never give a chunk an unauthenticated key to make it look classifiable; that was tried and made the false verdict worse.

### A key in the batch poll

**Tests:** `test_every_batch_carries_both_classes`, `test_batch_poll_urls_stay_within_the_router_budget`

Every batch needs one authenticated and one unauthenticated key, or the dead-session rule cannot fire on it. And the URL is bounded at ~2048 characters — a **length** budget, not a name count.

### A sensor key alias

**Tests:** `test_every_aliased_key_is_requested_by_the_batch_poll`

Add the spelling to the cross-model block in `api.py`, or the alias names a key never requested.

### A thermal sensor

**Tests:** `test_thermal_sensor_set_matches_the_descriptions`

The five `pm_*` entities are a defined set, not a subset. Add the test and the description together.

### A sensor fed from the extended poll

**Tests:** `test_no_sensor_declares_a_source_its_data_does_not_come_from`

Only set `source=ENDPOINT_EXTENDED` if the keys really are in `_EXTENDED_PARAMS`. `Allowance` and `Alert Threshold` declared it while their keys sat in `_CORE_PARAMS`, so both went unavailable holding data the mandatory poll had just refreshed. The sweep resolves keys through lambdas, helper functions and alias tuples — its first version scanned description text only, found nothing for `data_allowance`, and passed with the defect deliberately restored.

### A sensor description

**Tests:** `test_every_sensor_carries_a_stable_unique_id`

Every description needs a `key` that yields a distinct `unique_id`. HA silently declines to register an entity without one: it still appears and still reports a value, while every user customization is discarded on restart.

### A config-flow field

**Tests:** `test_no_field_leaks_the_stored_secret`, `test_stored_secrets_are_never_pre_filled`

Never pre-fill a stored secret — not as a `default`, not as a `suggested_value`, and not into a non-secret field. A masked value still reaches the browser and the eye icon reveals it. Both schema builders are fed a sentinel secret that must appear nowhere in the rendered schema.

### Anything that orders SMS

**Tests:** `tests/test_sms_ordering.py`

Order on `helpers.sms_instant`, not on the ISO string, and treat a value it rejects as undated. Ids order nothing once both banks are in one list.

### A destructive write

**Tests:** `test_every_public_method_is_covered_by_the_sweep`, and the delete tests in `tests/test_sms_and_usage_diagnostics.py`

Verify the effect, do not trust the `result`. This API answers `success` for a `DELETE_SMS` naming an id it does not hold.

### A name added to the batch poll

**Tests:** `test_no_discovery_candidate_is_already_requested`

Remove it from `DISCOVERY_CANDIDATES` and `DISCOVERY_VALUE_SAFE`. Discovery exists for names the poll does **not** carry, so a name in both is probed for an answer already in hand.

### A derived figure in the download

**Tests:** `[4] no structural difference between the two runs` in `scripts/diag_check.py`

Anything computed from a counter or a clock differs between two passes twenty seconds apart. Add its path to `_VOLATILE` — but not the structural fields beside it, such as `spelling_used`, whose changing _is_ the fault that check looks for.

### A field returned by `run_discovery`

**Tests:** `test_every_discovery_field_is_classified`

Name it in `DISCOVERY_METADATA_PUBLISHED` or `DISCOVERY_METADATA_GATED`. `_sanitize_discovery` copies through an allow-list, so a field absent from both is produced and then dropped in silence — branch coverage cannot see it, because the list is data and the loop runs either way. `session_alive_after` was caught by memory; `canary` was not, and shipped in v3.3.9-dev5 recorded by the API and absent from every download. Assert it in `tests/test_diagnostics_artefact.py`, which tests the file rather than the return value, and confirm on hardware with `scripts/diag_check.py`.

### A name observed on any device

**Tests:** `known_names.py`

Add it there, not to one device's mined set. Every device is probed with the union: whether a device's web UI _mentions_ a name and whether it _answers_ it are independent facts, and the MC888 Pro answered 102 names absent from the MC7010's entire vocabulary. Names only, by observation, never by invention.

### An outcome for a probed name

**Tests:** `test_the_download_separates_silent_names_from_unasked_ones`

Three outcomes, three fields. `values` means answered, `probed_no_answer` means asked alone and silent, `not_reprobed` means the pass could not ask and claims nothing. Never merge two of them: a capped re-probe published about a hundred names a pass as established absences, and the MC888 key conclusions were drawn from exactly that.

### A key in the router payload

**Tests:** `test_no_identifier_survives_anywhere_in_the_output`

Diagnostics is asserted as a property over the whole rendered file, not per key — a leak is by definition somewhere the key list did not reach. Sanitize by **shape and position**, never by seeding real values, and keep the diagnostic substance. Over-redaction fails the companion test.

### A `DATA_LIMIT_SETTING` field

**Tests:** `test_every_data_volume_field_is_polled`

The form is all-or-nothing and is built read-modify-write from the last poll, so every field it carries must be in `_CORE_PARAMS`. A field the poll does not fetch cannot be echoed back, and the router answers `{"result":"failure"}` for a payload missing any of them.

### A switch fed from the extended poll

**Tests:** `test_no_switch_reads_from_a_degradable_endpoint`

Move the key to `_CORE_PARAMS`. §22: a stale diagnostic is cosmetic, a stale **control** position invites a write composed from a reading that is no longer true.

### A repair issue

**Tests:** `REPAIR_NAMES` in `coordinator.py`, and the step-8 sweeps in `tests/test_health_contract.py`

Add it there, or unload and removal will not clear it and it becomes permanent unfixable litter in the Repairs panel. Registry ids carry the entry id; `translation_key` stays bare. The set is fixed family-wide by `x_project/repair_set_alignment.md` §2, so a third one is a cross-project decision. **Never rename or retire a live `issue_id` without adding it to `RETIRED_REPAIR_NAMES`** — `ir.async_delete_issue` looks up by id, so the old id orphans a raised repair with no UI path out.

### A condition only ever exercised one way

**Tests:** `Pytest: Check Test Coverage` reports a partial branch (`123->126` in the `Missing` column)

**Write the test.** All eleven found here were missing tests; none was dead code, matching WiFi's 12 of 12. Delete a guard only where the type system or the immediate caller already prevents the case — never in code consuming held or stored state, where the "impossible" shape arrives exactly when something upstream has already failed. `# pragma: no cover` changes the denominator, so it raises the percentage without testing anything.

### A test that runs code without checking it

**Tests:** `Tests: Assertion Audit`

Assert the **observable outcome**. Where "this must not raise" is the real contract, assert what that implies — nothing cancelled, no task created, exactly one event on the bus. Adding a trivial assertion to clear the count is a defect, not a fix. Last resort: `tests/zero_assertion_allowlist.txt`, with a reason.

---

## Guards Added to the Table (2026-09-23)

Tests that fire on an ordinary change and were not previously listed. Each rationale is the test's docstring.

### `test_refresh_button_has_an_icon`

Refresh Now has no device_class to derive one from.

### `test_services_have_icons`

Section 12 requires icons.json to cover services, not just entities.

### `test_registered_services_match_the_icon_entries`

Guards against an icon entry drifting from the real service name.

### `test_every_attribute_the_sensor_emits_is_unrecorded`

Section 14: the default is total — no attribute is recorded. `sntp_server1` and `sntp_dst_enable` were previously exempted here as "static configuration worth seeing in history". Section 14 (Standard Version 1.12.0) withdrew that reasoning: attributes are not a history mechanism, and a value whose history is genuinely wanted should be an entity or a user template sensor.

### `test_health_detail_is_unrecorded`

The health sensor's detail churns with every failure.

### `test_every_repair_issue_has_title_and_rendered_text`

A missing entry shows the raw key, or a card with an empty body. Stronger than the check this replaces, which asserted only that the key was _present_ in `issues`. **`description` and `fix_flow` are mutually exclusive**, and the sweep has to allow for that or it contradicts `hassfest`. Its issues schema (`script/hassfest/translations.py`) requires a `title`, then exactly one of the two — `vol.Exclusive(..., "fixable")` — because a fixable issue renders its prose in the flow's step rather than on the card. A sweep asserting both demands a shape Home Assistant rejects, and would pass while validation failed. So: a title always, and rendered text in whichever form the issue's fixability calls for.

### `test_the_fixable_repair_is_the_one_with_a_fix_flow`

The two forms must line up with what the code actually raises. A `fix_flow` on an issue raised with `is_fixable=False` is text nobody can reach; a fixable issue without one gets `ConfirmRepairFlow` and a Fix button that dismisses the card. Both are silent failures, which is why the pairing is asserted rather than assumed.

### `test_no_orphan_issue_translations`

Text left behind for a key nothing raises any more. An orphan is invisible: nothing renders it, so nothing reveals that it describes a repair that no longer exists. It then quietly becomes the documentation for a key someone later reuses. The retired keys are the live case here — three of them were retired on 2026-08-25, and their text had to go with them.

### `test_every_repair_the_code_raises_is_registered_for_removal`

The sharp one: a repair omitted here outlives the integration. `async_remove_entry` deletes exactly the list it is given. A repair the code can raise but that list omits sits in the Repairs panel forever, with `is_fixable=False` and no UI path to clear it and no integration left that could. This class of defect has recurred twice in this family. Driven rather than read out of the source: an assertion that `__init__.py` mentions the removal constants is satisfied by the import line alone, and passes with the loop emptied. Raising a card under every id the code knows about and asserting the registry empties cannot.

### `test_translation_keys_resolve_in_both_files`

Every translation_key used in code must resolve in both files. Compared against the code, not file-to-file: a healthy entry count in one file conceals both stale entries and live entities with no entry at all.

### `test_every_polled_key_is_read_by_something`

A key in the request that nothing reads is a round trip for nothing. The alias sweeps run one way — every key an entity names must be polled. Nothing ran the other way, so `net_select_mode` sat in `_CORE_PARAMS` unread, and `network_net_select_mode` was added beside it to let a second device answer the same unread key. A key counts as read when an entity names it, when it belongs to an alias tuple some entity uses, when it feeds the data-volume write form, when it belongs to a prefix-matched family, or when it is listed above with the reason it is requested anyway.

### `test_sms_sender_number_is_never_recorded`

The SMS sender's number is third-party personal data. Recording it would write someone else's phone number into the user's database on every poll.

### `test_no_log_line_carries_the_sms_sender_number`

Section 20: the log is a wider surface than the event bus. The sender's number is third-party personal data, and it used to be interpolated into an INFO line on every new message. The bus event still carries it, scoped to this entry; the log is copied into every diagnostics download, issue report and screenshot, and nothing redacts it there. Asserted over the source rather than over captured output because the interesting case is the line nobody wrote a test for. `%s` formatting means the number never appears as a literal, so a search of `caplog.text` on the one path a test happens to drive would pass while a second site leaked.

### `test_a_new_sms_logs_nothing_that_identifies_the_sender`

The runtime half of the check above, on the path that used to leak.

### `test_every_published_severity_is_in_the_section_19_vocabulary`

A severity outside the vocabulary breaks every automation reading it. This exists because a mutation survived on `wifi_ssid_monitor`: every test asserted the severity of the check it was written for, so nothing noticed when one stopped setting one at all. Asserted over the **published strings**, and over every path that writes a snapshot, not just the happy one.

### `test_every_finding_is_classified_exactly_once`

A finding must be drift or capability, never both and never neither. The two lists are what a template reads to decide whether a problem is the router's shape changing or an endpoint being unavailable. A finding in both is reported twice; a finding in neither is a `problem: true` the user cannot explain.

### `test_every_snapshot_the_coordinator_writes_carries_the_full_contract`

The vacuity guard, and a shape sweep over every write path. Section 19's attribute names are a published contract: users write templates against them, so a missing key silently yields an empty template value rather than an error. There are four places that assign `health_snapshot` — success, success-fallback, failure, failure-fallback — and they are easy to let drift apart. One of them was missing `repairs` when this sweep was written. Asserts the **count** of keys as well as their presence, so the guard cannot quietly shrink.

### `test_every_suppression_is_on_the_reviewed_allow_list`

No `type: ignore`, `noqa` or `pragma: no cover` without a written reason. **If this fails, the new suppression needs a reason, not an entry.** Ask what the tool would have said and whether that thing is actually true — an `attr-defined` ignore on a library call is a _claim about that library_.

### `test_every_allowed_suppression_states_a_reason`

The reason is the entire value of the allow-list. An entry with a token justification is indistinguishable from one added to make a check pass, which is the thing being guarded against.

### `test_allowed_suppressions_has_no_dead_entries`

An allow-list entry must not outlive the suppression it covers. A dead entry silently pre-approves the next occurrence of the same directive in the same file, which is how a reviewed exception becomes an unreviewed habit.
