# ZTE Router Access Reference 🔗

This document details how this integration navigates the ZTE `goform` interface to fetch data and issue commands — the endpoints, the authentication chain, the commands used (and deliberately not used), and the behaviors of this API that are not obvious from the traffic.

Everything below is drawn from `custom_components/zte_router_5g/api.py` and verified against live hardware. Where a claim was confirmed against a specific model or firmware, that is stated.

---

## 📐 The shape of this API — read this first

The UniFi companion document (`ha-unifi-network-monitor/docs/api_endpoints.md`) is organized by URL, because that API has a URL per resource. **ZTE does not.** The entire interface is two endpoints:

| Endpoint                        | Method                           | Role                                                        |
| :------------------------------ | :------------------------------- | :---------------------------------------------------------- |
| `goform/goform_get_cmd_process` | GET (and POST for paged queries) | **Reads.** The resource is named in a `cmd=` parameter.     |
| `goform/goform_set_cmd_process` | POST                             | **Writes.** The action is named in a `goformId=` parameter. |

So the unit that corresponds to "an endpoint" elsewhere is **a `cmd` name or a `goformId` name**, and this document is organized that way. Two practical consequences:

- **You cannot tell from a URL what a request does.** All read traffic looks identical in a proxy log until you read the query string. When debugging, capture the full query string, not the path.
- **Reads are batched, not enumerated.** One `cmd=` accepts a comma-separated list of names alongside `multi_data=1`, and the router answers with a single flat JSON object. There is no per-resource read to isolate — see [Read commands](#-read-commands-goform_get_cmd_process). **The limit is the URL, not the name count** — see [the batch ceiling](#the-batch-ceiling-is-a-url-length-budget).

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

| Signature           | What it looks like                                                                                                                                     | Where        |
| :------------------ | :----------------------------------------------------------------------------------------------------------------------------------------------------- | :----------- |
| **HTML redirect**   | Response URL contains `index.html`, or `Content-Type: text/html` with a body starting `<`                                                              | `api.py:152` |
| **Unparsable JSON** | Body is not JSON at all                                                                                                                                | `api.py:202` |
| **Hollow JSON**     | Valid JSON, HTTP 200, in which **every value is an empty string** — or `result` is one of `session expired` / `unauth` / `fail`, or `status` is `fail` | `api.py:219` |

The third is the dangerous one: a successful-looking 200 with a well-formed body whose fields are blank. Any client that checks only the status code will silently record a router full of empty values. This is precisely the "silent failure" class that `dev_standards.md` §19 Integration Health exists to catch.

**The rule is "every value", not "these named keys".** It previously named `network_type` and `signalbar` — which exist only in the batch-poll response — so it could never fire on an SMS or capacity response, and those endpoints silently returned "no data" on a dead session. Full signature table under [Gotchas](#️-gotchas). Never narrow it back.

On any of the three, the client re-logs in and retries **once** (`_retry=False` on the retry, so a genuinely rejected credential surfaces as `ZTEAuthError` rather than looping).

#### The fourth signature — and why it is not in the table

**A write on a dead session answers `{"result":"failure"}`.** That is not a fourth _detectable_ signature; it is the absence of one. It matches nothing above — not all-values-empty, and not the `is_auth_error` strings, where the list has `fail` and the router says `failure`.

It cannot simply be added to that list, because **`{"result":"failure"}` is also exactly what a genuinely declined command returns** — a partial `DATA_LIMIT_SETTING` form, for instance. Treating it as an expiry signal would resend commands the router meant to reject; for `SEND_SMS` that means delivering the message twice.

Consequence, verified on hardware 2026-07-30: reads recover from a stolen session and **writes did not**. Signing into the router's web page ended Home Assistant's session, and every write then failed until some read happened to trip the all-empty rule and re-login. The user-visible form was a switch that failed on every attempt until **Refresh Now** was pressed.

The fix is ordering, not detection. `_ensure_session()` performs one short authenticated read **before** the write derives its `AD`, so `_request`'s existing read-side recovery does the work. It is called from `get_ad()`, the single choke point every write passes through.

Recovering _after_ a refused write was implemented first and **verified not to work** — the session was renewed, the payload replayed, and the router refused it again. The reason is not established. A plausible explanation (that `RD` rotates on re-login, staling the `AD`) was **disproved** by `scripts/hardware_check.py`, which observed `RD` surviving a re-login. Do not reinstate post-hoc retry on the strength of a fresh theory; run the script.

### Proactive session reset

Independently of the above, if more than **150 seconds** (`SESSION_IDLE_RESET_SECONDS`) have passed since the last successful request, the client discards `stok` and re-logs in before sending. **Measured:** a session idle for **200 seconds** was already dead on MC7010 firmware `V1.0.0B03` (2026-07-27) — the router answered `200 OK` with every value blank. So the real boundary is at or below 200s, and 150s sits safely under it and under the 180s default scan interval.

Preempting is also _cheaper_ than reacting, which is the opposite of the intuition: reacting costs a failed request, then a login, then a retry — three round trips, where preempting costs a login and a request. Do not remove this in favour of the reactive detection above.

---

## 🔑 The `AD` token — required for every write

Read commands need only the `stok` cookie. **Every write additionally needs an `AD` parameter**, computed per request (`get_ad`, `api.py:693`).

> **`get_ad()` assures the session before deriving the token.** It is the one function every write passes through, which is why the check lives there rather than in each setter — see [The fourth signature](#the-fourth-signature--and-why-it-is-not-in-the-table). Anything that bypasses `get_ad()` also bypasses the only dead-session protection the write path has.

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

**Client-side enforcement**: `api.py:_require_success()` is called on the result of every write command and raises `ZTEConnectionError` on an explicit non-success `result`. Before it existed, a refused write was reported to the user as a successful action — a user watched an SMS action succeed with no message sent. It raises only on an explicit non-success value; a response carrying no `result` key is left alone, because not every `goformId` returns one.

**`RD` is a static per-device seed, so `AD` is _not_ single-use.** Measured on MC7010 firmware `V1.0.0B03` (2026-07-29): `cmd=RD` returned the identical value across logins and across a deliberately invalidated session. Since `AD = H(H(version + cr_version) + RD)` and both inputs are fixed for a given device, **the token is constant per router** — which is why `_request` can replay a write payload verbatim after a re-login without the embedded `AD` going stale. An earlier revision of this document claimed the opposite ("fetched fresh for every write, so `AD` is single-use"); that was an assumption, and the measurement contradicts it. Do not build a retry or caching decision on the single-use reading.

---

## 📥 Read commands (`goform_get_cmd_process`)

### The batch poll — `multi_data=1`

- **Used**: Yes — this is the main polling call, once per scan interval.
- **Request**: `GET goform/goform_get_cmd_process?multi_data=1&isTest=false&sms_received_flag_flag=0&cmd=<100 comma-separated names>`
- **Response**: one flat JSON object. **The router does not error on an unknown `cmd` name**, which means a firmware update that drops a field is invisible unless the parse layer checks for it.
- **Implementation**: `get_all_data`, `api.py:426`.

#### A requested name comes back in one of three states

This is not a binary, and treating it as one has caused defects here before:

| State                 | Response                     | Meaning                                                                               |
| :-------------------- | :--------------------------- | :------------------------------------------------------------------------------------ |
| **Populated**         | `"key": "value"`             | Supported and in use.                                                                 |
| **Present but empty** | `"key": ""`                  | The firmware **knows the name** but this model or configuration does not populate it. |
| **Absent**            | key not in the object at all | The name is not in the firmware's dictionary.                                         |

The middle state is the one that surprises. On the MC7010, `data_volume_clear_date`, `data_volume_clear_day`, all five `pm_*` thermal keys and `night_mode_switch` all answer `""` — the names are real, the hardware simply has nothing to report. By contrast `SET_DATA_VOLUME_LIMIT`, `clear_data_day`, `clean_date`, `reset_date` and `cycle_start_date` are genuinely absent: invented names that no firmware knows.

**Any consumer must therefore treat present-but-empty as absent**, which is what `_get_first()` and `_safe_int()` / `_safe_float()` / `_safe_str()` do. `in data` alone is not a support test.

It also interacts with expiry detection: the dead-session signature is _every_ value being an empty string, so knowing which keys are structurally empty on healthy hardware is what keeps that rule sound. A hypothetical batch of only-unpopulated keys would be indistinguishable from a dead session — in practice the poll always includes keys that populate.

#### The batch ceiling is a URL-length budget

Not a name count. The router accepts a GET up to roughly **2,048 characters**; a 183-name batch succeeded when the URL stayed under that, and truncation is what happens past it.

**This is why the poll is split in two.** A single list had reached 127 names and 1,889 characters — within ~160 of the ceiling, where the next addition would have truncated the response. Rather than keep trading one key away for another, the request became two:

| Request             | Names |    URL | Headroom | Failure mode                                         |
| :------------------ | ----: | -----: | -------: | :--------------------------------------------------- |
| `get_all_data`      |    75 | ~1,167 |     ~880 | Mandatory — a whole-integration failure              |
| `get_extended_data` |    41 |   ~735 |   ~1,310 | Optional — three strikes, then its own entities only |

The split is **by criticality, not alphabetically**, and that is the part worth preserving. The core request carries everything feeding an enabled-by-default entity, the contract keys, and the device identity latched into `entry.data`. The extended request carries diagnostics, disabled-by-default entities, router settings and the thermal keys — so a failure there degrades diagnostics while Signal and Data keep serving real values.

Cross-model aliases stay in the **core** request even though the MC7010 answers `""` for all of them: they feed enabled-by-default sensors on other `goform` models, and a Signal sensor on an MC888 must not depend on an endpoint that is allowed to degrade.

This changes the standing advice in two ways.

**It is no longer free.** Past the budget the response truncates, which presents as missing fields and looks exactly like firmware contract drift. Budget before adding, and put a new key in whichever batch matches how badly it is needed — `test_batch_poll_urls_stay_within_the_router_budget` covers both halves and fails well before the hard ceiling.

**It is not unconditionally safe either.** The rule that an unknown `cmd` is simply absent holds for names **in the firmware's dictionary**, and the integration's current 127 all are — verified 2026-07-29, where every requested name came back, 46 of them empty and **none absent**. A name that is _not_ in the dictionary is a different matter: a discovery probe mixing fictional candidates into a batch saw **the whole chunk time out and fall back to empty defaults**, taking a genuinely populated key down with it. So a speculative spelling copied from another project should be probed on its own before it joins the poll, not dropped straight into the batch.

The names, grouped by what they feed:

<details>
<summary><b>Signal and radio</b> (LTE / 5G NR measurements)</summary>

`lte_rsrp`, `lte_rsrq`, `lte_rssi`, `lte_snr`, `lte_pci`, `rssi`, `rscp`, `signalbar`, `Z5g_rsrp`, `Z5g_rsrq`, `Z5g_rssi`, `Z5g_SINR`

**Cross-model aliases**: `5g_rsrp`, `nr5g_rsrp`, `5g_sinr`, `nr5g_sinr`, `Z5g_snr`, `Z5g_CELL_ID`

These are alternative spellings other members of the `goform` family use for the same measurements. The MC7010 does not populate them; they are requested so the integration works on an MC888 or MC889 without a code change, and resolved by `_get_first()` in `sensor.py`, which takes the first spelling that arrives non-empty. Each one costs URL budget, so the set is deliberately small.

</details>

<details>
<summary><b>Carrier aggregation and bands</b></summary>

`lte_ca_pcell_band`, `lte_ca_pcell_bandwidth`, `lte_ca_scell_band`, `lte_ca_scell_bandwidth`, `wan_lte_ca`, `wan_active_band`, `wan_active_channel`, `nr5g_action_band`, `nr5g_action_channel`, `nr5g_pci`, `lte_band_lock`, `lte_multi_ca_scell_info`

`lte_multi_ca_scell_info` is a raw descriptor string, one semicolon-terminated group per secondary cell — see [Field formats](#-field-formats).

</details>

<details>
<summary><b>Cell and network identity</b></summary>

`cell_id`, `enodeb_id`, `network_type`, `network_provider`, `mdm_mcc`, `mdm_mnc`, `rmcc`, `rmnc`, `net_select`, `net_select_mode`

`mdm_mcc`/`mdm_mnc` are the modem's view; `rmcc`/`rmnc` are the registered network's. They differ while roaming.

</details>

<details>
<summary><b>Connection and addressing</b></summary>

`wan_connect_status`, `wan_ipaddr`, `lan_ipaddr`, `ppp_status`, `wan_apn`, `opms_wan_mode`, `opms_wan_auto_mode`

`opms_wan_mode` is the active operational mode — `LTE_BRIDGE` or `AUTO_LTE_GATEWAY`. `opms_wan_auto_mode` is the mode the router falls back to on its own; the two differing is normal. Both are read-only here by deliberate choice — see [Not used](#-not-used).

</details>

<details>
<summary><b>Throughput and data volume</b></summary>

`realtime_tx_thrpt`, `realtime_rx_thrpt`, `realtime_tx_bytes`, `realtime_rx_bytes`, `realtime_time`, `monthly_tx_bytes`, `monthly_rx_bytes`, `data_volume_limit_switch`, `data_volume_alert_percent`

**Cross-model aliases**: `flux_monthly_tx_bytes`, `flux_monthly_rx_bytes`

**Billing cycle**: `traffic_clear_date`, `wan_auto_clear_flow_data_switch`, and the aliases `data_volume_clear_date`, `data_volume_clear_day`

`realtime_time` is the router's uptime counter, and is the input to reboot detection — see [Gotchas](#️-gotchas).

`traffic_clear_date` (1–31) is the day of the month the router zeroes its monthly counters — **the billing cycle need not start on the 1st**, so anything reasoning about a month must read it rather than assume. Confirmed on hardware 2026-07-29 as the spelling that carries the value; the two `data_volume_*` spellings answer `""` on the MC7010 and are retained only as cross-model aliases.

`wan_auto_clear_flow_data_switch` (`on`/`off`) is the **master** for the automatic monthly reset. With it off the counters never roll over and there is no cycle at all, which is why the projection sensor suppresses itself rather than projecting against a number that only ever climbs.

</details>

<details>
<summary><b>Device identity and hardware</b></summary>

`model_name`, `wa_inner_version`, `hardware_version`, `imei`, `sim_imsi`, `sim_iccid`, `battery_value`

**Thermal**: `pm_sensor_pa1`, `pm_sensor_ambient`, `pm_sensor_mdm`, `pm_modem_5g`, `pm_sensor_5g`

The five thermal keys are the set a sibling `goform` project polls with °C units. **The MC7010 answers `""` for every one** — present-but-empty, so the names are real but this hardware reports nothing. All five ship disabled by default for that reason, and no model is yet confirmed to populate any of them.

**`battery_value` is different, and instructive.** It answers **`100`** on this mains-powered unit — along with `battery_vol_percent` `100`, `battery_pers` `4` and `battery_charging` `0`. The firmware hardcodes `100` as a dummy sentinel on CPE models with no physical battery (MC7010, MC801A, MC888). So the value is not merely uninformative, it is **actively misleading**: it looks like a healthy full battery and is a constant. That is why the sensor ships disabled by default with an `about` note saying so.

It is also a caution about batch probing. An earlier probe reported `battery_value` as empty; it had been grouped into a chunk alongside fictional candidate names, and **that chunk timed out and fell back to empty defaults**. Queried individually it returns `100`. An empty result from a batch containing unknown names is not evidence that the key is unpopulated — re-probe it alone before concluding anything.

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

`ODU_led_switch`, `ODU_led_off_time`, `upnpEnabled`, `alg_sip_enable`

**Reboot schedule**: `reboot_schedule_enable`, `reboot_schedule_mode`, `reboot_dow`, `reboot_dod`, `reboot_hour1`, `reboot_min1`, `reboot_hour2`, `reboot_min2`

**Time**: `sntp_server0`, `sntp_server1`, `sntp_server2`, `sntp_dst_enable`, `sntp_timezone`

**Web UI power**: `web_sleep_switch`, `web_wake_switch`

Encodings for the reboot-schedule and timezone fields are under [Field formats](#-field-formats).

</details>

**Why one batch rather than targeted reads.** Each request costs a round trip on hardware that is slow and single-session. Splitting this into per-topic reads would multiply the polling cost with no benefit, and would widen the window in which a user's web-UI login can collide with a poll.

### The extended batch — `get_extended_data`

- **Used**: Yes — optional endpoint, polled with its own strike budget on every cycle.
- **Request**: identical in shape to the core batch, with `_EXTENDED_PARAMS` in the `cmd=` list.
- **Merged** under the core payload, so entities read one flat dictionary and do not know which request a value arrived in. Core wins any key collision — a stale cached diagnostic must never mask a fresh core value.
- **Implementation**: `get_extended_data`, sharing `_batch_get` with the mandatory fetch.

Entities fed from here carry `source=ENDPOINT_EXTENDED` on their description and gate `available` on it, so once the endpoint exhausts its three strikes they go unavailable rather than showing a value frozen at whatever it was hours ago.

### Available but not polled

The 2026-07-29 discovery run probed 183 candidate names. These answered with a value and are **not** in either batch — recorded so the next person asking "what else does this router expose?" can start here rather than re-running the probe. Adding any of them costs URL budget (see above).

| Key                                                       | Live value      | What it is                                                                                                |
| :-------------------------------------------------------- | :-------------- | :-------------------------------------------------------------------------------------------------------- |
| `monthly_time`                                            | —               | Connected time this billing month, alongside the byte counters. Zeroed by `RESET_DATA_COUNTER` with them. |
| `odu_mode`                                                | —               | Outdoor-unit operating mode.                                                                              |
| `RadioOff`                                                | —               | Radio disable flag.                                                                                       |
| `dns_mode`                                                | —               | Automatic or manual DNS. Paired with the `ROUTER_DNS_SETTING` write, which is declined.                   |
| `pppoe_status`, `pppoe_dial_mode`, `dhcp_wan_status`      | —               | WAN establishment detail beyond `wan_connect_status`.                                                     |
| `pdp_type_ui`, `ipv6_pdp_type`                            | —               | PDP context types; `pdp_type` is already polled for the APN select.                                       |
| `rplmn_num`                                               | —               | Registered PLMN, numeric. Overlaps `rmcc`/`rmnc`, which are polled.                                       |
| `nitz_sync_flag`, `sntp_time_set_mode`                    | —               | How the router last set its clock — network time versus SNTP.                                             |
| `modem_msn`, `hardwarenumber`, `web_version`              | —               | Further hardware and web-UI identifiers.                                                                  |
| `sntp_server_list1` … `sntp_server_list7`                 | —               | The router's menu of selectable time servers, distinct from the three configured ones.                    |
| `battery_pers`, `battery_charging`, `battery_vol_percent` | `4`, `0`, `100` | Battery detail. See the note on `battery_value` above — `100` is a sentinel on hardware with no battery.  |

**Present but empty on the MC7010**, so real names with nothing behind them here:

| Key                                     | Note                                                                                               |
| :-------------------------------------- | :------------------------------------------------------------------------------------------------- |
| `gps_lat`, `gps_lon`                    | The firmware has GPS fields. This unit reports nothing in them; a model with a GPS receiver might. |
| `pm_sensor_pa2`, `pm_mdm`, `modem_5g`   | Three more thermal spellings beyond the five already polled.                                       |
| `night_mode_switch`                     | State for the `SET_DEVICE_LED` night-mode scheduler.                                               |
| `DIAG_CHECK`, `DIAG_URL`, `LocalDomain` | Vendor diagnostic and LAN-domain fields.                                                           |

Full probe results, and the router-facing agent's answers on encodings and write semantics, are in `.notes/info/zte_element_discovery_report.md`.

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

| `goformId`                   | Purpose                                        | Extra parameters                                                                                                                                                     | Implementation             |
| :--------------------------- | :--------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------- |
| `LOGIN` / `LOGIN_MULTI_USER` | Authenticate                                   | `password`, optional `username`                                                                                                                                      | `api.py:287`               |
| `LOGOUT`                     | End the session                                | — (but **`AD` is required**)                                                                                                                                         | `api.py:391`               |
| `REBOOT_DEVICE`              | Reboot the router                              | —                                                                                                                                                                    | `api.py:584`               |
| `SEND_SMS`                   | Send a message                                 | `Number`, `MessageBody` (UTF-16BE hex), `encode_type` (`GSM7_default` or `UNICODE`), `ID=-1`, `sms_time`, `notCallback=true`                                         | `api.py:send_sms`          |
| `DELETE_SMS`                 | Delete one or more messages                    | `msg_id` — semicolon-separated for a batch                                                                                                                           | `api.py:596`               |
| `APN_PROC_EX`                | Set default APN profile, or switch auto/manual | `apn_mode`, `apn_action`, `set_default_flag`, `pdp_type`, `index`                                                                                                    | `api.py:721`, `api.py:737` |
| `ODU_LED_SWITCH_SET`         | Outdoor-unit LED on/off                        | `ODU_led_switch` (`1`/`0`)                                                                                                                                           | `api.py:749`               |
| `DATA_LIMIT_SETTING`         | **The entire data-volume form** — see below    | `data_volume_limit_switch`, `data_volume_limit_unit`, `data_volume_limit_size`, `data_volume_alert_percent`, `wan_auto_clear_flow_data_switch`, `traffic_clear_date` | `api.py:763`               |
| `SET_BEARER_PREFERENCE`      | Network mode                                   | `BearerPreference` (`4G_AND_5G`, `Only_5G`, `Only_LTE`)                                                                                                              | `api.py:778`               |

**`sms_time` format**: `yy;mm;dd;HH;MM;SS;+0` — semicolon-delimited, unlike the comma-delimited format the router _returns_ on received messages. The two are not interchangeable.

### `DATA_LIMIT_SETTING` is all-or-nothing

This command is **not** a data-limit toggle despite its use here. It writes the complete data-volume configuration, and **the router refuses a partial payload**:

| Field                             | Values                                          |
| :-------------------------------- | :---------------------------------------------- |
| `data_volume_limit_switch`        | `1` / `0`                                       |
| `data_volume_limit_unit`          | `data` (byte cap) or `time` (hours/minutes cap) |
| `data_volume_limit_size`          | cap size, e.g. `2_1048576` for 2 GB             |
| `data_volume_alert_percent`       | e.g. `80`                                       |
| `wan_auto_clear_flow_data_switch` | `on` / `off`                                    |
| `traffic_clear_date`              | `1` … `31`                                      |

**Verified on hardware 2026-07-29** (MC7010 `V1.0.0B03`): a POST carrying only `data_volume_limit_switch=1` returned `{"result":"failure"}`. The omitted fields were re-read afterwards and were **100% intact** — the router rejects the write rather than blanking what is missing.

That is the better of the two possible failure modes, and worth being precise about: the earlier concern was that a partial form would silently clear the user's data cap. It does not. It refuses.

Two consequences:

- **Any write to this form must send all six fields**, sourced from the last successful poll — a read-modify-write, with the field being changed substituted in.
- `traffic_clear_date` and `wan_auto_clear_flow_data_switch` have **no separate `goformId`**. They are written through this form or not at all. `SET_DATA_VOLUME_LIMIT`, proposed by an earlier internal analysis, does not exist in the firmware.

**Delete-all is currently a client-side loop** (`delete_all`, `api.py:608`): query the message list, collect the IDs, and issue one `DELETE_SMS` with them joined by `;`.

A native **`ALL_DELETE_SMS`** does exist — it takes `which_cgi` and clears router (`nv`) storage in bulk. An earlier revision of this document asserted that no bulk-delete command existed; that was wrong. The loop is kept because it is proven and because it is explicit about which messages it removes, but the native command is the simpler path if this is ever revisited.

---

## 🗂️ The full `goformId` inventory

Twenty-six write actions were recovered from the router's own `js/service.js` bundle. Nine are used. The rest are listed so the same discovery is not repeated, and so a decision not to use one is visible rather than implied by absence.

| `goformId`                       | Status       | Note                                                                                                                                                                                                              |
| :------------------------------- | :----------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `LOGIN`                          | **Used**     | Also `LOGIN_MULTI_USER`, which the mining did not surface separately.                                                                                                                                             |
| `SEND_SMS`                       | **Used**     |                                                                                                                                                                                                                   |
| `DELETE_SMS`                     | **Used**     |                                                                                                                                                                                                                   |
| `APN_PROC_EX`                    | **Used**     | `APN_PROC` also exists — presumably the older form.                                                                                                                                                               |
| `DATA_LIMIT_SETTING`             | **Used**     | See above; the current single-field call is wrong.                                                                                                                                                                |
| `SET_DEVICE_LED`                 | Not used     | **Not** the LED toggle. It configures _night mode_: `night_mode_switch`, `night_mode_start_time`, `night_mode_end_time`, `night_mode_close_all_led`. A scheduled LED shutoff, distinct from `ODU_LED_SWITCH_SET`. |
| `ALL_DELETE_SMS`                 | Not used     | Bulk SMS delete, `which_cgi`. See above.                                                                                                                                                                          |
| `SAVE_SMS`                       | Not used     | Save a draft. No use case here.                                                                                                                                                                                   |
| `SET_MSG_READ`                   | Not used     | Marks a message read. **The most interesting unused command** — the integration exposes an unread count it cannot currently clear.                                                                                |
| `SAVE_TSW`                       | Not used     | Writes `web_sleep_switch`, `web_wake_switch`, `web_wake_time`, `web_sleep_time`. This is the write path for the two web-power sensors, which currently ship read-only.                                            |
| `FLOW_CALIBRATION_MANUAL`        | **Declined** | Calibrates the monthly counter baseline against an ISP billing figure. Adjusting a usage counter to match an external number is a manual reconciliation, not an automation.                                       |
| `RESET_DATA_COUNTER`             | **Declined** | Zeroes `monthly_rx_bytes`, `monthly_tx_bytes` and `monthly_time`. Session counters unaffected. **No undo.** One accidental press destroys the month's record and the projection sensor's input.                   |
| `OPERATION_MODE`                 | **Declined** | Bridge ↔ gateway.                                                                                                                                                                                                |
| `LTE_LOCK_CELL_SET`              | **Declined** | Lock to a PCI / cell ID.                                                                                                                                                                                          |
| `ROUTER_DNS_SETTING`             | **Declined** | Custom LAN/WAN DNS.                                                                                                                                                                                               |
| `SET_BIND_STATIC_ADDRESS`        | **Declined** | DHCP static reservations.                                                                                                                                                                                         |
| `DHCP_RESERVATION_TO_STATIC`     | **Declined** | As above.                                                                                                                                                                                                         |
| `SET_NETWORK` / `UNLOCK_NETWORK` | **Declined** | Network selection and unlock.                                                                                                                                                                                     |
| `SET_WIFI_BAND`                  | Not used     | Out of scope — this integration monitors the CPE, not its WLAN.                                                                                                                                                   |
| `QUICK_SETUP` / `QUICK_SETUP_EX` | Not used     | First-run wizard.                                                                                                                                                                                                 |
| `SET_NV`                         | Not used     | Raw NV-item write. Unbounded and undocumented; nothing good comes of calling it blind.                                                                                                                            |
| `SET_UPGRADE_NOTICE`             | Not used     | Firmware-update prompt suppression.                                                                                                                                                                               |
| `REDIRECT_REDIRECT_OFF`          | Not used     | Web UI redirect behaviour.                                                                                                                                                                                        |

### Why the declined rows are declined

An earlier revision of this document gave all of them one reason — that each changes the path Home Assistant reaches the router over, so the control that undoes a mistake becomes unreachable. **That is true of one command, not five.** Home Assistant talks to the router at its **LAN address**, and locking to a dead cell or setting bad DNS breaks the _WAN_, not the management path. The undo stays available.

The reasons are actually three:

| Command                                                 | Objection                                                                                                                                                                                                             |
| :------------------------------------------------------ | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `OPERATION_MODE`                                        | **Reachability.** Bridge ↔ gateway changes the router's LAN role and addressing, so it genuinely can move or remove the management path. On a headless outdoor unit, recovery may mean physical access.              |
| `LTE_LOCK_CELL_SET`                                     | **Foot-gun, poor value.** Cells change with load and maintenance, so a lock that works today fails next week — and the failure is no service at all. The diagnostic value already exists in `lte_pci` and `nr5g_pci`. |
| `ROUTER_DNS_SETTING`                                    | **Scope and blast radius.** This integration monitors the CPE. DNS breaks name resolution for every device on the LAN, which is far wider than the thing being managed.                                               |
| `SET_BIND_STATIC_ADDRESS`, `DHCP_RESERVATION_TO_STATIC` | **Scope, plus collision risk.** A bad reservation can change Home Assistant's own address. LAN address management belongs in the router's UI or a DHCP integration.                                                   |
| `SET_NETWORK`, `UNLOCK_NETWORK`                         | **Scope.** Operator selection and network unlock are one-time provisioning acts, not automation.                                                                                                                      |
| `RESET_DATA_COUNTER`                                    | **Irreversible.** Zeroes the monthly counters with no undo, and destroys the projection sensor's own input.                                                                                                           |

**Recoverable is not the same as harmless.** Three of these are reversible from the router's own web page in under a minute, and that is the point: where a setting is a one-time act with a wide blast radius, the router's UI is the better place for it. It shows the current configuration in context, warns before applying, and does not tempt anyone into automating a change that should be made once and deliberately. Exposing a control in Home Assistant implies it is safe to script; for these, it is not.

Where the read side is useful it is still exposed — `opms_wan_mode` ships read-only so the operating mode is visible without offering a switch that can strand the user.

---

## ❌ Not used

Documented for reference — these exist on the interface but are deliberately not called.

### Per-field reads (`cmd=<single_name>`) — for telemetry

- **Used**: **No** for telemetry (the three protocol commands and the two uses below are the exceptions).
- **Rationale**: every telemetry field this integration needs is already in the batch. A targeted read purely to fetch something already in hand would add a round trip to a single-session device.
- **Where a targeted read _is_ used**, both on the write path rather than for telemetry: `get_params()` confirming a control after a write, and `_ensure_session()` before one. Measured 2026-07-30 — a single-key read costs **16 ms median, 22 ms p90, 27 ms max**, against **30 ms median** for the full 75-key core batch, so the cost is the round trip, not the payload. Reading one key is barely cheaper than reading everything; the reason to do it is precision, not speed.

### Connected-device / station listing

- **Used**: **No**.
- **Rationale**: client tracking is out of scope for this integration, and the payload is large and noisy relative to its value. Home Assistant's own device-tracker integrations are the right home for it.

### Write commands for settings this integration does not expose

`sntp_*`, `upnpEnabled`, `alg_sip_enable`, `reboot_schedule_*`, `web_sleep_switch` / `web_wake_switch` and `lte_band_lock` are **read** in the batch poll but have no write path here.

- **Rationale**: these are configuration a user sets once in the router's own UI. Exposing writes for them would mean owning validation for settings that can render the router unreachable — band locking in particular. Reading them is useful; writing them is a support burden with no automation use case.
- For the two web-power switches this was originally because no write command was known. One now is (`SAVE_TSW`), so the position is a choice rather than a gap: a setting that governs the router's own web page has no bearing on Home Assistant, which logs in afresh regardless.

### Traffic statistics history

- **Used**: **No**.
- **Rationale**: the router exposes only current counters (`monthly_*`, `realtime_*`), not a queryable history. Long-term statistics are produced by Home Assistant's recorder from the counter sensors instead — see `dev_standards.md` §14.

---

## 🔤 Field formats

Values this API returns as opaque strings, and what is known about their encoding. Everything here is from the vendor's own JavaScript or from hardware, not inferred from a single sample unless stated.

### `traffic_clear_date`

Day of the month, `1`–`31`. **If the value exceeds the length of the current month the firmware clamps to the last calendar day** — a clear date of 31 fires on 30 April and on 28 or 29 February. It does not skip the month. Any client-side cycle arithmetic must clamp the same way or it will compute the wrong cycle boundary in short months.

### `reboot_schedule_mode`, `reboot_dow`, `reboot_dod`

| Field                  | Encoding                                                            |
| :--------------------- | :------------------------------------------------------------------ |
| `reboot_schedule_mode` | `1` = weekly, `2` = monthly                                         |
| `reboot_dow`           | Day of week, **1-indexed from Sunday** — `1` = Sunday, `2` = Monday |
| `reboot_dod`           | Day of month, `1`–`31`                                              |

Both day fields are populated regardless of mode, so the mode is what selects which one applies. Reading `reboot_dow` without checking `reboot_schedule_mode` will report a weekday for a router that reboots monthly.

### `sntp_timezone`

Format is `<utc_offset><dst_offset>`. The observed `0-1` is UTC+0 with a DST adjustment of −1.

**Treated with caution.** Only one sample exists, from a UTC+0 unit, and the sign convention is not obvious — a DST-active router would conventionally be _ahead_ of its base offset, not behind it. The integration exposes the raw string rather than a decoded offset, because publishing a wrong timezone is worse than publishing an opaque one. A second sample from a non-UTC router would settle it.

### `lte_multi_ca_scell_info`

Comma-separated fields, one semicolon-terminated group per secondary cell. Observed: `2,352,1,20,6300,10;`

| Position | Field            | Confidence                                                                        |
| :------- | :--------------- | :-------------------------------------------------------------------------------- |
| 1        | Cell index       | Inferred                                                                          |
| 2        | PCI              | Inferred; 352 is a valid PCI                                                      |
| 3        | **Unidentified** | Observed to change between polls (`1` ↔ `2`) while every other field held steady |
| 4        | LTE band         | **Confirmed**                                                                     |
| 5        | EARFCN           | **Confirmed**                                                                     |
| 6        | Bandwidth, MHz   | **Confirmed**                                                                     |

**Positions 4 and 5 are the other way round from the discovery report**, which listed `[earfcn],[band_number]` and so read the sample as EARFCN 20 on band 6300. EARFCN 6300 sits inside band 20's allocation (6150–6449) and `20` is not a valid EARFCN, so the report's ordering is wrong. Corroborated twice on live hardware: band 20's bit is set in `lte_band_lock`, and field 6 (`10`) matches `lte_ca_pcell_bandwidth` of `10.0`.

**Position 3 is deliberately unnamed.** The report called it `dl_bandwidth_code`, which the data contradicts — a bandwidth code of `2` means 5 MHz, disagreeing with field 6, and a bandwidth would not change between polls while the band and channel do not. It is more likely an SCell activation state or a MIMO layer count, but that is a guess and the integration publishes the string raw.

### `lte_band_lock`

Hexadecimal bitmask of the 4G bands the modem may use. **Bit N represents band N+1** — bit 0 is band 1, bit 2 is band 3, bit 19 is band 20.

**Verified on hardware 2026-07-30.** `0x60088080045` decodes to bands **1, 3, 7, 20, 28, 32, 42, 43** — the standard European CPE set. Two independent cross-checks on the same poll: `wan_active_band` reported `LTE BAND 28` and bit 27 is set; the carrier-aggregation secondary cell reported band 20 and bit 19 is set.

### `data_volume_limit_size`

Cap size as `<value>_<multiplier>`, where the multiplier is **the number of mebibytes in the chosen unit**. `2_1048576` is **2 TiB**, because 1 TiB is 1,048,576 MiB.

**Corrected 2026-07-29.** The discovery report annotated this same value as "2 GB". The router's own Data Management page shows **2TB** for it, with the 80% reminder at **1.6TB** — direct observation of the device beats the annotation, so the multiplier is MiB-based rather than KiB-based.

Note the router counts in **binary** units throughout that page: its "1.01TB used" against a Monthly Total of 1,107.75 GB decimal is the same quantity (1,107.75 GB ÷ 1024⁴ ≈ 1.01 TiB), not a disagreement. A cap that reads "2TB" on the router therefore reads about **2199 GB** in Home Assistant, which converts to decimal.

Paired with `data_volume_limit_unit`, which is `data` for a byte cap or `time` for an hours/minutes cap. When it is `time`, the size field is a duration and means nothing as an allowance.

### SMS date fields

`date` on a received message is `yy,mm,dd,HH,MM,SS` — **comma**-delimited. `sms_time` on an outgoing message is `yy;mm;dd;HH;MM;SS;+0` — **semicolon**-delimited, with a trailing offset field. The two are not interchangeable.

---

## 🔬 Discovering new fields

Both times this interface has been extended, the same two-step method found things that guesswork did not. Recorded so it can be repeated rather than reinvented.

**Step 1 — mine the web UI's JavaScript.** The router serves its own admin UI, and that UI is a client of this same API. Crawl and parse the bundles — `js/service.js` is the main one, alongside `statusBar.js`, `home.js` and the RequireJS modules — and extract every `cmd=` name and every `goformId` literal. This is the **only** reliable source for write commands: a `goformId` cannot be discovered by probing, because an unknown one fails the same way a refused one does. It is also the only source for a command's full **field set**, which is what the `DATA_LIMIT_SETTING` case turned on.

A 2026-07-29 pass produced 175 GET commands, 26 `goformId` write actions and 63 parameter keys.

**Step 2 — batch-probe the candidates against live hardware.** Take the mined names plus any spellings from sibling projects, and request them in batches within the URL budget. Sort the results three ways — populated, present-but-empty, absent — because that distinction is the actual finding. Present-but-empty means the name is real and this model does not populate it; absent means the name is fiction.

The same pass probed 183 candidates and found 66 populated.

**Two cautions.**

- **Mined ≠ verified.** Step 1 tells you a name exists in a bundle. It does not tell you the firmware on the unit in front of you accepts it, and bundles are shared across models. Every write recovered this way needs a live round-trip before it is trusted — the mining reported `SET_DEVICE_LED` as the LED toggle, and it is in fact an unrelated night-mode scheduler.
- **A refused write and an unknown write look identical**: `200 OK`, `{"result":"failure"}`. Distinguishing them means reading the JavaScript, not probing harder.

---

## ⚠️ Gotchas

Behaviors of this interface that have cost real debugging time.

### `encode_type` and message length

`encode_type` selects the **encoding the router declares on the wire** — it does _not_ change the format of `MessageBody`, which this API always takes as **UTF-16BE hex regardless**. Verified against two independent implementations (`Kajkac/pygsm7.py::encodeMessage()`, `rosenrot00/zte_api.py::_encode_sms_message()`), both of which hex-encode UTF-16 code units for either type. **Do not "fix" a `GSM7_default` send by packing 7-bit septets client-side.**

What it does change is how the router counts segments:

| `encode_type`  | Single SMS    | Per concatenated segment | Router maximum (5 segments) |
| :------------- | :------------ | :----------------------- | :-------------------------- |
| `GSM7_default` | 160 septets   | 153                      | **765**                     |
| `UNICODE`      | 70 characters | 67                       | **335**                     |

Concatenated segments give up 7 bytes each to a header, which is why the per-segment figure is lower than the single-message one. The MC7010 web UI advertises `(765) (1/5)` for plain text — exactly 5 x 153, confirming the five-segment ceiling.

Pick the type from the message content: if every character is in the GSM 03.38 alphabet, `GSM7_default`; otherwise `UNICODE`. **One out-of-alphabet character changes the encoding for the entire message**, so a single emoji cuts the ceiling from 765 to 335. Behaviour past five segments is untested — `async_send_sms` rejects it rather than finding out.

Confirmed on hardware (2026-07-29): a 159-character plain message and an 80-character message with three emoji both arrived as **one** message on the handset, so the router segments and the phone reassembles. Nothing is truncated.

**Everything fails soft.** An unknown `cmd`, a missing `AD`, an expired session — none of these produce an HTTP error. You get `200 OK` with an empty field, a `{"result":"failure"}`, or a body of blank strings. **Never treat a 200 as success on this API.** Check the body shape every time.

The client enforces this in three layers, each covering a shape the others miss:

| Guard                               | Catches                                                                                  | Where                                             |
| :---------------------------------- | :--------------------------------------------------------------------------------------- | :------------------------------------------------ |
| Expiry detection in `_request`      | A body whose values are **all** empty strings — the dead-session shape                   | `api.py:_request`                                 |
| `_require_contract(data, key, cmd)` | A populated body missing the key the caller needs — firmware drift, or a partial session | reads (`get_sms_messages`, `get_sms_capacity`, …) |
| `_require_success(data, cmd)`       | An explicit `{"result":"failure"}` on an otherwise healthy session                       | all eight write commands                          |

They are deliberately separate: the first raises before the others are reached, so a single guard cannot stand in for the rest. `tests/test_dead_session_sweep.py` drives every public API method against all three fault shapes and asserts that each either succeeds or raises — never returns a success-shaped result having done nothing.

**The dead-session signature, precisely.** An expired session does not redirect and does not error. It answers **HTTP 200** with the **requested keys echoed back empty** — verified on MC7010 firmware `V1.0.0B03` (2026-07-27) by replaying an invalidated `stok`:

| Request                         | Live session       | Dead session                            |
| :------------------------------ | :----------------- | :-------------------------------------- |
| `cmd=sms_data_total`            | `{"messages":[…]}` | `{"sms_data_total":""}`                 |
| `cmd=sms_data_total`, empty box | `{"messages":[]}`  | `{"sms_data_total":""}`                 |
| batch poll                      | real values        | `{"network_type":"","signalbar":"", …}` |
| `cmd=sms_capacity_info`         | real values        | `{"sms_capacity_info":""}`              |
| `cmd=wa_inner_version`          | real value         | **real value** — unauthenticated        |

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
- `.notes/info/zte_element_discovery_report.md` — the 2026-07-29 discovery run this document's inventory and field formats are drawn from, including the raw probe results and the router-facing agent's answers.
- `.shared/dev_std/dev_standards.md` §8 (per-endpoint strike budgets), §10 (session cleanup on unload), §19 (Integration Health), §20 (diagnostics sanitization).
