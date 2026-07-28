# ZTE Router Access Reference 🔗

This document details how this integration navigates the ZTE `goform` interface to fetch data and issue commands — the endpoints, the authentication chain, the commands used (and deliberately not used), and the behaviors of this API that are not obvious from the traffic.

Everything below is drawn from `custom_components/zte_router_5g/api.py` and verified against live hardware. Where a claim was confirmed against a specific model or firmware, that is stated.

---

## 📐 The shape of this API — read this first

The UniFi companion document (`ha-unifi-network-monitor/docs/api_endpoints.md`) is organized by URL, because that API has a URL per resource. **ZTE does not.** The entire interface is two endpoints:

| Endpoint | Method | Role |
| :-- | :-- | :-- |
| `goform/goform_get_cmd_process` | GET (and POST for paged queries) | **Reads.** The resource is named in a `cmd=` parameter. |
| `goform/goform_set_cmd_process` | POST | **Writes.** The action is named in a `goformId=` parameter. |

So the unit that corresponds to "an endpoint" elsewhere is **a `cmd` name or a `goformId` name**, and this document is organized that way. Two practical consequences:

- **You cannot tell from a URL what a request does.** All read traffic looks identical in a proxy log until you read the query string. When debugging, capture the full query string, not the path.
- **Reads are batched, not enumerated.** One `cmd=` accepts a comma-separated list of up to ~100 names alongside `multi_data=1`, and the router answers with a single flat JSON object. There is no per-resource read to isolate — see [Read commands](#-read-commands-goform_get_cmd_process).

Base URL is `{protocol}://{ip}/`, where protocol is probed at setup (`try_set_protocol`, `api.py:249`): `http` is tried first, then `https`, taking the first that answers with status < 400. TLS verification is disabled throughout (`ssl=False`) because these CPEs ship self-signed certificates.

Every request carries `Referer: {base}index.html`. The router rejects requests without it.

---

## 🔧 Authentication

### The login chain

Login is a challenge-response over SHA-256, not a credential POST. Four steps, in order (`api.py:287`):

1. **`GET goform_get_cmd_process?cmd=LD`** → returns `LD`, a per-session salt. Upper-cased on receipt.
2. **`GET goform_get_cmd_process?cmd=wa_inner_version`** → the firmware version string. Fetched here because it determines _which login form to use_ (below), not for telemetry.
3. **Hash twice.** `SHA256(password)` → uppercase → concatenate `LD` → `SHA256` again → uppercase. Both uppercase steps are required; the router rejects lowercase digests.
4. **`POST goform_set_cmd_process`** with `goformId=LOGIN` or `LOGIN_MULTI_USER`, `password=<the double hash>`, and `username=` when a username is configured.

The session token arrives as a **`stok` cookie**, which is then sent as a literal `Cookie: stok=<value>` header on every subsequent request. The value is stripped of surrounding double quotes before use (`api.py:354`) — some firmware quotes it, and passing the quoted form back produces a silent session failure rather than an error.

### `LOGIN` vs `LOGIN_MULTI_USER` — a model split

`LOGIN` (single-user form) is used only when **both** are true: a username is configured, **and** the firmware version contains `MC801` or `MC7010`. Everything else uses `LOGIN_MULTI_USER`. The flag is held as `is_multi` (`api.py:301`).

This is the first of two places where model detection changes the protocol. It is string-matching on the firmware version, which is fragile by nature — a model outside the known set that expects the single-user form will fail login with no distinguishing error.

### The post-login initialization GET

Immediately after a successful login the client issues a throwaway `GET goform_get_cmd_process?cmd=wa_inner_version` carrying the new cookie (`api.py:358`). This is not telemetry — **some ZTE firmware rejects the first POST of a session unless a GET has preceded it.** Its failure is caught and logged at debug only; the session is usable either way on firmware that does not need it.

### One session at a time

**A ZTE CPE permits exactly one login session.** This is the single most important operational fact about this interface:

- Logging into the router's web UI **terminates** the integration's session.
- Conversely, an abandoned integration session **locks the user out of the web UI** until it times out.

This is why `logout()` (`api.py:391`) runs on unload and why it is best-effort — an unreachable router must never block Home Assistant from tearing down the entry, but leaving the session open has a real user-visible cost. See `dev_standards.md` §10.

It is also why you cannot verify a logout by checking whether the web UI is reachable: the web UI can **always** be logged into, and doing so terminates whatever session existed. The only sound verification is to replay the old `stok` against an authenticated `cmd` and confirm it is rejected.

### Session expiry — three different signatures

The router does not return `401`. Expiry is detected by pattern, and all three are handled in `_request` (`api.py:96`):

| Signature | What it looks like | Where |
| :-- | :-- | :-- |
| **HTML redirect** | Response URL contains `index.html`, or `Content-Type: text/html` with a body starting `<` | `api.py:152` |
| **Unparsable JSON** | Body is not JSON at all | `api.py:202` |
| **Hollow JSON** | Valid JSON, HTTP 200, in which **every value is an empty string** — or `result` is one of `session expired` / `unauth` / `fail`, or `status` is `fail` | `api.py:219` |

The third is the dangerous one: a successful-looking 200 with a well-formed body whose fields are blank. Any client that checks only the status code will silently record a router full of empty values. This is precisely the "silent failure" class that `dev_standards.md` §19 Integration Health exists to catch.

**The rule is "every value", not "these named keys".** It previously named `network_type` and `signalbar` — which exist only in the batch-poll response — so it could never fire on an SMS or capacity response, and those endpoints silently returned "no data" on a dead session. Full signature table under [Gotchas](#-gotchas). Never narrow it back.

On any of the three, the client re-logs in and retries **once** (`_retry=False` on the retry, so a genuinely rejected credential surfaces as `ZTEAuthError` rather than looping).

### Proactive session reset

Independently of the above, if more than **150 seconds** (`SESSION_IDLE_RESET_SECONDS`) have passed since the last successful request, the client discards `stok` and re-logs in before sending. **Measured:** a session idle for **200 seconds** was already dead on MC7010 firmware `V1.0.0B03` (2026-07-27) — the router answered `200 OK` with every value blank. So the real boundary is at or below 200s, and 150s sits safely under it and under the 180s default scan interval.

Preempting is also _cheaper_ than reacting, which is the opposite of the intuition: reacting costs a failed request, then a login, then a retry — three round trips, where preempting costs a login and a request. Do not remove this in favour of the reactive detection above.

---

## 🔑 The `AD` token — required for every write

Read commands need only the `stok` cookie. **Every write additionally needs an `AD` parameter**, computed per request (`get_ad`, `api.py:693`):

```text
AD = H( H(firmware_version) + RD )
```

where `RD` comes from `GET goform_get_cmd_process?cmd=RD` and `H` is:

| Model family                         | `H`     | Case              |
| :----------------------------------- | :------ | :---------------- |
| Firmware contains `MC888` or `MC889` | SHA-256 | **uppercase** hex |
| Everything else                      | MD5     | lowercase hex     |

This is the second model-dependent branch in the protocol. MD5 here is a vendor protocol requirement, not a security choice (`# noqa: S324`).

**A write sent without `AD`, or with a stale one, does not error.** The router answers `{"result":"failure"}` with HTTP 200 and does nothing. This was confirmed on MC7010 firmware `V1.0.0B03` (2026-07-27) using `LOGOUT`: without `AD` the call returned failure and the `stok` remained live; with `AD` it returned success and the `stok` was genuinely invalidated. Assume the same of any `goformId` — a silent no-op is the default failure mode of this API.

`RD` is fetched fresh for every write, so `AD` is single-use in practice.

---

## 📥 Read commands (`goform_get_cmd_process`)

### The batch poll — `multi_data=1`

- **Used**: Yes — this is the main polling call, once per scan interval.
- **Request**: `GET goform/goform_get_cmd_process?multi_data=1&isTest=false&sms_received_flag_flag=0&cmd=<100 comma-separated names>`
- **Response**: one flat JSON object, one key per requested name. Missing or unsupported names are simply absent — **the router does not error on an unknown `cmd` name**, which means a firmware update that drops a field is invisible unless the parse layer checks for it.
- **Implementation**: `get_all_data`, `api.py:426`.

The 100 names, grouped by what they feed:

<details>
<summary><b>Signal and radio</b> (LTE / 5G NR measurements)</summary>

`lte_rsrp`, `lte_rsrq`, `lte_rssi`, `lte_snr`, `lte_pci`, `rssi`, `rscp`, `signalbar`, `Z5g_rsrp`, `Z5g_rsrq`, `Z5g_rssi`, `Z5g_SINR`

</details>

<details>
<summary><b>Carrier aggregation and bands</b></summary>

`lte_ca_pcell_band`, `lte_ca_pcell_bandwidth`, `lte_ca_scell_band`, `lte_ca_scell_bandwidth`, `wan_lte_ca`, `wan_active_band`, `wan_active_channel`, `nr5g_action_band`, `nr5g_action_channel`, `nr5g_pci`, `lte_band_lock`

</details>

<details>
<summary><b>Cell and network identity</b></summary>

`cell_id`, `enodeb_id`, `network_type`, `network_provider`, `mdm_mcc`, `mdm_mnc`, `rmcc`, `rmnc`, `net_select`, `net_select_mode`

`mdm_mcc`/`mdm_mnc` are the modem's view; `rmcc`/`rmnc` are the registered network's. They differ while roaming.

</details>

<details>
<summary><b>Connection and addressing</b></summary>

`wan_connect_status`, `wan_ipaddr`, `lan_ipaddr`, `ppp_status`, `wan_apn`

</details>

<details>
<summary><b>Throughput and data volume</b></summary>

`realtime_tx_thrpt`, `realtime_rx_thrpt`, `realtime_tx_bytes`, `realtime_rx_bytes`, `realtime_time`, `monthly_tx_bytes`, `monthly_rx_bytes`, `data_volume_limit_switch`, `data_volume_alert_percent`

`realtime_time` is the router's uptime counter, and is the input to reboot detection — see [Gotchas](#️-gotchas).

</details>

<details>
<summary><b>Device identity and hardware</b></summary>

`model_name`, `wa_inner_version`, `hardware_version`, `imei`, `sim_imsi`, `sim_iccid`, `battery_value`

`imei`, `sim_imsi` and `sim_iccid` are subscriber identifiers and are sanitized out of diagnostics — see `dev_standards.md` §20.

</details>

<details>
<summary><b>SMS counters</b> (counts only — message bodies come from a separate command)</summary>

`sms_unread_num`, `sms_received_flag`, `sms_nv_rev_total`, `sms_nv_send_total`, `sms_nv_draftbox_total`, `sms_nv_total`, `sms_sim_rev_total`, `sms_sim_send_total`, `sms_sim_draftbox_total`, `sms_sim_total`

`nv` = router internal storage, `sim` = SIM card storage. They are separate banks with separate capacities.

</details>

<details>
<summary><b>APN configuration</b></summary>

`apn_index`, `apn_mode`, `apn_interface_version`, `ipv6_apn_index`, and `APN_config0` … `APN_config19`

Each `APN_config<n>` is a **single delimited string** holding a whole profile, not an object. Twenty slots are always requested; unused slots come back empty. Because these carry the subscriber's carrier configuration, diagnostics summarizes rather than reproduces them.

</details>

<details>
<summary><b>Device settings</b> (the writable ones)</summary>

`ODU_led_switch`, `ODU_led_off_time`, `reboot_schedule_enable`, `reboot_hour1`, `reboot_min1`, `reboot_hour2`, `reboot_min2`, `sntp_server0`, `sntp_server1`, `sntp_dst_enable`, `upnpEnabled`, `alg_sip_enable`

</details>

**Why one batch rather than targeted reads.** Each request costs a round trip on hardware that is slow and single-session. Splitting this into per-topic reads would multiply the polling cost with no benefit, and would widen the window in which a user's web-UI login can collide with a poll.

### `cmd=sms_capacity_info`

- **Used**: Yes — optional endpoint, polled with its own strike budget.
- **Request**: `GET ...?isTest=false&cmd=sms_capacity_info`
- **Purpose**: storage capacity and used counts for both banks.
- **Implementation**: `get_sms_capacity`, `api.py:538`. Returns `{}` on non-auth, non-connection failure; auth and connection errors propagate so the resilience layer can count a strike.

### `cmd=sms_data_total` — message bodies

- **Used**: Yes — optional endpoint, own strike budget.
- **Request**: **POST** (not GET) to `goform_get_cmd_process` with form fields `cmd=sms_data_total`, `page=0`, `data_per_page=500`, `mem_store=<1|0>`, `tags=10`, `order_by=order by id desc`.
- **Note the shape**: `order_by` takes a **literal SQL fragment**. This is the vendor's interface, passed through as-is; it is not constructed from user input anywhere in this integration and must not be.
- **`mem_store`**: `1` = router storage, `0` = SIM storage. `tags=10` selects received messages.
- **Implementation**: `get_sms_messages`, `api.py:663`. `get_last_sms_content` (`api.py:552`) is the same call with `data_per_page=1`.

**Fields arrive hex-encoded.** `content` and `number` are UTF-16BE hex strings; `date` is a comma-separated `yy,mm,dd,HH,MM,SS` list. The client decodes each into a parallel `*_decoded` key (`content_decoded`, `number_decoded`, `date_decoded`) and leaves the raw value in place. A decode failure yields the literal `[Decoding Error]` rather than raising — a malformed message must not take down the poll.

### `cmd=LD`, `cmd=RD`, `cmd=wa_inner_version`

Used, but as protocol machinery rather than telemetry — see [Authentication](#-authentication) and [The `AD` token](#-the-ad-token--required-for-every-write). `LD` and `wa_inner_version` are fetched **unauthenticated** (`authenticated=False`), which is what makes the login chain possible; `RD` requires a session.

`wa_inner_version` appears twice by design: once unauthenticated during login, and again inside the batch poll as a normal sensor value.

---

## 📤 Write commands (`goform_set_cmd_process`)

All are `POST`, all carry `Content-Type: application/x-www-form-urlencoded`, all require `AD`, and all are sent as a **pre-built form string** rather than a dict — the parameter order matters to some firmware.

| `goformId` | Purpose | Extra parameters | Implementation |
| :-- | :-- | :-- | :-- |
| `LOGIN` / `LOGIN_MULTI_USER` | Authenticate | `password`, optional `username` | `api.py:287` |
| `LOGOUT` | End the session | — (but **`AD` is required**) | `api.py:391` |
| `REBOOT_DEVICE` | Reboot the router | — | `api.py:584` |
| `SEND_SMS` | Send a message | `Number`, `MessageBody` (UTF-16BE hex), `encode_type=UNICODE`, `ID=-1`, `sms_time`, `notCallback=true` | `api.py:635` |
| `DELETE_SMS` | Delete one or more messages | `msg_id` — semicolon-separated for a batch | `api.py:596` |
| `APN_PROC_EX` | Set default APN profile, or switch auto/manual | `apn_mode`, `apn_action`, `set_default_flag`, `pdp_type`, `index` | `api.py:721`, `api.py:737` |
| `ODU_LED_SWITCH_SET` | Outdoor-unit LED on/off | `ODU_led_switch` (`1`/`0`) | `api.py:749` |
| `DATA_LIMIT_SETTING` | Data-volume limit on/off | `data_volume_limit_switch` (`1`/`0`) | `api.py:763` |
| `SET_BEARER_PREFERENCE` | Network mode | `BearerPreference` (`4G_AND_5G`, `Only_5G`, `Only_LTE`) | `api.py:778` |

**`sms_time` format**: `yy;mm;dd;HH;MM;SS;+0` — semicolon-delimited, unlike the comma-delimited format the router _returns_ on received messages. The two are not interchangeable.

**Delete-all is a client-side loop**, not a router command (`delete_all`, `api.py:608`): query the message list, collect the IDs, and issue one `DELETE_SMS` with them joined by `;`. There is no bulk-delete `goformId`.

---

## ❌ Not used

Documented for reference — these exist on the interface but are deliberately not called.

### Per-field reads (`cmd=<single_name>`)

- **Used**: **No** (except for the three protocol commands above).
- **Rationale**: every telemetry field this integration needs is already in the batch. A targeted read would add a round trip to a single-session device to fetch something already in hand.

### Connected-device / station listing

- **Used**: **No**.
- **Rationale**: client tracking is out of scope for this integration, and the payload is large and noisy relative to its value. Home Assistant's own device-tracker integrations are the right home for it.

### Write commands for settings this integration does not expose

`sntp_*`, `upnpEnabled`, `alg_sip_enable`, `reboot_schedule_*` and `lte_band_lock` are **read** in the batch poll but have no corresponding write path here.

- **Rationale**: these are configuration a user sets once in the router's own UI. Exposing writes for them would mean owning validation for settings that can render the router unreachable — band locking in particular. Reading them is useful; writing them is a support burden with no automation use case.

### Traffic statistics history

- **Used**: **No**.
- **Rationale**: the router exposes only current counters (`monthly_*`, `realtime_*`), not a queryable history. Long-term statistics are produced by Home Assistant's recorder from the counter sensors instead — see `dev_standards.md` §14.

---

## ⚠️ Gotchas

Behaviors of this interface that have cost real debugging time.

**Everything fails soft.** An unknown `cmd`, a missing `AD`, an expired session — none of these produce an HTTP error. You get `200 OK` with an empty field, a `{"result":"failure"}`, or a body of blank strings. **Never treat a 200 as success on this API.** Check the body shape every time.

**The dead-session signature, precisely.** An expired session does not redirect and does not error. It answers **HTTP 200** with the **requested keys echoed back empty** — verified on MC7010 firmware `V1.0.0B03` (2026-07-27) by replaying an invalidated `stok`:

| Request | Live session | Dead session |
| :-- | :-- | :-- |
| `cmd=sms_data_total` | `{"messages":[…]}` | `{"sms_data_total":""}` |
| `cmd=sms_data_total`, empty box | `{"messages":[]}` | `{"sms_data_total":""}` |
| batch poll | real values | `{"network_type":"","signalbar":"", …}` |
| `cmd=sms_capacity_info` | real values | `{"sms_capacity_info":""}` |
| `cmd=wa_inner_version` | real value | **real value** — unauthenticated |

So the test is **"every value is an empty string"**, not "these named keys are empty". Detecting on named keys works for the batch poll and silently fails everywhere else: an SMS response has no `network_type`, so a check for `network_type == ""` can never fire, and the caller sees an empty inbox rather than an error. That was a real defect, fixed 2026-07-27.

Note that an **empty inbox** returns `{"messages":[]}` — the contract key is present. That is what makes "no messages" distinguishable from "no session", and any check here must preserve the distinction.

**`auth status` reporting healthy while every command fails** is the signature of a stale session, not a credential problem. Re-login once; if it persists across a retry, it is a genuine problem and should be surfaced rather than retried further. See `agent_conventions.md`.

**The web UI always wins.** Any manual login to the router's web interface terminates the integration's session. During diagnosis this means the act of checking the router changes the thing you are checking.

**`realtime_time` goes down, not up, on reboot.** It is an uptime counter, so reboot detection watches for a _drop_ beyond `UPTIME_REBOOT_MARGIN`, and the derived boot timestamp is latched so it only moves on a genuine reboot. Comparing successive values naively produces spurious reboots on every poll jitter.

**Hex fields are UTF-16BE, four hex digits per character**, and the decoder walks the string in 4-character steps. An odd-length or truncated field yields `[Decoding Error]` rather than a partial string — deliberately, so a corrupt SMS cannot produce plausible-looking wrong text.

**Model detection is string-matching on firmware version**, in two places with two different model sets: `MC801`/`MC7010` selects the single-user login form, and `MC888`/`MC889` selects SHA-256 over MD5 for `AD`. A new model outside both sets gets the multi-user login and MD5 — which may be right or may fail silently. If a new model misbehaves, check these two branches first.

---

## 📚 Related documents

- `ha-unifi-network-monitor/docs/api_endpoints.md` — the companion for UniFi, organized by URL because that API has one per resource.
- `docs/DEVELOPMENT.md` — setup, devcontainer, and the resilience/health architecture that sits above this client.
- `docs/all_sensors.md` — which entity each field above ends up as.
- `.shared/dev_std/dev_standards.md` §8 (per-endpoint strike budgets), §10 (session cleanup on unload), §19 (Integration Health), §20 (diagnostics sanitization).
