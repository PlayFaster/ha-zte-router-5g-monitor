# Roadmap: ZTE Router 5G Monitor

Forward view for `ha-zte-router-5g-monitor`, and the record of what has been decided against. The integration is feature-complete for its core purpose — monitoring, SMS, data-usage tracking and a small set of safe controls. Most of what remains is either verification work on hardware nobody has tested, or write controls that have been considered and declined.

Format document `roadmap_format.md` used.

**Reviewed 2026-09-05** against the running instance (121 entities) and the current source.

---

## To Be Done

### Billing-cycle write controls

#### **Value ⭐⭐⭐ · Effort Low**

The hard part is done. `DATA_LIMIT_SETTING` is confirmed as a six-field, all-or-nothing form, `api.set_data_volume_settings()` performs the read-modify-write, and the round trip is verified on hardware. The same work fixed a Data Limit Switch that had never functioned, because it was sending exactly the partial payload the router refuses.

Two entities remain on the Data sub-device:

- a **Number** for the reset day (1–31), writing `traffic_clear_date`
- a **Switch** for `wan_auto_clear_flow_data_switch`, which decides whether monthly counters roll over at all

Both keys are already polled, and the switch already drives the projection sensor's suppression logic. Neither has a user-facing control. **Design detail — the entity inventory, the write path and its risks — is `.notes/info/data_projection/data_cycle_and_projection_plan.md` §8 and §2.2.** That file is reference; this entry owns the work.

**Both ship disabled by default**, matching the existing Data Limit Switch. Changing the reset day moves the boundary that the projection sensor and every data-cap automation reason about — not dangerous, but not a display setting either.

**Next build.** Moved from Maybe on 2026-10-15 at the owner's direction; the build plan is not yet written. The write path, both polled keys and the write classification are in place (`api.set_data_volume_settings()`, `poll_plan.py`, `scripts/write_classification.py`); the Number needs a router-write path, as `number.py` holds only the local polling interval, following `switch.py`'s `setter_fn` pattern.

## Maybe

### SMS feature-group toggle

#### **Value ⭐⭐⭐ · Effort Medium**

Two of the three polled endpoints exist solely for SMS, so a user who never sends one still pays two round trips per cycle. Disabling the sub-device hides the entities without stopping the polling.

Needs a `CONF_ENABLE_SMS` option, guards on both `_fetch_optional` calls, and an exclusion in `_degraded_endpoints()` — without the last, Integration Health reports "degraded" for a capability the user deliberately switched off. `dev_standards` §15.

### Entity defaults learned from the router's answers and declarations

#### **Value ⭐⭐ · Effort Medium**

For a router model with no `MODEL_OVERLAY` entry, on a new install, disable once the default-on entities that read blank in every settled full poll, so a user on an unmeasured model does not start with a block of `unknown` entities. MC7010 and MC888 Pro installs are untouched, and `MODEL_OVERLAY` stays as the curated override.

**Approach documented and evidence-checked, 2026-10-15.** The full design is section 14 of the reference record below: new entries of unmeasured models only, once; disable only; evidence from full polls taken at least 120 s after the integration's first successful poll, in at least three samples over ten minutes, an entity disabled only if blank in all of them; computed and state-dependent entities never judged (5G, carrier aggregation, rates, WAN address, `apn_profile`, `firmware_changes`, `last_updated`); `disabled_by = INTEGRATION`, so one click or the `reset_entities` action restores it. Simulated on the held data as though each model were unmeasured, the rule disables exactly the MC7010 overlay's two entities on unredacted coordinator data, and the MC888 Pro overlay's four judged entities on its downloads (section 14.5). The feasibility checks behind it (replay, the config flow's fetch, a router reboot) are section 13. A second phase, a core and extras split with extras enabled by the same evidence, is section 14.7 and not designed.

**What exists.** `entity_defaults.default_enabled(description, model)` is the single resolver, and it takes only the description's flag and the model string. A model absent from the overlay, which holds MC888 and MC7010 only, gets the flags written for the MC7010. What answers do feed is the `reset_entities` action (`enable_populated`), through the ever-populated record in `observations.py`, and polling since 3.4.4-dev2. Defaults are the one place a router's answers play no part unless the user runs the action.

**Why this is a different question from the one parked on 2026-09-02.** That decision weighed a per-entry default against the MC7010 and found it would suppress nothing: nine sensor descriptions read only empty keys, and all nine were already disabled by category. That holds for the reference device and says nothing about a model nobody owns. The basis here is compatibility for unseen models. Cleaner or lighter polling is not the aim.

**Constraints already recorded** (`divergence_review.md` §4.4, "open, not scheduled"): a key can read empty while the modem is initializing, so one poll must not suppress a working entity; a default can only be set when an entity is first created and never changes an existing one; and the evidence needs re-measurement and not latching. `entity_defaults.py` adds that being populated is not the criterion in either direction.

**Pitfalls already met in building the overlay and the populated record:** a boolean entity answers `False` from an empty payload; a derived value such as `enodeb_id` is filled when its source field is empty, which made an overlay disable a sensor that worked; 5G and secondary-carrier entities read blank while the router is on LTE; and an overlay seeded from a measurement went stale when the code changed what it did with that measurement.

**The config flow's fetch is not enough.** `config_flow.py:107-108` logs in and calls `get_all_data()` before any entity exists, but measured on 2026-10-15 it returns the core batch only, 118 keys against the poll's 283, and 44 working entities read blank in it. Evidence is therefore taken from the coordinator's full polls after setup and applied to the registry once (reference record §13.2, §14.2).

**Reference.** `.notes/info/entity_defaults/entity_defaults_for_unseen_models.md` holds the full research: the current mechanism read from the code, every recorded position and its source, the hardware evidence held for the MC7010 and MC888 Pro, the lessons, the options, the questions to settle, and the Huawei project's findings from 2026-10-07. That file is reference; this entry owns the work.

**Declared capabilities as one source.** Merged from _Device capabilities learned at setup_ on 2026-10-15. The device-specific `config.js` the device profile already reads declares capabilities such as `WIFI_SWITCH_SUPPORT`, `HAS_BATTERY` and `HAS_FOTA`; `device_profile.parse_device_config()` extracts them, but only after the first poll. Using them for defaults needs one extra read during setup, before the platforms load. On its own the gain is small, because the live readings of both supported routers already show which features exist; as one input beside the answers it separates capability from state, which the answers alone cannot.

**Huawei's design for the same problem.** `huawei_router_5g` has a layered design, not built and not agreed: `shared/ProjNotes/Notes-ha-huawei-router-5g-monitor/info/entity_defaults_and_polling_design.md`, with the task `tasks/per_model_entity_defaults.md`. The two are separate builds, because the projects differ in execution. Elements of that design to weigh here: fail open, so a layer with weak or missing evidence leaves the curated default in place; a capability rule only where two models agree, or limited to the model that showed it; a replay of every rule against each held download, with a mutation that must fail a test; value evidence taken through each description's own `value_fn` after derivations; and state-dependent groups (5G, carrier aggregation, SMS text, rates and counters) excluded from value evidence.

**Would be justified by:** a third model whose first-install defaults leave many entities `unknown`, or the overlay growing an entry per model. The owner's review of 2026-10-07 is done (reference record §13 and §14).

---

## Blocked

### Per-band and per-network Wi-Fi detail

#### **Value ⭐⭐ · Effort Medium once unblocked**

Wi-Fi Clients Connected and Wi-Fi Enabled report totals. The MC888 Pro also answers per-radio, per-network keys: `wifi_chip1_*` and `wifi_chip2_*`, most likely the 2.4 GHz and 5 GHz radios, each with `ssid1` and `ssid2`, the main and a second network, carrying clients connected, on or off, and the client limit. It answers `guest_switch` and mesh keys as well. From these, sensors for clients per band and each network's state would be possible, disabled by default.

**The keys are known from one router, through its diagnostics downloads.** Testing is the constraint: the reference MC7010 has no Wi-Fi, so nothing could be checked on hardware here, and every value's meaning would rest on a reporter's downloads.

**Blocked by:** no Wi-Fi router to test on. The reference MC7010 has no Wi-Fi, so the meaning of every key would rest on one reporter's downloads. Unblocked by a user who can supply downloads, or a second Wi-Fi model that answers the same keys. Nothing else depends on it.

### Encrypted SMS sending

#### **Value ⭐⭐ · Effort Medium once unblocked**

Newer MC888 and MC889 firmware is reported by another ZTE project to accept `SEND_SMS` only with the phone number and message encrypted, by RSA key exchange and AES-GCM. An MC888 Pro reporting to this project answers a send with success and keeps the message as a draft, which may be the same cause.

The first step is read-only: the device's own web scripts, which the device profile already reads, would show whether that firmware encrypts SMS. Code follows only if they do. **Detail is `.notes/info/other_zte_projects/recent_release_assessment_20260924.md`.**

**Blocked by:** no MC888 or MC889 on newer firmware to read or test against. The reference MC7010 sends SMS unencrypted. Unblocked by a device's web scripts showing SMS encryption, or a diagnostics download from an MC888 or MC889 whose sends are stored as drafts. Nothing else depends on it.

---

## Revisit

### "Refresh Now" always re-logs in

Not doing it. The button already logs back in whenever the router says the session has gone, so forcing a login on every press costs four round trips instead of one and buys nothing.

**Reopens if:** a silent logged-out fault is observed again — entities blank or `unknown` while the integration reports success. That observation would mean the cheap path is unreliable, at which point the cost objection stops mattering.

**Detail.** After the `[3.3.2-rc11]` session-detection rebuild, two mechanisms cover session loss with no gap: the proactive idle reset at 150s, and `_classify_session`, which reaches a verdict on every core poll — `test_every_batch_carries_both_classes` makes an undecidable verdict unreachable there. The argument in favour is insurance: Refresh Now is what a user presses when something looks wrong, so making it always work would survive detection breaking again. It was declined because that insurance works by masking — this fault has recurred twice and both times the damage was in the silence, so redundancy in the most-exercised path would hide a third occurrence rather than surface it. Full reasoning in `DEVELOPMENT.md` §5. If ever built: Refresh Now only, and the `not_ready` case must be preserved so a booting router still holds last known values.

---

## Declined

### Token persistence

Not doing it. Saving the login token to reuse after a restart means starting up with a token that may already be dead, and this router reports a dead token as a normal-looking empty response rather than an error. It saves one login per restart, in exchange for a class of bug that has already bitten twice.

**Detail.** The router permits one session at a time, and an HA restart is precisely when it is most likely to have moved on. The failure mode is not hypothetical — it is the class behind both the `[3.3.0-dev12]` SMS empty-inbox bug and the `[3.3.1-dev6]` silent-action failure.

### Band locking — write side

Not doing it. Locking the router to a band it cannot actually see kills the connection completely rather than degrading it, and the only version safe to leave unattended is one the router undoes by itself, which it cannot do.

**Detail.** An earlier revision justified this by claiming the control that undoes a bad lock is unreachable over the connection the lock breaks. That is wrong in the ordinary case: Home Assistant reaches the router at its **LAN** address, and a band lock kills the **WAN**. The undo stays available. Three objections survive and are sufficient:

- The failure is total and silent to automation — no service, not degraded service. Anything depending on that connection stops.
- It genuinely is unreachable for remote users, who reach Home Assistant over the same WAN and lose both the connection and the fix.
- It is a setting made once with a signal meter to hand, not something to script. Exposing it as an entity implies it is safe to automate.

The condition that would make it safe — a self-clearing lock that reverts if no data connection appears within _N_ seconds, enforced router-side — is not something this firmware offers, which is why this is Declined rather than Revisit.

**Where a user should go instead:** the router's own web page. It shows the current band and the alternatives in context, and is reachable on the LAN whether or not the WAN is up.

### Cell locking (PCI)

Not doing it. A cell is a smaller and more fragile target than a band — operators change cells with load and maintenance, so a lock that works today can leave the router with no service next week for reasons the user never sees.

**Detail.** `LTE_LOCK_CELL_SET` exists in the firmware and is deliberately not called. The router already reports `lte_pci` and `nr5g_pci`, which is where the diagnostic value is. For a genuine one-time pin, the router's own web page is the right place.

### Router operating mode (`OPERATION_MODE`)

Not doing it. This one really can strand the user: it changes the router's LAN role and addressing, which is the path Home Assistant reaches it over, so a bad change takes away the control that would undo it.

**Detail.** `opms_wan_mode` ships read-only, so the mode is visible without offering a switch that can cut the management path. This is the one declined write where the reachability objection genuinely applies.

### Projection accuracy from cycle history

Not doing it. `Projected Cycle Usage` extrapolates from the cycle in flight, so it is volatile in the first few days and settles as usage accumulates. Leaning on stored totals from earlier cycles would smooth those days, at the cost of a persistent cycle-history store, a fallback for a missing or corrupt store, and tests for both.

**Detail.** The entry's own trigger was early-cycle volatility causing a bad automation decision, and none has been reported. `helpers.project_cycle_usage()` keeps its `prior_rate` argument; the design is in `.notes/info/data_projection/data_cycle_and_projection_plan.md` §2.4 should the trigger ever occur.

### Reboot-on-degradation blueprint

Not doing it. The README automation example "Auto-Reboot on a Prolonged Outage" meets the need, and a blueprint would add packaging only.

**Detail.** The example carries the guards a blueprint would have locked in: a 30-minute trigger that ignores transitions from `unknown` and `unavailable`, conditions that the Data Connection switch is on and Integration Health is off, `mode: single` with a 10-minute hold after the reboot, and the reboot-loop and `manual_dial` warnings. The remaining benefit, use without copying YAML, does not justify a second artefact to maintain. Reconsidered only if users ask for a blueprint or the README example is shown to be copied incorrectly.

### DNS and static address binding

Not doing it. Both are network plumbing set once at installation, and neither belongs in a monitoring integration's entity list.

**Detail.** `ROUTER_DNS_SETTING` and `SET_BIND_STATIC_ADDRESS` were found by the same discovery run that surfaced the locking commands. Bad DNS breaks name resolution for every client on the network while leaving the router reachable — recoverable, but a foot-gun with no automation use case. The router's web page handles both.

---

## Summary

Forward work only. Declined and Revisit items are recorded above and are not work in progress.

| Item                             | Group | Value  | Effort |
| :------------------------------- | :---- | :----- | :----- |
| Billing-cycle write controls     | To Be Done | ⭐⭐⭐ | Low    |
| SMS feature-group toggle         | Maybe | ⭐⭐⭐ | Medium |
| Encrypted SMS sending            | Blocked | ⭐⭐   | Medium |
| Per-band Wi-Fi detail            | Blocked | ⭐⭐   | Medium |
| Entity defaults from router answers | Maybe | ⭐⭐ | Medium |

**Current state.** 132 entities across four sub-devices, 123 carrying `about` notes. 2129 tests, 100% coverage, `ruff` and `mypy --strict` clean, hassfest passing. Conformant across the 21 `dev_standards` sections.

---

## Done

Items that were on this roadmap and have since been built. Detail is in `CHANGELOG.md` and `docs/changelog_local.md`; this records only that the roadmap item was met.

| Item | Origin | Where it landed |
| :-- | :-- | :-- |
| **SMS management** | Original item | Four actions ship: `send_sms`, `delete_sms`, `delete_all_sms`, `get_sms_list`. Encoding is chosen per message — GSM-7 to 765 characters, Unicode to 335. |
| **Carrier aggregation metrics** | Original item | `wan_lte_ca`, `lte_ca_pcell_bandwidth`, `lte_ca_scell_bandwidth`, `nr5g_action_channel`. Shipped as a sensor, not the proposed binary sensor — the router reports the aggregation _configuration_, and an on/off would have discarded it. |
| **Data-usage projection** | Added 2026-07-29 | `Projected Cycle Usage` and `Reset Day` on the Data sub-device, cycle-relative rather than calendar-relative — the router's counters reset on its own billing day. |
| **Immediate refresh after a write** | Original item | Every write action routes through `async_force_refresh()`. The originally proposed `async_request_refresh()` would have been wrong: it is silently swallowed while Pause Polling is on. |
| **Cross-model verification** | Original item, merged 2026-08-01 | Three diagnostics downloads arrived from an MC888 Pro through issue #56. The README moved from an inferred compatibility claim to **Diagnostic Capture Verified** for that model, and the prize the entry predicted — keys another model populates that this integration does not poll — produced ten alias spellings in `[3.3.9-dev11]`. **MC889 remains unverified**: no download exists for it, and no hardware is reachable. Whether the ten aliases populate on the MC888 is confirmed by the next download rather than by this item. |
| **Band lock — read side** | Original item | `LTE Band Lock Mask` (`lte_band_lock`), disabled by default. `Network Mode Selection` covers the adjacent bearer preference. The write side is declined — see below. |
| **Long-term history for key text sensors** | Added 2026-09-02 | `[3.3.10-dev8]`. Both approaches the entry left open were built, because they answer different questions: a per-device store holds the last 20 transitions of six values as `timestamp`, `from`, `to` and `uptime_at_change`, surfaced as unrecorded attributes; six `TOTAL_INCREASING` counters put the same changes into long-term statistics, with **Firmware Changes** enabled by default. Tracks `wa_inner_version`, `wan_ipaddr`, `wan_apn`, `cell_id`, `network_provider` and `opms_wan_mode`. **eNodeB ID is deliberately not tracked**: it is derived from the cell identity, so a change of mast already appears in the `cell_id` history. |
| **Entity defaults matched to the router model** | Added 2026-08-01 | `[3.3.10-dev7]`, corrected at `[3.3.10-dev11]`. `entity_defaults.MODEL_OVERLAY` carries a per-model set matched as a family substring, longest first; `default_enabled` resolves it and both platform setup and the `reset_entities` action call that one function, so a reset cannot undo the overlay and an existing installation can adopt it. The MC888 entry disables five entities that firmware cannot fill and enables four it can. **Two departures from the entry as written**: the overlay enables as well as disables, because on that device RSSI and SINR are the only signal-quality figures it reports; and the list is curated rather than generated, the proposed regenerating test having been dropped as invalid — it would have re-derived the one stale entry that actually occurred, since the download shows `enodeb_id` empty and the derivation fills it. **Follow-on:** a default taken from the router's own answers for models with no overlay entry is the Maybe item _Entity defaults learned from the router's answers_. |

---

## Version Control

- **v3.14.0** (2026-10-15) - **Entity defaults learned from the router's answers and declarations**: approach documented from the feasibility checks (reference record §13 and §14): disable-only, new entries of unmeasured models only, settled full-poll evidence, an exclusion list; measured models untouched. The config flow's fetch measured as core-only and not used as evidence.
- **v3.13.0** (2026-10-15) - Merged **Device capabilities learned at setup** into **Entity defaults learned from the router's answers and declarations**: declared capabilities are one source of evidence for the same defaults. Cross-referenced the `huawei_router_5g` design for the same problem, built separately, and listed its elements to weigh. Corrected the research record's path. At the owner's direction.
- **v3.12.0** (2026-10-15) - Moved **Billing-cycle write controls** from Maybe to To Be Done, as the next build. Moved **Per-band and per-network Wi-Fi detail** and **Encrypted SMS sending** from Maybe to Blocked: each needs hardware this project does not have, the reference MC7010 having neither Wi-Fi nor SMS encryption. Both at the owner's direction.
- **v3.11.0** (2026-10-15) - Moved **Reboot-on-degradation blueprint** from Maybe to Declined, at the owner's direction: the README example "Auto-Reboot on a Prolonged Outage" meets the need with its guards, and a blueprint would add packaging only.
- **v3.10.0** (2026-10-07) - Added **Entity defaults learned from the router's answers** to Maybe, at the owner's request, as a review for compatibility with unseen router models. It differs from the 2026-09-02 decision in its basis: that decision asked whether the feature would suppress anything on the reference MC7010, and this one asks what an unmeasured model should start with. The research behind it, including the Huawei project's findings, is in `.notes/info/entity_defaults/entity_defaults_for_unseen_models.md`.
- **v3.9.1** (2026-09-30) - Current state updated to 132 entities across four sub-devices, 123 carrying `about` notes, and 2129 tests.
- **v3.9.0** (2026-09-25) - Added **Device capabilities learned at setup** to Maybe: the router's declared capabilities as a fallback for entity defaults, at the cost of one extra read during setup.
- **v3.8.0** (2026-09-25) - Added **Per-band and per-network Wi-Fi detail** to Maybe, from the Wi-Fi keys the MC888 Pro answers in its diagnostics downloads.
- **v3.7.0** (2026-09-24) - Added **Encrypted SMS sending** to Maybe, from the assessment of recent releases of two other ZTE projects.
- **v3.6.0** (2026-09-24) - Moved **Projection accuracy from cycle history** from Maybe to Declined. Its trigger, early-cycle volatility causing a bad automation decision, has not occurred, and the estimate settles within days on its own; a persistent cycle-history store and its failure handling are not justified by that.
- **v3.5.0** (2026-09-05) — Moved **Long-term history for key text sensors** and **Entity defaults matched to the router model** to Done, at `[3.3.10-dev8]` and `[3.3.10-dev7]`. The history item built both mechanisms its entry left open rather than choosing between them. The defaults item departs from its entry twice, both recorded in the Done row: the overlay enables as well as disables, and the regenerate-and-compare test the v3.3.0 entry proposed was dropped as invalid — its inputs are untracked, it assumes a list that is derivable where the criterion is judgement, and it would have reproduced the one stale entry that actually occurred.
- **v3.4.0** (2026-09-02) — **Cross-model verification moved to Done, and Custom triggers removed.** The verification item's blocker was a volunteer diagnostics download, and three arrived from an MC888 Pro through issue #56; both outcomes it named followed — the README compatibility claim became evidence-backed, and ten alias spellings shipped in `[3.3.9-dev11]`. Recorded with the MC889 gap stated, since no download exists for that model. **Blocked is now empty and its heading is removed**, per `roadmap_format.md` — an absent group means empty. **Custom triggers for `zte_router_5g_sms_received` is deleted rather than filed under a group.** It restated the blocker and the analysis pointer of the family-wide item at `.shared/issues/x_project/custom_trigger_options.md`, which carries a `zte_router_5g` cell and owns the work. Declined would have been untrue — nothing has been decided against — and the format has no group for an item another tracker owns, so the transfer is recorded here instead. **"Refresh Now" always re-logs in stays in Revisit.** Its trigger is a silent logged-out fault, which `roadmap_format.md` requires to be realistically achievable for Revisit rather than Declined; it has occurred twice, and every session fault found during 3.3.9 was a _false_ report of session loss, which re-logging in does not address.
- **v3.3.0** (2026-09-02) — Added **Entity defaults matched to the router model** to Maybe, after reading `Kajkac/ZTE-MC-Home-assistant-repo`'s per-model disable lists directly. Recorded with the measurement that argues against building it now: on the reference MC7010, nine sensor descriptions read only empty keys and all nine are already disabled by category, while no binary sensor, switch, select or number is both enabled and fed solely by empty keys — so the feature would currently suppress nothing. Entered as a Maybe rather than declined because the condition it addresses is real and unmeasurable on one device: it needs downloads from several models to be worth more than the category defaults. Notes the failure mode observed in the reference implementation, whose MC801A and MC888 lists are byte-identical and whose G5 Ultra list is derived from MC801A, and states that any version here would be generated from downloads and guarded by a regenerate-and-compare test.
- **v3.2.1** (2026-08-01) — Added a **Prior art** subsection to the text-sensor history item, recording that Home Assistant has no native mechanism and that the gap is recognized rather than obscure: long-term statistics are numeric-only by design, retention is global rather than per-entity, and the community workarounds (external time-series database, a blanket `purge_keep_days` rise, helper entities, `homeassistant-historical-sensor`) each fail this case for a stated reason. Includes the nuance that a helper's current value persists indefinitely while its history does not, flags the monotonic-counter idea as untested reasoning rather than observed practice, and notes the `update` entity domain as the nearest core concept. Dated so it does not get re-searched.
- **v3.2.0** (2026-08-01) — Added **Long-term history for key text sensors** to To Be Done. Long-term statistics only accept numeric sensors with a `state_class`, so `Firmware Version` and every other text sensor is capped at the recorder's retention window — ten days by default — and the record of a firmware change is gone by the time anyone asks what changed. Recorded as intended work with the mechanism explicitly undecided: a `.storage` store of transitions, or a monotonic `TOTAL_INCREASING` change counter that reaches LTS without the value needing to be ordinal. Notes that encoding the version string itself is a dead end, and that the store half is the same infrastructure the projection-history item needs.
- **v3.1.0** (2026-08-01) — **Cross-model verification merged with "Diagnostics-driven compatibility reporting" and moved to Blocked.** The two were one item: the diagnostics procedure existed only to feed the verification, and its own entry admitted it did nothing alone. Effort had been scored **Low**, which measured the work of editing a few alias tuples once data arrives rather than the difficulty of obtaining the data — and that difficulty is not effort at all. Neither MC888/MC889 hardware nor a volunteer diagnostics download is within this project's reach, so the item is Blocked with asking recorded as the only available action. Also recorded, after checking `DEVELOPMENT.md`, that **nothing is waiting on it**: the three speculative aliases and the five thermal keys are settled decisions to keep regardless, so confirmation is information rather than a trigger. The entry previously read as though work were pending on them. Summary table corrected — SMS feature-group toggle was listed as To Be Done while the body had moved it to Maybe.
- **v3.0.0** (2026-08-01) — Restructured to `roadmap_format.md` v1.0.0 and renamed from `docs/Future.md`. Six groups replace the previous mix of delivered / not-implemented / open-items / candidates, which had split forward work across two sections for historical reasons rather than useful ones. Every Declined and Revisit entry now opens with the decision in one plain sentence, with mechanism moved below it. Three declines that existed only inside Version Control paragraphs — `OPERATION_MODE`, `ROUTER_DNS_SETTING`, `SET_BIND_STATIC_ADDRESS` — are now entries in the body, since a decision recorded only in a changelog is a decision nobody will find. Framing that treated an earlier revision as a milestone ("delivered since the original roadmap") removed. Summary table no longer mixes declined items with work, and no longer sorts by short/medium/long term horizons that were never actually decided.
- **v2.5.0** (2026-08-01) — Added "Refresh Now always re-logs in" as a held contingency with a defined trigger rather than an open proposal.
- **v2.4.0** (2026-07-29) — Corrected the reasoning behind the declined write controls. All had been justified by a single claim: that the integration reaches the router over the connection the change breaks. **That holds only for `OPERATION_MODE`** — Home Assistant talks to the router at its LAN address, so a band lock, a cell lock or bad DNS kills the WAN and leaves the management path intact. The declines stand, on three distinct grounds now stated per command.
- **v2.3.0** (2026-07-29) — Billing-cycle write controls rescoped. The feared blocker — a partial POST clearing the user's data cap — does not exist; the router refuses an incomplete form. The read-modify-write path is built and verified, and the same work fixed a Data Limit Switch that had never worked. Effort dropped Medium → Low.
- **v2.2.0** (2026-07-29) — Data-usage projection delivered. Two candidates added in its place, both carved out of the same work. `OPERATION_MODE`, `LTE_LOCK_CELL_SET`, `ROUTER_DNS_SETTING` and `SET_BIND_STATIC_ADDRESS` found by the same discovery run and declined.
- **v2.1.0** (2026-07-29) — Removed the proposed signal-quality history sensor: Home Assistant's Statistics helper already produces a rolling mean with no code, and there is no sound formula for a single combined quality score. Replaced by a "Reading Your Signal Data" section in `README.md`. Removed the config-entry migration handler row (a `DEVELOPMENT.md` tripwire, not roadmap work) and the thermal-sensor row.
- **v2.0.0** (2026-07-29) — Rewritten after review against the live instance. Three of four original priorities found delivered. Token persistence declined with reasoning rather than left open. Band and cell locking re-scoped. Corrected a stale claim of compliance with "PlayFaster v1.2 standards".
- **v1.0.0** (2026-05) — First roadmap.
