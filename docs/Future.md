# Future Roadmap: ZTE Router 5G Integration

Strategic opportunities for `ha-zte-router-5g-monitor`. The original roadmap (2026-05) framed the goal as a transition from **monitoring** to **active management**. That transition has largely happened — most of what follows is now either shipped or deliberately declined.

**Reviewed 2026-07-30** against the running instance (92 entities) and the current source. Status below is verified, not assumed.

---

## ✅ Delivered since the original roadmap

| Original item | Status | Where it landed |
| :-- | :-- | :-- |
| **`send_sms` service** _(then the single largest gap)_ | **Done** | Four SMS actions ship: `send_sms`, `delete_sms`, `delete_all_sms`, `get_sms_list`. Encoding is now chosen per message — GSM-7 up to 765 characters, Unicode to 335 — which the roadmap did not anticipate. |
| **Carrier Aggregation & MIMO metrics** | **Done** | `wan_lte_ca`, `lte_ca_pcell_bandwidth`, `lte_ca_scell_bandwidth`, `nr5g_action_channel` all exposed. |
| **Data-usage projection** _(added as candidate 2 on 2026-07-29)_ | **Done** | `Projected Cycle Usage` ships on the Data sub-device, along with `Reset Day`. It is cycle-relative rather than calendar-relative — the router's counters reset on its own billing day, which the integration now reads. |
| **Coordinator "fast-path" after writes** | **Done, and better than specified** | The roadmap proposed `async_request_refresh()`. That would have been **wrong**: it is silently swallowed while Pause Polling is on. Every write action routes through `async_force_refresh()`, which consumes a one-shot flag _before_ the pause check. |

**One deviation worth recording.** The roadmap proposed `wan_lte_ca` as a **binary sensor** ("CA Active"). It shipped as a **sensor**, because the router reports the aggregation _configuration_ rather than a simple on/off. A binary sensor would have thrown away the detail. No change proposed.

---

## 🚧 Not implemented — and why

### Token persistence — **declined, and the reasoning has since strengthened**

_Original proposal: store `stok` in `ConfigEntry` data or a local cache to avoid a login cycle on every HA restart._

Still unimplemented, now deliberately. This router permits **one session at a time**, and a persisted token would be indistinguishable from a live one after any event that invalidated it — an HA restart is precisely when the router is most likely to have moved on. The integration would begin every session by presenting a token that may already be dead, against an API whose dead-session response is `200 OK` with blank values.

That failure mode is not hypothetical: it is the class behind both the `[3.3.0-dev12]` SMS-empty-inbox bug and the `[3.3.1-dev6]` silent-action-failure bug. The saving is one login per HA restart. **Recommendation: close this item rather than carry it.**

### Band locking — **partially delivered, and the remainder is the risky half**

- **Read side: done.** `LTE Band Lock Mask` (`lte_band_lock`) is exposed, disabled by default.
- **Adjacent control: done.** `Network Mode Selection` sets the bearer preference (4G/5G combinations, or either alone).
- **Write side: not implemented.** No `select` forces a specific band such as B20 or n78. `api.py` contains no `BAND_SELECT` or `WAN_PERFORM_NR5G_BAND_LOCK` command.

The original safety requirement — a "Reset to Auto" escape — remains correct. **A previous revision of this entry overstated why.** It claimed the integration reaches the router over the connection a bad lock breaks, so the reset control would be unreachable. That is wrong in the ordinary case: Home Assistant talks to the router at its **LAN address**, and a band lock kills the WAN, not the management path. The escape stays reachable and the lock can be undone.

The objection that survives is different, and still sufficient:

- **The failure is total, and silent to automation.** A lock to a band the router cannot see means no service at all — not degraded service. Anything depending on that connection stops.
- **It genuinely is unreachable for remote users.** Anyone reaching Home Assistant over that same WAN, via cloud or VPN, loses both the connection and the control that fixes it. That is a property of their access path, not of the router, but it is common enough to design for.
- **It is a setting to make once, not to script.** Band selection is tuning done deliberately with a signal meter to hand. Exposing it as an entity implies it is safe to automate.

**Where a user should go instead:** the router's own web page. It shows the current band and the alternatives in context, applies the change with the modem in front of it, and is reachable on the LAN whether or not the WAN is up.

**If this is ever built**, a self-clearing lock — revert if no data connection within _N_ seconds, enforced router-side rather than by the integration — is the only shape that is safe unattended.

### Cell locking (PCI) — **not implemented, and lower value than it appears**

No PCI lock control (`LTE_LOCK_CELL_SET` exists in the firmware and is deliberately not called). The objection above applies with more force: a cell is a smaller target than a band, and cells change with load and maintenance — so a lock that works today can leave the router with no service next week, after a change at the operator's end that the user never sees. The router already reports `lte_pci` and `nr5g_pci` for diagnosis, which is where the value is. If someone genuinely wants to pin a cell, the router's web page is the right place: it is a one-time tuning act, not something to automate.

---

## 📋 Current open items

Carried from `DEVELOPMENT.md` § Technical Debt — recorded here so this document is a complete forward view rather than a partial one.

| Item | Value | Effort | Note |
| :-- | :-- | :-- | :-- |
| **SMS feature-group toggle** (`dev_standards` §15) | ⭐⭐⭐ | Medium | Two of three polled endpoints exist solely for SMS, so a user who never sends one still pays two round trips per cycle. Disabling the sub-device hides the entities without stopping the polling. Needs a `CONF_ENABLE_SMS` option, guards on both `_fetch_optional` calls, and a `_degraded_endpoints()` exclusion — or Integration Health reports "degraded" for a capability the user switched off. |
| **Custom triggers** for `zte_router_5g_sms_received` | ⭐⭐ | Low | Would make the SMS event a GUI-discoverable trigger. **Blocked**: the HA trigger platform is a 2026.x construct against a declared floor of 2024.8.0, and is undocumented. Analysis in `.shared/issues/x_project/custom_trigger_options.md`. |

---

## 🔭 Candidates not previously considered

Proposed 2026-07-29. None is committed; each states what would justify it.

### 1. Cross-model verification ⭐⭐⭐⭐

Release 3.3.1 added alternative key spellings, a login-form fallback and channel-to-band resolution for other `goform` routers — **none of it exercised on hardware.** Three alias spellings (`5g_rsrp`, `5g_sinr`, `nr5g_sinr`) were not found in any source project and are speculative. The realistic path is a diagnostics download from an MC888 or MC889 user, which would confirm or delete them in one pass. **The single highest-value item on this list, and it costs nothing but a request in the issue tracker.**

### 2. Reboot-on-degradation automation blueprint ⭐⭐

The README carries an auto-reboot example with the necessary glitch guards. A shipped blueprint would make it usable without copying YAML, and would put the guards beyond reach of a copy-paste error. Blueprints are supported well below the current HA floor.

### 3. Diagnostics-driven compatibility reporting ⭐

`diagnostics.py` already sanitizes the vendor payload. A short documented procedure asking users on other models to attach one would feed item 1 directly. Documentation, not code.

---

### 4. Billing-cycle write controls ⭐⭐⭐ — _unblocked; only the entities remain_

**The hard part is done.** `DATA_LIMIT_SETTING` was confirmed as a six-field, all-or-nothing form, `api.set_data_volume_settings()` performs the read-modify-write, and the round trip is verified on hardware. The same work fixed a Data Limit Switch that had never functioned, because it was sending exactly the partial payload the router refuses.

What is left is two entities on the Data sub-device:

- a **Number** for the reset day (1–31), writing `traffic_clear_date`
- a **Switch** for `wan_auto_clear_flow_data_switch`, the master that decides whether monthly counters roll over at all

The key is already polled and the switch's state already drives the projection sensor's suppression logic; neither has a user-facing control. Both are thin wrappers over a write path that exists and is tested. Detail in `.notes/issues/data_cycle_and_projection_plan.md` §8.

**One decision to make first.** The reset day is the router's own billing configuration, and changing it moves the boundary the projection sensor and any data-cap automation reason about. It is not dangerous in the way a band lock is — nothing becomes unreachable — but it is not a display setting either. Both controls should ship **disabled by default**, matching the existing Data Limit Switch.

### 5. Projection accuracy from cycle history ⭐⭐

`Projected Cycle Usage` currently extrapolates from the cycle in flight alone, which is why it is volatile in the first few days. Storing the previous two or three cycle totals would let the estimate lean on them early and shed them as real usage accumulates — blended into the **unobserved remainder** only, so the prior's influence decays with the days left rather than needing a tuned constant. The groundwork is in place: `helpers.project_cycle_usage()` already takes a `prior_rate` argument. What is missing is the store. §2.4 of the same plan.

## Roadmap Summary

| Phase | Task | Effort | Value |
| :-- | :-- | :-- | :-- |
| **Short term** | Cross-model verification via user diagnostics | Low | ⭐⭐⭐⭐ |
| **Short term** | SMS feature-group toggle (§15) | Medium | ⭐⭐⭐ |
| **Short term** | Billing-cycle write controls — write path done, two entities outstanding | Low | ⭐⭐⭐ |
| **Medium term** | Projection accuracy from cycle history | Medium | ⭐⭐ |
| **Long term** | Band locking write side — **only** with a self-clearing lock | High | ⭐⭐⭐ |
| **Declined** | Token persistence | — | — |
| **Blocked** | Custom triggers (HA version floor) | Low | ⭐⭐ |

**Current status.** 92 entities across four sub-devices, 85 carrying `about` notes. 749 tests, 100% coverage, `ruff` and `mypy --strict` clean, hassfest passing. Conformant across the 21 `dev_standards` sections.

---

## Version Control

- **v2.4.0** (2026-07-29) — Corrected the reasoning behind the declined write controls. Every one of them had been justified with a single claim: that the integration reaches the router over the connection the change breaks, so the undo would be unreachable. **That holds only for `OPERATION_MODE`.** Home Assistant talks to the router at its LAN address, so a band lock, a cell lock or bad DNS kills the WAN and leaves the management path intact. The declines all stand, but on three distinct grounds — reachability, foot-gun value, and scope — now stated per command rather than blanket. Also recorded the case where reachability _does_ apply (a user reaching Home Assistant remotely over that same WAN) and, for each, that the router's own web page is the better place for a one-time tuning act.
- **v2.3.0** (2026-07-29) — Item 4 (billing-cycle write controls) rescoped after the router-facing agent answered the open questions. The blocker it described — a partial POST possibly clearing the user's data cap — turned out not to exist: the router **refuses** an incomplete form rather than blanking the omitted fields. The read-modify-write path is built and verified, which also fixed a Data Limit Switch that had never worked. Only the Number and Switch entities remain, so the effort drops from Medium to Low.
- **v2.2.0** (2026-07-29) — **Data-usage projection delivered** and moved to the delivered table. `Projected Cycle Usage` and `Reset Day` ship on the Data sub-device, cycle-relative rather than calendar-relative, after a live probe confirmed the router exposes `traffic_clear_date`. Two candidates added in its place, both carved out of the same work and both deliberately not shipped: the **billing-cycle write controls**, blocked on `DATA_LIMIT_SETTING` being a multi-field form that a partial POST could clear; and **projection accuracy from cycle history**, which needs a store the integration does not yet have. Also recorded that `OPERATION_MODE`, `LTE_LOCK_CELL_SET`, `ROUTER_DNS_SETTING` and `SET_BIND_STATIC_ADDRESS` were found by the same discovery run and declined under the objection this document already applies to band and cell locking — the control that undoes a bad change sits on the far side of the connection it breaks.
- **v2.1.0** (2026-07-29) — Removed the proposed _signal-quality history sensor_. Home Assistant's built-in **Statistics** helper already produces a rolling mean over any signal entity with no code, and there is no sound formula for a single combined quality score: which metric limits a connection depends on whether the site is interference-limited or noise-limited, so a weighted average would score one of those two cases wrong. SINR is the honest single number. Replaced by a **Reading Your Signal Data** section in `README.md` covering which metric answers which question, the threshold tables gathered in one place, establishing a personal baseline, and building the Statistics helper to compare antenna positions. Also removed the _config-entry migration handler_ row — it is a tripwire documented in `DEVELOPMENT.md`, not roadmap work, and there is no VERSION 3 planned. Removed the thermal-sensor row: that decision is closed.
- **v2.0.0** (2026-07-29) — Rewritten after review against the live instance. Three of the four original priorities are delivered (`send_sms`, CA metrics, write-action fast path); recorded that the fast path shipped as `async_force_refresh()` rather than the proposed `async_request_refresh()`, which would have been swallowed while polling was paused. Token persistence **declined** with reasoning rather than left open. Band and cell locking re-scoped around the observation that the control which undoes a bad lock is unreachable over the connection the lock breaks. Added five new candidates and folded in the open items from `DEVELOPMENT.md`. Corrected a stale claim of compliance with "PlayFaster v1.2 standards".
- **v1.0.0** (2026-05) — Original roadmap.
