# Internal Detailed Changelog: ZTE Router 5G Monitor

All notable changes to this project will be documented in this file.

---

## [3.3.2] - 2026-08-01 - Release

### Summary

Wider router support, better data use tracking, SMS improvements, several fixes and a lot of under the hood improvements in this release.

- **Data usage tracking**: the router's own billing cycle, data cap and alert threshold now appear as entities, alongside a new projection of where the current cycle will finish.

- **Wider ZTE model support**: should now have better support for the wider family of ZTE 5G/LTE Routers that use the `goform` API.
  - MC7010, MC801, MC888, MC889, MF266, MF286, MF289

- **SMS improvements**: send the same long messages the router's own web page allows.

- **Action & Settings Fixes**: Fixed issues where Actions (SMS read or send etc.) and Settings Changes (APN, Data Limit switch etc.) could fail silently on long polling intervals.

- **`about` attribute**: Most entities now carry a short built-in explanation of what the value means — and for signal metrics, what counts as good, fair or poor.

- **Integration Health** problem sensor: tells you when the integration is running but the data coming back from the router has issues.

### Added

- **Data usage tracking follows your router's Data Management settings.** If you enable **Data Management** in the router's web page, you can set a **Clear Date** matching your provider's billing day, a **Data Plan** cap, and a **limit reminder** percentage. Those three settings now appear in Home Assistant as **Reset Day**, **Allowance** and **Alert Threshold**. Data use automations can use your router plan numbers — the README has a worked example. Note the router counts in binary units, so a plan it calls "2TB" shows here as about 2199 GB: the same amount, counted the way Home Assistant counts. If you have not set Data Management on the router, the integration falls back to the calendar month.
  - Alongside these, a new **Projected Cycle Usage** sensor estimates how much data you will have used by the end of the cycle, based on your average daily consumption so far. It follows whichever cycle applies — the router's or the calendar month — and reads low on the first day before settling within 24 hours. Its attributes say how much of the figure rests on real usage rather than assumption: `confidence`, `basis`, `cycle_day`, `cycle_start` and `cycle_source`.

- **Integration Health sensor**: a new problem binary sensor on the System device that turns on when the integration detects a problem — including the case where a fetch _succeeds_ but returns nothing usable (which can otherwise be a silent fail, unless you are watching the entities closely). Attributes carry the detail: `issues`, `severity`, `degraded_capabilities`, `drift`, `repairs`, `last_good_update` and `consecutive_failures`.

- **Built-in explanations on entities**: most entities now carry an `about` attribute — a plain sentence saying what the value is. Click the entity, then **⋮ → Details**. Signal metrics also give typical ranges ("better than -80 excellent, -80 to -90 good…"). The note is never written to the history database, to avoid bloat.

- **Router Unreachable repair**: after multiple consecutive failed fetches, a repair appears in the Repairs panel.

- **Seven new entities**, all **disabled by default**: Carrier Aggregation Secondary Cells, WAN Operating Mode, WAN Fallback Mode, Router Timezone, APN Interface Version, Web Page Sleep and Web Page Auto-Wake.
  - This is part of _completeness_. These are included because they are available, and may be of use to some, not necessarily because they contain critical info.

### Changed

- **Longer SMS messages**: `send_sms` now accepts the same message length the router's own web page does — up to **765** characters, where the integration previously capped you at 160. A message containing an emoji, curly quote or other special character uses a different encoding and is limited to **335**, again matching the router. The limit is chosen automatically per message, with nothing to configure, and going over it gives a clear error naming the limit that applied.
  - **Obligatory Warning**: It is _**YOUR**_ responsibility to understand whether having your Router send SMS messages is going to incur an extra charge from your ISP.
    - Remember **longer** messages generally get **billed** as multiple SMS.

- **Wider ZTE model support**: signal and data-usage sensors now recognize the alternative field names used by other `goform` routers, the login falls back to the other form when a model rejects the first, and the LTE/5G band name is worked out from the channel number when the router leaves it blank.

- **Attributes are not written to history**: no entity in this integration records any attribute to the database — only its state. The current state of all Attributes stay visible in the More Info dialog, Developer Tools and templates.

- **Documentation**: the README's example automations now ignore `unknown` and `unavailable` states, to avoid false alerts from a HA restart or router reboot.

- **Icons and branding** refreshed.

### Fixed

- **APN Profile could show a profile that was not in use**: while APN Selection Mode is **Auto** the router uses the routers default APN — but the dropdown still displayed whichever profile was last chosen **manually**. It now shows the profile only when it genuinely matches the APN in use, and blank otherwise. The **Network APN** sensor remains the authoritative answer to which APN is in use.

- **APN Selection Mode could not be set to Manual**: switching it to **Auto** worked, but switching back to **Manual** was silently rejected by the router.
  - Both directions now work. Switching to **Manual** requires the router to be told _which_ stored profile to use, so if the APN currently in use is not one of your saved profiles, the integration asks you to choose one from **APN Profile** instead — which sets the mode and the profile together, in one step.
  - The integration can only **select** among profiles already stored on the router. Creating, editing or deleting an APN profile is done on the router's own web page; a new one appears in the **APN Profile** dropdown at the next poll, or immediately if you press **Refresh Now**.

- **Settings & Actions did not check for login**: If the polling interval was long, Pause Polling was on or the web GUI was used, the integrations login to the router could get dropped.
  - It re-establishes on every new read, but independent activities, e.g. changing settings or running actions, were not properly checking for an active login.
  - This, coupled with problems with some of the setting writes, could result in silent failures and unpredictable behavior.
  - This was also an issue immediately after Router reboot, as that also logged out active sessions.
  - Now addressed across all Actions and Writes (Settings changes), and for Router reboots.

- **Actions Fixes**:
  - re-login if the session has expired
  - confirm the router's action response
  - provide an error message if there is an error
  - update the message counters on SMS send immediately

- **Settings Fixes**:
  - **Data Limit Switch**: This always read the correct state but could fail to set the state, now fixed.
  - **ODU LED Switch**: Could show incorrect state and invalid toggles temporarily after trying to change. Now fixed.
  - **APN Prole & Mode**: Also fixed, see above.

- **Monthly Data counters misclassified**: the monthly upload, download and total sensors were recorded state_class=TOTAL, which is incorrect and can cause issues on reset. This has now been corrected to TOTAL_INCREASING - a resetting counter.

---

## [3.3.2-rc11] - 2026-07-31 - Unreleased - No Manifest Bump - Session Detection Rebuilt On A Measured Invariant

### Bumps

- **Shared CI**: Bump `.github` Shared CI Validation via SHA from v2.0.7 to v2.0.8
- **Validate Bump**: Update PHACC `pytest-homeassistant-custom-component` from 0.13.349 to 0.13.350

### Summary

The reported fault — many entities going `unknown` for up to a minute after a reboot or an APN change — was investigated on hardware and turned out to be neither transient nor a fetch failure. It was a _successful_ fetch of a dead session, and it had silently disabled two detectors.

### The fault, as measured

Two instrumented reboots plus a direct probe with an invalidated `stok` (MC7010, firmware `V1.0.0B03`, 2026-07-31):

- A dead session leaves **3 of 80 core keys populated** (`imei`, `model_name`, `wa_inner_version`) and **2 of 36 extended keys** (`opms_wan_mode`, `opms_wan_auto_mode`). These answer without authentication.
- The expiry rule was `all(value == "" for value in resp_json.values())`. With those keys in the batch, that condition **cannot be true**, so neither batch poll could ever detect an expired session.
- Consequence: the poll was scored a clean success, `consecutive_failures` reset to zero, the health sensor stayed green, nothing was logged, and every sensor fed by a blanked key resolved to `None` and published `unknown`.
- **There is no self-recovery on this path.** The observed run held 52 blanked keys for 130 s and was still blank when the watch ended. Recovery in normal use comes from something incidental re-authenticating — a write via `_ensure_session`, or an SMS endpoint whose response genuinely is all-empty and does trip the rule.

Two things had been masking it. Normal polling is covered by `SESSION_IDLE_RESET_SECONDS = 150`: at the 180 s default interval every scheduled poll already re-logs in preemptively, so the reactive detector is never needed. And **Refresh Now does not re-authenticate** — it re-publishes the blank payload, which is why pressing it repeatedly made the symptom worse rather than better.

The same three keys had also disabled `_check_contract_drift`: `wa_inner_version` sat in `CORE_KEYS`, so `present` was never empty, `_drift_strikes` reset every cycle, and the check could not fire under any circumstances — including the firmware change it exists to catch.

### Changed — the rule now tests a relationship, not a total

`_classify_session` reads a `200 OK` response as two classes of key and returns one of four verdicts:

| verdict | condition | response |
| --- | --- | --- |
| `live` | any authenticated key populated | proceed |
| `expired` | authenticated all blank, unauthenticated populated | re-login and retry |
| `not_ready` | everything blank | `ZTEConnectionError` — hold last known values |
| `undecidable` | no unauthenticated key requested | fall back to the previous all-empty rule |

`not_ready` is new and matters: a router that is answering but has nothing to report yet is booting, not expired. Re-logging in would not help, so it takes the reachability path instead of burning a login and heading toward a reauth prompt.

The project owner's framing drove this. The device separates the two states cleanly — unauthenticated keys prove reachability, authenticated keys prove the session — and deciding from the _relationship_ between them removes the fragility that caused both recurrences. The old rule was a property of **what was requested**, not of the session, so it silently stopped being a valid test the moment the batch composition changed. Nothing could notice, because the rule had no stated precondition.

### Changed — a rejected password is no longer confused with a lapsed session

`ZTECredentialsError`, a subclass of `ZTEAuthError`, is raised only when the router rejects the password. The coordinator raises `ConfigEntryAuthFailed` for that alone; a session that merely lapsed now raises `UpdateFailed`.

Without this, fixing the detection would have introduced a new fault: three lapsed sessions in a row would have told the user their credentials were wrong and sent them to re-enter a password that was never the problem. The subclass keeps every existing `except ZTEAuthError` handler working, including the config flow's.

Confirmed with the project owner and material to the design: on this router **the most recent login wins**. HA logging in takes the session back from the web GUI, which ends the web session with an on-screen notice. There is therefore no state in which HA is reachable but permanently unable to authenticate.

### Added — the test that stops this recurring

`tests/test_session_detection.py`, 16 tests. The load-bearing one is `test_every_batch_carries_both_classes`, which fails if a batch edit leaves either class unrepresented — the precondition the rule needs and never had. Also `test_contract_keys_all_require_a_session`, which fails if an unauthenticated key is put back into `CORE_KEYS`.

All three fixes were mutation-proved by reverting them in turn:

- old all-empty rule restored → `test_expired_session_triggers_a_relogin` fails
- `wa_inner_version` returned to `CORE_KEYS` → `test_contract_keys_all_require_a_session` and `test_drift_can_now_fire` fail
- `opms_` keys dropped from the unauthenticated set → `test_every_batch_carries_both_classes[extended]` fails

`test_init.py`'s reauth test was rewritten as a parametrized pair covering both branches. It had asserted the old behavior, so it correctly failed on the change.

### Changed — attended `[G]` now watches the recovery

The reboot step took a baseline, rebooted, and waited for the router to answer. Answering only proves it is powered, and the bug lived entirely inside successful responses, so waiting could never have found it.

`[G]` now takes a settled baseline of which core keys carry values, then polls the recovery and scores each response against it. A `LOST` line means a poll succeeded while normally-populated keys were blank — the signature of the detection being defeated again, most likely by a firmware change to which keys need a session. This is the only instrument that can catch that: a mock is written from our model of the device, and this model was wrong for the life of the release.

`scripts/observe_recovery.py`, written to investigate this, was folded into `[G]` and deleted rather than left as a second reboot path to maintain.

### Known — not addressed here

Polling intervals below 150 s stop the preemptive idle reset firing on every cycle, which is what covered this fault in normal operation. That is now safe because detection works, but it is worth recording that the two settings interact.

## [3.3.2-rc10] - 2026-07-31 - Unreleased - No Manifest Bump - Sensor Review; APN Documentation Completed

`sensor_review` (SOURCE=Via_HAB, SCOPE=Full) reconciled the whole inventory, and the APN behavior documented across rc7-rc9 was completed with the half that was missing.

### Verified — `sensor_review`, full run

Report: `.notes/sensors_states/ha_sensor_review_20260731_0320.md`.

- **The entity inventory reconciles exactly in both directions**: 92 live, 92 documented, and the per-sub-device split matches the README table row for row (System 33, Signal 40, Data 15, SMS 4). Categories A, B, C, E, F, G, H all clean; 4 services live and documented.
- **A restart was used, not a config-entry reload.** Code changed during this session, and a reload re-serves cached modules — the fetch would have faithfully reported the state before the change, with nothing erroring. Confirmed effective: the rewritten `Network APN` note appeared in the live fetch.
- **Category D**: 19 entities report `unknown`, 18 already annotated or expected. The two buttons were deliberately **not** flagged — a button has no state until pressed, and an availability note there would be wrong. The one finding, `Recent Msg`, was **not** actioned: `unknown` with an empty inbox is the correct reading.
- **No delivery faults.** Every documented `about` note reaches the user; nothing is declared in code and dropped in delivery.
- The 34 temporarily-enabled entities were restored to disabled and verified twice — live list back to 58, registry at 92 registered / 34 disabled.

### Changed

- **`about_attribute_list.md` v1.4.0.** The four notes rewritten in code during rc7-rc9 refreshed here: the three APN/network selects and `Network APN`.
- **`ODU LED Switch` gains a note** (code and inventory), moving out of the deliberate-omission list. Coverage **85 → 86 of 92**, omissions 7 → 6. It was self-explanatory when that list was drawn up; it is now a control whose position is confirmed by reading the router back, and the note says so — the switch reflects the unit, not the last command sent.

### Added — the missing half of the APN documentation

The project owner asked whether adding an APN is documented as a router-web-page action. It was not, anywhere. Verified against the code: the only `apn_action` used is `set_default`, so the integration can **select** among stored profiles and cannot create, edit or delete one. The dropdown is built from `APN_config0-9` in the core poll, so a profile added on the router appears at the next poll or on **Refresh Now**; the router holds ten.

- **`CHANGELOG.md`** — the `APN Selection Mode` entry said "Both directions now work directly", which is true on the reference router only because a duplicate of the network default was added there by hand. On a stock router, switching to Manual is **refused** with guidance, because the router will not accept a mode change that does not name a profile. Amended to state the condition and the add-a-profile route.
- **`README.md`** — the same two facts stated plainly in the APN section, ahead of the existing tip.
- **`about` note on `APN Profile`** — one clause: new profiles are added on the router's own web page, not here. Inventory updated in the same pass, so no drift was introduced.

### Known — deliberately left

`all_sensors.md`'s `About` column reads 85 ✔ and now understates by one; `ODU LED Switch` should be ✔. Left as-is by decision rather than oversight, and recorded here so the next `sensor_review` run reads it as known rather than as fresh drift.

## [3.3.2-rc9] - 2026-07-31 - Unreleased - No Manifest Bump - Attended Tier Completed; Two Self-Inflicted Defects

All eleven write commands are now either exercised on hardware or locked against silent change. Getting there produced two defects of my own making, both caught by running the thing rather than by any test.

### Added

- **`tests/test_write_payload_shapes.py`** — a payload shape lock over all eleven writes. A **change detector, not a correctness check**: it cannot tell you a shape is right, it makes any change to one visible and deliberate. That is the gap left by commands no script may exercise unattended.
  - **Mutation-proved three ways**: dropping `encode_type` from `send_sms`, dropping a field from the six-field data-volume form, and changing `delete_all`'s `;` id separator each fail the suite.
  - Asserts the **set**, not membership — every defect of this class has been a _missing_ field, which `in` cannot see.
  - Cross-checked against the classification register, so a command cannot be classified but left unlocked.

- **Four attended checks**, taking scripted coverage from 4 writes to 8: `send_sms`, `delete_sms` (newest message), `delete_all`, and `reboot`. Ordered send → delete one → delete all → reboot, since reboot ends the session.
  - `send_sms` takes the destination **at the prompt** — never stored, never echoed, only its character count printed. A phone number in a committed script or a `.reports/` log is exactly the personal data that should not be lying around.
  - `delete_sms` prints **id and timestamp only**; sender and body are withheld because the run is teed to a log file.
  - `delete_all` states the **message count** in the prompt. "Yes" to an unspecified number is not informed consent, and that is the whole safeguard.
  - `reboot` verifies by **uptime going backwards**, not by the router answering — a device that never rebooted also answers.

### Changed

- **Tier renamed `NEVER` → `NEVER_AUTOMATED`, and it is now empty.** The old name conflated _cannot be automated_ with _cannot be scripted at all_. With a person supplying the target and confirming, sending and deleting an SMS are ordinary tests. The tier stays defined so the decision point exists for a future command that genuinely warrants it. The project owner made this argument; it was right.
- **README**: network-mode values as a table with their web-UI names, and a new **How do I download diagnostics?** section modelled on the `unifi_network_monitor` one — including the note that a diagnostics file from a non-MC7010 model is valuable even when nothing is wrong, since cross-model support is inferred rather than tested.

### Fixed — a false dead-session detection I introduced this session

- **A targeted read of legitimately empty keys was mistaken for an expired session.** `sms_nv_send_total` and `sms_nv_total` are empty on the reference MC7010, so reading just those two produced an all-empty response — the exact dead-session signature — causing a spurious re-login and a `ZTEAuthError` on a healthy session.
  - The rule was written when every read was a 75-key poll, where something is always populated. **The targeted reads added earlier this session broke that assumption**, and nothing asked whether the rule still held.
  - `get_params()` now always appends a **sentinel key** (`wan_connect_status`, a contract key populated whenever the session is alive), so an all-empty response still distinguishes "these fields are empty" from "this session is gone".
  - Verified on hardware both ways: the empty-counter read now succeeds, and a genuinely dead session still raises. Mutation-proved — removing the sentinel fails the suite.
  - Latent elsewhere: the switch read-back would have hit this if a control's key were ever empty. Harmless there (a failed verify is treated as _unverified_), but it would have caused needless re-logins.

### Fixed — a reasoning failure, recorded because it is the third of its kind

- **`send_sms` reported a successful send as a failure**, twice over.
  - The narrow bug: the check read the counters from the **batch poll**, where those keys are empty, instead of `sms_capacity_info`, where they are populated. `0 -> 0` forever.
  - The real error: I probed the message list, saw zero, and concluded **"this model does not retain sent messages"** — writing it into a code comment as fact. The inbox was empty **because `delete_all` had just emptied it**. I measured a state I had created and generalized it into a property of the hardware.
  - Corrected by the project owner, who had the sent message in front of him. The router does retain sent messages (`tag=2`, against `tag=1` for received) and `sms_nv_send_total` does increment.
  - The check now takes two independent confirmations — counter increment via `sms_capacity_info`, plus a new `tag=2` message — and treats the absence of either as **unverified, not failed**.
  - This is the third time this session a plausible mechanism was written down as established: after `RD` rotation and the first `set_apn_mode` explanation. **`dev_standards` §11 already forbids it** — "record what was measured and stop there" — and it was written hours before this happened. The rule is right; following it is the hard part.

### State

All eleven writes: **8 exercised on hardware**, 3 covered by real-world use, **11 locked** against payload change. 800 tests, 100% coverage, `mypy --strict` clean.

## [3.3.2-rc8] - 2026-07-31 - Unreleased - No Manifest Bump - APN Resolution Corrected; Attended Tier Completed

The rc7 fix introduced a hazard, caught before release by the project owner's description of how the router actually behaves. All four scriptable ATTENDED writes are now exercised on hardware.

### Fixed — a hazard introduced by the previous entry

- **`set_apn_mode` resolved the profile from `apn_index`, which is meaningless in auto mode.** Observed live: `apn_mode=auto`, `apn_index=5` (`open.internet.public`), traffic running over `3FWA.ie` — profile 6. Switching to manual would have activated a **different APN than the one working**. That is worse than the refusal rc7 set out to fix, and it existed for about an hour.
  - `_resolve_apn_profile()` now matches `wan_apn` (the authoritative value) against each profile's APN field, case insensitively.
  - Falls back to `apn_index` **only while already manual**, where it genuinely is the selection — the branch that makes the `Default` profile work, since its empty APN leaves `wan_apn` blank.
  - Otherwise **refuses**, pointing at the APN Profile selector. The network default need not exist in the manual list at all; on the reference device it does only because a duplicate profile was added by hand. There is no honest automatic answer, so it does not invent one.
  - **Verified on hardware**: the attended run resolved to slot 6, not the stale 5.

- **The APN Profile selector displayed a profile that was not in use.** In auto mode it reported whatever `apn_index` held. It now matches `wan_apn` and returns nothing when no stored profile corresponds, which is the normal case.

### Changed

- **`about` notes rewritten for all three selects**, recording behavior that reads as broken otherwise: choosing a profile also switches the mode to manual; in auto the list may not contain the APN in use and `Network APN` is authoritative; the `Default` profile stores an empty APN so `Network APN` goes blank; and the network-mode values carry their web-UI names (`4G_AND_5G` = Auto, `LTE_AND_5G` = 5G NSA, `Only_5G` = 5G SA, `Only_LTE` = 4G Only) — **reported by the project owner**, not verifiable from the API.

### Fixed — the hardware script's own defects, both exposed by running it

- **The restore did not survive the reconnect it had just caused.** It reported `restored — Request failed` while the router had in fact already gone back to auto. Restore now **reads the current value first** and only re-writes if the router still disagrees, then retries through the reconnect. On this API a write reported as failed may well have landed, so what the router says _now_ is the only trustworthy question.
- **One failing check aborted the whole run** — worst in the one place it must not, after a write had changed something and before its restore. Each attended check is now wrapped so a failure is recorded and the rest continue.

### Added — attended coverage completed

- **`set_apn`** round-trips between two stored profiles, verifying against `wan_apn` rather than `apn_index`, and restores the selection mode afterwards because `set_apn` forces manual as a side effect. The `Default` profile is skipped as a target, since its empty APN makes verification meaningless. **Passed**: `3fwa.ie` → `3broadband.ie` → `3fwa.ie`, mode restored to auto.
- **`set_data_limit_switch`** round-trips the cap, and **only from ON**. Starting from on, the risky direction is merely restoring what was there, and a crash leaves the cap off — harmless. Starting from off, the same round trip would switch enforcement _on_ and a crash could strand it, against a cap and usage figure only the owner can judge; that direction is refused rather than offered with a warning. **Passed**: on → off → on. This is the switch that had never worked in any release.
- `reboot` remains classified ATTENDED and deliberately unscripted.

### Verified state after all exercises

`apn_mode=auto`, `wan_apn=3FWA.ie`, `net_select=4G_AND_5G`, all six data-volume fields at their original values, `ppp_connected`. Checked independently of the script.

## [3.3.2-rc7] - 2026-07-31 - Unreleased - No Manifest Bump - `APN_PROC_EX` Partial-Form Defect

Found by the attended tier on its **first real run**, one prompt in. A defect the safe tier structurally could not reach.

### Fixed

- **`set_apn_mode()` sent a payload the router refuses, for the manual direction, in every release.** Established by replaying payloads against the value already set, so acceptance was tested without changing anything:
  - `apn_mode=manual` — refused
  - `apn_mode=manual&apn_action=set_default&index=N` — refused
  - `apn_mode=manual&apn_action=set_default` — refused
  - `apn_mode=auto` — **accepted**
  - complete five-field form — accepted, **both** directions
  - So `APN_PROC_EX` is all-or-nothing like `DATA_LIMIT_SETTING`, and **asymmetric**: `auto` needs no profile, `manual` is meaningless without one.
  - Now a read-modify-write taking the poll data, deriving `index` and `pdp_type` from `APN_config{index}`. The complete form is used for **both** directions — it is the only one verified to actually _apply_ (mode changed, `wan_apn` followed). Bare `auto` is verified only as _accepted_, so it survives purely as the fallback when the poll has not yet supplied `apn_index`.
  - Manual with no known profile now **raises locally** rather than sending a doomed payload, so the user sees "refresh and retry" instead of an opaque `result=failure`.
  - **Verified on hardware, both directions**: manual → auto → manual, with `wan_apn` tracking and the connection restored.

### Corrected — a claim made in this session

"`set_apn_mode` has never worked" was **half wrong**. The auto direction always worked; only manual was refused. That asymmetry is why the entity never looked dead, and it was masked further by `set_apn()`, which already sends the complete form — choosing an **APN Profile** works, and that form carries `apn_mode=manual`, so the mode flipped as a side effect. The project owner supplied that observation; it is what made the asymmetry make sense.

### Testing note — the same lesson, a third time

The two existing tests asserted only `"apn_mode=manual" in data`. **Both passed against a payload the router had never once accepted.** Replaced with assertions on every required field, plus two tests for the auto paths. This is the third defect this session where a green mock-based test sat on top of a wrong model of the device.

### Changed

- `select.py` passes the poll data to `set_apn_mode`.
- `scripts/hardware_check.py` gained `_call_setter`, which supplies the profile context that setter now needs — fetched fresh either side of a reconnect rather than cached.

## [3.3.2-rc6] - 2026-07-30 - Unreleased - No Manifest Bump - Write Classification, Hardware Exercise, Attended Tier

Follow-on from the control write-path work. The question that prompted it: the ODU LED switch was broken for weeks and nobody noticed, because the owner does not use that entity. What else is in that position, and how far can hardware exercise be pushed safely?

### Added

- **`scripts/write_classification.py`** — a register placing all **11** write commands in exactly one tier, each with a written reason.
  - **SAFE (3)**: `set_odu_led_switch`, `set_data_volume_settings`, `logout`.
  - **ATTENDED (5)**: `set_apn_mode`, `set_apn`, `set_bearer_preference`, `set_data_limit_switch`, `reboot`.
  - **NEVER (3)**: `send_sms`, `delete_sms`, `delete_all` — cost, third parties, irreversible destruction.
  - The bar for SAFE includes **either resting state being harmless**, because a crash can strand it mid-check. That single clause is what separates the data-volume _alert percentage_ (SAFE) from the data-limit _switch_ (ATTENDED): a stranded threshold warns at a slightly wrong point, a stranded cap stops the router passing traffic.

- **`tests/test_write_classification.py`** — 9 tests, no router required. Fails when a write is added with no entry, when a SAFE write is not actually exercised, when an entry goes stale, and when a write appears in two tiers.
  - **Mutation-proved both ways**: adding a `set_new_untested_thing` method to `api.py` fails the suite; removing a name from the exercised set fails it.
  - **Guard-the-guard included.** Detecting writes by searching for `goformId` is the obvious implementation and is **wrong** — `delete_all` and `set_data_limit_switch` delegate to another method and contain no `goformId` of their own. A test asserts the detector still sees both, because a blind detector would let two real writes escape classification with everything green.

- **Two new SAFE checks in `scripts/hardware_check.py`**, taking it from 8 to 11 checks:
  - **The data-volume form**, exercised by nudging the alert percentage and restoring it. This covers `DATA_LIMIT_SETTING` — the all-or-nothing six-field form that was broken in every release — without touching the cap or the switch.
  - **Logout**, which replays the old token and confirms the router rejects it. Worth its own check because the failure is invisible: an ignored `LOGOUT` leaves the user locked out of their own web UI with nothing logged, and it cannot be verified through the web UI, since logging in there terminates any session regardless.

- **An attended tier (`--attended`)** for the writes that re-establish the connection. Offers `set_apn_mode` and `set_bearer_preference` **one at a time**: each prints the current value, the target, the risk and the manual undo path _before_ asking for a typed `y`, then restores and verifies. A failed restore prints a red block naming the single setting that may still be wrong. It refuses to run without a terminal.
  - `reboot` and `set_data_limit_switch` are classified ATTENDED but deliberately **unscripted** — reboot cannot be made quick or quiet, and turning on a data cap depends on the user's plan against current usage, which is a judgement rather than a check.

### Observed — an intermittent refusal, cause not established

On the first run of the new data-volume check the router **refused a well-formed six-field form**, then accepted an identical payload seconds later; a raw-payload probe immediately afterwards succeeded three times out of three. The check now retries once, and **the attempt count is always printed** — retrying silently would conceal exactly the class of fault this script exists to expose. Why it happened is unknown and is not guessed at in the code.

### Known — not verified on hardware

The attended **confirm** path (`y`) has not been run: doing so reconnects the live router. The **decline** path is verified over a real pty, and the no-terminal refusal is verified with `< /dev/null`.

### Testing note

The register is not a behavioral test and proves nothing about whether any write works. It makes it impossible to add one **in silence** — which is the actual failure that let two broken controls ship.

## [3.3.2-rc5] - 2026-07-30 - Unreleased - No Manifest Bump - Control Write Path Reworked

Reported as erratic ODU LED toggling: the switch would move, revert, then correct itself seconds later. Two independent faults, neither in the router.

### Fixed

- **Controls did not reach the state machine until the debounced poll ran.** `async_force_refresh()` goes through the coordinator's debouncer, cooldown **10 s**, so a write landing inside that window left the entity state unchanged for up to ten seconds — long enough for the frontend's optimistic toggle to revert first. Whether it happened depended on the timing of the _previous_ refresh, which is why it felt random.
  - Fixed with a **targeted read-back**: `api.get_params()` reads the key straight back and publishes it. Opt-in per description via `verify_after_write` + `state_key`, set on the two switches only.
  - Three outcomes kept distinct: read agrees → publish; read disagrees twice (200 ms apart) → `switch_write_not_applied`; read **errors or omits the key** → _unverified_, left to the next poll. A failed confirmation is not a failed write.
  - The router was measured first and exonerated: it applies in **~128 ms**, correct on the first read-back, holding. The read-back costs ~16 ms median, ~38 ms with a full poll in flight.
- **A write never noticed a session taken away.** Signing into the router's web page ends Home Assistant's session; the write then answers `{"result":"failure"}`, which matches neither the all-values-empty read rule nor the `is_auth_error` list. Every subsequent attempt failed until some read happened to re-login — the user hit exactly this, and Refresh Now cleared it.
  - Fixed by `_ensure_session()`, called from `get_ad()` — the choke point every write passes through, so `send_sms`, `reboot`, the selects and both switches all inherit it.
  - **`"failure"` was deliberately not added to `is_auth_error`.** It is equally what a genuinely declined command returns, and retrying one would resend it — for `send_sms`, twice.
- **`select.py` swallowed write exceptions**, so a rejected APN or bearer change silently sprang back. Now raises `select_set_failed`. Deliberately **not** given a read-back: those setters re-establish the connection and the router answers blank meanwhile, which reads as an expired session.
- **A missing key rendered as a confident "off".** Switch position is now latched and held when a payload omits the key. `None`/unknown was considered and rejected — a toggle landing on unknown is worse than the bug.

### Changed

- **`PARALLEL_UPDATES = 1`** on `switch`, `select`, `number`, `button`; `0` retained on `sensor` and `binary_sensor`. `0` means _unlimited_, which on a single-session router is how concurrent writes tear a session down. Confirmed not an IQS violation: the rule requires the constant to be set deliberately, and core does exactly this split (`liebherr` has `1`/`0` and `parallel-updates: done`).
- **Five writable keys promoted to `_CORE_PARAMS`** — `ODU_led_switch` and the four `data_volume_*` fields. A control showing a cached position invites a write built on a stale reading, and `DATA_LIMIT_SETTING` composes four of them into its form. Core 80 keys/1269 chars, extended 36/623; budget test unchanged at 1700.

### Added

- **`scripts/hardware_check.py`** — round-trips every safe write against a real router, including with the session deliberately invalidated, and captures observed payloads to `tests/fixtures/`. Excludes `send_sms`, `reboot` and the APN/bearer selects by design.

### Corrected — a claim this file made hours earlier

`[3.3.2-rc5]` originally explained the failed retry by `RD` rotating on re-login. **`hardware_check.py` disproved that on its first run**: `RD` survived a re-login. The retry's failure is real and reproducible; its mechanism is **not established**. The code and tests now assert the ordering that was measured to work and claim no mechanism, and the script records `rd_survives_relogin` as an observation rather than a scored check.

### Testing lesson, recorded because it cost real time

`test_write_refused_with_a_dead_session_relogs_in_and_retries` **passed against code that failed on hardware**. The mock was written from the same wrong model as the code, so it could only confirm the code agreed with the mistake. Mocks cannot falsify a belief about the device. The enumerate-and-guard tests fared better — the dead-session sweep forced `get_params` into coverage the moment it was added.

## [3.3.2-rc4] - 2026-07-30 - Unreleased - No Manifest Bump - Toolchain Moved To HA 2026.8; Harness Unblocked

The devcontainer took **HA 2026.8.0b1**, **PHACC 0.13.349** and **ruff 0.16.0**. The harness problem recorded in `[3.3.2-dev1]` is **resolved** — PHACC 0.13.349 supports 2026.8, so the suite runs with no shim and the throwaway probe is gone for good. Pins were already updated in `.validate/requirements_test.txt` and `version_matrix.json`.

### Fixed — two `PLR0917` findings from ruff 0.16

`PLR0917` (too many positional arguments) is newly enforced. Both findings were real signature smells rather than noise.

- **`ZTERouterAPI._request()` took 7 positional parameters.** Everything after `path` is now **keyword-only**. Nothing outside the class was passing them positionally — only the three internal retry calls were, each re-listing `method, path, params, data, headers, timeout_sec, authenticated` in order, which is exactly the argument-transposition risk the rule exists to catch. Those three now pass by keyword. No call site outside `api.py` changed, and no behavior changed.
- **`test_web_power_sensors_read_the_router_flag` took 6.** Two fixtures plus four parametrize values. The four parametrized values are now keyword-only; pytest injects by name, so the decorators are untouched.

### Verified on the new stack

- **750 tests pass** (749 plus `test_no_sensor_uses_the_total_state_class`), **100% coverage**, `mypy --strict` clean across 14 source files, `ruff check` and `ruff format --check` clean on 0.16.0 across 47 files.
- This is the first unshimmed run on 2026.8. The nine device-registry test fixes in `[3.3.2-dev1]` hold up without the probe, and nothing beyond them surfaced.

### Still open

- **`unifi_network_monitor` and `huawei_router_5g` keep the same `via_device` test gap**, and both will now also hit `PLR0917` if they have comparable signatures. Neither is actioned here.
- §7 of the shared device-registry record was verified against **b0**; this run was on **b1**, with no change observed. A final-release check is still the honest closing step.

## [3.3.2-rc3] - 2026-07-30 - Unreleased - No Manifest Bump - Bumps

### Bumps

- **Validate Bump**: Update `ruff` from 0.15.22 to 0.16.0
- **Validate Bump**: Update `zizmor` from 1.25.2 to 1.28.0
- **Validate Bump**: Update PHACC `pytest-homeassistant-custom-component` from 0.13.348 to 0.13.349

### Changed

- **Docs**: Changes to CHANGELOG.md and README.md prior to v3.3.2 release

## [3.3.2-rc2] - 2026-07-30 - Unreleased - No Manifest Bump - `TOTAL` State Class Banned; Release Notes Rewritten

A guard so the `TOTAL` / `TOTAL_INCREASING` confusion cannot recur

### Added

- **`test_no_sensor_uses_the_total_state_class`** (`tests/test_entity_hygiene.py`). No sensor may use `SensorStateClass.TOTAL`. Backed by `ALLOWED_TOTAL_STATE_CLASS`, an **empty** frozenset in the same shape as `ALLOWED_RECORDED` — adding an entry is a reviewable act, typing `TOTAL` into a new description is not.
  - **Why a blanket ban rather than "resetting counters must be `TOTAL_INCREASING`".** The narrower rule needs the test to know _which sensors reset_ — a list that drifts silently the moment someone adds one. The ban needs no such knowledge and cannot go stale. `TOTAL` is for a value that can legitimately fall without that being a reset (net import/export, a draining tank) and requires a `last_reset` attribute; nothing a 5G router reports fits. Current state: **16 `MEASUREMENT`, 6 `TOTAL_INCREASING`, 0 `TOTAL`**, so the ban cost nothing to adopt.
  - Sweeps live entities rather than the static `SENSOR_TYPES` tuple, matching the other two sweeps in the file, and carries the same `checked >= 3` guard-the-guard.
  - **Mutation-verified**, not merely passing: flipping one description to `TOTAL` fails with the offending entity named (`sensor.zte_5g_data_monthly_sent_gb`). Restored; 14/14 pass, ruff clean. The four `mypy --strict` findings in that file are pre-existing and outside this addition.
  - Known gap, deliberately not covered: the ban does not stop a resetting counter being marked `MEASUREMENT`.

## [3.3.2-rc1] - 2026-07-30 - Unreleased - No Manifest Bump - Device-Registry Tests Unlocked From HA 2026.7

The devcontainer took **HA 2026.8.0b0**, which triggered the pending re-verification in `.shared/issues/x_project/device_registry_2026_08.md` §7. The compat shims are correct; nine tests were not.

### Fixed

- **Nine tests asserted the pre-2026.8 device-link shape and would have failed on any 2026.8 install.** They hard-coded `info["via_device"] == (DOMAIN, …)`, or stubbed `dev_reg.async_get_device.return_value`, where 2026.8 emits `via_device_id` and calls `async_get_device_by_identifier`. The production code was behaving **correctly** throughout — the shim feature-detects and had already switched branch. The tests were only ever green because 2026.7 takes the branch they assert.
  - Added `assert_links_to_parent()` and `assert_is_root()` to `tests/conftest.py`. They branch on `_compat._HAS_BY_IDENTIFIER` and assert the link's **presence and exclusivity** — never both keys, since `DeviceInfo` raises if both are set — rather than a hard-coded key name. Value and shape stay covered by `test_compat.py`, which patches a real registry.
  - Two coordinator tests needed the same treatment, stubbing both registry methods so the mock answers whichever branch runs.
- **Result: 749 pass on 2026.8.0b0** (with the harness unblocked, below). `mypy --strict` and `ruff` clean.

### Verified — HA 2026.8 device registry

The §7 checklist ran against the beta. Every assumed API landed unchanged, so **no shim needs updating in any project**. `async_get_device_by_identifier((DOMAIN, id), entry_id)` matches its assumed signature exactly; `config_entry_id` is a scalar with `config_entries` as a compat property; `DeviceInfo` carries both keys and raises if both are set; and all three ZTE sub-devices resolve to the System root by `via_device_id` on the live instance. **Zero deprecation lines in the log, from any integration.**

### Known — the test harness cannot run on 2026.8 yet

`pytest-homeassistant-custom-component` 0.13.348 — the newest published, hard-pinned to `homeassistant==2026.7.4` — patches two symbols 2026.8 removed, so all 749 tests error at _setup_. There is **no newer release to move to**, and this is not beta-specific: the symbol is gone from the 2026.8 source tree entirely. It will likely resolve when PHACC publishes for 2026.8, or if the removal changes before final. **No workaround has been committed** — a local monkeypatch of the harness would outlive the problem. Full reasoning, and the shape of the workaround should it ever be needed, in the shared record.

**Other projects:** the same test pattern almost certainly exists in `unifi_network_monitor` and `huawei_router_5g`. Flagged in the shared record, not actioned here.

## [3.3.1-dev20] - 2026-07-30 - Unreleased - No Manifest Bump - Allowance Enabled; Entity Naming Convention

### Changed

- **`Allowance` is now enabled by default.** It is the figure `Projected Cycle Usage` is judged against, and hiding it while showing both the projection and the alert threshold made no sense. It reports nothing when no cap is configured, which is the honest answer rather than a reason to hide the entity.
- **`Data Volume Alert` renamed to `Alert Threshold`.** It was producing `sensor.zte_5g_data_data_volume_alert` — Home Assistant prefixes the device name, so "Data Volume Alert" in the Data group doubles the word. Neither candidate name quite fit: "Volume Alert" reads as an alert entity when this is a **setting** that never alerts, and "Usage Alert Percent" repeats a unit the `%` already shows. `Alert Threshold` says what it is and pairs with its sibling — **Allowance** 2199 GB, **Alert Threshold** 80%.
- Its `about` note now names that pairing explicitly: "80% of a 2 TB plan means it warns you at 1.6 TB".

### Added

- **`AGENTS.md` § Entity naming — do not repeat the sub-device word.** Written up after a scan found three doubled entity IDs, only one of which was worth fixing.

### Deliberately not changed

- **`sensor.zte_5g_signal_signal_bars` and `switch.zte_5g_data_data_limit_switch` keep their doubled IDs.** Both are long released. Renaming fixes nothing for anyone who already has them — **Home Assistant never renames an existing `entity_id`** — while anyone referencing the friendly name in a dashboard or template gets a silent break. The only beneficiary would be a new install. `Data Volume Alert` was worth renaming precisely because it was disabled by default until this session, so almost nobody has it.

### Known state on the development instance

`sensor.zte_5g_data_allowance` shows `disabled_by='user'` in the registry rather than `'integration'`, so Home Assistant will not auto-enable it there — an explicit user choice is respected over an integration default. It has to be enabled once by hand. Fresh installs get it enabled. This is the same asymmetry recorded in `[3.3.1-dev18]`: the enable direction propagates from an integration default, the disable direction and any explicit user choice do not.

## [3.3.1-dev19] - 2026-07-30 - Unreleased - No Manifest Bump - Two Raw Diagnostics Made Readable

`Carrier Aggregation Secondary Cells` and `LTE Band Lock Mask` both told the user the value was raw without telling them how to read it. Both notes now carry the decode, and both decodes are verified on hardware rather than asserted.

### Fixed

- **`LTE Band Lock Mask` now explains the bitmask.** Bit N is band N+1. Verified: the live value `0x60088080045` decodes to bands **1, 3, 7, 20, 28, 32, 42, 43** — the standard European CPE set — and two independent cross-checks land on the same poll. `wan_active_band` reported `LTE BAND 28` with bit 27 set, and the carrier-aggregation secondary cell reported band 20 with bit 19 set.
- **`Carrier Aggregation Secondary Cells` now names its fields**, and in the process corrects the discovery report. The report ordered them `[earfcn],[band_number]`, which read the live sample as EARFCN 20 on band 6300 — impossible, since EARFCN 6300 falls inside band 20's allocation (6150-6449) and `20` is not a valid EARFCN. The order is band then EARFCN.

### Not adopted

- **Field 3 was proposed as a "Subframe Code" and is left unnamed.** Three readings of the same string show it oscillating between `1` and `2` while band, EARFCN and bandwidth hold steady — a subframe configuration does not do that. The discovery report's own label, `dl_bandwidth_code`, is contradicted by the same data: code `2` would mean 5 MHz, disagreeing with field 6's `10`. It is more likely an SCell activation state or a MIMO layer count; naming either would be publishing a guess in a note whose whole purpose is to let someone parse the string.

### Notes

- `docs/zte_how_to_access.md` § Field formats now carries a per-position confidence column for the CA descriptor, so the three confirmed fields are distinguishable from the two inferred ones and the one unknown.
- The band-lock warning was retained rather than dropped: the sensor is read-only, but it is where someone checks a lock they applied elsewhere, and "locking to a band the router cannot see leaves it with no service" is the consequence they need at that moment.

## [3.3.1-dev18] - 2026-07-29 - Unreleased - No Manifest Bump - Default-State Review and `about` Note Corrections

User-directed pass over which entities appear out of the box, and over six `about` notes that were awkward, outdated or misleading. Note text is edited in the entity descriptions, not in `docs/about_attribute_list.md`, which is generated from them.

### Changed

- **`MDM MCC` and `MDM MNC` are now disabled by default.** Both are static in normal use — they change only if the modem attaches to a different operator — so they were two permanently unchanging rows in every user's default entity list. `RMCC` and `RMNC`, which report the _registered_ network and do differ while roaming, were already disabled.
- **`Data Volume Alert` is now enabled by default**, and keeps its lack of a `state_class` so it stays out of long-term statistics. It is the threshold the router's own alert fires on, and it pairs directly with the new `Allowance` sensor; hiding it while showing the cap made little sense. A configured percentage has no useful trend line, hence no statistics.

### Fixed — `about` notes

- **WAN Fallback Mode** — "It differing from the active mode is normal" was an awkward gerund. Now "A difference between the fallback mode and the active mode is normal and not a fault."
- **Monthly Sent / Received / Total** — all three told users to prefer the legacy GB sensors for display and the byte sensors for arithmetic. That advice predates Home Assistant's unit normalization and is now wrong: the byte sensors carry `DATA_SIZE` with a `GIGABYTES` suggested unit, so HA renders them in GB on a dashboard while storing exact bytes. The legacy GB sensors are disabled by default and exist only for history. Rewritten to say HA displays in GB while storing the byte count, so one sensor serves both purposes.
- **Bridge Mode** — the note described the PPP session accurately but never connected it to the entity's name, leaving users to wonder how it relates to WAN Operating Mode. It now states the distinction directly: this reports whether the pass-through session is **up**, while WAN Operating Mode reports which mode the router is **configured** for. The APN-versus-coverage diagnostic hint is kept.
- **Router Timezone** — previously declined to interpret the format at all. The encoding is now known, so it explains it: base timezone plus DST offset, with `0-1` as the worked example.

## [3.3.1-dev17] - 2026-07-29 - Unreleased - No Manifest Bump - Monthly Counter Statistics Fixed; Allowance Sensor Added

Prompted by a user challenge to a claim made in review, which turned out to be half right and exposed a defect that had been corrupting statistics every month.

### Fixed

- **The six monthly counters were `TOTAL`; they are now `TOTAL_INCREASING`.** These zero on the router's billing day, and the two state classes handle that completely differently. Verified against `homeassistant/components/sensor/recorder.py`: `reset_detected()` — which treats a fall below 90% of the previous value as a new cycle — is reached **only** from the `TOTAL_INCREASING` branch. Under plain `TOTAL` a reset is recognized solely from a `last_reset` attribute this integration does not publish, so **every monthly rollover recorded as a large negative delta and walked the long-term statistics sum backwards**. Affects `monthly_tx_bytes`, `monthly_rx_bytes`, `monthly_total_bytes` and their three `_raw` counterparts.
  - **Existing statistics are not repaired by this.** Home Assistant applies the new class going forward; historical sums already skewed by past rollovers stay as they are. Developer Tools → Statistics offers a fix-up for affected entities.
- **`data_volume_limit_size` was documented as `2_1048576` = "2 GB".** It is **2 TiB** — the multiplier is the number of mebibytes in the chosen unit. The annotation came from the discovery report; the router's own Data Management page shows "2TB" for that stored value with an 80% reminder at "1.6TB", and direct observation of the device beats the annotation. Also recorded that the router counts in **binary** units throughout that page, so its "1.01TB used" and a Monthly Total of 1,107.75 GB decimal are the same quantity, not a disagreement.

### Added

- **`Allowance` sensor** (`data_allowance`) on the Data sub-device — the monthly cap configured on the router, decoded from `<value>_<MiB multiplier>`. Disabled by default, `DIAGNOSTIC`, guard-banded to 1 PiB. Returns nothing when no cap is set or the router is limiting by **hours** rather than data, since a duration is not an allowance. Verified live: decodes to 2.00 TiB against the router's "2TB", and 80% of it to 1.60 TiB against the router's "1.6TB" — two independent cross-checks of the same encoding.
- **A cap-relative variant of the Projected Overage automation.** With `Allowance` enabled the threshold tracks the router instead of a number typed into the automation, so changing your plan does not mean editing YAML. The template carries a `> 0` guard because the sensor is unavailable when no cap is set, and without it an unset cap would read as zero and fire immediately. Verified by rendering it at four states.

### Notes

- Every field on the router's **Data Management** page is now polled. Three are still without an entity: `wan_auto_clear_flow_data_switch`, `data_volume_limit_unit`, and the "Data Used" calibration write.
- **`FLOW_CALIBRATION_MANUAL` is that "Data Used" box** — an editable current-usage field, not a missing feature. It re-bases the counter to match an operator's billing figure, which means it _writes_ the counter and so carries the same statistics caveats as a reset, upward as well as down.
- Named `Allowance` rather than `Data Allowance`: Home Assistant prefixes the sub-device name, so the latter yields "ZTE 5G Data Data Allowance". Same reasoning as `Reset Day`.

## [3.3.1-dev16] - 2026-07-29 - Unreleased - No Manifest Bump - Corrected Reasoning on Declined Write Controls

Documentation only. All declined write commands stay declined; the reason given for most of them was wrong.

### Fixed

- **One objection had been applied to five commands, and it only fits one.** `docs/zte_how_to_access.md` and `docs/Future.md` both claimed that each declined write changes the path Home Assistant reaches the router over, so the control that undoes a mistake becomes unreachable. Home Assistant talks to the router at its **LAN address**. A cell lock, a band lock or bad DNS breaks the **WAN**, not the management path — the undo stays available. Only `OPERATION_MODE`, which changes the router's LAN role and addressing, carries a genuine reachability risk.
- **Replaced with a per-command reason.** Reachability for `OPERATION_MODE`; poor value against real risk for `LTE_LOCK_CELL_SET`, where cells change with operator load and maintenance so a working lock can fail later; scope and blast radius for `ROUTER_DNS_SETTING`, which affects every device on the LAN; scope plus address-collision risk for the DHCP reservation commands; one-time provisioning for `SET_NETWORK` / `UNLOCK_NETWORK`. `RESET_DATA_COUNTER` remains declined for irreversibility, which was always its own reason.
- **Recorded the case where reachability does hold** — a user reaching Home Assistant remotely over the same WAN loses both the connection and the control that fixes it. That is a property of their access path rather than of the router, but it is common enough to design for.

### Added

- **"Recoverable is not the same as harmless", stated explicitly.** Three of these are reversible from the router's web page in under a minute, and that is the argument for leaving them there rather than against it: a setting that is a one-time deliberate act with a wide blast radius belongs somewhere that shows it in context and warns before applying. Exposing a control in Home Assistant implies it is safe to script.
- Each declined entry now names the router's own web page as where the user should go, rather than only saying no.

**Why this was worth correcting rather than leaving.** A tidy single objection that does not survive inspection is worse than three specific ones: the next reader either applies it to a sixth command where it also fails, or notices the LAN path survives, concludes the whole rationale is bogus, and implements all of them.

## [3.3.1-dev15] - 2026-07-29 - Unreleased - No Manifest Bump - Projection Refinements

Four changes to `Projected Cycle Usage` following a review of how it behaves in the first days of a cycle.

### Changed

- **Removed the `state_class`, so it no longer reaches long-term statistics.** It was `measurement`, which generated LTS mean/min/max. That was wrong on reflection: this is an estimate of where the cycle ends up, useful _now_ rather than as a history, and the measurement it derives from — `Monthly Total` — is already recorded with a proper state class. Keeping both stored a derived view of a number already stored, and invited charts of what was once guessed rather than what happened. It still appears in normal recorder history; an integration can exclude its own attributes but not its own state.

### Added

- **A calendar-month fallback.** A router reporting no reset day previously produced a permanently `unknown` sensor with no explanation. It now assumes the 1st — right for anyone billed calendar-monthly, no worse than nothing for anyone else, and far better than a blank that never clears. The assumption is published as a new `cycle_source` attribute (`router` or `calendar_assumed`) so it is visible rather than buried in the arithmetic.
- **README note on first-day behavior.** The projection reads _low_ on day one, not high: the denominator floor caps the rate at one day's usage rather than dividing by a fraction of a day. It settles within 24 hours and is accurate from day 2 of every cycle — including the first cycle after install, which is worth stating because "wait a few months for it to learn" would be wrong.
- **A `Projected Overage Alert` automation example**, gated on `cycle_day >= 3` so a single large download on the 1st cannot page the user about an overage that never happens. The template guards the attribute being absent (`or '0 of 0'`), since `.split` on a missing attribute throws when the sensor is unavailable. Both `confidence`-based alternatives are documented alongside it. YAML and Jinja verified by parsing them out of the README and rendering the condition at day 2, day 3 and with the attribute absent.

### Not done

- **Phase 4, the cycle-history store, is declined for now.** It would only improve the opening ~18-24 hours of each cycle — precisely the window `confidence` already reports as `low`. `helpers.project_cycle_usage()` keeps its `prior_rate` hook, so it remains one line plus a store if the 1 August rollover shows something worse than predicted. Were it built, it should use `homeassistant.helpers.storage.Store` (already used in two sibling projects) rather than `RestoreEntity` (used in none).

## [3.3.1-dev14] - 2026-07-29 - Unreleased - No Manifest Bump - Documentation Reconciliation

Documentation only. Closes the gap between what this session built and what the docs claim, and folds the last of the discovery report into the interface reference.

### Fixed

- **Entity counts were wrong in three places.** `README.md` said 82 entities; the registry holds **91**. `all_sensors.md` section headers said System 32 and Signal 39 against actual row counts of 33 and 40 — the summary table had been corrected earlier but the headers had not. All three now agree with the live registry, and the README's per-sub-device breakdown lists the nine entities added this session.
- **`docs/Future.md` item 4 described a blocker that no longer exists.** It warned that a partial `DATA_LIMIT_SETTING` POST might zero the user's data cap. Hardware showed the router **refuses** an incomplete form instead, and the read-modify-write path is now built and verified. Rescoped: only the Number and Switch entities remain, effort drops Medium → Low.
- **The implementation plan claimed Phase 2 complete. It is not.** Phase 2 was defined as the clear-day Number and the auto-clear Switch; what shipped was the write path underneath them. Corrected rather than quietly left — the entities do not exist, and a status line saying otherwise is how work gets skipped.

### Added

- **`zte_how_to_access.md` § Available but not polled** — the fifteen keys the MC7010 populates that neither batch requests (`monthly_time`, `odu_mode`, `dns_mode`, the PPPoE and PDP fields, the SNTP server menu, the battery detail), plus the notable present-but-empty ones: **`gps_lat` / `gps_lon`**, three further thermal spellings, and the night-mode state. The point is to stop the next person re-running a 183-key probe to discover what already exists.
- **`DEVELOPMENT.md` § 5** gains two pitfalls: the **URL-length budget** (with the rule that a speculative key is probed alone first, since a batch containing fictional names was seen to time out and fall back to empty defaults), and **`DATA_LIMIT_SETTING` being all-or-nothing** — the write that never worked, and the swallowed exception that hid it.
- **`DEVELOPMENT.md` § 7** gains the two real debts: the billing-cycle write entities, and the projection's missing cycle-history store.

## [3.3.1-dev13] - 2026-07-29 - Unreleased - No Manifest Bump - Batch Poll Split In Two

The batch poll had grown to 1,889 characters against a ~2,048-character URL ceiling. Rather than keep trading one key away to make room for the next, the request is now two.

### Changed

- **`get_all_data()` split into a mandatory core fetch and an optional extended one**, divided by criticality rather than alphabetically.
  - **`_CORE_PARAMS`** (75 names, ~1,167 characters) — everything feeding an enabled-by-default entity, the contract keys, and the device identity latched into `entry.data`. Mandatory: its failure is a whole-integration failure, exactly as before.
  - **`_EXTENDED_PARAMS`** (41 names, ~735 characters) — diagnostics, disabled-by-default entities, router settings and the thermal keys. Optional, through the existing `_fetch_optional`.
  - Headroom goes from ~160 characters to ~880 and ~1,310. A future addition no longer forces a removal.
- **Hardened as an optional endpoint, not merely as a second request.** The extended fetch gets its own last-good payload and its own three-strike budget: a single failed cycle changes nothing a user can see, three hold the previous values, and only past that do its entities go unavailable — while Signal and Data keep serving real values throughout. `ZTEAuthError` is still not absorbed there; it reaches the global handler so the session is renewed and the whole set retried once.
- **`source=ENDPOINT_EXTENDED` on every entity fed from it**, so those entities follow that endpoint's health rather than showing a value frozen hours ago. `binary_sensor.py` and `switch.py` gained the `source` field and the `available` gate that `sensor.py` already had.
- **Merge order is core-over-extended**, so a stale cached diagnostic can never mask a fresh core value if the two batches ever come to share a key.
- **Cross-model aliases stay in the core batch** despite the MC7010 answering `""` for all of them. They feed enabled-by-default sensors on other `goform` models, and a Signal sensor on an MC888 must not depend on an endpoint that is allowed to degrade.
- **APN profile slots capped at 10** (`APN_PROFILE_SLOTS`), from 20. The firmware exposes twenty and an MC7010 in normal use populates two; twenty cost 250 characters — a fifth of the old request — to carry eighteen empty strings. The request and the APN select now derive from one constant, so they cannot disagree about how many slots exist.
- `Extended diagnostics` is reported by name in the Integration Health `degraded_capabilities` list when it exhausts its budget.

### Added

- Seven coordinator tests for the split, covering the properties that matter rather than the plumbing: core data survives an extended failure, last-good values are held within budget, only the extended entities degrade past it, one success recovers, an auth error still drives reauth, core wins a key collision, and the degraded endpoint is named in health.
- Availability tests for the new `source` gate on both binary sensors and switches.
- `test_batch_poll_urls_stay_within_the_router_budget` is now parametrized across both halves.

### Verified

Live MC7010 after a full restart: 120 merged keys, values present from both batches (`traffic_clear_date` and `monthly_tx_bytes` from core, `sntp_timezone`, `opms_wan_mode`, `data_volume_limit_size`, `reboot_dow` from extended), Integration Health `off`, and `endpoint_failures` zero across all three optional endpoints.

## [3.3.1-dev12] - 2026-07-29 - Unreleased - No Manifest Bump - Data Limit Switch Fixed; Batch Poll Budgeted

Acts on the router-facing agent's answers in `.notes/info/zte_element_discovery_report.md` §6, which resolved every question raised against the discovery report. One of the answers uncovered a defect in shipped code.

### Fixed

- **The Data Limit Switch had never worked.** `DATA_LIMIT_SETTING` is a six-field form covering the limit switch, the cap and its unit, the alert percentage, the monthly auto-reset and the billing reset day. The integration sent one field, and the router refuses a partial payload — confirmed on hardware, where the same single-field POST returned `{"result":"failure"}`. `set_data_volume_settings()` now performs a read-modify-write, sourcing untouched fields from the last successful poll and refusing to write at all if any is missing rather than inventing a value for someone's data cap. `set_data_limit_switch()` routes through it, so there is one write path for this form instead of two that can drift.
- **A refused switch write no longer disappears into the log.** `switch.py` caught every exception and logged it, so a command the router declined looked like a toggle that quietly sprang back. It now raises a translated `HomeAssistantError` (IQS `action-exceptions`). This mattered more than usual here because the API answers `200 OK` for a refused write.
- **Two `about` notes stated something untrue.** Web Page Sleep and Web Page Auto-Wake said no write command existed for them. `SAVE_TSW` does. They remain read-only — a setting governing the router's own web page has no bearing on Home Assistant — but the stated reason was wrong and is now the actual one.

### Added

- **`test_batch_poll_url_stays_within_the_router_budget`.** The batch limit is a **URL length of roughly 2,048 characters**, not a number of names, and the poll had grown to ~1,885 without anything watching. Past the ceiling the response truncates, which presents as missing fields and is indistinguishable from firmware contract drift. The test carries a soft threshold ahead of the hard one, so the warning arrives before the failure.
- `data_volume_limit_unit` and `data_volume_limit_size` to the batch poll — the write path cannot echo back a field it never reads. `test_every_data_volume_field_is_polled` keeps the two in step.

### Changed

- **Three keys dropped from the batch poll** to pay for the two above: `sms_received_flag`, `ipv6_apn_index` and `ODU_led_off_time`. None fed an entity or any logic. Net effect is one key fewer and slightly more headroom than before.
- **The reboot-schedule encoding is now documented rather than guessed at.** `reboot_schedule_mode` is `1` = weekly, `2` = monthly; `reboot_dow` is 1-indexed from Sunday. The attributes are still published raw — this is a disabled-by-default diagnostic whose reader is comparing against the router's own settings page, where these are the values shown — but the code comment no longer claims the mapping is unconfirmed, and the `about` note now says which day field applies.

### Documentation

- **`docs/zte_how_to_access.md` substantially extended.** The batch-poll key list was 25 keys behind the code; it is current. New sections cover the **three-way response split** (populated, present-but-empty, genuinely absent — a distinction that has caused defects here), the **URL-length ceiling**, the **full 26-command `goformId` inventory** with a status and reason for each, **field formats** for the values this API returns as opaque strings, and the **two-step discovery method** that found them.
- **Two claims in that document were wrong and are corrected.** It asserted there is no bulk-delete `goformId` — `ALL_DELETE_SMS` exists. And it documented `DATA_LIMIT_SETTING` as a single-field toggle.
- Recorded that `SET_DEVICE_LED`, which the discovery report offered as an alternative to `ODU_LED_SWITCH_SET`, is in fact an unrelated night-mode LED scheduler. Not a conflict, a separate feature.
- Two decisions to publish a raw string rather than parse it were vindicated by the answers. The field order given for `lte_multi_ca_scell_info` has **positions 4 and 5 transposed** — the sample reads `…,20,6300,…`, and EARFCN 6300 falls inside band 20's allocation while `20` is not a valid EARFCN. And `sntp_timezone` rests on a single sample from a UTC+0 unit with a sign convention that runs backwards from expectation. Parsing either would have shipped a wrong value.
- **`battery_value` returns a hardcoded `100`**, not an empty string. An earlier probe reported it empty because its batch chunk contained fictional names and timed out. The `about` note calling the value meaningless on a mains-powered unit was right all along.

## [3.3.1-dev11] - 2026-07-29 - Unreleased - No Manifest Bump - Billing-Cycle Reads and Data-Usage Projection

Acts on `.notes/info/zte_element_discovery_report.md`, a two-step discovery run (web UI JavaScript mining plus a live batch probe against the MC7010) that isolated 66 answering parameters. Phase 1 and Phase 3 of the plan in `.notes/issues/data_cycle_and_projection_plan.md`. **Reads only — no new write command reaches the router in this entry.**

### Added

- **Projected Cycle Usage** (`data_projection`) — an estimate of end-of-cycle data usage, and the answer to the question the monthly counters do not address: _am I on course to exceed my allowance?_ Enabled by default on the Data sub-device.
  - **Cycle-relative, not calendar-relative.** The router's counters reset on its own billing day, which need not be the 1st. Projecting against a calendar month would be wrong for most users.
  - **Never shows `unknown`.** The naive form divides by elapsed time, so seconds into a cycle its error is unbounded — half a gigabyte one second in projects to over a million. The denominator is floored at one day, which bounds the result without inventing a cap. An `unknown` on day one reads as a broken sensor; the caveat belongs in the attributes, which carry `confidence`, `basis`, `cycle_day` and `cycle_start`.
  - **`state_class` is `MEASUREMENT`, not `TOTAL`.** A projection falls whenever a heavy first week is diluted by a quiet second one. Under `TOTAL`, long-term statistics would read every such fall as a counter reset — a corruption only a manual purge undoes.
  - Suppressed entirely when the router's automatic monthly reset is switched off, because then there is no cycle to project against.
- **Reset Day** (`data_clear_day`) — the day of the month the router zeroes its counters. Enabled by default; bounded 1-31. Named `Reset Day` rather than `Data Reset Day` because Home Assistant prefixes the sub-device name, which would otherwise yield `ZTE 5G Data Data Reset Day` and an entity ID to match.
- **Seven diagnostic entities**, all disabled by default: Carrier Aggregation Secondary Cells, WAN Operating Mode, WAN Fallback Mode, Router Timezone, APN Interface Version, Web Page Sleep and Web Page Auto-Wake.
- **Reboot schedule detail** — `reboot_schedule_mode`, `reboot_dow` and `reboot_dod` added as attributes on the existing **Scheduled Reboot** binary sensor rather than as new entities, which already carried the hour and minute. All three are published **raw**: which mode value selects the weekly day versus the monthly one is not confirmed on any firmware, and resolving it would mean publishing a guess as a state.
- `sntp_server2` folded into the existing SNTP Server attributes.

### Changed

- **Three spellings of the reset day are requested and aliased** — `traffic_clear_date`, `data_volume_clear_date`, `data_volume_clear_day`. Two internal analyses disagreed on the name; only the first is confirmed by a live probe, and requesting an unknown `cmd` costs nothing because the router omits it rather than erroring. `_clear_day()` **warns when two spellings arrive with different values** instead of silently taking the leader — a disagreement between firmware spellings of the same setting is the kind of fault that surfaces months later as a projection a week out.
- **`test_get_all_data_requests_every_aliased_key` now derives its key set** from the `_ALIAS_*` constants by introspection rather than a hand-maintained list. That list had already drifted; a new alias tuple is now covered the moment it is added.
- 15 new keys in the batch poll. Safe by the existing rule: an unknown `cmd` is absent from the response rather than an error, and an absent key cannot trip the "every value is an empty string" expired-session detection.

### Verified on hardware

Live MC7010 (`IRL_H3G_MC7010DV1.0.0B03`), read from a diagnostics download after a full restart.

- **All 15 new keys answered.** `traffic_clear_date` returned `1` — the discovery report's spelling is the right one. The two `data_volume_*` spellings returned `""`, meaning the firmware knows the names but does not populate them on this model; `_safe_int` treats present-but-empty as absent, so the resolution is clean and the disagreement warning does not fire.
- **No truncation.** 131 keys came back with every pre-existing field intact, closing the risk that a longer `cmd` list would silently drop data and look like firmware contract drift.
- **The projection is coherent against real usage** — 1107.75 GB on day 29 of 31 projected to 1200.5 GB, `confidence: high`.
- 91 entities registered, 7 of the 9 new ones disabled by default.

### Deferred

- **`wan_auto_clear_flow_data_switch` is polled but has no entity.** The projection reads it directly. Shipping it as a binary sensor now and a switch when the write path lands would strand a registry entry needing migration.
- **The clear-day write is not implemented.** `DATA_LIMIT_SETTING` is a multi-field form covering the cap, the unit and the alert percentage, so a POST carrying only the clear date may zero the other two — a user would discover it when the router stopped passing traffic. It needs a read-modify-write path and a hardware round-trip test first.
- **`RESET_DATA_COUNTER` and `FLOW_CALIBRATION_MANUAL` not implemented.** The first is irreversible and destroys the projection's own input; the second has semantics the discovery report does not describe, and a write whose effect cannot be stated in an `about` note should not ship.

### Declined

- **`OPERATION_MODE`, `LTE_LOCK_CELL_SET`, `ROUTER_DNS_SETTING`, `SET_BIND_STATIC_ADDRESS`.** Each changes how the router routes traffic — including the traffic this integration reaches it over — so the control that undoes a bad change becomes unavailable exactly when it is needed. This is the objection `Future.md` already records against band and cell locking, applied consistently. `opms_wan_mode` ships read-only so the mode is visible without offering a switch that can strand the user; the router's own web page remains the right place to change it.

## [3.3.1-dev10] - 2026-07-29 - Unreleased - No Manifest Bump - `Future.md` Roadmap Rewritten

`docs/Future.md` dated from 2026-05 and had not been revisited. Reviewed every item against the running instance and the current source, then rewrote it. Documentation only — no code touched.

### Changed

- **Three of the four original priorities are delivered**, now recorded as such: the `send_sms` service (then called "the single largest feature gap"), the Carrier Aggregation metrics, and the write-action fast path.
- **Two implementation deviations recorded rather than quietly ticked off.**
  - The fast path was specified as `async_request_refresh()`. That call is **silently swallowed while Pause Polling is on**, so following the roadmap literally would have produced the bug. It shipped as `async_force_refresh()`, which consumes a one-shot flag before the pause check. Worth keeping because the roadmap named a specific API and the specific API was wrong.
  - `wan_lte_ca` was proposed as a binary sensor ("CA Active") and shipped as a **sensor** — the router reports the aggregation configuration, not an on/off, and a binary sensor would have discarded the detail.
- **Token persistence closed as declined**, with reasoning, instead of left open indefinitely. The router permits one session at a time and a persisted `stok` is indistinguishable from a live one after exactly the event most likely to have invalidated it. Presenting a possibly-dead token to an API whose dead-session reply is `200 OK` with blank values is the same class as `[3.3.0-dev12]` and `[3.3.1-dev6]`. The saving is one login per HA restart.
- **Band and cell locking re-scoped.** The read side (`lte_band_lock`) and the adjacent bearer control (`Network Mode Selection`) already ship; only the write side is missing. The original "Reset to Auto" safeguard is necessary but **not sufficient**: lock to a band the router cannot see and the control that undoes it sits on the far side of the connection the lock just broke. On a headless outdoor unit that means physical access. Recorded that only a router-side self-clearing lock is a safe shape.
- **Corrected a stale conformance claim** — the footer asserted compliance with "PlayFaster v1.2 standards"; that is now 21 numbered `dev_standards` sections.

### Added

- **Five candidates**, each with what would justify it. Highest is **cross-model verification**: 3.3.1 shipped key aliases, a login-form fallback and channel-to-band resolution with none of it exercised on hardware, including three alias spellings found in no source project. One diagnostics download from an MC888 or MC889 user confirms or deletes the lot.
- **Open items folded in from `DEVELOPMENT.md`** (§15 SMS toggle, custom triggers, the thermal keep-or-remove question, the migration handler) so `Future.md` is a complete forward view rather than a partial one that silently omits known work.
- **Version Control** section — the document had none, which is why a two-month-old roadmap gave no signal that it was stale.

## [3.3.1-dev9] - 2026-07-29 - Unreleased - No Manifest Bump - `about` Notes: Six Added, Three Corrected, One Cross-Reference Removed

Reconciled the `about` note suite against the running instance with `sensor_review` (`SCOPE=About`), then acted on what it found plus three inaccuracies reported from live use. **74 of 82 entities now carry a note, up from 68.**

### Added

- **`about` support on three more platforms.** `select.py` had none at all — it now carries the `ZTEAboutEntity` mixin and `_unrecorded_attributes`; `binary_sensor.py` and `switch.py` gained an `about` field on their entity-description classes. The mixin already resolved `getattr(description, "about", None)`, so no change was needed there.
- **Six notes on control entities**, chosen on one test — _does the name leave a consequential question unanswered?_
  - **SIP ALG Enabled** — an obscure acronym that silently breaks VoIP; one-way audio and calls dropping on a timer are the classic symptoms.
  - **UPnP Enabled** — the security trade-off is not in the name, and it is a no-op in bridge mode.
  - **APN Profile** — the wrong profile means _no data_, not slow data.
  - **APN Selection Mode** — auto versus manual is not self-evident, and it gates the profile above.
  - **Network Mode Selection** — locking to `Only_5G` can drop the connection where 5G coverage is marginal.
  - **Data Limit Switch** — at the limit the router **stops passing traffic** rather than warning, which is worth knowing before enabling it.
- **`docs/about_attribute_list.md`**: an **Entities without a note** section covering all remaining 8, each with its group and a one-line reason. An omission a reader cannot see is indistinguishable from a gap.

### Fixed

- **`Battery` claimed the MC7010 reports nothing. It reports 100%.** Verified live. A mains-powered unit with no battery still publishes a full charge, so the old note actively misled anyone checking whether the reading meant something. Now states that outright.
- **`Network Type` did not mention the value the router is actually reporting.** Live state is `LTE-NSA`; the note covered only `ENDC` and `LTE`. Corrected to cover all three: ENDC (5G carrier in use), LTE-NSA (attached for 5G but running on the 4G anchor alone — what weak 5G coverage looks like), plain LTE (no 5G).
- **`5G Radio Temperature` told the reader to go and read another note.** Reaching an `about` note takes three clicks; sending the reader back out to reach a second one is not a design, it is a dead end. Rewritten to be self-contained and symmetric with the 5G Modem Temperature note. A note may mention a sibling entity; it may not require reading one.

### Changed

- **`Firmware Version` simplified.** It explained field renaming and contract drift — accurate, but far more machinery than a firmware string warrants in a tooltip. Cut to one sentence; the contract-drift explanation belongs to the README and the Integration Health sensor, which both already carry it.
- **`docs/all_sensors.md`**: `About` column refreshed, 68 → 74 ticks.
- **`docs/about_attribute_list.md`**: regenerated from live — System 21, Signal 39, Data 12, SMS 2. The `ᴰ` legend moved from the foot to the top, where a reader meets the marker. Removed a footer claim that a test enforced the file: that test had been deleted, and a guarantee that is not real is worse than none because it stops people checking.

### Verified

- 639 tests passing, **100% coverage**, `ruff`, `mypy --strict`, `codespell`, `prettier`.
- All 74 notes confirmed **published live**, not merely declared — 74 in source, 74 arriving as entity attributes, so no `extra_state_attributes` override is dropping one. That check is the reason the inventory is read from the running instance rather than parsed from source.
- Report: `.notes/sensors_states/ha_sensor_review_20260729_0406.md`.

### Notes

- **A config-entry reload does not pick up changed Python.** HA keeps the modules imported, so the first two post-edit fetches returned the pre-change state with no error and no clue — the note count simply did not move. A full restart (~150 s) is required, and the re-enable must follow it, because a restart reinstates disabled entities. Recorded in `sensor_review.md` v2.9.3 so the next run does not lose the same time.

## [3.3.1-dev8] - 2026-07-29 - Unreleased - No Manifest Bump - Encoding-Aware SMS Length Limit

The `send_sms` limit was a flat **160** in the service schema — an integration invention the router never saw, and wrong in both directions.

### Changed

- **The message limit now depends on the message.** `_validate_sms_length()` applies **765** characters when the text is entirely GSM 03.38, and **335** when anything in it forces UCS-2. Constants `SMS_MAX_CHARS_GSM7` / `SMS_MAX_CHARS_UNICODE` / `SMS_SEGMENTS_MAX` in `const.py`.
- **Rejection is now explanatory.** The old failure was voluptuous' `length of value must be at most 160 for dictionary value @ data['message']. Got None` — which names no limit the router has, and whose "Got None" is a voluptuous artefact rather than a real value. A new translated `sms_too_long` `ServiceValidationError` names the actual length, the limit that applied, which encoding triggered it, and that removing emoji buys the longer one.

### Why those numbers

A single SMS carries 160 GSM-7 septets or 70 UCS-2 characters; concatenated segments give up 7 bytes each to a header, leaving 153 and 67. The MC7010 web UI advertises `(765) (1/5)` for plain text — exactly 5 x 153, confirming a five-segment ceiling, so the Unicode equivalent is 5 x 67 = 335. behavior past five segments is untested, and the limit keeps callers out of it.

Validation lives in `async_send_sms`, not the schema, because which limit applies is only knowable from the message content. The schema keeps the absolute ceiling so a wildly oversized payload is still refused early.

**Live-confirmed (2026-07-29):** a 159-character plain message and an 80-character message with three emoji each arrived as **one** message on the handset. The router segments and the phone reassembles — nothing is truncated. The practical effect of the GSM-7 change in `[3.3.1-dev2]` is therefore **fewer billable segments**, not more characters: a 159-character plain message was 3 Unicode segments before and is 1 now.

### Documentation

- **`README.md`**: a limits table under `send_sms`, that one special character changes the encoding for the whole message, and that carriers charge per segment.
- **`docs/zte_how_to_access.md`**: new "`encode_type` and message length" section — the segment arithmetic, the `MessageBody`-stays-UTF-16BE rule with its two independent sources, and the hardware confirmation. `SEND_SMS` table row corrected: `encode_type` is no longer hardcoded to `UNICODE`.
- **`AGENTS.md`**: the content-dependent limit and why it is not in the schema.

## [3.3.1-dev7] - 2026-07-29 - Unreleased - No Manifest Bump - Dead-Session Fault-Injection Sweep

The systematic guard behind `[3.3.1-dev6]`. Both silent-failure bugs in this class were found one at a time, by a user, after release. This makes the next one fail in CI instead.

### Added

- **`tests/test_dead_session_sweep.py`** (116 tests). Drives every public API method against three fault modes and asserts one property throughout: **a method either does the thing or raises — it may never return a success-shaped result having done nothing.**
  - **`_DyingSession`** — session dies after _N_ requests (`N` = 0…3, so it dies at each point in a method's internal sequence). Exercises the expiry detection in `_request`.
  - **`_RefusingSession`** — live session, `{"result":"failure"}` on writes. Exercises `_require_success`.
  - **`_DriftingSession`** — a populated response missing the key the caller contracts for. Exercises `_require_contract`.
- **Three drift guards**: `_CALLS` must name every public API method, `_WRITES` every write command, and `_BEST_EFFORT` is capped at five entries each needing a stated reason. **A new API method fails the suite the moment it exists** — which is the whole point of the file.
- **`test_an_empty_inbox_is_not_an_error`** as a deliberate counterweight: without it, the drift test could be satisfied by making any empty result raise, which would break a router that genuinely has no messages. It pins the distinction the SMS fix rests on — `{"messages": []}` is an empty inbox, a missing `messages` key is a broken conversation.

### Notes

- **The first two versions of this file were worth nothing, and mutation testing is what proved it.** With only `_DyingSession`, deleting `_require_success` from `send_sms` left the suite **green**, and so did deleting `_require_contract` from `get_sms_messages`. Both blind for the same reason: on a dead session `_request` raises _upstream_, so neither guard is ever reached. A single fault mode could not exercise the code it claimed to cover. `_RefusingSession` and `_DriftingSession` exist solely because those mutations came back green.
- **Mutation matrix, all caught, all reverted**: `_require_success` removed from `send_sms`; from `set_bearer_preference`; `_require_contract` removed from `get_sms_messages`; and the `last_activity` gate reverted to reproduce the original field bug.
- The double deliberately serves `LD` and `wa_inner_version` even while dead, because the real hardware does — and that is precisely why those calls could reset the activity clock. Modelling them as dying would be a fault the router cannot produce.

## [3.3.1-dev6] - 2026-07-29 - Unreleased - No Manifest Bump - Actions Silently Failed on an Expired Session

**User-reported.** With Pause Polling on, `zte_router_5g.send_sms` reported success and no message arrived. Turning Pause Polling off and resending worked immediately. Two distinct defects, both shipped in **3.2.5**.

### Fixed

- **The session-activity clock was reset by calls that prove nothing.** `_request` stamped `last_activity` on **every** successful request, including unauthenticated ones. Every write calls `get_ad()` → `get_version()` first, and `get_version()` is unauthenticated — so it reset the clock immediately before the authenticated call that depended on it. The 150-second idle check then saw a session that had been idle for hours as "active 0 seconds ago", kept the stale `stok`, and the write went out on a dead session. **Only authenticated calls now count as activity**, because only they prove the session is alive. Present since `[3.1.1-dev4]`, so this shipped in 3.2.5.
- **Write commands never checked whether the router accepted them.** `send_sms`, `reboot`, `delete_sms`, `set_apn`, `set_apn_mode`, `set_odu_led_switch`, `set_data_limit_switch` and `set_bearer_preference` all awaited the request and returned success unconditionally. This API answers `200 OK` with `{"result":"failure"}` for a refused write, so **a rejected command was reported to the user as success** — the green action screen with no SMS. New `_require_success()` is applied to all eight.
- **`send_sms` did not refresh afterwards.** It was the only write action not calling `async_force_refresh()`, against the invariant stated in `AGENTS.md`. So even a successful send left the SMS counters and Recent Message frozen — and with Pause Polling on, frozen indefinitely.

### Notes

- **Live-hardware verification eliminated the leading hypothesis.** The suspicion was that `_request` retries a write payload verbatim after re-login, carrying an `AD` token derived from the dead session. Probing an MC7010 (`V1.0.0B03`) showed `RD` is a **static per-device seed**, so `AD` is constant for a given router and a retried payload is still valid. Full test plan and results: `.notes/issues/silent_login_fail.md`.
- **Reboot is deliberately not special-cased.** An earlier draft swallowed connection errors on `REBOOT_DEVICE`, on the theory that the router acknowledges then drops the link. An existing test caught it, and the test was right: that theory is untested, and a dropped link cannot be told from a router that was never reachable — so swallowing it would report "rebooted" for a command that never arrived, reintroducing the exact failure being removed. Reboot keeps its previous connection-error behavior and gains only the refusal check.
- **Static audit of all 20 `_request` call sites** found no further unguarded path. `get_all_data` relies solely on the all-empty detector, which is correct — it requests ~110 keys and has no single mandatory one. `get_rd`'s exception swallowing is now harmless: an empty `AD` makes the router refuse, and that refusal is now raised.

### Not in the public changelog — decision needed

Both defects were present in the released **3.2.5**, so by the "would a user on the last release have hit this?" test they qualify for a `Fixed` bullet in `CHANGELOG.md` `[3.3.1]`. Recorded here as an open decision rather than assumed either way.

## [3.3.1-dev5] - 2026-07-29 - Unreleased - No Manifest Bump - Thermal Set Completed to Five

Completes the thermal telemetry set following independent verification of the source research. The set is now defined by a statable rule rather than by which keys the research document happened to name.

### Added

- **Three further thermal diagnostic sensors**: `pm_sensor_mdm` (Modem Temperature), `pm_modem_5g` (5G Modem Temperature) and `pm_sensor_5g` (5G Radio Temperature), joining `pm_sensor_pa1` and `pm_sensor_ambient`. All five carry `DIAGNOSTIC`, `MEASUREMENT`, °C, guard bands of -40…125 °C, `about` notes, and **`entity_registry_enabled_default = False`**.
- **`api.py`**: The three new keys added to the `get_all_data()` batch poll.
- **`strings.json` / `translations/en.json`**: Names for all three, in both files.
- **`tests/test_sensor.py`**: The thermal tests now run over a single `_THERMAL_KEYS` tuple, plus `test_thermal_sensor_set_matches_the_descriptions`, which fails if a `pm_*` sensor is added without a test or a test without a sensor.

### Why five

Verified directly against `Kajkac/ZTE-MC-Home-assistant-repo`: its `const.py` names and gives °C units to exactly these five, and its live batch `cmd=` strings (`mc.py:560`, `mc.py:638-639`) request them. The rule is therefore "the thermal keys a sibling `goform` project polls with °C units", not a hand-picked subset. Note that `pm_sensor_pa2` and `pm_mdm` appear in local probe lists but are **not** Kajkac keys and are deliberately excluded.

**Caveat, recorded deliberately:** no model is yet confirmed to populate _any_ of these. A live MC7010 probe returns `""` for all of them, and the sibling project is only evidence that it _asks_, not that a router answers. All five are disabled by default precisely for that reason — the cost on the primary target hardware is zero.

### Verified

- 498 tests passing, **100% coverage**, `ruff`, `mypy --strict`, `codespell`, `prettier`, hassfest (`Invalid integrations: 0`).
- **Mutation-checked (dev_standards §11)**: deleting the `pm_sensor_5g` description fails the drift guard plus its three parametrized cases. Reverted.

### Changed

- **`docs/all_sensors.md`**: Three rows added; System count 23 → 26, total 78 → 81.
- **`docs/value_min_max.md`**: Three guard-band rows added.

## [3.3.1-dev4] - 2026-07-28 - Unreleased - Manifest Bump 3.3.0 → 3.3.1 - Release Preparation

Release preparation for 3.3.1. This is the first entry in this line to carry a manifest bump.

### Changed

- **`manifest.json`**: Version bumped `3.3.0` → `3.3.1`.
- **`api.py` login result type**: `_attempt_login()` now returns a `_LoginAttempt` named tuple carrying the session token alongside the two error classifications, instead of the caller re-reading `self.stok`. behavior is unchanged; the previous shape made mypy narrow `self.stok` to `None` across the retry and report the fallback's success branch as unreachable, which was a fair complaint about readability as much as types — which attempt produced the session is now explicit.
- **`sensor.py` band resolver typing**: `_band_or_channel_fallback()` takes a typed `Callable` rather than `Any`, so the return type is checked rather than inferred.
- **`docs/all_sensors.md`**: Added a `v3.3.1` version-history entry recording the two thermal entities and the count change.
- **`docs/value_min_max.md`**: Added a `v1.3.0` version-history entry recording the two temperature guard bands.

### Verified

- **Full validation suite green**: 488 tests passing, **100% coverage** (1643 statements, 0 missed), `ruff check`, `ruff format --check`, `mypy --strict`, `codespell`, `prettier --check`, and hassfest (`Invalid integrations: 0`).
- **Mutation-checked (dev_standards §11)**: three of the new guards were confirmed to fail when the thing they guard breaks — removing `Z5g_snr` from the batch-poll params fails both "every aliased key is requested" tests; reverting `_monthly_total_bytes()` to the un-aliased form fails the totals-agree-with-components test and two of the six-call-site cases; and reordering `_ARFCN_BANDS` so n77 precedes n78 fails four band-resolution cases. All mutations reverted.

### Deferred

- **`CHANGELOG.md`**: The public `## [3.3.1]` entry is deliberately **not** written yet, by instruction. Until it is, `manifest.json` reports 3.3.1 while the public changelog's newest entry is 3.3.0 — an intentional, temporary mismatch to be closed before release.
- **`docs/about_attribute_list.md`**: Still two entities behind (`pm_sensor_pa1`, `pm_sensor_ambient`), per the deferral recorded in `[3.3.1-dev1]`.

## [3.3.1-dev3] - 2026-07-28 - Unreleased - No Manifest Bump - Sensor Aliasing & Thermal Entities

Phase 3 of the cross-model compatibility expansion. On an MC7010 every existing sensor reads exactly as before — the primary key is always tried first — and the two new entities are off by default.

### Added

- **`sensor.py` cross-model key aliasing**: New `_get_first()` selects the first spelling the router actually populated, treating a present-but-empty value as absent (this API answers `""` for unsupported fields, so `in data` alone cannot distinguish "supported" from "reported"). Alias tuples are named constants so the set can be checked against `api.py` rather than being scattered through lambdas. Applied to 5G RSRP, 5G SINR, 5G PCI and **all six** monthly TX/RX call sites.
- **`sensor.py` band name fallback**: `wan_active_band` and `nr5g_action_band` fall back to `earfcn_to_band()` / `arfcn_to_band()` when the router reports a channel number but no band name. A name reported by the router always wins.
- **Two thermal diagnostic sensors**: `pm_sensor_pa1` (Power Amplifier Temperature) and `pm_sensor_ambient` (Ambient Modem Temperature), both `DIAGNOSTIC`, `MEASUREMENT`, °C, guard-banded to -40…125 °C, with `about` notes. **Disabled by default** — an MC7010 answers `""` for both, so on the primary target hardware they would only add two permanently-unknown entities to the UI.
- **`strings.json` / `translations/en.json`**: Names for both new sensors, added to both files.
- **`tests/test_sensor.py`**: Every alias reads through to its sensor; the primary spelling wins when both are present; all six monthly call sites honour the `flux_` spelling; the totals are proved to agree with their own components on either spelling; band fallback prefers the reported name, derives from the channel when absent, and reports unknown rather than guessing; the thermal sensors coerce `""` to unknown and carry their guard bands. Plus a check that every aliased key appears in `api.py`.

### Changed

- **`sensor.py` monthly totals**: The two total sensors previously inlined `int(data.get(...))` and are now shared via `_monthly_total_bytes()`. behavior is unchanged, but aliasing only the individual TX/RX sensors would have left the totals silently zeroed on `flux_`-spelling hardware — a divergence that would have looked like real data rather than a bug.
- **`docs/all_sensors.md`**: Added both thermal entities; System count 21 → 23, total 76 → 78.
- **`docs/value_min_max.md`**: Added guard band entries for both thermal sensors (-40 to 125 °C).

## [3.3.1-dev2] - 2026-07-28 - Unreleased - No Manifest Bump - API Params & Login Fallback

Phase 2 of the cross-model compatibility expansion. behavior on the MC7010 is unchanged except for SMS encoding, which now stops wasting more than half of every plain-text message.

### Added

- **`api.py` cross-model batch-poll keys**: Added ten keys to `get_all_data()` — `5g_rsrp`, `nr5g_rsrp`, `5g_sinr`, `nr5g_sinr`, `Z5g_snr`, `Z5g_CELL_ID`, `flux_monthly_tx_bytes`, `flux_monthly_rx_bytes`, `pm_sensor_pa1`, `pm_sensor_ambient`. These are the alternative spellings other `goform` models use, plus optional thermal telemetry. Requesting a key the router does not know is safe: it is simply absent from the response rather than an error, and an absent key cannot trip the "every value is an empty string" expired-session rule.
- **`api.py` best-effort login form fallback**: The login POST is now `_attempt_login()`, and `login()` retries once with the alternate `goformId` when the first form yields no session. Which form a router accepts is a per-model quirk and the tested-model list covers only MC801 and MC7010, so an unlisted router could previously be rejected purely for using the wrong form. A credentials rejection is **not** retried — the password is wrong whichever form carries it, and a second attempt only counts against routers that lock out.
- **`tests/test_api.py`**: Fallback fires in both directions, does not fire on a credentials rejection, does not fire when the primary form already worked, reports an auth error the fallback uncovers, and keeps a double unclassified failure as a connection error rather than an auth one. Plus SMS encoding selection, and a guard asserting every aliased key is actually requested and that no key is requested twice.

### Changed

- **`api.py:send_sms()` encoding selection**: `encode_type` is now chosen per message — `GSM7_default` when the text is entirely within the GSM 03.38 alphabet, `UNICODE` otherwise. It was previously hardcoded to `UNICODE`, which capped every message at 70 characters and needlessly split plain-text notifications that would have fitted in 160. `MessageBody` remains UTF-16BE hex for both encodings; `encode_type` selects the DCS and segment accounting, not the body format.

## [3.3.1-dev1] - 2026-07-28 - Unreleased - No Manifest Bump - Helpers & GSM-7 Inspector

Phase 1 of the cross-model compatibility expansion. Pure additions to `helpers.py` with no call sites yet — nothing in the integration's behavior changes until Phases 2 and 3 wire these in.

### Added

- **`helpers.py` GSM 03.38 inspector**: `is_gsm7()` and the `GSM7_CHARS` alphabet (basic plus extension table). Phase 2 uses this to choose `encode_type` for outgoing SMS, so a plain-text message gets its full 160 characters instead of being sent as UCS-2 at 70.
- **`helpers.py` channel-to-band resolvers**: `earfcn_to_band()` (3GPP TS 36.101 Table 5.7.3-1) and `arfcn_to_band()` (TS 38.104 Table 5.4.2.3-1), for routers that report a channel number but no band name. Both return `None` for missing, unparsable or out-of-range input rather than guessing, so the sensor reports unknown instead of a wrong band. NR ranges genuinely overlap (n78 sits inside n77), so `arfcn_to_band()` is explicitly best-effort and resolves ties by a documented order; a band name reported by the router always takes precedence.
- **`tests/test_helpers.py`**: Coverage for all three functions, including range edges, the n77/n78 overlap ordering, string and float-shaped inputs from the `goform` API, and the None-not-a-guess contract.

### Deferred

- **`docs/about_attribute_list.md`** is deliberately not updated in this release line, per project directive; it will be regenerated from `sensor.py` in a later release.

## [3.3.0-rc5] - 2026-07-28 - Unreleased - No Manifest Bump - AGENTS README About List and Expected Compatibility

### Changed

- **`README.md`**: Updated Acknowledgements and added a list of other ZTE Router integrations (these overlap) if this does not work for the user.
- **Compatibility**: Updated `README.md` expected compatibility list to clarify that a ZTE MC or MF in the `goform` API Family should work (although untested beyond the MC7010).

### Added

- **`about_attribute_list.md`**: Added a document to list all of the `about:` attributes.
- **`expected_zte_compatibility.md`**: Added a document to detail what additional ZTE Routers _should_ be compatible.

## [3.3.0-rc4] - 2026-07-28 - Unreleased - No Manifest Bump - Automation Example Glitch Guards & Float Rounding in README

Reinforced example automations in `README.md` to prevent false triggers during router reboots, network glitches, or entity unavailability, and rounded numeric outputs.

### Changed

- **`README.md` Layout & Collapsible Structure**:
  - Added `<details>` and `<summary>` tags to feature group subsections (`Advanced 5G/LTE Diagnostics`, `Data Usage Tracking`, `Essential Router Management`), individual SMS service actions (`send_sms`, `delete_sms`, `delete_all_sms`, `get_sms_list`) and event payloads, `Manual Installation`, and `Runtime Options` to shorten document length and improve reading flow.
  - Added always-visible summary text paragraphs above `<details>` tags for `Advanced 5G/LTE Diagnostics`, `Data Usage Tracking`, and `Essential Router Management` to provide immediate context when sections are collapsed.
- **`README.md` Example Automations Glitch Protection**:
  - **`Serving Cell Changed` & `Firmware Version Changed`**: Added `not_from` and `not_to` state trigger filters (`unknown` / `unavailable`) to ensure state transitions during reboots or network glitches do not fire false alerts.
  - **`Signal Quality Alert`**: Added `not_to` filters (`unknown` / `unavailable`) on state triggers and an overarching template condition verifying live network state data is valid before evaluating multi-entity degradation logic.
  - **`APN Failover` & `Auto-Reboot on Prolonged Outage`**: Added `not_from` filters for `unknown` and `unavailable` on `sensor.zte_5g_signal_wan_connect_status`.
  - **`Data Usage Alert` & `Morning Signal Report`**: Applied `| float(0) | round(0)` formatting to `sensor.zte_5g_data_monthly_total` so notification messages render clean whole-number data values instead of raw 8+ decimal place floats.

---

## [3.3.0-rc3] - 2026-07-28 - Unreleased - No Manifest Bump - `about` Notes on 63 Entities

Brings the `about` attribute suite to parity with `unifi_network_monitor` and `wifi_ssid_monitor`. **408 tests passing, 100% coverage, ruff clean, mypy strict clean.**

### Added

- **`ZTEAboutEntity` mixin** in `helpers.py`, ported from the two sibling projects — keep the three interchangeable. It resolves the note from `_attr_about` (single-instance entities) or an `about` field on the entity description (description-driven ones), and carries `_unrecorded_attributes = frozenset({"about"})` so the recorder never stores it.

- **57 description-level notes across the sensor platform**, concentrated where the entity name alone does not say what the value is:
  - **31 signal sensors** — every acronym decoded in place: RSRP, RSRQ, RSSI, SNR, SINR, PCI, CA/SCell, eNodeB, ENDC, MCC/MNC, APN, RSCP, NR-ARFCN.
  - **The signal metrics also carry typical ranges** — "better than -80 excellent, -80 to -90 good, -90 to -100 fair, below -100 poor". For siting a router that is the question actually being asked, and expanding the acronym alone does not answer it.
  - **11 data sensors** — chiefly the distinctions users get wrong: monthly versus session counters, the router's own count versus the ISP's billing, and why the raw byte sensors exist alongside the GB ones.
  - **9 system, 2 SMS, and the remainder of the signal group.**

- **6 control-entity notes via `_attr_about`** — Integration Health, Best Connection, Refresh Now, Reboot, Polling Interval, Pause Polling. These are the single-instance entities that half of the mixin exists for.

- **`about` field on `ZTESensorEntityDescription`**, and the mixin wired into the sensor, binary-sensor, button, number and switch entity classes.

### Changed

- **README documents the notes** under What You Get: where to find them (⋮ → Details), that the signal ones carry good/fair/poor ranges, and that they are unrecorded so they cost nothing to carry.

- **Every `extra_state_attributes` path now routes through `_with_about`.** A bare `return {}` on any branch would drop the note for that entity alone — the kind of gap that surfaces much later as "some entities have an about and some do not".

### Notes

- **Not every entity got one — 63 of 77.** Self-explanatory entities (Model Name, Hardware Version, LAN IP, Last Updated, unread-SMS count) were deliberately left without. A note on everything trains users to ignore notes.

- **Coverage regression caught and closed.** Adding only description-level notes left two statements in the mixin unreachable — the `_attr_about` branch and the mixin's default `extra_state_attributes`, neither of which any entity used. Rather than write tests for dead branches, the control entities above were given notes via `_attr_about`, which exercises both paths and matches how the siblings use the mixin (8 and 4 such uses respectively). Back to 100%.

- **Mutation-proved, and the first attempt was misleading.** Removing `about` from the mixin's `_unrecorded_attributes` alone did **not** fail the recorder sweep — because each entity class also lists `"about"` in its own set, matching UniFi's belt-and-braces pattern. Removing it from the mixin **and** every class set turns the sweep red, which is what confirms the guard is real rather than incidental.

- Two existing tests asserted `extra_state_attributes == {}` for sensors that now carry a note; both updated, and a new test added asserting that a sensor with **no** `about` still publishes nothing — guarding the other half of `_with_about`.

## [3.3.0-rc2] - 2026-07-28 - Unreleased - No Manifest Bump - External Code Review Triage

Triage of `.notes/code_review/code_review_20260728_0019.md` (external agent, 0 findings + 3 architectural observations). **407 tests passing, 100% coverage, ruff clean, mypy strict clean.** Two of the three observations were declined with reasons; the review's most useful effect was prompting a measurement that settled one of them, and a re-read that found a defect the review missed.

### Fixed

- **`docs/zte_how_to_access.md` contradicted itself about session expiry.** Its "Session expiry — three different signatures" table still described the **named-key** rule (`network_type` and `signalbar` both empty) while the Gotchas section added in `[3.3.0-dev12]` correctly described the generalized "every value is an empty string" rule. Introduced by me in dev12: the new section was added without updating the table above it.

  This matters more than a normal doc slip — `AGENTS.md` points at this file as the authority on the API's failure modes, so the stale table was the one an implementer would find first. Corrected, with an explicit note on why the named-key form was blind and an instruction not to narrow it back.

### Changed

- **The 150-second idle reset is now `SESSION_IDLE_RESET_SECONDS` in `const.py`**, not a bare literal in `api.py`. The project's other thresholds (`FETCH_STRIKE_LIMIT`, `UNREACHABLE_STRIKE_LIMIT`) already live there, and `code_review.md`'s own category 4 flags inline timeouts — a finding the external review did not make while recommending a change to that very line.

- **The value is now documented as measured rather than assumed.** A session left idle for **200 seconds** was already dead on MC7010 firmware `V1.0.0B03` (2026-07-28) — the router answered `200 OK` with every value blank. The real boundary is therefore at or below 200s, so 150s sits safely under it and under the 180s default scan interval.

- **`async_get_sms_list` now records why it fetches in full.** Tag filtering happens client-side, so server-side pagination would return fewer than `count` messages once filtered; a combined box must also merge both stores before it can sort by date. The behavior is necessary, not an oversight, and now says so.

### Notes

- **Observation 1 (remove the idle timer) — declined, and the measurement shows it would be a regression.** The review proposed dropping the proactive reset and relying solely on the reactive expiry detection in `_request`. That is **more** traffic, not less: reacting costs a failed request, a login, then a retry — three round trips, where preempting costs a login and a request. It also removes the second line of defense on a router whose expired-session response is indistinguishable from success at the HTTP layer, which is precisely the failure `[3.3.0-dev12]` fixed. The review's premise — "firmware keeps sessions valid for 180 seconds" — was unsourced; the measured result is that 200s is already dead. A warning against this change is now in `const.py` beside the value.

- **Observation 2 (SMS full fetch) — declined, no code change.** The concern is directionally fair but the review missed the constraint that makes the behavior necessary: client-side tag filtering. Recorded as a comment rather than changed.

- **Observation 3 (adopt `via_device_link` for sub-devices) — factually wrong; already done.** The review states `helpers.py` line 45 builds `DeviceInfo` with `via_device=(DOMAIN, entry.unique_id)`. It does not: `helpers.py:10` imports `via_device_link` from `._compat` and line 87 calls it, with a comment naming the 2026.8 deprecation and the 2027.8 removal. That work landed in `[3.3.0-dev4]`, and the review is dated after it. Line 45 is inside `get_router_model`'s model-matching loop. **No change made — the recommendation was to do something already done.**

## [3.3.0-dev14] - 2026-07-27 - Unreleased - No Manifest Bump - doc_update Reconciliation Pass

Produced by a `doc_update` run over the whole `[3.3.0-dev1]`–`[3.3.0-dev13]` cycle. Documentation only; **407 tests passing, 100% coverage.** Both findings are statements that were true when written and had since become false — the class a purely additive documentation pass cannot find.

### Fixed

- **`AGENTS.md` described the pre-`[3.3.0-dev12]` session-expiry rule.** It said `_request` detects expiry via "HTML redirect, unparsable JSON, or empty/`fail` status fields" — the **named-key** form, which is exactly the wording whose logic could never fire on an SMS response. `_require_contract()` was not mentioned at all.

  This is the file an agent reads before touching `api.py`, so the stale description actively invited re-narrowing the detector — the single thing dev12 warns against. Now states the rule as **"every value is an empty string"**, gives both dead-session shapes, explains why the named-key form was blind, documents the contract assertion as the second defense, and says plainly: never reintroduce a `.get(key, [])` fallback on those paths.

- **README's Integration Health note omitted the `drift` attribute**, published since `[3.3.0-dev6]`. The `note:` listed `severity`, `degraded_capabilities`, `repairs` and `consecutive_failures` — so a user reading it had no way to know `drift` existed.

  **Same defect class that started this week's cross-project work, in mirror image.** `unifi_network_monitor`'s README named attributes its coordinator never wrote; this named fewer than the coordinator publishes. Both come from a README drifting from the code it documents, which is why `dev_standards` §19 now requires documented examples to be diffed against the implementation.

### Changed

- **README § Session Handling now covers automatic session recovery.** It described only logout-on-unload. Because the router permits one session, using its web UI ends the integration's — and the router signals that by answering `200 OK` with empty values rather than erroring. The section now explains that the integration detects this, re-logs in and retries once, and that a request which genuinely cannot be completed **raises** rather than returning empty data.

### Notes

- **A `doc_update` blind spot worth knowing:** `.notes/` is gitignored (`.gitignore:88`), so changes to `proj_structure.md` are **invisible to `git status`**. Anyone using git as their only change signal would conclude that file was untouched. The prompt's other three signals cover it, which is why it requires all four.
- No new-entry duplication: dev1–dev13 already recorded the session's work, so this entry covers only the two corrections and the README addition. `all_sensors.md`, `value_min_max.md`, `DEVELOPMENT.md`, `proj_structure.md` and `zte_how_to_access.md` were assessed and correctly skipped — no entity, guard-band or structural change since each was last updated.
- Neither `README.md` nor `AGENTS.md` carries a `## Version Control` section, so neither received a version entry.

## [3.3.0-dev13] - 2026-07-27 - Unreleased - No Manifest Bump - Records Caught Up After a Long Session

Documentation only, closing the loose ends left by twelve dev entries in one day. **407 tests passing, 100% coverage.**

### Fixed

- **`DEVELOPMENT.md` §7 stated a deviation that had been retired hours earlier.** The "§3 Root Identity Deviation" entry described the `{imei}_system` root as an accepted deviation from `dev_standards` §3 — but §3 was amended at **Standard Version 1.15.0** the same day and the cell moved to `DONE`. Rewritten as "resolved, no longer a deviation", with the reasoning (the ladder had no rung for a non-MAC hardware identifier and would have routed this integration to a **worse**, IP-keyed root) and an explicit **"do not 'fix' this to an IP-keyed root."**

- **`DEVELOPMENT.md` §7 pointed at a file that no longer exists** — the custom-trigger analysis, which moved twice today: out of `.notes/issues/` to `.shared/issues/`, then into the new `x_project/` queue. Now `.shared/issues/x_project/custom_trigger_options.md`.

- **`.notes/proj_structure.md` was stale within hours of being updated.** Its own `v1.1.1` entry was written this morning and recorded `test_binary_sensor_health.py` — a file renamed to `test_integration_health.py` later the same day — so the table listed something that does not exist. Also missing: **`_compat.py`**, a _source_ file absent since it landed; `docs/zte_how_to_access.md`; and `tests/test_compat.py`. All added, rename corrected, `v1.1.2` entry appended.

### Changed

- **`DEVELOPMENT.md` §5 gained the expired-session pitfall** — the `[3.3.0-dev12]` defect written up as a pitfall rather than only as a changelog entry, because §5 is where someone looks when the same class of thing happens again. Carries the rule that matters: **never narrow the expiry detector back to named keys**, and the reason an empty inbox (`{"messages":[]}`) stays distinguishable from a dead session.

- **README documents the behavior change in `get_sms_list`.** It now **raises** when the router cannot be reached or the session has expired, instead of returning an empty list. That is the point of the fix — an automation can tell "no messages" from "could not ask" — but it is user-visible, so the response table now says so and points at `continue_on_error: true` for anyone who would rather the automation carry on.

### Notes

- Final sweep for stale references across ZTE markdown found nothing further; the remaining `STRIKE_LIMIT` matches are the legitimate `FETCH_STRIKE_LIMIT` / `UNREACHABLE_STRIKE_LIMIT` constants. Changelog entries were left pointing at old paths deliberately — they are historical records.

## [3.3.0-dev12] - 2026-07-27 - Unreleased - No Manifest Bump - Expired Session Returned "No SMS"

**User-reported and reproduced.** `get_sms_list` returned an empty list while messages were present on the router; pressing **Refresh Now** and retrying then worked. **407 tests passing, 100% coverage, ruff clean, mypy strict clean.**

### Fixed

- **An expired session made SMS actions report "no messages" instead of failing.** The session-expiry detector in `_request` tested two **named** keys — `network_type` and `signalbar` — which only exist in the batch-poll response. An SMS response has neither, so `.get()` returned `None`, `None == ""` was `False`, and the detector could never fire on that endpoint. The dead-session body was returned intact, `.get("messages", [])` yielded `[]`, and the action reported an empty inbox.

  **Why Refresh Now was a workaround, and why that proves the diagnosis:** Refresh Now runs the batch poll, whose keys the detector _did_ recognize — so it re-logged in and repaired the session, after which SMS worked. Detection existed on one endpoint and not the other; that asymmetry is exactly what was observed.

  Two aggravating factors: `_request` then set `last_activity = now`, so the client **recorded a dead session as healthy** and pushed the 150s inactivity guard forward, masking it further. And the 150s guard only fires when >150s have passed since the last _successful_ request — this router permits **one session**, so opening its web UI kills the integration's session instantly, and acting within 150s of a poll leaves the guard quiet.

- **Detector generalized to the router's actual dead-session shape.** Captured by replaying an invalidated `stok` against an MC7010 on firmware `V1.0.0B03` (2026-07-27) — every dead-session response is **HTTP 200** with the requested keys **echoed back empty**:

  | Request | Live session | Dead session |
  | :-- | :-- | :-- |
  | `sms_data_total` | `{"messages":[…]}` | `{"sms_data_total":""}` |
  | `sms_data_total`, empty box | `{"messages":[]}` | `{"sms_data_total":""}` |
  | batch poll | real values | `{"network_type":"","signalbar":"","wan_ipaddr":""}` |
  | `sms_capacity_info` | real values | `{"sms_capacity_info":""}` |

  The rule is now **"every value is an empty string"**, which covers all three shapes. `Content-Type` is `text/html` even on valid responses, so it carries no signal — that is why the existing HTML check has to inspect the body.

- **Endpoint contract assertions — a second, independent defense.** `_require_contract()` makes each SMS call assert the key it must receive (`messages`, `sms_nv_total`) and raise `ZTEConnectionError` if absent. `get_sms_messages`, `get_last_sms_content`, `delete_all` and `get_sms_capacity` no longer fall back to an empty default on a failure path — the `masked_errors_check` Class A rule. This holds even if the router's dead-session shape changes and slips past detection.

  Consequence worth noting: a persistent failure now raises into `_fetch_optional`, so the SMS endpoint burns its own strike budget and its entities go **unavailable** (§8) rather than displaying an empty inbox — and the Integration Health sensor reports it.

### Changed

- **Two existing tests asserted against payload shapes the router never returns** — `{"cap": 100}` for SMS capacity, in `test_api.py` and `test_coverage_ext.py`. Both now use the real captured shape. A fabricated fixture is how an unasserted contract stays unasserted: the test passed, and told you nothing about the endpoint.

### Added

- **Six regression tests** built from the **real captured payloads**, with a comment forbidding anyone from "tidying" them into something more plausible-looking — their exact shape is the point. They cover: every dead shape satisfying the rule; an empty inbox and a populated inbox **not** satisfying it (over-correction guard); the reported bug end to end (dead → re-login → real messages); a persistently dead session raising rather than returning `[]`; and a missing contract key raising even when expiry goes undetected.

### Notes

- **Mutation-proved, three ways** (§11 bar): reverting the detector to the named-key form → **red**; removing the contract assertion → **red**; reverting both, i.e. the exact pre-fix code → **red**. Each defense fails the suite independently, so neither is load-bearing alone.
- **Live-verified against the router**: session deliberately killed from a second client with `last_activity` kept fresh — the precise reported condition — then `get_sms_messages()` logged _"Session expired in JSON response; renewing session"_ and returned both real messages.
- **You remembered this correctly: it was fixed on `huawei_router_5g`**, which wraps every action in `_execute_with_retry` (re-login, retry once). That could not be ported — Huawei's library **raises** `ResponseErrorLoginRequiredException`, so there is something to catch. ZTE's `goform` API returns `200` with a benign body, so the fix had to be **detection**, not retry.
- **Not a cross-project item, checked rather than assumed.** `unifi_network_monitor` raises on a real `401`; `wifi_ssid_monitor` already flags a missing `accesspoints` key into its health checks (`payload_no_ap_list`) rather than swallowing it; `huawei_router_5g` uses a library that raises. ZTE's goform API is the only one in the family that answers an auth failure with `200 OK` and a plausible body. Deliberately **not** added to the `x_project` queue — it fails the entry criteria.

## [3.3.0-dev11] - 2026-07-27 - Unreleased - No Manifest Bump - Device-Registry Record Cross-Referenced

**No code changed.** Documentation only — the HA 2026.8 device-registry analysis has been split out of `unifi_network_monitor`'s notes into `.shared/issues/device_registry_2026_08.md`, and this project's `AGENTS.md` now points at it.

### Changed

- **`AGENTS.md` — Device Identity Model section rewritten.** It had **no mention of `_compat.py` at all**, despite this integration having shipped the shims in `[3.3.0-dev4]`. An agent reading it would not have known the parent link goes through a version shim, and could reasonably have "simplified" `via_device_link(...)` back to a raw `via_device` tuple — which warns from HA 2026.8 and breaks at 2027.8.

  Now records: the two shims (`via_device_link`, `device_by_identifier`); that `owning_entry_ids` is **deliberately absent** because this integration never reads `device.config_entries` and an unused shim is dead code against a 100% coverage bar; and a pointer to the shared record for the family analysis and the 2026.8.0 re-verification checklist.

- **The System-as-root topology is now stated as conformant**, with an explicit instruction not to "fix" it to an IP-keyed root. `dev_standards` §3 at Standard Version 1.15.0 ranks a stable non-MAC hardware identifier such as IMEI equal to a MAC; the earlier ladder implied the IP fallback, which would have been strictly worse. Written into `AGENTS.md` because that is the file an agent reads before touching device identity.

### Notes

- This project's status in the shared record is **DONE** — two of three shims, the third correctly not applicable. Nothing outstanding here.
- The shared record carries an **open family action**: re-verify the shims natively once HA 2026.8.0 is available in a devcontainer. The current implementation is verified against the HA `dev` branch and mock-patched flags, not a real 2026.8 build.

## [3.3.0-dev10] - 2026-07-27 - Unreleased - No Manifest Bump - §3 Deviation Retired

**No code changed.** `dev_standards` **1.15.0** amends §3's root-identity ladder; this integration's `PARTIAL` and its Project Deviation are withdrawn as a result. **The deviation described a gap in the standard, not in this project.**

### Notes

- **§3 moves `PARTIAL` → `DONE`, and the Project Deviation entry is retired.** The root stays exactly as it is: a single device named `"<title> System"`, keyed `{imei}_system` (`__init__.py:349`), with Signal/Data/SMS as sub-devices. Nothing about this integration changed.

- **What was wrong was the ladder.** It offered two rungs — MAC, else host/IP "when the MAC cannot be obtained". The `goform` API never exposes a MAC, so a literal reading routed this integration to an **IP-keyed root**. That is strictly worse than the IMEI it uses today, contradicts §3's own opening line ("the strongest available hardware identity"), and is precisely the failure §2 exists to prevent. The ladder now has a rung for a stable non-MAC hardware identifier, ranked **equal** to MAC rather than beneath it.

- **On multi-interface hardware, IMEI is arguably the better key anyway.** A router has separate LAN / WAN / WiFi MACs and "the" MAC is ambiguous; an IMEI is singular and permanent.

- **The second objection had already expired.** §3 said a `{id}_system` root "can never merge" with a core integration. HA **2026.8 stops merging on `connections`**, and this family removed `CONNECTION_NETWORK_MAC` from every project ahead of that change — it appears in zero source files across all three. So that argument no longer distinguishes the options for anyone. §3 now names both **hardware-as-root** (UniFi, Gateway at the top) and **System-as-root** (this project, Huawei) as valid, with the real requirement stated plainly: the identifier before any suffix must be a stable hardware ID, and a synthetic root must never displace an unrepresented physical device.

- **Section Conformance is now 19 `DONE`, 1 `N/A` (§21), 1 `PENDING` (§15).** §15 Feature-Group Toggles is the only outstanding item and is **parked by decision** — a large piece of work for a group most users are unlikely to disable. It remains the single Project Deviation on record for this integration.

## [3.3.0-dev9] - 2026-07-27 - Unreleased - No Manifest Bump - §9 Secret Pre-fill Guard

Closes the last outstanding `**Test:**` tag for this project. **398 tests passing, 100% coverage, ruff clean, mypy strict clean.** This is now the first project covering **every tagged section that applies to it** — §6, §9, §10, §12, §14 `DONE`, §21 `N/A`.

### Added

- **`test_stored_secrets_are_never_pre_filled`** — feeds both `_user_schema` and `_edit_schema` an entry containing a sentinel password and asserts no secret-typed field carries it, either as a voluptuous `default` or as `description={"suggested_value": ...}`.

  **The behavior was already correct** — `_edit_schema` declares `CONF_PASSWORD` with `default=""` and documents why in its docstring, and `_merge_credentials` fills a blank field from the stored value. Nothing was broken. What did not exist was a guard, and this is a change someone makes in good faith: pre-filling the field looks like a convenience improvement, the screen looks right afterwards, and the stored password is exposed only when a user clicks the eye icon. `dev_standards` §9 records two projects having shipped exactly that.

- **`test_no_field_leaks_the_stored_secret`** — asserts the sentinel appears nowhere in the rendered schema at all. The first test only inspects fields already known to be secret; this one catches the other shape, a stored password copied into a **non-secret** field, where the eye icon is not even needed to read it.

  Both schemas are checked, including `_user_schema`. It takes a defaults dict today but is only called with `None` on the initial-setup path — covering it means a future change that starts seeding it from a stored entry is caught immediately rather than becoming a new hole.

### Notes

- **Mutation-proved against three separate regressions** before being recorded `DONE`, per the §11 bar:
  - `default=defaults_dict.get(CONF_PASSWORD, "")` — the classic "helpful" pre-fill → **red**
  - `description={"suggested_value": defaults_dict.get(CONF_PASSWORD)}` — the subtler form → **red**
  - the stored password copied into the **username** field's default → **red**, caught only by the second test, which is why both exist

  `config_flow.py` restored and verified byte-identical afterwards.

- **Deliberately narrow.** §9's host-normalization bullet is **not** covered here and is not tagged in the standard — a doubled `configuration_url` is visible, so it fails the "silent" half of the tagging rule. `test_clean_host` already covers it anyway.

- **Reference implementation for the other two projects**, both of which are `PENDING` on §9. Neither has the defect today — UniFi's three `suggested_value` uses are rogue-AP ignore lists, and WiFi uses `suggested_value` nowhere — so this is a guard against a plausible future change, not a fix.

## [3.3.0-dev8] - 2026-07-27 - Unreleased - No Manifest Bump - §12 Icon Sweep Made Real

Accompanies `dev_standards` **1.13.0 / 1.14.0**, which introduce the `**Test:**` tag — a per-section statement of the automated check that section requires — and name this project as the reference implementation for §12 and §14. **394 tests passing, 100% coverage, ruff clean, mypy strict clean.**

### Fixed

- **The §12 icon test was blind on five of six platforms.** `test_every_entity_without_a_device_class_has_an_icon` iterated `SENSOR_TYPES` — the sensor platform only — so the icons for **15 entities** across `binary_sensor`, `switch`, `select`, `number` and `button` could be deleted with the suite still green.

  It was also blind in a second direction: it flattened `icons.json` into a single set of keys across all platforms, so an entry filed under the **wrong** platform satisfied the check.

  Found by a validation agent reviewing the standards change, then confirmed by mutation. This is the same defect class the new §11 rule was written for — a test that looks like coverage and is not — and it mattered more than usual because the standard was about to cite this test as the thing for other projects to copy.

- **Replaced with `test_every_live_entity_has_an_icon_or_a_device_class`**, a runtime sweep over live entities checking each entity's own platform. Entity descriptions here live in a mix of tuples (`SENSOR_TYPES`, `BINARY_SENSORS`, `SWITCH_TYPES`, `SELECT_TYPES`) and module-level singletons (`POLLING_INTERVAL_DESCRIPTION`, `REBOOT_DESCRIPTION`, …), so any static enumeration drifts the moment one is added. Sweeping live entities is the only form that cannot.

  **Mutation-verified across every platform:** deleting the `icons.json` entry for `binary_sensor`, `switch`, `select`, `number` and `sensor` each turns the test red. `button/system_reboot` is correctly _not_ caught — it carries `ButtonDeviceClass.RESTART` and so derives its icon from the device class, which is the standard's own exemption. Its `icons.json` entry is therefore redundant but harmless.

- **The superseded static test was deleted**, not left alongside. A weak test kept for reassurance is exactly the failure mode being fixed.

### Changed

- **`_live_entities` extracted** as a shared async context manager, now used by both the §12 and §14 sweeps. Both need the same live entity list and both are worthless without the `entity_registry_enabled_default` patch, so the setup lives in one place rather than being copied and drifting apart.

### Notes

- **This project is `DONE` on four of the six tagged sections, and both new `DONE` cells were mutation-proved before being recorded** — §6 (deleting the rounding in `_safe_float` turns `test_safe_float_rounds_at_parse_time` red) and §10 (replacing `await coordinator.api.logout()` on unload turns `test_init` and `test_options_lifecycle` red). Files restored and verified byte-identical afterwards.
- **§9 is `PENDING` here**, as it is everywhere: no project asserts that stored secrets are absent from a rebuilt options/reauth schema. This project uses `suggested_value` nowhere, so there is no defect today — only no guard against one.

## [3.3.0-dev7] - 2026-07-27 - Unreleased - No Manifest Bump - §14 Attributes Are Unrecorded by Default

Implements `dev_standards` §14 as revised at **Standard Version 1.12.0**: `_unrecorded_attributes` must cover every key an entity can publish, with no per-attribute judgement and no undocumented exceptions. **394 tests passing, 100% coverage, ruff clean.**

### Fixed

- **The reboot-schedule binary sensor recorded four attributes** — `reboot_hour1`, `reboot_min1`, `reboot_hour2`, `reboot_min2`. `ZTERouterBinarySensor` declared no `_unrecorded_attributes` at all, so every attribute its descriptions produce was written to the recorder on each state change.

  **Nothing had found this before, including the static sweep run earlier in this session.** The attributes come from an `extra_attrs_fn` lambda on the entity description, so there is no dict literal in the class for a source-reading check to see; and the entity is disabled by default, so it is never instantiated in an ordinary test run. It took the runtime sweep below, with disabled-by-default entities forced on, to surface it.

### Changed

- **`sntp_server1` and `sntp_dst_enable` are now unrecorded.** They were the one documented exception in this project, justified as "static configuration, cheap to store, worth seeing in history". §14 1.12.0 withdraws that reasoning: attributes carry detail about something that does not merit its own entity, but they are not a history mechanism — retrieving historical attribute values is advanced HA work, and a value whose history is genuinely wanted should be an entity or a user template sensor. `test_every_attribute_the_sensor_emits_was_evaluated` is renamed to `..._is_unrecorded` and no longer carries an exception set.

### Added

- **`test_no_entity_publishes_a_recorded_attribute`** — a runtime sweep that sets up the integration against a real `hass`, iterates every live entity, and asserts each published attribute key appears in that entity's `_unrecorded_attributes`. `ALLOWED_RECORDED` is an explicit, currently-empty allow-list, so granting an exception is a visible act while forgetting one is not.

  **Two details that decide whether this test is worth anything:**
  - It patches `Entity.entity_registry_enabled_default` to `True` so disabled-by-default entities are added. **Verified by mutation:** with a key removed from a disabled-by-default sensor's set, the sweep passed until this patch was added — the test was silently skipping a whole class of entities. Adding it immediately failed, and surfaced the reboot-schedule defect above.
  - It asserts `checked >= 3`. A sweep whose fixture stops producing attributes passes vacuously and keeps passing after a real regression; the floor makes that failure loud.

  Re-verified by mutation after both fixes: removing a single key from `_unrecorded_attributes` fails the sweep.

## [3.3.0-dev6] - 2026-07-27 - Unreleased - No Manifest Bump - §19 `drift` Attribute

Closes the gap flagged in `[3.3.0-dev5]`. **393 tests passing, 100% coverage, ruff clean, mypy strict clean.**

### Added

- **The health sensor now publishes a `drift` attribute** (`dev_standards` §19, normative attribute table added at Standard Version 1.11.0). That table makes `drift` conditional — omit it only where no drift check exists. This integration runs one, `_check_contract_drift`, and it already backed the `firmware_contract_drift` repair and wrote a line into `issues`; the finding simply had nowhere of its own to be read from. A template could see that _something_ was wrong, and could see the repair key, but could not distinguish "the firmware changed shape" from "an endpoint is down" without string-matching the `issues` prose.

  `drift` is a list, empty when healthy, carrying the finding on the success path. On the **failure** path it is reported empty rather than held from the last cycle: no payload arrived, so no drift verdict is possible, which matches the existing `_active_repairs(False)` call beside it. Both defensive fallback snapshots carry the key too, so the attribute can never be absent — an attribute that vanishes under load is a contract violation exactly when a user is looking at it.

- **`DRIFT_CONTRACT` constant** in `coordinator.py`. The message is published in two places — `drift` and `issues` — and a literal repeated at two sites is one edit away from disagreeing with itself.

- **`test_publishes_the_section_19_attribute_contract`** — asserts the §19 names are present, with the reasoning in the docstring for why `auth_mode` is legitimately absent here (single auth mode) and `drift` is not. The existing drift test now also asserts the attribute is set when the repair raises and cleared on recovery. Without a test naming the contract, the next rename is silent again — which is how this gap arose.

### Changed

- **`drift` added to `_unrecorded_attributes`.** Caught by the existing `test_attributes_are_unrecorded`, which walks the published attributes and asserts each is excluded from the recorder — the test did its job on the first run.

## [3.3.0-dev5] - 2026-07-27 - Unreleased - No Manifest Bump - Interface Documentation

Documentation and agent-guidance only — no source or test files changed, so no re-validation of the suite was required. Markdown checks (prettier, codespell) clean.

### Added

- **`docs/zte_how_to_access.md` — a full reference for navigating the ZTE `goform` interface.** Written against `api.py` and the behaviors verified on live hardware during this week's work, using `unifi_network_monitor`'s `docs/api_endpoints.md` as the template.

  **The structure had to diverge from that template, and the reason is the most useful thing in the document.** UniFi's reference is organized by URL because that API has a URL per resource. ZTE has exactly **two** endpoints — `goform_get_cmd_process` for reads and `goform_set_cmd_process` for writes — and the actual resource is named in a `cmd=` or `goformId=` parameter. So the document is organized by command, and says so at the top: all read traffic is indistinguishable in a proxy log until you read the query string, which is a real obstacle when debugging and is not apparent from the code.

  Covers: the four-step SHA-256 login chain and why `LD` and `wa_inner_version` are fetched unauthenticated; the `LOGIN` vs `LOGIN_MULTI_USER` model split; the post-login initialization GET that some firmware requires before it will accept a POST; the single-session constraint and why it makes a logout unverifiable through the web UI; the three distinct session-expiry signatures; the `AD` token derivation with its second model-dependent branch (MD5 vs SHA-256); all 100 batch-poll parameters grouped by the entities they feed, in collapsible `<details>` sections; every `goformId`; and what is deliberately not called, with rationale.

  **The section that earns its place is "Gotchas."** This API fails soft everywhere — an unknown `cmd`, a missing `AD` and an expired session all return `200 OK` with an empty field or `{"result":"failure"}`. The `AD` behavior is recorded with the evidence: confirmed on MC7010 firmware `V1.0.0B03` using `LOGOUT`, where the call without `AD` returned failure and left the `stok` live, and with `AD` returned success and genuinely invalidated it.

### Fixed

- **`AGENTS.md` referenced `STRIKE_LIMIT`, which no longer exists.** The `[3.3.0-dev4]` rename to `FETCH_STRIKE_LIMIT` (and the move to `const.py`) did not update this file, so the one document an agent reads first named a constant that would fail to import. Now names the constant and its module. Found while adding the cross-link below — the kind of stale reference a rename leaves behind precisely because the file is prose rather than code and nothing type-checks it.

### Changed

- **`AGENTS.md` links to the new interface reference** from the `api.py` section, matching how `unifi_network_monitor` surfaces `docs/api_endpoints.md`.

### Notes

> [!IMPORTANT] **An open §19 gap was found while writing this entry, and is not yet fixed.** `dev_standards.md` **1.11.0** (this session) made the Integration Health attribute set a normative table, and one row is a conditional: `drift` may be omitted **only where no drift check exists**. This integration runs one — `_check_contract_drift`, backing the `firmware_contract_drift` repair — but its health sensor does not publish a `drift` attribute (`binary_sensor.py:226`). `unifi_network_monitor` publishes it; `wifi_ssid_monitor` has the same gap.
>
> This is not a regression from the `[3.3.0-dev4]` alignment. That pass compared the attribute names the three projects **had**, and could not ask which ones were **missing**, because no list of required names existed until 1.11.0. It is the first finding produced by the new table, which is a fair indication the table was worth writing.
>
> Deliberately left open rather than fixed inside a documentation-only entry: it changes a published contract and needs a test.

## [3.3.0-dev4] - 2026-07-27 - Unreleased - Cross-Project Alignment

Follows a three-way review of `zte_router_5g`, `unifi_network_monitor` and `wifi_ssid_monitor`, checking that the three meet the shared standards the **same way** rather than merely meeting them. The functionality differs by design; the approaches should not. Seventeen of the 21 `dev_standards` sections were already identically DONE — these are the divergences that were not deliberate.

### Changed

- **Health-sensor attribute renamed `degraded` → `degraded_capabilities`** (dev_standards §19). The standard names the attribute "degraded capabilities", and `unifi_network_monitor` already used the full name. Three projects had drifted to three vocabularies for the same concept, which meant an automation written against one did not transfer to another. All three now publish the identical six-key contract: `problem`, `issues`, `severity`, `degraded_capabilities`, `last_good_update`, plus per-project extras. Not a breaking change here — the ZTE health sensor has not shipped.
- **Strike-limit constants moved to `const.py` and renamed `STRIKE_LIMIT` → `FETCH_STRIKE_LIMIT`**, matching `unifi_network_monitor`, which already had the constant under that name and in that file. `UNREACHABLE_STRIKE_LIMIT` moved alongside it. Tests import both from `const` rather than from `coordinator`. No behavior change — the values are unchanged at 3 and 10.
- **`tests/test_binary_sensor_health.py` renamed to `tests/test_integration_health.py`.** New convention across all three projects: name the test file after the **standard** it covers, not the platform or the symptom. The same rename landed in the other two.

### Added

- **`_compat.py` — device-registry compatibility shims**, ported from `unifi_network_monitor`, which implemented and validated the pattern first. HA 2026.8 deprecates the `DeviceInfo.via_device` identifier tuple and the ambiguous `async_get_device(identifiers=…)`; both are **removed in 2027.8**. This integration used the deprecated forms in `helpers.build_device_info` and in the coordinator's hardware-metadata refresh, so it would have warned from 2026.8 and broken at 2027.8.
  - `via_device_link()` and `device_by_identifier()` feature-detect the HA **class** (not an instance, so a `MagicMock` registry in tests cannot fool them) and use the new API where present, the old one otherwise. **No version floor** is introduced.
  - UniFi's third shim, `owning_entry_ids()`, is deliberately **not** carried over — this integration never inspects a device's owning entries, and an unused shim is dead code against a 100%-coverage bar.
  - Registry and entry id are resolved from the coordinator inside `build_device_info`, so no new argument had to be threaded through the entity call sites.
  - `tests/test_compat.py` forces **both** branches by patching the detection flag, so the path the installed HA does not take is still exercised — the point of a floor-free shim being that it must be correct on ≤2026.7 and post-2027.8 alike.

### Documentation

- README updated for the `degraded_capabilities` rename.

### Tests

- **386 → 392**, coverage **100%** maintained.

### Notes

- **`_compat.py` deliberately omits the `owning_entry_ids` shim** — see above. If a future feature inspects device ownership (a cleanup path, for instance), port it then rather than preemptively.
- Two further alignment items were identified and are **not** in this release: §15 SMS feature-group toggle (recorded PENDING, a Guideline rather than a Gap) and the deferred custom-trigger work.

## [3.3.0-dev3] - 2026-07-27 - Unreleased - Unreachable Repair & Record Corrections

Follows a consolidated review of everything not marked DONE across both standards. One real gap was found and closed; two records were corrected.

### Added

- **`router_unreachable` Repair Issue**: raised after **10 consecutive failed fetches**, with `IssueSeverity.ERROR`, and cleared by the next successful poll.
  - **Why this was a gap.** Because of the Section 1 non-blocking-startup departure, `async_setup_entry` always returns `True` — so a router that has become permanently unreachable presents as _"integration loaded, every entity unavailable"_ with no prompt anywhere. The Integration Health sensor turns on, but only a user who knows to look at a diagnostic binary sensor would see it. Nothing told them to act.
  - **Why 10 and not 3.** The 3-strike threshold governs entity _unavailability_ and is reached in a few minutes — a Repair there would fire on every router reboot, which is exactly the Repairs-panel noise Section 19 warns against. Ten consecutive failures is the point at which the condition has demonstrably stopped resolving itself, which is what makes it _serious, named and actionable_ under Section 19's second tier.
  - **The text is deliberately cause-agnostic.** Ten failures does not mean "the IP changed" — it means the router is not answering. The Repair says so, then lists what to check in rough likelihood order: power-cycle the router; check whether its IP has changed (the configured host is named in the text so it can be compared directly, with a DHCP reservation suggested as the permanent fix); check whether the password changed; check the network path. **Reconfigure** is offered for the two cases where it is the answer, rather than presented as the answer.

### Changed

- **`stale-devices` recorded as N/A rather than REJECT** (compliance matrix; `quality_scale.yaml` stays `exempt`, which is the only value HA's vocabulary provides). REJECT is a family-level _policy_ — "devices persist intentionally; user controls removal" — and it had been copied down verbatim. It does not describe this integration: the four sub-devices come from a fixed group list, the integration never enumerates clients behind the router, and replacing the router mints a new IMEI and therefore a new config entry whose removal takes its devices with it. **Nothing can become stale, so there is no removal policy to decline.** The comment now says that, and flags that it stops being true if Section 15 feature-group toggles are implemented — disabling a group would orphan its sub-device.

### Records

- **`dev_standards.md` §15 Feature-Group Toggles: N/A → PENDING.** The original N/A claimed _"no optional functional groups exist"_, which is false. **SMS is exactly the group §15 describes**: 4 entities and 4 actions, **two of the three polled endpoints exist solely to serve it**, and the README already tells users to disable the SMS sub-device by hand if they do not use it — which hides the entities without stopping the polling, the precise outcome §15 exists to replace. §15 is a **Guideline**, so this is an Observation rather than a Gap and no code is required; but the N/A asserted something untrue about the codebase. Recorded in Project Deviations with the reasoning.
- **`manifest.json` `quality_scale` key observation withdrawn** from the IQS report (and removed from `[3.3.0-dev2]`). It was an unsourced assertion: no guidance in any input mentions the key, and none of the four sibling projects sets it either — so this integration was consistent with the family, not an outlier.

### Tests

- **382 → 385.** Three tests for the new Repair: that it stays quiet through nine consecutive failures (a router reboot must not raise it), that it fires on the tenth with the configured host present in the translation placeholders, and that a single successful poll clears it however long it was raised. The loops suppress `UpdateFailed`, which the coordinator raises from the fourth failure onward — the Repair logic runs before that raise, and the tests have to drive past it.

### Notes

- **Custom triggers investigated and deferred — no code written.** HA's trigger platform (`trigger.py` + `async_get_triggers`, `triggers.yaml`, a `triggers` block in `strings.json`) is real and mature — 45 of 58 core integrations use it, and platform discovery resolves custom components identically to core ones. Two candidates were assessed: `sms_received` (turning the existing raw bus event into a GUI-discoverable, filterable trigger — genuinely valuable) and `router_rebooted` (dropped; a plain state trigger on the uptime sensor already works). **Blocked on a product decision, not a technical one:** the API is a 2026.x construct, while this integration declares a minimum of HA **2024.8.0** and ships to users via HACS — adopting it means roughly a two-year floor raise. There is also **no developer documentation** for the API (the docs site has no page and the blog has no post), so it can still shift without a migration note. Full analysis written up at `ha-wifi-ssid-monitor/.notes/issues/custom_trigger_condition/wifi_trigger_options.md`, since the same decision applies there.

## [3.3.0-dev2] - 2026-07-27 - Unreleased - IQS Compliance Pass

Full `SCAN=Full` IQS pass (`iqs_next_steps`), run immediately after the `dev_standards` work in `3.3.0-dev1` because several rules were last assessed against code that no longer looked the same. 51 of 54 rules validated DONE or exempt against source on the first pass; the three gaps found are all closed here. **`zte_router_5g` is now 48 `done` / 6 `exempt` / 0 outstanding across the canonical 54 rules.**

### Fixed

- **User-Facing Exceptions Were Not Translatable** (IQS Gold `exception-translations` — was a **false DONE**): nine `HomeAssistantError` raises carried plain f-string messages with no `translation_domain` or `translation_key`, and `strings.json` had **no `exceptions` block at all**. Every one of them reached the user as untranslated English in a failed action dialog or button-press error. Seven were in `__init__.py` (the four SMS action handlers plus three coordinator target-resolution failures) and two in `button.py` (Reboot, Delete All SMS).
  - All nine now use `translation_domain=DOMAIN` + `translation_key`, with interpolated values moved to `translation_placeholders`.
  - A 9-key `exceptions` block was added to **both** `strings.json` and `translations/en.json`.
  - The rule had been marked `done` since v1.4.3 on the strength of a `quality_scale.yaml` comment asserting _"No custom service exceptions required"_ — which was simply untrue, and is why it survived every prior pass. The comment has been replaced.

### Changed

- **Target-Resolution Failures Reclassified to `ServiceValidationError`**: "no active entries found" and "multiple routers configured — specify entry_id" are faults in how the action was **called**, which the user can correct, rather than failures of the integration. `ServiceValidationError` is the correct type and Home Assistant presents it differently. `HomeAssistantError` is retained for "router is not ready" and for the six genuine operation failures.
- **`quality_scale.yaml` — five stale comments refreshed.** Each described an implementation that had since moved on, and collectively they are the same record decay that let the `exception-translations` false DONE stand:
  - `diagnostics` still said "redacts sensitive fields (password, username, IPs)" — it is now a four-layer sanitizer, and the SMS body and sender no longer survive at all.
  - `repair-issues` listed only `sms_storage_full`; `firmware_contract_drift` was added in `3.3.0-dev1`.
  - `parallel-updates` and `entity-translations` both said five platform files; there are six — `select` was missing from both lists, and the entity count was 51 against an actual 77 keys.
  - `icon-translations` predated the `services` block added in `3.3.0-dev1`.

### Added

- **`docs-conditions` and `docs-triggers` recorded as `exempt`**: both rules were missing entirely from `quality_scale.yaml` (52 of the canonical 54) and unassessed in the compliance matrix. The integration provides no `condition.py`, `trigger.py`, `conditions.yaml` or `triggers.yaml`, and no corresponding `strings.json` blocks. Note the `zte_router_5g_sms_received` bus **event** is not a trigger platform and does not change this. The file now matches the canonical rule set exactly, in canonical order.
- **`test_every_raised_exception_has_translated_text`**: walks every `HomeAssistantError` / `ServiceValidationError` raise in the component, asserts each carries a `translation_key`, and asserts every key resolves in **both** translation files. An untranslated raise added later fails the suite rather than quietly reintroducing this defect.

### Tests

- **381 → 382 tests.** Twelve existing tests needed updating for an instructive reason: a translated exception resolves its message through `hass` at `str()` time, so `pytest.raises(..., match="Failed to send SMS")` now raises `async_get_hass called from the wrong thread` under a mocked hass. Assertions were moved to `err.value.translation_key`, which is both the fix and the better assertion — it survives any future wording or translation change.

### Records

- **`ha_quality_standard.md`**: `exception-translations` DONE→PARTIAL→DONE, `docs-conditions` and `docs-triggers` `-`→N/A in the `zte_router_5g` column. Version entries **v1.15.0** (the scan) and **v1.15.1** (the implementation) appended.
- **Verification checks** all passed on coverage, before and after: cross-table verdict diff 54/54 compared with no mismatches; code-to-artefact reconciliation clean across all six platforms; `quality_scale.yaml`-vs-matrix 54/54 compared with no conflicts (up from 52, now that the two missing rules exist).

### Notes

- **The one Check B finding is benign and deliberately not "fixed".** `system_uptime_duration` has no `icons.json` entry, but carries `SensorDeviceClass.DURATION` and so renders a device-class default. `dev_standards.md` §12 explicitly exempts device-class-derived icons; adding an entry would be harmless but is not required.

## [3.3.0-dev1] - 2026-07-27 - Unreleased - dev_standards Conformance Pass

Brings the integration into full conformance with the PlayFaster `dev_standards.md`, following the first `dev_std_review` pass on this project. 18 of 21 sections now DONE, 2 N/A, 1 accepted deviation (§3). Test suite 297 → 381, coverage 99%, `mypy --strict` and all pre-commit hooks clean.

### Added

- **Integration Health Sensor** (§19): New diagnostic binary sensor `binary_sensor.zte_5g_system_integration_health` (`device_class: problem`) on the System sub-device, reporting the integration's own degradation state. It exists to catch the failure Home Assistant cannot see — a poll that **succeeds** while the parsed data is empty or wrong, because a firmware update renamed the fields underneath it.
  - **Always available.** `available` is overridden to return `True` unconditionally. The inherited `CoordinatorEntity.available` tracks `last_update_success`, which would take the sensor down at precisely the moment it has something to report.
  - **Total-outage reporting.** Flags on the **first** failure at cold start (nothing has ever been fetched, so waiting out the strike budget would leave the user with no explanation), and on the **3rd** consecutive failure at runtime. A success clears it in the same cycle.
  - **Contract-drift detection.** If a non-empty response contains none of five core fields for 3 consecutive cycles, the sensor turns on and a `firmware_contract_drift` repair issue is raised (auto-clearing on recovery). Startup grace prevents a verdict before a baseline exists.
  - **Verdict stored outside `coordinator.data`.** `data` is `None` before the first success and frozen at last-good values during an outage, so a verdict held there could never describe the failure that stopped it updating. It lives in `coordinator.health_snapshot`, written on both the success and failure paths.
  - Detail is exposed as **unrecorded** attributes: `issues`, `severity`, `degraded`, `repairs`, `last_good_update`, `consecutive_failures`.
- **Force Refresh** (§13): New `coordinator.async_force_refresh()` with a one-shot flag honoured before the pause check.
- **Per-Endpoint Resilience** (§8): The two optional SMS endpoints now hold their own last-good payload and strike count via `_fetch_optional()`, plus a `coordinator.endpoint_available(source)` check entities consult.
- **Options Update Listener** (§9): `entry.add_update_listener` with a `LIVE_OPTION_KEYS` allow-list.
- **`ZTERouterAPI.logout()`** (§10): Ends the router session on unload.
- **Service Icons** (§12): Added an `icons.json` `services` block covering all four SMS actions, and a `default` icon for the Refresh Now button (which has no `device_class` to derive one from).

### Fixed

- **Refresh Now Did Nothing While Polling Was Paused** (§13): `ZTERefreshButton` called the bare `async_request_refresh()`, which `_async_update_data` short-circuits to cached data whenever `stop_polling` is on — so the button was silently swallowed in the one situation it exists for. All **nine** explicit user actions now route through `async_force_refresh()`: Refresh Now, Delete All SMS, the polling-interval slider, both router switch setters, pause-resume, the APN/network select, and the `delete_sms` / `delete_all_sms` services. Scheduled polls still respect the pause. _Verified live: paused, pressed Refresh Now, data updated; then waited two full poll intervals paused with no update._
- **Options Flow Changed Credentials Without Applying Them** (§9): `ZTEOptionsFlow` wrote a new host, username or password into `entry.options` and nothing reloaded, because no update listener was registered. The running `ZTERouterAPI` kept using the **old host and password until Home Assistant was restarted**. A listener now reloads on any non-live option change; `scan_interval` and `stop_polling` remain live-apply so the slider and pause switch do not tear down every entity.
- **Diagnostics Leaked Personal and Third-Party Data** (§20): `coordinator.data` is the raw `goform` payload, and key-name redaction reached almost none of it. A real download contained the **body and sender number of the most recent SMS**, the serving `cell_id` / `enodeb_id` / `lte_pci`, `mdm_mcc` / `mdm_mnc` (which together locate the subscriber on a named carrier), `wan_apn`, and raw `APN_config*` profile strings. Replaced with a layered sanitizer:
  - **Blanked** — credentials, IMEI/IMSI/ICCID/MSISDN, and carrier identity.
  - **Pseudonymized** — IPs, cell identifiers and SMS senders become stable tokens (`ip-1`, `cell-2`, `phone-1`), preserving cross-reference within the file.
  - **Summarized** — `APN_config*` reduces to `<apn profile: 13 fields, 7 set, pdp=IPv4v6>`, keeping the diagnostic shape while dropping any embedded APN credentials.
  - **Swept** — anything IP- or MAC-shaped anywhere, for keys this module does not enumerate. Matched on shape only, never seeded with real values.
  - SMS keeps its metadata and character counts (whether hex decoding worked is diagnostic); the text and sender do not survive.
  - The coordinator payload is `deepcopy`'d first — diagnostics is a read path.
  - Diagnostics now also includes the health snapshot, endpoint failure counts and update interval.
- **SMS Sender's Phone Number Was Written to the Recorder** (§14): The `msg_recent` sensor published the sender's number as a recorded attribute, storing third-party personal data in the user's database on every poll. `_unrecorded_attributes` now covers `id`, `number`, `date` and the eight SMS counters. `sntp_server1` / `sntp_dst_enable` remain recorded deliberately — static configuration, cheap, and worth seeing in history.
- **`logout()` Was Silently Ignored by the Router**: The first implementation omitted the `AD` token that every other `goform` setter requires. The router answered `{"result":"failure"}` and **left the session open** — the method looked like it worked while changing nothing. Now sends `AD`. _Verified against MC7010 firmware V1.0.0B03: with the token the router returns `{"result":"success"}` and replaying the old `stok` returns the session-expired shape; without it the `stok` stays live._ `LOGIN_OUT` and `USER_LOGOUT` were probed and are not valid commands on this firmware.
- **Binary Sensors Claimed "Off" Before Any Data Arrived** (§18): `is_on` returned `False` when `coordinator.data` was absent, asserting "not on the best connection" about a router that had not yet been read. Both classes now return `None` (HA `unknown`) until data exists.
- **Numeric Values Stored at Full Source Precision** (§6): `_safe_float` now rounds to 3 decimal places at parse time, so controller noise does not reach long-term statistics. This is distinct from `suggested_display_precision`, which governs what is _shown_ rather than what is _stored_.

### Changed

- **SMS storage check ordering**: `_check_sms_storage` now runs **before** the health snapshot is written, so the storage repair state it reports is from the current cycle rather than one cycle stale. The existing `sms_storage_full` repair is _reflected_ in the health sensor's attributes rather than double-raised.
- **Auth-retry structure**: The mandatory and optional fetches were factored into `_fetch_all()`, preserving the existing "renew session and retry the whole set once" semantics exactly while adding per-endpoint containment for non-auth errors.
- **Four `# noqa: BLE001` waivers** added where a standard requires a broad catch: the health computation must never crash the update it diagnoses (§19), endpoint containment must absorb an unexpected response (§8), and unload must never be blocked by an unreachable router (§10). Each carries a comment explaining why narrowing defeats the requirement.

### Tests

- **297 → 381 tests**, coverage 99%.
- **New `tests/test_integration_setup.py`** (§11): Integration-level tests driven through a **real** `hass` with `await hass.async_block_till_done()` — previously used **zero** times in the suite despite setup creating a background task. The old setup test asserted only that `async_create_background_task` was _called_, against a `MagicMock` hass, so the coroutine inside it was never driven. Also covers entities existing at cold-start failure, which is the evidence §1's departure from `test-before-setup` actually rests on.
- **New `tests/test_coordinator_resilience.py`**: Force-refresh-vs-pause in both directions, per-endpoint strike budgets, and every §19 failure regime including the combination of a degraded endpoint during a total outage.
- **New `tests/test_binary_sensor_health.py`**: Forces `last_update_success = False` — the exact condition the inherited `available` keys off — so removing the override fails a test rather than silently reintroducing the defect.
- **New `tests/test_options_lifecycle.py`**: Asserts host and password changes reload while slider and pause do not, and exercises the real `logout()` rather than a double.
- **New `tests/test_entity_hygiene.py`**: Guards rounding, the unrecorded-attribute decisions, icon coverage, and that every `translation_key` and repair key resolves in **both** `strings.json` and `translations/en.json` — compared against the code, not file-to-file.
- **New `tests/test_diagnostics_sanitization.py`**: 35 property tests over `json.dumps(result)` with wholly synthetic fixtures, asserting no identifier survives anywhere, tokens are stable across sections, and the non-identifying substance is still present. The old key-presence tests it replaces were the kind §20 identifies as inadequate.

### Documentation

- **README — Example Automations reworked**: Every automation now carries inline `note:` annotations on its triggers, conditions and actions, matching the style used in `unifi_network_monitor` and `wifi_ssid_monitor`. The notes explain _why_ a value was chosen (why the APN failover waits five minutes, why SMS forwarding needs `mode: queued`, why the auto-reboot duration is deliberately long) rather than restating what the YAML already says. All examples gained an explicit `description:` and `mode:`.
- **README — five new automation examples**: **Auto-Reboot on a Prolonged Outage** (cross-checks Integration Health before acting, so it does not reboot on the strength of a stale held value), **Cell Tower Change Alert**, **Firmware Change Notification** (paired with the contract-drift detection added this release), **Dynamic Polling Interval**, and **Force a Fresh Reading Before Reporting** (demonstrates that explicit actions now fetch while paused). Polling examples were grouped under a new **Polling Control Automations** heading.
- **README — cross-linking**: Use Cases, Features and the SMS section now link directly to the relevant worked example, following the pattern in `wifi_ssid_monitor`. Two new Use Cases added: _Unattended Recovery_ and _Knowing When the Integration Itself Is Wrong_. All 31 internal anchors verified to resolve.
- **README — new content for this release's behavior**: Integration Health added to the entity table; new **Self-Diagnosis** and **Session Handling** subsections under Technical Architecture; per-endpoint resilience and forced-refresh documented alongside the 3-strike explanation; the "why can't I access the web UI" FAQ extended to cover session release on unload.
- **`docs/DEVELOPMENT.md`**: Eight new success patterns and four new pitfalls, including the `goformId=LOGOUT` `AD`-token trap **and why the obvious verification cannot detect it** (the ZTE web UI always accepts a login and evicts the existing session, so it reports success whether logout worked or not). Recorded the §3 deviation and the config-entry migration constraint under Technical Debt.
- **`AGENTS.md`**: Coordinator, API, `__init__`, platform and diagnostics descriptions brought current with the force-refresh, per-endpoint, health-snapshot, options-listener and sanitizer behavior.

### Notes

- **§3 (Early Root Registration) is an accepted deviation, recorded in `dev_standards.md` → Project Deviations.** The root stays keyed `{imei}_system` rather than a bare hardware identifier. The ladder exists to enable a merge with a core integration and to prevent IP-to-MAC identifier swaps; neither is reachable here — the `goform` API never exposes a MAC, there is no core `zte` integration, and the IMEI cannot swap.
- **The `AD`-token logout finding is specific to MC7010 firmware V1.0.0B03**, the only hardware available to test. `get_ad()` already branches by model for the hash algorithm, but `LOGOUT` behavior on MC888/MC889 is untested. If it differs, the failure mode is the pre-existing one: the session lingers until timeout, and `logout()` swallows the error rather than blocking unload.

## [3.2.6-dev8] - 2026-07-26 - Unreleased - No Manifest Bump

### Changed

- **Icons & Branding**: Updated the icons and logos for the project.
- **AGENTS**: Rewrite of AGENTS.md to move content shared across projects to a shared file, and to move sensor entity counts to using `docs/all_sensors.md`as the definitive source.

### Bumps

- **Shared CI**: Bump `.github` Shared CI Validation via SHA from v2.0.6 to v2.0.7
- **Validate Bump**: Update `ruff` from 0.15.20 to 0.15.22
- **Validate Bump**: Bumped PHACC `pytest-homeassistant-custom-component` from 0.13.346 to 0.13.348
- **Validate Bump**: Update `codespell` from 2.42 to 2.43

## [3.2.6-dev7] - 2026-07-12 - Unreleased

### Changed

- **PyTest**: Increased PyTest coverage to 100%. There was one uncovered statement, in api.py, unreachable, but required for MyPy strict. Marked via `pragma: no cover`as defensive.
- **Formats**: Codespell alignment, words like behavior and color etc.

## [3.2.6-dev6] - 2026-07-12 - Unreleased - Bumped pytest-homeassistant-custom-component from 0.13.345 to 0.13.346

### Bumps

- **Validate Bump**: Bumped pytest-homeassistant-custom-component from 0.13.345 to 0.13.346

### Changed

- **Docs**: Minor fixes to README for alignment with other project READMEs (clarification on disabling devices and/vs. entities)
- **Formats**: Codespell alignment, words like behavior and color etc.

## [3.2.6-dev5] - 2026-07-06 - Unreleased

### Bumps

- **Shared .github CI Validation**: Bump .github Shared CI Validation via SHA from v2.0.5 to v2.0.6

## [3.2.6-dev4] - 2026-07-05 - Unreleased

### Changed

- **PyTest Errors and Coverage**: The changes in dev3 below caused several of the existing PyTests to fail and also introduced new uncovered statements. Fixed and added tests to get to 100% coverage with all tests passing.
  - **297 tests all pass** (was 32 failing + 1 error)
  - **Coverage: 100%** across all files (was 98%)

### Test Changes

| Category | Count | Fix |
| :-- | :-- | :-- |
| **Python 3.14 tz-aware iso-format** | 4 tests | `+00:00` suffix now included — updated assertions |
| **Generic `Exception` not caught by code** | 14 tests | Changed to `aiohttp.ClientError` / `TimeoutError` (which the code catches) |
| **Missing `json_data` on MockResponse** | 6 tests | `_request` expects JSON; added `json_data={"result": "ok"}` |
| **MockResponse missing `read()`** | conftest.py | Added `async def read()` method for login session init |
| **Missing 3rd GET in login mock** | 2 tests | Login now does a session init GET; added 3rd mock response |
| **AsyncMock for async methods** | 1 test | `return_value = None` → `AsyncMock(return_value=None)` |
| **Indentation error** | 1 test | Fixed broken indent |
| **Uncovered lines coverage** | 3 new tests | Lines 333-334, 373-374, 593-595 in api.py |

### Files modified

- `tests/conftest.py` — added `read()` to MockResponse
- `tests/test_api.py` — 19 test fixes
- `tests/test_coverage_ext.py` — 12 test fixes + 3 new tests
- `tests/test_init.py` — 1 test fix

## [3.2.6-dev3] - 2026-07-05 - Unreleased

### Changed

- **Ruff Checks Extended**: As of shared CI Dev-workbench v2.2.1, Ruff checks have been extended to align with Home Assistant. This involves INcluding a wide range of checks and then EXcluding several items because of the wider range. In this project, that lead to 17 issues to be addressed.
- **Ruff Production Code Compliance**: Resolved 17 static analysis violations in the custom component source:
  - **Exception Flow Control (`TRY301` / `TRY300`)**: Refactored HTTP request execution and authentication validation blocks in `api.py` and service callbacks in `__init__.py` to perform status code evaluations and raise custom errors (`ZTEAuthError`/`ZTEConnectionError`) outside of the primary `try-except` blocks.
  - **Timezone Awareness (`DTZ`)**: Eliminated naive datetimes (`datetime.now()`, `datetime.min`) in session expiry and SMS timestamp calculations in `api.py`, converting them to timezone-aware UTC datetime structures using the Python-standard `UTC` alias.
  - **Defensive Catching Hardening (`BLE001` / `S110` / `SIM105`)**: Replaced generic `except Exception` blocks with targeted catches (such as `TimeoutError` and `aiohttp.ClientError`) to avoid masking syntax/developer defects. Converted catch-all error handling on entities to use explicit stack trace logs (`_LOGGER.exception`), and refactored body JSON decoding fallbacks in `api.py` to use Pythonic `contextlib.suppress`.
  - **MD5 Hashing Bypass (`S324`)**: Bypassed linter flag on legacy MD5 password hashing with `# noqa: S324` as required by the ZTE router's hardware API protocol.
- **Ruff Test Parity Compliance**: Addressed 30 static analysis issues in the test suites:
  - **Timezone-Aware Mocking (`DTZ005` / `DTZ001`)**: Made all mock activity timestamps in `test_api.py` and `test_coverage_ext.py` timezone-aware via `datetime.now(UTC)` and updated original boot anchors in `test_init.py` to use timezone-aware date objects (`tzinfo=UTC`).
  - **Clean Test Scopes (`PT012`)**: Nested `pytest.raises` blocks cleanly inside mock patches to ensure each assertion context evaluates exactly one execution statement.

## [3.2.6-dev2] - 2026-07-05 - Unreleased

### Changed

- **IQS Validation**: `dev-workbench` script `iqs_static_check.py` added via `tasks.json` now checks for Home Assistant Integration Quality Scale ( IQS ) compliance to 7 basic IQS rules.
- **IQS `test-before-setup`**: IQS rule `test-before-setup` had been marked as complete, but the new script, referenced above, highlighted that it was not complete. Addressed this via:
  - Imported ConfigEntryAuthFailed from homeassistant.exceptions.
  - Modified the exception handler for ZTEAuthError in \_async_update_data() to raise ConfigEntryAuthFailed when a persistent/non-bypassed auth failure occurs.
  - Removed the direct call to self.entry.async_start_reauth(self.hass) because raising ConfigEntryAuthFailed delegates this cleanly to Home Assistant Core.
  - Updated `test_init.py` to check for this, maintained 100% coverage.
  - The normal **3-strike resilience logic** applies, to avoid false flags. Only on the 4th consecutive failure (or on the very first fetch during setup when self.data is None) will ConfigEntryAuthFailed be raised.
- **Documentation**: Updated README.md , re-ordered some sections for logical flow and readability.

### Bumps

- **Validate Bump**: Bumped `pytest-homeassistant-custom-component` from 0.13.344 to 0.13.345

## [3.2.6-dev1] - 2026-07-03 - Unreleased

### Changed

- **Dev-WorkBench**: Updated the Check Drift script to account for the situation where the HA Core version online is ahead of the local version (dev-workbench v2.1.0-dev9).
- **Documentation**: Minor doc updates and formatting.

## [3.2.5] - 2026-07-03 - Release

### Added

- **Refresh Now Button**: New System button that triggers an immediate data refresh, complementing the existing Pause Polling switch and configurable polling interval.

### Changed

- **Display Units & Precision**: 16 sensors now display expected units and decimal places in the UI — data sizes in GB, throughput in Mbit/s, uptime duration in hours, and rounded signal-strength/bandwidth values. Underlying native values (used for long-term statistics) are unchanged.
- **SMS Actions Default to the Sole Router**: The `delete_sms`, `delete_all_sms`, and `get_sms_list` actions no longer require `entry_id`. When exactly one router is configured it is selected automatically; with more than one configured, `entry_id` is required and omitting it now raises a clear "specify entry_id".
- **Polling Toggle Future Ready**: Turning off "Enable polling for changes" in the entry's system options now reliably stops scheduled polling and will satisfy the upcoming HA requirement (implicit `ContextVar` detection is being removed in HA 2026.8).
- **Minimum Home Assistant Version**: Documented minimum raised to 2024.8.0 (driven my polling option change above, this was added to HA in 2024.8)

### Fixed

- **Password No Longer Pre-filled on Edit Screens**: On Reconfigure, Options, and Reauth, the password field is now masked and left blank — the stored value is never pre-filled or revealable. Leave it blank to keep the current password, or enter a new one to change it.
- **Doubled Device URL**: A full URL or trailing slash entered in the Host field is now stripped before storage, preventing a malformed device link (e.g. `http://http://192.168.0.1`).

## [3.2.5-dev12] - 2026-07-03 - Unreleased

### Changed

- **SMS Actions Default to the Sole Router**: The `delete_sms`, `delete_all_sms`, and `get_sms_list` actions no longer require `entry_id`. When exactly one router is configured it is selected automatically; with more than one configured, `entry_id` is required and omitting it now raises a clear "specify entry_id" error instead of silently acting on an arbitrary router (`send_sms` already behaved this way). Implemented by relaxing the three service schemas and `services.yaml` to optional, and tightening `_get_coordinator` to auto-select only when a single entry is loaded. Added tests for the single-entry fallback and the multiple-entry guard.
- **Documentation**: Updated the README to align as closely as possible with the Huawei 5G Monitor README.

## [3.2.5-dev-11] - 2026-07-03 - Unreleased

### Changed

- **PyTest Coverage**: Increased coverage from 99% to 100% (seven uncovered statements addressed).

## [3.2.5-dev10] - 2026-07-03 - Unreleased

### Bumps

- **Validate Bump**: Update Ruff from 0.15.19 to 0.15.20

### Changed

- **Documentation**: Updated the README screenshots to include Refresh Now button and with higher resolution. Updated all_sensors.md and README.md to correctly reflect sensor counts and groups.

## [3.2.5-dev9] - 2026-07-02 - Unreleased

### Summary

- **Explicit `config_entry` on the Coordinator**: Pass the config entry explicitly to `DataUpdateCoordinator` so Home Assistant reliably honours the "Enable polling for changes" system option and to satisfy the upcoming HA requirement (implicit `ContextVar` detection is being removed in HA 2026.8).

### Changed

- **Coordinator `config_entry`**: `ZTERouterDataUpdateCoordinator` now passes `config_entry=entry` to `super().__init__()`. This makes `self.config_entry` explicit, which is what HA core's `_schedule_refresh()` checks (`config_entry.pref_disable_polling`) to stop scheduled polling when the user sets **Settings → Devices & Services → (⋮) → System options → "Enable polling for changes" = OFF**. Manual updates (`homeassistant.update_entity`, "Refresh Now", Pause-Polling off→on) still fetch. No behavior change on current HA — it removes reliance on implicit context detection, which HA logs as an error from **2026.8**.
- **Minimum HA Version**: Documented minimum raised to **2024.8.0** (the release that added the `config_entry` argument to `DataUpdateCoordinator`).

### Tests

- Added a coordinator test asserting `coordinator.config_entry is entry`.

### Bumps

- **Shared .github CI Validation**: Bump .github Shared CI Validation via SHA from v2.0.4 to v2.0.5 (PR #31 #32)

## [3.2.5-dev8] - 2026-07-02 - Unreleased

### Summary

- **Suggested Display Units & Precision**: Applied Home Assistant's `suggested_unit_of_measurement` / `suggested_display_precision` to 16 sensors so the UI shows friendly units and sensible decimal places while native values (used for long-term statistics) stay canonical.

### Changed

- **Data Size Sensors (Bytes → GB)**: `monthly_tx_bytes_raw`, `monthly_rx_bytes_raw`, `monthly_total_bytes_raw` suggest `GIGABYTES` at precision **1** (monthly); `realtime_tx_bytes`, `realtime_rx_bytes` (session) suggest `GIGABYTES` at precision **2**. Native unit stays `BYTES`.
- **Data Rate Sensors (B/s → Mbit/s)**: `realtime_tx_thrpt`, `realtime_rx_thrpt` suggest `MEGABITS_PER_SECOND` at precision **2**. Native unit stays `BYTES_PER_SECOND`.
- **Duration Sensor (s → h)**: `realtime_time` (Uptime Duration) suggests `HOURS` at precision **1**; its native unit was normalized from the `"s"` string to `UnitOfTime.SECONDS` (identical value).
- **Bandwidth (MHz)**: `lte_ca_pcell_bandwidth`, `lte_ca_scell_bandwidth` now round to **0** decimal places; unit unchanged (`MHz`).
- **Signal Strength (dBm)**: `lte_rsrp`, `lte_rssi`, `z5g_rsrp`, `z5g_rssi`, `rssi`, `rscp` round to **0** decimal places; unit unchanged. (RSRQ/SNR in dB left fractional.)

### Notes

- Native units are unchanged in every case — only the display hint is added, so long-term statistics and the guard-band limits (defined in native units) are unaffected.
- The legacy GB sensors (`monthly_tx_bytes`, `monthly_rx_bytes`, `monthly_total_bytes`, already GB and disabled by default) were intentionally left as-is.

### Tests

- Added parametrized coverage asserting the suggested unit/precision on all 16 affected sensors (and that the uptime-duration native unit stays seconds).

### Bumps

- **Validate Bump**: Bumped `pytest-homeassistant-custom-component` from 0.13.340 to 0.13.344
- **Validate Bump**: Bumped `check-jsonschema` from 0.37.2 to 0.37.4

## [3.2.5-dev7] - 2026-07-02 - Unreleased

### Summary

- **Config Flow Hardening & Refresh Button**: Normalized host input before storage, stopped exposing the stored password on edit screens, and added a "Refresh Now" button.

### Added

- **Refresh Now Button**: New System sub-device button that triggers an immediate coordinator refresh (`async_request_refresh`), complementing the existing Pause Polling switch and configurable polling interval.

### Changed

- **Host Normalization in Config Flow**: Added `_clean_host()` and applied it to all four config-flow steps (user, reconfigure, reauth, options) so a full URL or trailing slash entered in the Host field is stripped before it is stored in `entry.options`. Prevents a doubled device `configuration_url` (e.g. `http://http://192.168.0.1`).
- **Password No Longer Exposed on Edit Screens**: Split the config-flow schema into setup (`_user_schema`) and edit (`_edit_schema`). The password now uses a masked `TextSelector` and is left blank on Reconfigure/Options/Reauth — the stored value is never pre-filled or revealable via the UI eye icon. A blank submission keeps the stored password via `_merge_credentials()`; entering a value changes it.
- **Field Helper Text**: Added `data_description` guidance under the password field on the Reconfigure/Options screens ("Leave blank to keep the current password, or enter a new one to change it.").

### Tests

- Added coverage for host cleaning, credential merge, URL-host stripping in the user/reconfigure flows, blank-password retention (reconfigure + options), and the new Refresh Now button.

## [3.2.5-dev6] - 2026-07-01 - Unreleased

### Changed

- **Validate Bump**: Updated `ruff` from 0.15.18 to 0.15.19 (PR #33)

## [3.2.5-dev5] - 2026-06-29 - Unreleased

### Changed

- **Validate Bump**: Updated ruff from 0.15.17 to 0.15.18 (PR #33)

## [3.2.5-dev4] - 2026-06-29 - Unreleased

### Summary

- **All about YAML Lint**: Multiple YAML Lint local validation warns/fails in the ha-dev-pf stub repo highlighted some shortcomings with YAML Lint implementation. Updated to avoid need for "---" at the top of every YAML file, which is a YAML standard, but NOT the HA standard. Also updated to only run on git tracked files (avoids linting devcon files for example).

### Changed

- **YAML Lint**: Added "document-start: disable" to .yamllint rule file, to stop warns/fails for "no --- at document start", which brings it in line with Home Assistant.
- **YAML Files**: Updated YAML files to remove any "---" document starts added.
- **Tasks.json**: Updated tasks.json, via hosts-tooling so that YAML-Lint only runs on git tracked files.
- **Dependabot Bump**: Updated ruff from 0.15.16 to 0.15.17
- **Bump**: Updated PyTest Custom from 0.13.326 to 0.13.340
- **.gitignore**: Added scratch folders

## [3.2.5-dev3] - 2026-06-18 - Unreleased

### Summary

- **CI Validation Overhaul**: Major overhaul of the local (tasks.json) and online (github.com CI) Validation system

### Changed

- **dev-workbench**: Moved CI Validation and Sync to dev-workbench system, with major restructure of files and folders.
- **CI Local Tasks**: Fixed an issue with tasks.json where it shows pass, after error messages, for three validation steps.
- **.gitignore**: Further updates to .gitignore

## [3.2.5-dev1] - 2026-06-15 - Unreleased

### Changed

- **CI Local Tasks**: Reordered local tasks.json, added color for pass/fail.

## [3.2.4] - 2026-06-15 - Release

### Changed

- **CI Validation Bump**: Shared CI validation bumped to v2.0.3. No user changes in this release, background/infrastructure only.

## [3.2.4-dev3] - 2026-06-15 - Unreleased

### Changed

- **CI Validation Bump**: Shared CI validation bumped from v2.0.2 to v2.0.3
- **CI Coverage Report**: Removed the pytest coverage report as it required extra permissions and is separate to the coverage badge, which is what is really required.

## [3.2.4-dev2] - 2026-06-15 - Unreleased

### Changed

- **CI Validation Bump**: Shared CI validation bumped from v2.0.1 to v2.0.2

## [3.2.4-dev1] - 2026-06-15 - Unreleased

### Changed

- **CI Validation Sync**: Updated the shared CI validation to include the Theme project, which required some all round changes.

## [3.2.3] - 2026-06-14

### Summary

- **CI Validation Only**: Changes to the CI Validation set-up require another release to test properly, but there are no user changes in this release, background/infrastructure only.

### Changed

- **CodeQL**: CodeQL shared config and local caller modified to detail permissions to that Zizmor will pass

## [3.2.2] - 2026-06-14

### Summary

- **CI Validation Only**: Changes to the CI Validation set-up require another release to test properly, but there are no user changes in this release, background/infrastructure only.

### Changed

- **CodeQL**: Added a shared CodeQL validation config to the shared validation repo, pulled into each project, incl this one.

## [3.2.1] - 2026-06-14

### Summary

- **CI Validation Only**: Changes to the CI Validation set-up require a release to test properly, but there are no user changes in this release, background/infrastructure only.

## [3.2.1-dev9] - 2026-06-14 - Unreleased

### Changed

- **Validation Config**: Fixed use of .prettierrc.json

## [3.2.1-dev8] - 2026-06-14 - Unreleased

### Changed

- **Link Check**: Updated markdown-link-check to ignore .notes/ and .shared/ links in projects as these are excluded.
- **Validation Config**: Changed from .prettierrc.js to .prettierrc.json to allow GitHub.com CodeQL to run without errors

## [3.2.1-dev7] - 2026-06-14 - Unreleased

### Changed

- **DependaBot**: Bumped Shared Validation from v1.0.8 to v1.0.9
- **DependaBot**: Bumped Ruff from 0.15.12 to 0.15.16
- **.gitignore**: Multiple updates to .gitignore
- **AGENTS.md**: Added AGENTS.md to repo root

## [3.2.1-dev4] - 2026-06-10 - Unreleased

### Changed

- **Validation Sync**: Moved to a better system and process to keep validation (lint/format/test) tools in sync, across PlayFaster projects and between the projects and what Home Assistant uses.
  - .validate/version_matrix.json added as the definitive source of tool version use.
  - Several Env: entries added to .vscode/tasks.json for tool sync and checking.
  - .validate/requirements_test.txt pulled as generic, with all tools pinned to versions, and requirements_custom.txt used to add project specific items.
  - As part of the sync, docker-compose.yml and devcontainer.json are now generic, with a .env file holding project specific info and a docker-compose.override.yml holding additional, project specific steps.
  - HA Manifest and HACS schema files updated.
  - Ruff updated from 0.15.12 to 0.15.15

## [3.2.1-dev1] - 2026-06-08 - Unreleased

### Fixed

- **2 `RuntimeWarning: coroutine was never awaited` + 2 test failures** (`test_api.py`, `test_coverage_ext.py`, `conftest.py`): Two tests (`test_api_get_sms_messages_error`, `test_api_get_last_sms_content_exception`) that set `mock_aiohttp_client.post.side_effect` triggered a re-login due to inactivity timeout (`last_activity = datetime.min`). The login path's GET request returned a bare `MagicMock` whose `headers.get("Content-Type", "")` resolved to an un-awaited coroutine. Fixed by setting `session.get`'s default `return_value` to `MockResponse()` in the conftest fixture, and providing `{"LD": "test_ld"}` mock data to the failing tests so login succeeds and the expected `ZTEConnectionError` propagates correctly.

### Changed

- **README Emoji Consistency**: Replaced all VS16 compound emoji in headings and ToC links with always-color single-codepoint alternatives (`⚙️`→`🔧`, `🗑️`→`❌`, `⚠️`→`❗`, `⏱️`→`🔁`, `✉️`→`💬`, `⏯️`→`🔁`, `🛠️`→`🔩`, `🎛️`→`🔘`); moved License badge out of heading; standardized Use Cases icon to `🎯`.

- **`pyproject.toml` — mypy Configuration Realigned with HA's Internal `mypy.ini`**: The project's `[tool.mypy]` section has been restructured to closely match HA's auto-generated `mypy.ini` (produced by `script/hassfest -p mypy_config`). This ensures the pre-commit mypy hook, and the project's basic `mypy custom_components/` check, run under materially the same conditions as HA's own integration quality checks. The goal is for any type errors caught here to be errors HA itself would also catch — and vice versa.

## [3.2.0] - 2026-05-28

### Added

- **New Sensors**: Added several new entities, the most useful of which is a select for **APN Profile**. Changing APN can be as or more effective than rebooting to restore 5G signal that has dropped to 4G only. New entities are:
  - **APN Control Selects**: Added select entities for switching active APN profiles (`apn_profile`) and toggling between automatic/manual APN mode (`apn_mode`).
  - **Network Mode Select**: Added carrier network preference selection (`net_select_mode`) to choose between Auto (4G/5G), 5G NSA, 5G SA, and 4G Only.
  - **ODU LED Control Switch**: Added a switch (`odu_led_switch`) to toggle the physical outdoor unit status LEDs.
  - **Data Limit Control Switch**: Added a switch (`data_limit_switch`) to toggle data limit enforcement on the router.
  - **Reboot Schedule & Security Binary Sensors**: Added binary sensors to monitor Reboot Schedule, UPnP status, and SIP ALG status.
  - **New Diagnostic Sensors**: Added sensors for LTE Band Lock Mask, Data Volume Alert %, and SNTP Time Server.

### Changed

- **Database Cleanup (Reduced LTS)**: Removed long-term statistics tracking from 8 non-critical sensors (realtime throughput, uptime duration, etc.) to prevent database bloat.

### Fixed

- **Centralized Session Stability**: central request helper now resets expired tokens proactively, preventing transient authentication errors and empty sensor states.

## [3.1.1-dev11] - 2026-05-27 - Unreleased

### Added Tests

- **57 new tests** across `test_select.py`, `test_switch.py`, `test_binary_sensor.py`, and `test_api.py`. Coverage: `select.py` (new) 0% → 100%, `switch.py` 80% → 100%, `binary_sensor.py` 89% → 100%, `api.py` 92% → 100%. Overall: 88% → 99%.

## [3.1.1-dev10] - 2026-05-27 - Unreleased

### Fixed

- **Type Checking (mypy)** (`binary_sensor.py`): Fixed list comprehension type compatibility by explicitly annotating the entities list as `list[BinarySensorEntity]`.

## [3.1.1-dev9] - 2026-05-27 - Unreleased

### Added

- **New Entities**: Added several new entities, most notably the ability change APN.
- **APN Profile Select** (`select.py`): Added `signal_apn_profile` select entity allowing users to switch between configured APN profiles on the router.
- **APN Mode Select** (`select.py`): Added `signal_apn_mode` select entity for switching between manual and automatic APN selection.
- **Network Mode Select** (`select.py`): Added `signal_net_select_mode` select entity to set carrier network mode preferences (Auto, 5G NSA, 5G SA, 4G Only).
- **ODU LED Control Switch** (`switch.py`): Added `system_odu_led_switch` to control the router's outdoor unit indicator LED.
- **Data Limit Control Switch** (`switch.py`): Added `data_limit_switch` to toggle the router's cellular data volume limit enforcement.
- **System Binary Sensors** (`binary_sensor.py`): Exposed Reboot Schedule (`system_reboot_schedule`), UPnP status (`system_upnp_enabled`), and SIP ALG (`system_sip_alg_enabled`) as binary sensors.
- **Diagnostic/Config Sensors** (`sensor.py`): Exposed LTE Band Lock Mask (`signal_lte_band_lock`), Data Volume Alert % (`data_volume_alert_percent`), and SNTP Time Server (`system_sntp_server`).

### Fixed

- **Type Checking (mypy)** (`binary_sensor.py`): Fixed list comprehension type compatibility by explicitly annotating the entities list as `list[BinarySensorEntity]`.

## [3.1.1-dev8] - 2026-05-25 - Unreleased

### Fixed

- **Exception Syntax** (`sensor.py`): Corrected legacy tuple format `except ValueError, TypeError:` to standard parenthesized format `except (ValueError, TypeError):`.

## [3.1.1-dev7] - 2026-05-25 - Unreleased

### Fixed

- **Exception Syntax** (`sensor.py`, `coordinator.py`): Fixed 2 additional bare-tuple `except A, B:` expressions (`sensor.py:54`, `sensor.py:76`) to parenthesized `except (A, B):` form for Python 3.12+ compatibility (5 total across all sessions).
- **E501 line-too-long** (`number.py`): Wrapped `self.hass.async_create_task(...)` call to comply with 88-char limit.
- **Test failures** (`test_number.py`): Resolved 2 `TypeError: 'MagicMock' object can't be awaited` failures caused by migrating from `asyncio.create_task` to `self.hass.async_create_task` — added `_mock_hass_with_async_create_task` helper that returns a real `asyncio.Task`.

### Changed

- **HA lifecycle tracking** (`number.py`): Migrated from `asyncio.create_task(...)` to `self.hass.async_create_task(...)` so the debounced polling-interval task is tracked by HA's task registry.

## [3.1.1-dev6] - 2026-05-25 - Unreleased

### Fixed

- **Exception Syntax** (`coordinator.py`, `sensor.py`): Fixed 3 bare-tuple `except A, B:` expressions to parenthesized `except (A, B):` form for Python 3.12+ compatibility (`coordinator.py:281`, `sensor.py:667`, `sensor.py:711`).

### Added Tests

- **17 new tests** across `test_init.py`, `test_sensor.py`, `test_binary_sensor.py`, and `test_api.py`. Coverage remains at 99% overall; the focus was on improving test depth with boundary value analysis, combinatorial path coverage, and error/negative-path engineering:
  - Failure resilience edge cases (`data=None`, reset-after-success)
  - Reboot detection at exact margin boundary (70/69/71 s)
  - Bad/negative uptime value handling
  - Sensor guard bands at exact limit boundaries
  - API inactivity timer at strict `>` threshold
  - Binary sensor ENDC+CA combinatorial states
  - Same-timestamp SMS hash detection path
  - Multiple new SMS chronological ordering
  - Missing `date_decoded` filtering and early return
  - Auth retry failure propagating to outer handler
  - `delete_all_sms` `keep_last` ≥ `total_messages` boundary
  - Bare-tuple bug proof tests for exception propagation
  - Invalid calendar values in `_parse_date`
  - SMS message missing `id` field

## [3.1.1-dev5] - 2026-05-25 - Unreleased

### Changed

- **Sensors**: Removed `state_class` from 8 sensors (`realtime_time`, `battery_value`, `rssi`, `rscp`, `realtime_tx_bytes`, `realtime_rx_bytes`, `realtime_tx_thrpt`, `realtime_rx_thrpt`) to prevent non-critical sensors from generating Long Term Statistics entries.
- **Documentation**: Add details on the non-LTS sensors to README

## [3.1.1-dev4] - 2026-05-25 - Unreleased

### Fixed

- **Tests**: Resolved 8 test failures caused by the inactivity-based session reset (150-second threshold) — set `api.last_activity = datetime.now()` in test setup to prevent proactive stok clearing from interfering with test mocks.

### Test Coverage

- `api.py` 93% → 100%, `coordinator.py` 95% → 100%
- **11 new tests**: session init GET success, non-auth exception handlers for `get_sms_capacity`/`get_last_sms_content`/`get_sms_messages`/`get_rd`, `boot_time` restore (valid + bad value), `last_uptime` restore (valid + bad value), SMS auth retry, `_check_new_sms` early-return, `_check_new_sms` same-timestamp hash dedup.

## [3.1.1-dev3] - 2026-05-25 - Unreleased

### Fixed

- **Authentication**: Implemented proactive inactivity-based session resetting (150-second threshold) inside the centralized `_request()` wrapper to force a login/activation before session tokens expire.
- **Authentication**: Added a session-initialization GET request inside `login()` immediately after authentication to allow subsequent POST requests to succeed.
- **Error Handling**: Refined `_request()` to correctly propagate `ZTEAuthError` when retry attempts are exhausted on unauth/expired responses, preventing silent empty states.
- **Error Handling**: Enabled auth and connection exception propagation in `get_rd()` and `get_last_sms_content()` to prevent silent setup/API failures.
- **Tests**: Resolved 15 failing unit tests by adjusting mock awaitables, adapting error assertions to the new exception propagation design, and updating obsolete coordinator API method patches.

## [3.1.1-dev2] - 2026-05-24 - Unreleased

### Changed

- **Documentation**: Additional updates to README, more automation examples, more icons.

## [3.1.1-dev1] - 2026-05-24 - Unreleased

### Changed

- **Dependabot**: Bump PlayFaster/.github shared validation from v1.02 to v1.04
- **Dependabot**: Bump [zizmor](https://github.com/zizmorcore/zizmor-pre-commit) from v1.24.1 to 1.25.2
- **Dependabot**: Bump [python-typing](https://github.com/cdce8p/python-typing-update) from v0.6.0 to 0.8.1

## [3.1.0] - 2026-05-24

### Added

- **SMS Services**: Four new Home Assistant actions — `send_sms`, `delete_sms`, `delete_all_sms`, and `get_sms_list` — for full SMS management from automations and scripts.
- **SMS Received Event**: Integration now fires a `zte_router_5g_sms_received` event when a new SMS arrives, enabling event-triggered automations.
- **SMS Storage Full Repair**: A repair issue is raised in the HA Repairs panel when NV SMS storage reaches capacity; it clears automatically when resolved.
- **Uptime Duration Sensor**: New sensor reporting how long the router has been running (disabled by default).
- **State-Dependent Entity Icons**: Entity icons now reflect live state (e.g. Best Connection sensor shows an active signal icon when connected).

### Changed

- **Flexible Host Input**: The host field now accepts addresses with `http://` or `https://` prefixes; they are stripped automatically during setup and reconfiguration.

### Fixed

- **Stable Uptime Timestamp**: Boot time is now latched once and only re-derived when the router's uptime counter drops — the only reliable reboot signal. Bad or missing uptime readings leave the cached value untouched, eliminating timestamp drift caused by independently ticking clocks.
- **Empty Sensor Values**: Sensors receiving an empty string from the router now correctly report **Unknown** state in HA instead of displaying a blank value.
- **Spurious Reauthentication**: Transient connection drops and network errors no longer incorrectly trigger the reauthentication flow; reauth is reserved for explicit credential rejection from the router.
- **Monthly Data (Legacy GB Sensors)**: Corrected unit calculation from binary gibibytes (GiB, 1,073,741,824 bytes) to decimal gigabytes (GB, 1,000,000,000 bytes).

## [3.0.2-dev11] - 2026-05-24 - Unreleased

### Changed

- **Documentation**: Added info on new SMS actions and event to README, plus additional automation examples.

## [3.0.2-dev10] - 2026-05-23 - Unreleased

### Added

- **`CLAUDE.md`** (project root): Added Claude Code guidance file documenting project structure, commands, Windows devcontainer usage (docker exec pattern, link to `.shared/prompts/devcon_run_gen.md`), integration architecture overview, and config entry storage convention (including new `last_uptime` field).

### Changed

- **Uptime boot timestamp stabilization** (`coordinator.py`): Replaced 30-second timestamp-delta tolerance latch with a reboot-detection latch. Boot time is now computed once and frozen; it re-derives only when the router's uptime counter drops by more than `UPTIME_REBOOT_MARGIN` (30 s) — the only clock-independent signal of a genuine reboot. Added bad-reading guard: missing or unparsable `realtime_time` readings leave the latched value untouched and do not advance the anchor. Added `last_uptime` as a persisted reboot-detection anchor in `entry.data` alongside `boot_time`. Eliminates drift caused by recomputing `now() − uptime` against two independently ticking clocks.

## [3.0.2-dev9] - 2026-05-23 - Unreleased

### Added

- **9 new tests** (`test_init.py`): Achieved 100% coverage on `__init__.py`. Covers: `_get_coordinator` with entry_id (ready and not-ready paths), fallback with no entries, exception handling in all 4 SMS services (`send_sms`, `delete_sms`, `delete_all_sms`, `get_sms_list`), mixed box-type SMS list, and `async_setup` service handler callables.
- **SMS received event firing** (`coordinator.py`, `test_init.py`): Implemented `zte_router_5g_sms_received` event firing when a new SMS message is parsed. Added unit test `test_sms_received_event_firing` to verify ordered firing and baseline deduplication.

### Test Coverage

- `__init__.py` 83% → 100%

## [3.0.2-dev8] - 2026-05-23 - Unreleased

### Added

- **SMS capabilities and services** (`api.py`, `__init__.py`, `services.yaml`): Implemented `send_sms` (UTF-16BE hex encoding), `delete_sms` (by index/id), `delete_all_sms` (bulk/partial deletes with safety `keep_last` count), and `get_sms_list` (response-supporting action with filtering and pagination).
- **Service definitions** (`services.yaml`): Added Home Assistant service registration and field configuration.
- **Service test coverage** (`test_api.py`, `test_init.py`): Added 7 new unit tests covering all services, input formatting, filtering, and error branches.

### Fixed

- **HASSFEST warning** (`__init__.py`): Defined `CONFIG_SCHEMA` helper to resolve setup validation warning.

## [3.0.2-dev7] - 2026-05-23 - Unreleased

### Fixed

- **Uptime Jitter & HA Restarts** (`coordinator.py`): Persisted the calculated boot timestamp in `entry.data` and restored it on startup, applying a 30-second tolerance window to prevent timestamp shifting on Home Assistant reboots.

## [3.0.2-dev6] - 2026-05-23 - Unreleased

### Added

- **14 new tests** (`test_coverage_ext.py`): Achieved 100% coverage on `api.py` and `coordinator.py`. New tests cover: IP protocol prefix stripping, HTML detection via URL and Content-Type (with/without retry), JSON parse retry/no-retry, login password_error result, outer-except re-auth re-raise, boot_time calculation/value-error/missing, reconnection log transition, SMS storage exception handling, and text/body preview exception handlers. Total project coverage: 99%.

### Fixed

- **24 test failures across 4 test files** (`test_api.py`, `test_coverage_ext.py`, `test_sensor.py`, `test_init.py`): Root cause — `MockResponse` lacked `headers`/`text()` methods and `session.request` was not routed to `get`/`post` in the conftest fixture. Additional fixes: aligned sensor byte-to-GB test values with decimal `_BYTES_PER_GB=1000000000`, corrected reauth trigger test to account for 3-tolerance retry logic before `UpdateFailed`, and fixed `extra_state_attributes` test using falsy empty dict.

## [3.0.2-dev5] - 2026-05-23 - Unreleased

### Fixed

- **mypy `--strict` import errors** (`sensor.py`, `switch.py`, `number.py`): Resolved `EntityCategory` import errors by importing directly from `homeassistant.const` instead of `homeassistant.helpers.entity`.
- **Unused import cleanup** (`__init__.py`): Removed unused `typing.Any` import to satisfy `ruff check`.

## [3.0.2-dev4] - 2026-05-23 - Unreleased

### Fixed

- **mypy `--strict` regression** (`coordinator.py`, `sensor.py`, `switch.py`, `number.py`, `button.py`, `binary_sensor.py`, `__init__.py`, `config_flow.py`): Resolved 43 mypy strict errors introduced by recent changes. Fixes include: removed stale `type: ignore` comments, removed redundant `cast()` calls, fixed Python 2 bare-comma `except` syntax, added explicit `datetime | None` type annotations to coordinator `_boot_time` and `last_update_success_time`, suppressed known HA ConfigFlow stub incompatibilities with `type: ignore[override]`, and fixed `MappingProxyType` argument mismatch by converting to `dict()`.

## [3.0.2-dev3] - 2026-05-22 - Unreleased

### Added

- **Uptime Duration Sensor** (`sensor.py`, `strings.json`, `translations/en.json`): Added `system_uptime_duration` sensor (disabled by default, device class `duration`, state class `measurement`, unit `"s"`).

### Changed

- **Centralized request helper** (`api.py`): Refactored all API methods to route through a centralized async `_request()` helper, automatically validating responses, handling Content-Type text/html overrides, and managing transparent login retries.
- **Uptime Timestamp stable calculation** (`coordinator.py`, `sensor.py`): Implemented cached `_boot_time` with a 15-second tolerance check to prevent boot timestamp jitter.
- **Legacy GB Sensors Correction** (`sensor.py`): Corrected `_BYTES_PER_GB` to use decimal base `1000000000` (GB) instead of binary `1073741824` (GiB) for legacy monthly data sensors.
- **Host Input Cleaning & Cookie Jar Cleardown** (`api.py`): Stripped HTTP/HTTPS scheme prefixes and trailing slashes from incoming IP/host inputs in `ZTERouterAPI.__init__`. Refined `stok` cookie clearing using a predicate lambda.

### Fixed

- **Empty Values to Unknown** (`sensor.py`): Implemented `_safe_str()` helper to map empty strings and `None` to Python `None` (Unknown state in HA) for candidates and 5G signal sensors.
- **Reauth Guard & Login Classification** (`api.py`, `coordinator.py`): Classify login responses to raise `ZTEAuthError` specifically on explicit credential error codes, preventing immediate re-auth flows on transient connection drops by holding last known values for 3 consecutive poll cycles.
- **Python Exception Syntax** (`sensor.py`): Updated legacy exception syntax to tuple format `except (ValueError, TypeError):` for Python 3.12+ compatibility.

## [3.0.2-dev2] - 2026-05-13 - Unreleased

### Added

- **Repair Issue — SMS Storage Full** (`coordinator.py`, `strings.json`, `translations/en.json`): `_check_sms_storage` raises an HA repair issue when NV SMS storage is at capacity; clears it when not. Surfaced in the HA Repairs panel with a description and Delete All button guidance.
- **`icons.json`**: State-dependent icon declarations for all 51+ entities; `signal_best_connection` uses `on: mdi:signal` / `off: mdi:signal-cellular-1`. Hardcoded `icon` properties removed from entity classes.

### Changed

- **Project Structure Document**: Updated the project structure document to v1.0.4.
- **IQS Full Compliance**: All 46 trackable rules across Bronze, Silver, Gold, and Platinum tiers now DONE — first project in the PlayFaster family to reach 100% IQS compliance. Records updated in `quality_scale.yaml` and `ha_quality_standard.md`.
- **README**: Added tested firmware version (MC7010 V1.0.0B01 and later) to Compatibility section.

### Fixed

- **mypy `--strict`**: 0 errors across all 12 source files (`mypy_strict.txt`: "Success: no issues found in 12 source files"). `quality_scale.yaml` `strict-typing` updated to DONE.
- **Stale test assertions** (`test_binary_sensor.py`): Removed `assert sensor.icon` lines that failed after `icon` property was replaced by `icons.json` declarations. CI unblocked.

## [3.0.2-dev1] - 2026-05-13 - Unreleased

### Changed

- **DevCon**: Devcontainer changes to pull in home assistant files to properly run mypy --strict
- **Devcontainer mount consolidation**: Moved `.notes` and `.shared` mounts from `devcontainer.json` to `docker-compose.yml` — mounts with absolute paths are unreliable in Docker Compose mode when declared in `devcontainer.json`; compose-file volumes are authoritative for the compose service.
- **HA core mounted for mypy**: Mounted HA core source (`C:/Local/Code/ha_core/core` → `/ha_core`) into the devcontainer via `docker-compose.yml` as read-only, so mypy can resolve HA type stubs without installing the full HA package.
- **`mypy_path` configured**: Added `mypy_path = "/ha_core"` to `[tool.mypy]` in `pyproject.toml` to point mypy at the mounted HA source.
- **mypy scoped to custom component**: Added `[[tool.mypy.overrides]]` for `homeassistant.*` with `ignore_errors = true` and `follow_imports = "silent"` to prevent mypy from checking and reporting errors from HA core files while still using them for type resolution.

## [3.0.1] - 2026-05-10

### Changed

- **Readme**: Overhaul of the readme file, additional example automations, re-ordered for readability.
- **Under the Hood**: Several internal code changes to improve maintainability and alignment with Home Assistant development standards (no functional breaking changes).
- **Validations**: Improved local and automated remote testing to ensure code remains secure and follows best practices.

## [3.0.1-rc1] - 2026-05-10 - Unreleased

### Changed

- **Readme**: Updated Readme with additional information. Re-ordered some sections. Added more emoji icons to headings.

## [3.0.1-dev8] - 2026-05-10 - Unreleased

### Changed

- **Readme**: Updated Readme with an additional automation example and some new sections.
- **`get_rd` auto-login guard** (`api.py`): Replaced `assert self.stok is not None` with `if not self.stok: self.stok = await self.login()` — consistent with 6 other methods.
- **`get_version` error return** (`api.py`): Changed from `""` to `None` (type updated to `str | None`). Both callers use `if not version`, behavior is identical.
- **Background task fallback** (`conftest.py`): Replaced `return MagicMock()` with `asyncio.ensure_future(coro)` to properly schedule coroutines and eliminate `RuntimeWarning`.

### Fixed

- **Protocol fallback silent failure** (`api.py`): Added `_LOGGER.warning` when both http/https probes fail — operators now see a log entry instead of silent failure.
- **Magic number in sensor.py**: Extracted `_BYTES_PER_GB = 1073741824` constant for clarity and maintainability.
- **2 `RuntimeWarning: coroutine was never awaited`** (`test_setup_entry_success`, `test_background_setup_failure`): Coroutine now scheduled on the event loop instead of discarded via `MagicMock()`.
- **Test assertion mismatch** (`test_api.py`): Updated `test_api_get_version_error` assertion from `== ""` → `is None` after `get_version` type change.

### Test Coverage

- **1 new test**: `test_coordinator_metadata_update_device_exists` — covers the coordinator path when a device already exists in the registry.

## [3.0.1-dev6] - 2026-05-10 - Unreleased

### Fixed

- **24 mypy errors in `api.py`**: Added type annotations to all functions, params, and return types. Changed `await self.login()` → `self.stok = await self.login()` in 7 methods so mypy sees `str` after login without breaking tests that mock `login()`.
- **6 test failures from mypy fix**: Updated 2 test files (`test_api.py`, `test_coverage_ext.py`) to set `api.stok` before calling `get_rd()` in error/success paths. Source in `api.py` changed from `assert` to return-value assignment.

### Test Coverage

- **8 new tests**: `delete_sms` exception handler, `get_all_data` retry-exhausted warning branch, `__init__` background setup success, 5 `config_flow` reconfigure flow tests (success + 3 error branches + form display).
- **Coverage to 100%**: `api.py` (98→100%), `__init__.py` (92→100%), `config_flow.py` (88→100%). Overall: 99% (824/824, 5 uncovered).

## [3.0.1-dev5] - 2026-05-10 - Unreleased

### Added

- **Reconfiguration Flow**: Support for updating host and credentials via the "Configure" menu.
- **Hierarchical Translations**: Canonical translation keys for all 63 entities with sub-device grouping.

### Changed

- **Translation Strategy**: Standardized on `translation_key` across all platforms; removed hardcoded `name` parameters.
- **Documentation**: Expanded README with Technical Architecture, Resilience (3-strike logic), and Firmware Compatibility.

## [3.0.1-dev4] - 2026-05-09 - Unreleased

### Changed

- **pyproject.toml**: pyproject.toml is now fully project agnostic. It does not contain the name of the specific project, instead just references the general custom_components folder for pytest coverage.
- **tasks.json**: tasks.json is also not fully project agnostic. It does require a settings.json file, but this now only requires one change per project.

## [3.0.1-dev3] - 2026-05-09 - Unreleased

### Dev Tooling

- **Shared Reusable CI Workflow**: Created `PlayFaster/.github` organization repo containing a parameterized reusable workflow (`validate.yaml`, named "Validate (Shared)"). All 8 validation jobs (`hassfest`, `hacs_val`, `py_val`, `test_val`, `file_val`, `codespell`, `zizmor`, `mypy_val`) now live in the shared repo and are called by each integration via a thin caller. Changes to validation logic propagate to all 4 projects on the next CI run without per-project edits.
- **Thin Caller Workflow**: Replaced the 270-line inline `.github/workflows/validate.yaml` with a ~30-line caller that delegates to the shared workflow via `uses: PlayFaster/.github/.github/workflows/validate.yaml@main`. Permissions correctly scoped: `contents: read` at workflow level, `contents: write` and `pull-requests: write` at job level (required by `test_val` for coverage badge and PR comments).
- **Shared Workflow Concurrency**: Reusable workflow uses `${{ github.workflow }}-${{ github.ref }}-${{ github.repository }}` as its concurrency group, preventing cross-repo cancellation when multiple integrations trigger simultaneously.
- **Shared Workflow Dependabot**: Added `dependabot.yml` to `PlayFaster/.github` tracking the `github-actions` ecosystem weekly, keeping SHA pins in the shared workflow current.
- **Pre-commit: Suppress Inapplicable Hooks**: Added `stages: [manual]` to the `no-commit-to-branch` hook — direct commits to `main`/`dev` are the working pattern for this project, so the hook is retained for explicit use but removed from the default commit flow. Added `exclude: \.yamllint$` to the `yamllint` hook to prevent it from linting its own config file (which lacks `---` and uses CRLF).
- **VS Code Tasks**: Added `Zizmor: Fix (Safe Auto-Fix)` task (`zizmor --fix .github/`) for applying zizmor's safe auto-fixes on demand. Added `Pre-commit: Autoupdate Hooks` task (`pre-commit autoupdate`) for updating all hook `rev:` pins to their latest releases. Neither task is wired into `Fix All` or `Validate All`.

## [3.0.0] - 2026-05-08

### Added

#### Major Refactoring (Version 3.0)

- This release introduces a modern, safer, and more resilient core architecture designed to improve the reliability and customization of the integration.

#### Performance & Stability

- **Faster, Non-Blocking Startup**: Integration setup now runs entirely in the background. Home Assistant will not "hang" or slow down while waiting for the router to respond during startup.
- **Native Async Architecture**: Rewritten to be more efficient and optimize resource utilization. This ensures the integration operates properly with the Home Assistant event loop.
- **Improved Connection Resilience**: Sensors will now hold their last known values for up to three failed connection attempts. This prevents "Unavailable" flickers during brief network hiccups.
- **Reliable Device Info**: Hardware models and software versions are now saved locally. The Device Page will stay populated even if the router is rebooted or goes offline.
- **Stable Device Identity**: The integration now uses the hardware IMEI as a stable identifier. This ensures your entities and their history remain consistent even if the router's IP address changes.
- **Enhanced Connection Security**: Verified that no sensitive tokens or passwords are logged or persisted in state attributes.
- **Domain Cleanup**: Implemented standardized unloading logic to ensure the integration key is scrubbed from Home Assistant's internal memory when no integration instances remain.

#### New Features & Customization

- **12 New Sensors**: Significant expansion of monitored metrics including **IMEI**, **Hardware Version**, **SIM IMSI**, **SIM ICCID** (System); **eNodeB ID**, **Network Mode**, **Bridge Mode** (Signal); **Upload/Download Speed**, and **Session Usage** (Data).
- **Custom Entity Naming**: You can now set a custom prefix (e.g., _"My ZTE Router"_) for all devices and entities during setup or via the **Configure** menu.
- **Smarter Device Organization**: Entities are now automatically grouped into logical sub-devices (**System**, **Signal**, **Data**, and **SMS**) to reduce the overwhelm factor and make it easy to disable certain sections if desired.
- **Data Integrity Guards**: New "Guard Bands" and safety checks ensure your sensors don't report impossible values or cause errors during initial connection.
- **Reauthentication Support**: If your router password changes, Home Assistant will now notify you and provide a simple dialog to update your credentials without needing to re-install the integration.
- **Download Diagnostics**: Added support for Home Assistant's diagnostic tool, allowing you to easily export redacted integration data for troubleshooting.
- **Monthly Data in Bytes**: Added Monthly data in native bytes unit (up, down, total). This is the default and supports Home Assistant's built-in unit conversion.

### Changed

- **User-Friendly Labels**: Refined entity labels for better readability (e.g., "PPP Status" → "**Bridge Mode**", "Wa Inner Version" → "**Firmware Version**").
- **Readme**: Updated and added automation examples.

## [3.0.0-rc1] - 2026-05-08

### Changed

- **Entity categories and visibility**: Refined sensor categorization and default settings. Moved **Device Uptime**, **Last Updated**, and **Best Connection** to regular Sensor category; moved **WAN Connect Status** to Diagnostic. Set **Battery** to be disabled by default.
- **User-Friendly Labels**: Renamed **PPP Status** sensor to **Bridge Mode** for better clarity in the UI.

### Fixed

- **Readme**: Updates to Readme including corrections to automation examples.

## [3.0.0-dev22] - 2026-05-08

### Fixed

- **Hassfest translation schema** (`strings.json`, `translations/en.json`): Removed invalid top-level `"reauth"` key; moved `reauth_confirm` step into `config.step` where the HA translation schema requires it. Resolves hassfest CI error: `extra keys not allowed @ data['reauth']`.
- **Reauth `{host}` placeholder** (`config_flow.py`): Added `description_placeholders={"host": host}` to `async_show_form` in `async_step_reauth_confirm` so the router IP resolves in the dialog description at runtime instead of rendering as a literal `{host}` string.

## [3.0.0-dev21] - 2026-05-08

### Added

- **Gold Standard README**: Comprehensive documentation overhaul with entity tables, technical context, and YAML automation examples.
- **Missing Translations**: Added 15+ missing translation keys for 5G signal metrics and hardware diagnostics to ensure 100% coverage.

### Changed

- **User-Friendly Labels**: Refined entity labels in `strings.json` for better readability (e.g., "Wa Inner Version" → "Firmware Version").

### Fixed

- **Hassfest Validation**: Resolved duplicate `reauth` keys in `strings.json` that caused CI/CD failures.

## [3.0.0-dev19] - 2026-05-07

### Changed

- **Shared `device_info` helper**: Extracted 5-way duplicated `device_info` property into `build_device_info()` in `helpers.py`. All platform files (`sensor.py`, `binary_sensor.py`, `button.py`, `switch.py`, `number.py`) now delegate to the shared helper. Fixes Low #2.
- **Dynamic `configuration_url`**: Migrated from hardcoded `http://` to `{protocol}://` using `coordinator.api.protocol`. Fixes Low #3.
- **Device Registry metadata updates**: Replaced mid-poll `async_update_entry(entry.data)` writes with `device_registry.async_update_device()`. Hardware metadata changes propagate to the registry without writing config entry data on every poll. Fixes Medium #2.
- **Sensor naming → translation-based**: 58 sensor descriptions migrated from hardcoded `name="..."` to `translation_key="<key>"`. `strings.json` is now the canonical display-name source. Added 3 missing entries to `strings.json`; added 7 missing entries to `translations/en.json`; resolved 5 name discrepancies between the two files.

### Fixed

- **Unbounded recursion in `get_all_data`**: Added `_retry: bool = True` guard parameter. Second re-login attempt with same empty response returns partial data instead of recursing until `RecursionError`. Fixes High #2.
- **Untracked async task in `ZTEPollingInterval`**: Added `async_will_remove_from_hass` to cancel `self._refresh_task` on integration unload. Fixes High #3.
- **Null dereference in `async_step_reauth_confirm`**: Added `entry is None` guard before accessing `entry.options`. Fixes High #4.
- **Python 2 `except` syntax**: Fixed 7 occurrences of bare comma-form `except ValueError, TypeError:` → `except (ValueError, TypeError):` and `except KeyError, AttributeError:` → `except (KeyError, AttributeError):`. Fixes Medium #1.
- **`ValueError` escape in `native_value`**: Widened except from `(KeyError, AttributeError)` to `(KeyError, AttributeError, ValueError)`. Fixes Medium #3.
- **Bare `Exception` for missing password**: Changed `raise Exception("No password provided")` to `raise ZTEAuthError(...)` so it triggers reauth instead of silent retry. Fixes Medium #4.
- **`delete_sms()` missing `stok` clearing**: Wrapped POST in try/except with `self.stok = None; raise`. Fixes Medium #5.
- **Orphaned test body**: Extracted reauth flow assertions into properly decorated `test_reauth_flow_show_form`. Fixes Medium #6.
- **`diagnostics.py` weak type annotation**: Changed `DataUpdateCoordinator` to `ZTERouterDataUpdateCoordinator`. Fixes Low #4.

### Removed

- **Duplicate `PARALLEL_UPDATES = 0`**: Removed second declaration from `sensor.py`, `binary_sensor.py`, `switch.py`, `number.py`. Fixes Low #1.

## [3.0.0-dev16] - 2026-05-07

### Changed

- **Shared `device_info` helper**: Extracted 5-way duplicated `device_info` property into `build_device_info()` in `helpers.py`. All platform files (`sensor.py`, `binary_sensor.py`, `button.py`, `switch.py`, `number.py`) now delegate to the shared helper. Fixes Low #2.
- **Dynamic `configuration_url`**: Migrated from hardcoded `http://` to `{protocol}://` using `coordinator.api.protocol`. Fixes Low #3.
- **Device Registry metadata updates**: Replaced mid-poll `async_update_entry(entry.data)` writes with `device_registry.async_update_device()`. Hardware metadata changes propagate to the registry without writing config entry data on every poll. Fixes Medium #2.
- **Sensor naming → translation-based**: 58 sensor descriptions migrated from hardcoded `name="..."` to `translation_key="<key>"`. `strings.json` is now the canonical display-name source. Added 3 missing entries to `strings.json`; added 7 missing entries to `translations/en.json`; resolved 5 name discrepancies between the two files.

### Fixed

- **Unbounded recursion in `get_all_data`**: Added `_retry: bool = True` guard parameter. Second re-login attempt with same empty response returns partial data instead of recursing until `RecursionError`. Fixes High #2.
- **Untracked async task in `ZTEPollingInterval`**: Added `async_will_remove_from_hass` to cancel `self._refresh_task` on integration unload. Fixes High #3.
- **Null dereference in `async_step_reauth_confirm`**: Added `entry is None` guard before accessing `entry.options`. Fixes High #4.
- **Python 2 `except` syntax**: Fixed 7 occurrences of bare comma-form `except ValueError, TypeError:` → `except (ValueError, TypeError):` and `except KeyError, AttributeError:` → `except (KeyError, AttributeError):`. Fixes Medium #1.
- **`ValueError` escape in `native_value`**: Widened except from `(KeyError, AttributeError)` to `(KeyError, AttributeError, ValueError)`. Fixes Medium #3.
- **Bare `Exception` for missing password**: Changed `raise Exception("No password provided")` to `raise ZTEAuthError(...)` so it triggers reauth instead of silent retry. Fixes Medium #4.
- **`delete_sms()` missing `stok` clearing**: Wrapped POST in try/except with `self.stok = None; raise`. Fixes Medium #5.
- **Orphaned test body**: Extracted reauth flow assertions into properly decorated `test_reauth_flow_show_form`. Fixes Medium #6.
- **`diagnostics.py` weak type annotation**: Changed `DataUpdateCoordinator` to `ZTERouterDataUpdateCoordinator`. Fixes Low #4.

### Removed

- **Duplicate `PARALLEL_UPDATES = 0`**: Removed second declaration from `sensor.py`, `binary_sensor.py`, `switch.py`, `number.py`. Fixes Low #1.

## [3.0.0-dev15] - 2026-05-07

### Added

- **12 new sensors** from live router interrogation (MC7010): IMEI, Hardware Version, Battery, SIM IMSI, SIM ICCID (System sub-device); eNodeB ID, Network Mode, PPP Status (Signal sub-device); Upload Speed, Download Speed, Session Sent, Session Received (Data sub-device). Entity count: 51 → 63.
- **Guard bands** on new numeric sensors: Battery (0–100 %), Upload Speed (min 0 B/s), Download Speed (min 0 B/s), Session Sent (min 0 bytes), Session Received (min 0 bytes).
- **Diagnostics redaction**: `imei`, `sim_imsi`, `sim_iccid` added to `TO_REDACT` in `diagnostics.py`.
- **Translation entries**: 12 new sensor keys added to `strings.json` and `translations/en.json`.

### Changed

- **Stable device identity**: `unique_id` now uses IMEI (hardware-bound modem identifier) instead of host IP. `config_flow.py` `_validate_credentials` returns `imei`; `async_step_user` uses `info.get("imei") or host` as unique*id. Fallback to `host*{IP}` preserved for firmware that does not expose IMEI.
- **`coordinator.mac` → `coordinator.imei`**: Renamed across `coordinator.py`, `__init__.py`, and all 5 platform `device_info` properties (`sensor.py`, `binary_sensor.py`, `button.py`, `switch.py`, `number.py`). Sub-device identifiers now use IMEI prefix.
- **Tests updated**: `conftest.py` fixture renamed to `coordinator.imei = "864155042229309"`; device identifier assertions updated in `test_number.py`, `test_sensor.py`, `test_binary_sensor.py`, `test_button.py`.

## [3.0.0-dev14] - 2026-05-07

### Added

- **`diagnostics.py`**: New diagnostics platform. Exposes coordinator state, entry data, and live router data (with credential redaction) via Developer Tools → Download Diagnostics.
- **Reauthentication Flow**: `async_step_reauth` and `async_step_reauth_confirm` in `config_flow.py`. `ZTEAuthError` in coordinator triggers `entry.async_start_reauth`. `strings.json` updated with reauth strings.
- **Installation Parameters**: Documented minimum HA version (2024.6.0), Python (3.12+), and tested firmware in README.
- **Configuration Parameters**: Documented polling interval range (30–3600s), defaults, and runtime options flow in README.
- **Config Flow Test Coverage**: Added show-form paths (`user_input=None`) for both config and options steps. Added options flow `ZTEAuthError` branch test.

### Changed

- **`runtime-data`**: Migrated from `hass.data[DOMAIN][entry.entry_id]` to `entry.runtime_data` in `__init__.py` and all 5 platform files. Simplified `async_unload_entry`.
- **`parallel-updates`**: Added `PARALLEL_UPDATES = 0` to all 5 platform files (`sensor.py`, `binary_sensor.py`, `button.py`, `switch.py`, `number.py`).
- **Log-on-unavailable**: Coordinator now logs WARNING on first failure, DEBUG on intermediate retries (2/3, 3/3), ERROR on transition to unavailable, and INFO on reconnection (`_was_available` flag).
- **`strings.json`**: Added `data_description` blocks for `host` and `password` in config and options steps.

### Fixed

- **Action Exceptions**: Both `async_press` handlers (`reboot`, `delete_all`) now raise `HomeAssistantError` on API failure instead of silently logging, enabling automation failure detection.
- **Test failures**: Updated `test_coverage_ext.py` button exception tests to expect `HomeAssistantError`. Fixed `test_init.py` reauth test to use `patch.object` for `async_start_reauth`.

## [3.0.0-dev11] - 2026-05-07

### Changed

- **Badge Links**: Added links to readme badges.

## [3.0.0-dev10] - 2026-05-02 - Unreleased

### Changed

- **Badge Links**: Added links to readme badges.

- **Sub-device Architecture**: Grouped entities into System (Root), Signal, Data, and SMS devices for better Home Assistant UI organization.

## [3.0.0-dev8] - 2026-04-29 - Unreleased

### Added

- **Sub-device Architecture**: Grouped entities into System (Root), Signal, Data, and SMS devices for better Home Assistant UI organization.
- **Data Standards Alignment**: Implemented `SensorDeviceClass.DATA_SIZE` and `UnitOfInformation.BYTES` for all volume sensors.
- **Standardized Units**: Aligned Signal units with 3GPP standards (RSRP/RSSI in dBm; RSRQ/SNR/SINR in dB).
- **Entity Identity**: Implemented stable `unique_id` strategy using lowercase internal keys (e.g., `z5g_rsrp`) and MAC address prefix.
- **SMS Resilience**: Added logic to maintain sensor state attributes during update failures, preventing data loss in the UI.
- Added `zte_all_sensors.md` which documents all sensors/data-elements, their source and unit etc.
- **Monthly Data in Bytes**: Added Monthly data in native bytes unit (up, down, total). This is the default.

### Changed

- **Coordinator Logic**: Enhanced with a 3-strike failure counter before raising `UpdateFailed`, improving stability against transient network timeouts.
- **API Authentication**: Refined `stok` reset logic to force reauthentication after specific service failures (SMS/Reboot).
- **Volume Sensors**: Legacy GB sensors are now disabled by default in favor of standard Byte sensors. They remain available for legacy reasons.
- **Disabled by Default**: Set several unknown sensors and some not useful to Disabled by Default. These can be enabled by the user if desired.
- **Entity Naming**: Improved many entity names to be more human readable, not just the shortened router element name.

### Fixed

- **Test Suite Stability**: Resolved `AttributeError` on `MockConfigEntry.options` by using `object.__setattr__` for immutable properties.
- **Resource Warnings**: Eliminated `RuntimeWarning` from background tasks by falling back to `asyncio.create_task` when the HA mock is present.
- **Config Flow**: Fixed `KeyError: 'host'` in tests by ensuring mandatory connection parameters are preserved during mocking.
- **Linting**: Achieved zero violations across the codebase (Ruff format/check).

### Removed

- **Redundant Logic**: Removed "just-in-case" error swallowing in the coordinator that masked legitimate API timeouts.

### Security

- **Credential Protection**: Verified that no sensitive tokens or passwords are logged or persisted in state attributes.

## [3.0.0-dev5] - 2026-04-07 - Unreleased

### Added

- **Declarative Guard Bands**: Implemented "Standard 4" data integrity validation. Technical sensors (Signal Strength, SNR, Signal Bar, and SMS counts) now utilize declarative `min_limit` and `max_limit` boundaries to filter out transient hardware reporting spikes.

### Changed

- **Standardized Resilience**: Aligned the Data Update Coordinator with the "PlayFaster" architectural standards. Increased the failure threshold to 3 cycles and synchronized warning logs to provide consistent status reporting across all PlayFaster router integrations.
- **Custom User Naming**: Implemented `CONF_NAME` support. Users can now define a custom prefix (e.g., "Home Gateway") during setup or reconfiguration, which is applied to the integration title, device name, and all child entities.
- **Standardized Device Info**: Updated the sensor platform to strictly use the integration title for device naming, ensuring full compatibility with the new custom naming standard.

### Fixed

- **Entity Naming Integrity**: Synchronized the sensor platform's naming logic to ensure deterministic entity IDs that correctly incorporate the user-defined custom name prefix.
- **Log Consistency**: Refactored coordinator error messages to use the standardized "PlayFaster" wording for better cross-project log analysis.

## [3.0.0-dev3] - 2026-04-07 - Unreleased

### Added

- **Declarative Entity Engine**: Refactored the sensor platform to use a modern callback-based architecture (`value_fn`). This replaces 100+ lines of imperative logic with clean, maintainable entity descriptions.
- **Dynamic Sub-Device Routing**: Unified multiple sensor classes into a single dynamic engine that automatically routes entities to the correct sub-device (SMS, Monthly Data, or Main Router) based on metadata.

### Changed

- **Modern Background Tasks**: Migrated the non-blocking startup sequence to the modern `entry.async_create_background_task` API. This ensures the setup task is formally tracked by Home Assistant and automatically cancelled if the integration is unloaded.
- **Standardized Resilience**: Aligned the Data Update Coordinator with Home Assistant best practices. Removed manual retry sleeps and implemented `asyncio.timeout` with structured `UpdateFailed` reporting.
- **Flat Identity Pattern**: Refactored `device_info` across all platforms to use persistent coordinator-level attributes. This ensures hardware model information is visible in the UI from the exact second of boot, even before the first network fetch.

### Fixed

- **Domain Cleanup**: Implemented standardized unloading logic to ensure the `DOMAIN` key is scrubbed from Home Assistant's internal memory when no integration instances remain.

## [3.0.0-dev2] - 2026-04-07 - Unreleased

### Added

- **Persistent Metadata**: The integration now fetches and stores the hardware model and software version in the `ConfigEntry` during setup. This ensures the Device Page is always populated correctly, even if the router is offline.
- **Strict Linting**: Enabled `N` (pep8-naming) and `D` (pydocstyle) rules in `ruff` configuration for ongoing code quality.
- **Comprehensive Documentation**: Added module, class, and method-level docstrings across the entire codebase.

### Changed

- **Non-Blocking Startup**: Removed the initial blocking data fetch during integration setup. Home Assistant now starts instantly, and the first data poll occurs in the background.
- **PEP8 Naming**: Internal API methods to lowercase (Python standards).
- **Docstring Style**: Add missing docstrings and standardize to use imperative tone.
- **README**: Improve screenshot visibility.
- **Tests and Coverage**: Added Testing and Coverage to GitHub Validation (previously only local).

### Fixed

- **Standardized Device Info**: All 46+ entities now use consistent coordinator-based metadata for the Home Assistant Device Registry.
- **Config Entry Setup**: Resolved a `KeyError: 'host'` by correctly reading configuration from `entry.options` instead of `entry.data`.
- **Data Safety**: Implemented safety checks for `None` data in sensors to prevent runtime errors during initialization or connection loss.
- **Exception Handling**: Fixed invalid syntax in multiple exception handlers.

## [3.0.0-dev1] - 2026-04-01 - Unreleased

### Added

- **Native Async Architecture**: Migrated the entire API and polling layer to `aiohttp` for native asynchronous execution.
- **Improved Performance**: Removed thread-based `executor_job` wrappers, aligning the integration with the Home Assistant event loop.
- **Dependency Simplification**: Removed `requests` as a required dependency, eliminating maintenance of version pinning.

### Changed

- **Version Bump**: Major version update to reflect the complete architectural shift.

## [2.3.1] - 2026-04-01 PUBLIC RELEASE

### Added

- **Development Documentation**: Added `DEVELOPMENT.md` containing architectural notes and project history.
- **Screenshots**: Added images to `README.md`.
- **Icon and Logo**: Added required assets for HACS and Home Assistant branding.
- **Automated Validation**: Integrated specialized GitHub Actions for Hassfest, HACS, and Python quality.

### Changed

- **Architecture Refactor**: Introduced `coordinator.py` to centralize and optimize data fetching logic.

### Fixed

- **Unavailable Bug**: Fixed an issue where sensors would never go unavailable due to misconfigured grace period.

## [2.2.4] - 2026-03-30

### Added

- **Coverage**: Added basic test coverage.

### Changed

- **Clean Code**: Code clean-up and formatting/linting rules.
- **Testing**: Improved scope of testing.
- **Strings**: Added strings.json in addition to en.json.

## [2.2.3] - 2026-03-30

### Added

- **Testing Infrastructure**: Added python tests.

### Fixed

- **Manifest**: Fixed manifest.json for GitHub tests.

## [2.1.1] - 2026-03-29

### Added

- **Error Logging**: Significantly improved home assistant (logger) error logging.

## [2.0.1] - 2026-03-29

### Added

- **Options Flow**: Allow reconfiguration of integration in-situ rather than delete and re-add.

## [1.9.4] - 2026-03-29

### Added

- **Model Number**: Pulls model number from device.

### Changed

- **Exception Handling**: Improved exception handling.

### Fixed

- **Strings and Translate**: Fixed strings en.json structure and moved all elements to this.
- **Sessions Handling**: Explicit closing of sessions.

## [1.8.1] - 2026-03-29

### Added

- **Strings and Translate**: Added translation folder structure, just en for now.

## [1.7.3] - 2026-03-29

### Fixed

- **Entity Naming**: Fixed entity sensor naming approach.

## [1.6.3] - 2026-03-28

### Changed

- **Reduced Startup Risk**: Moved to async for startup to avoid any potential for slowness/hangs/locks if router is unavailable at HA start.

## [1.5.7] - 2026-03-28

### Added

- **Integration Icon**: Added ZTE icons.

### Fixed

- **Sub Device Sensors**: Properly align sub device (data, sms) sensor naming.

## [1.5.1] - 2026-03-28

### Changed

- **Aligned Integration Naming**: All naming now ZTE Router 5G Monitor.

## [1.4.5] - 2026-03-28

### Added

- **Changelog**: Added Changelog (this) as CHANGELOG.md.

### Changed

- **Standard Names**: Changed specific sensor names (with ID tag) to standard names.

## [1.4.4] - 2026-03-28

### Added

- **All Relevant Attributes**: Added all relevant signal and status attributes available from the router as sensors.

## [1.4.3] - 2026-03-28

### Added

- **Pause Polling Switch**: New entity to manually halt API traffic to the router.
- **Polling Interval Slider**: Number entity to adjust the refresh rate (30s to 3600s) directly from the UI.
- **Persistence**: Integration now saves Polling State and Interval to `ConfigEntry` options, ensuring settings survive a Home Assistant restart.

### Fixed

- **Startup Deadlock**: Implemented "Initial Bypass" logic to ensure entities load correctly on restart even if polling was previously paused.
- **Boot Resilience**: Added a fail-safe to prevent the integration from becoming "Unavailable" if the router is unreachable during the initial Home Assistant startup sequence.

## [1.4.2] - 2026-03-27

### Added

- **SMS Monitoring**: Added sensors for SMS capacity (total/used) and a sensor to display the content of the latest received message.
- **Hybrid Resilience**: Implemented a "one-cycle grace period" where sensors hold their last known value during a single failed poll before marking as unavailable.
- **GitHub**: Initial release to GitHub repository.

## [1.4.1] - 2026-03-27

### Changed

- Refactored `DataUpdateCoordinator` to handle centralized data fetching for all platforms.
- Improved API login reliability with automatic protocol detection (HTTP/HTTPS).

## [1.4.0] - 2026-03-26

### Added

- Core sensors: Signal Strength (RSRP/RSRQ/SINR), Network Type, and Data Usage.
- Connection status binary sensor.

## [1.3.6] - 2026-03-25

### Added

- Initial release for ZTE MC7010 5G Router.
- Moved from one sensor with all data as sensor attributes to separate sensors.
- Added config flow.
- Added single device, then sub-devices (router, data, sms).

---

### Format

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
