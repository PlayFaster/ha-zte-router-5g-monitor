# Roadmap: ZTE Router 5G Monitor

Forward view for `ha-zte-router-5g-monitor`, and the record of what has been decided against. The integration is feature-complete for its core purpose — monitoring, SMS, data-usage tracking and a small set of safe controls. Most of what remains is either verification work on hardware nobody has tested, or write controls that have been considered and declined.

Format document `roadmap_format.md` used.

**Reviewed 2026-08-01** against the running instance (92 entities) and the current source.

---

## To Be Done

### Long-term history for key text sensors

#### **Value ⭐⭐⭐ · Effort Medium**

**The mechanism is undecided. The need is not.**

Long-term statistics only accept numeric sensors carrying a `state_class`, so every text sensor here is limited to the recorder's retention window — ten days by default. **Firmware Version** is the case that matters: a firmware change is exactly the event you want to look back at months later, when the router starts behaving differently and the question is _what changed, and when_. The `Firmware Change Notification` automation fires at the moment it happens, but nothing retains the record once history rolls off.

Other candidates once a mechanism exists: `Network Provider`, `Network APN`, `Cell ID`, `eNodeB ID`, `WAN IP Address`.

Two approaches, neither yet chosen:

- **A store in `.storage`** holding a bounded list of `(timestamp, from, to)` transitions, surfaced as attributes on the existing sensor. Keeps the record exact and human-readable. Costs a `Store`, a size cap, and a decision about what happens on entry removal.
- **A numeric companion that does reach LTS.** Encoding the version string itself is a dead end — firmware strings are not reliably ordinal, and a hash graphs as noise. A **monotonic change counter** works instead: a `TOTAL_INCREASING` sensor incremented whenever the string changes. It answers "when did it change" from the statistics timestamp without the value needing to mean anything, at the cost of not recording _what_ it changed to.

The two are not exclusive — the counter gives a durable timeline, the store gives the detail behind it.

**Worth knowing:** the `.storage` half is the same infrastructure the **Projection accuracy from cycle history** item needs — Phase 4 of `.notes/info/data_cycle_and_projection_plan.md`. Neither exists yet. Whichever is built first should be built to serve both rather than as a one-off.

#### Prior art — there is no native mechanism

Checked 2026-08-01, so it does not need re-searching. **Home Assistant has nothing that solves this**, and the gap is recognized rather than obscure:

- **Long-term statistics are numeric-only by design.** Only `state_class` of `measurement`, `total` or `total_increasing` produces LTS rows. An open architecture discussion asks for binary sensors to be included, which confirms they are not; text sensors are further out still. ([architecture #1268](https://github.com/home-assistant/architecture/discussions/1268))
- **Retention is global, not per-entity.** Raising `purge_keep_days` for one sensor means raising it for every sensor. Per-entity retention is a standing request, not a feature.

What the community does instead, none of it a clean fit:

| Approach | Why it does not settle this |
| :-- | :-- |
| **External time-series database** — InfluxDB, Prometheus, long-retention MariaDB | The usual answer, and it does keep strings. The data leaves Home Assistant's own history UI, which is where a user would look. |
| **Raise `purge_keep_days` globally** | Grows the whole database to preserve one string. |
| **A helper written by an automation** (`input_text`, `input_datetime`, `counter`) | Closest native option, with a nuance that matters: the helper's **current value** persists in `.storage` indefinitely and survives restarts, but its **state history** is purged like anything else. Good for "the last change and when"; no use for a multi-year list. |
| **`homeassistant-historical-sensor`** | A custom component that writes directly into the statistics tables. Real precedent for the idea, but built for numeric series. |

Two notes on confidence. The **monotonic counter** described above is reasoning from how LTS works, **not an observed community pattern** — no evidence was found of anyone doing it, so treat it as untested. And Home Assistant's **`update` entity domain** models `installed_version` / `latest_version`, which is the nearest core concept to firmware tracking; it carries no history either, so it does not solve this, but it is the domain core would expect if firmware ever became a first-class concern here.

### Billing-cycle write controls

#### **Value ⭐⭐⭐ · Effort Low**

The hard part is done. `DATA_LIMIT_SETTING` is confirmed as a six-field, all-or-nothing form, `api.set_data_volume_settings()` performs the read-modify-write, and the round trip is verified on hardware. The same work fixed a Data Limit Switch that had never functioned, because it was sending exactly the partial payload the router refuses.

Two entities remain on the Data sub-device:

- a **Number** for the reset day (1–31), writing `traffic_clear_date`
- a **Switch** for `wan_auto_clear_flow_data_switch`, which decides whether monthly counters roll over at all

Both keys are already polled, and the switch already drives the projection sensor's suppression logic. Neither has a user-facing control. **Design detail — the entity inventory, the write path and its risks — is `.notes/info/data_cycle_and_projection_plan.md` §8 and §2.2.** That file is reference; this entry owns the work.

**Both ship disabled by default**, matching the existing Data Limit Switch. Changing the reset day moves the boundary that the projection sensor and every data-cap automation reason about — not dangerous, but not a display setting either.

---

## Maybe

### SMS feature-group toggle

#### **Value ⭐⭐⭐ · Effort Medium**

Two of the three polled endpoints exist solely for SMS, so a user who never sends one still pays two round trips per cycle. Disabling the sub-device hides the entities without stopping the polling.

Needs a `CONF_ENABLE_SMS` option, guards on both `_fetch_optional` calls, and an exclusion in `_degraded_endpoints()` — without the last, Integration Health reports "degraded" for a capability the user deliberately switched off. `dev_standards` §15.

### Entity defaults matched to the router model

#### **Value ⭐⭐ · Effort Medium**

Every model answers a different subset of the parameter set, so a user sees entities their hardware never populates. Today the defaults are chosen by category — 28 diagnostic entities ship disabled regardless of model — and a per-model list would instead disable the entities that model is known to leave empty.

Measured on the reference MC7010: 40 of 137 requested keys are empty, nine sensor descriptions read only empty keys, and all nine are already disabled by default. Across binary sensors, switches, selects and numbers, the count of enabled entities whose keys are all empty is zero. On the one device that can be measured today, this would suppress nothing.

The lists would be curated from diagnostics downloads rather than measured at runtime, so they carry none of the hazards of runtime suppression — no key read empty while the modem is still initialising, no altering an entity that already exists. Unknown hardware keeps the category defaults. It only makes sense once downloads are held for several models, since a list built from one device is the category system with extra steps. `Kajkac/ZTE-MC-Home-assistant-repo` implements the per-model form and shows the failure mode: its MC801A and MC888 lists are byte-identical and its G5 Ultra list is derived from MC801A, so three of four models share one list that nobody has revisited. Any version here would be generated from the downloads and checked by a test that regenerates and compares, so a stale list fails rather than persists.

**Would be justified by:** downloads from several models showing enabled entities that stay empty on that hardware. Comparison detail is `.notes/info/other_zte_projects/divergence_review.md` §4.4.

### Reboot-on-degradation blueprint

#### **Value ⭐⭐ · Effort Low**

The README carries an auto-reboot example with the necessary glitch guards. A shipped blueprint would make it usable without copying YAML, and would put those guards beyond reach of a copy-paste error.

**Would be justified by:** anyone asking for it, or evidence that the README example is being copied incorrectly. Blueprints are supported well below the current HA floor, so nothing blocks it.

### Projection accuracy from cycle history

#### **Value ⭐⭐ · Effort Medium**

`Projected Cycle Usage` extrapolates from the cycle in flight alone, which is why it is volatile in the first few days. Storing the previous two or three cycle totals would let the estimate lean on them early and shed them as real usage accumulates — blended into the **unobserved remainder** only, so the prior's influence decays with the days remaining rather than needing a tuned constant.

`helpers.project_cycle_usage()` already accepts a `prior_rate` argument. What is missing is the store. **Design detail is `.notes/info/data_cycle_and_projection_plan.md` §2.4**; that file is reference and this entry owns the work.

**Would be justified by:** the early-cycle volatility actually causing a bad automation decision. It is a known cosmetic weakness until then.

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

### DNS and static address binding

Not doing it. Both are network plumbing set once at installation, and neither belongs in a monitoring integration's entity list.

**Detail.** `ROUTER_DNS_SETTING` and `SET_BIND_STATIC_ADDRESS` were found by the same discovery run that surfaced the locking commands. Bad DNS breaks name resolution for every client on the network while leaving the router reachable — recoverable, but a foot-gun with no automation use case. The router's web page handles both.

---

## Summary

Forward work only. Declined and Revisit items are recorded above and are not work in progress.

| Item                               | Group      | Value  | Effort |
| :--------------------------------- | :--------- | :----- | :----- |
| Billing-cycle write controls       | To Be Done | ⭐⭐⭐ | Low    |
| Long-term history for text sensors | To Be Done | ⭐⭐⭐ | Medium |
| SMS feature-group toggle           | Maybe      | ⭐⭐⭐ | Medium |
| Projection accuracy from history   | Maybe      | ⭐⭐   | Medium |
| Entity defaults matched to model   | Maybe      | ⭐⭐   | Medium |
| Reboot-on-degradation blueprint    | Maybe      | ⭐⭐   | Low    |

**Current state.** 92 entities across four sub-devices, 86 carrying `about` notes. 817 tests, 100% coverage, `ruff` and `mypy --strict` clean, hassfest passing. Conformant across the 21 `dev_standards` sections.

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

---

## Version Control

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
