"""Constants for the ZTE Router 5G Monitor integration."""

DOMAIN = "zte_router_5g"

# This is the default prefix used for the Integration Title and Entity IDs
# if the user doesn't provide a custom name during setup.
DEFAULT_NAME = "ZTE 5G"
CONF_NAME = "name"

# Legacy or internal naming if needed
NAME = "ZTE Router 5G Monitor"

# Storage keys
CONF_SCAN_INTERVAL = "scan_interval"
CONF_STOP_POLLING = "stop_polling"

# Options that may be applied without reloading the config entry.
#
# Reloading on an options change is the safe default (dev_standards Section 9):
# it guarantees the entity set and the options stay in sync. Only options that
# are read dynamically on every cycle — and that change neither the entity
# topology nor how we connect — may live-apply. Both of these qualify: the
# coordinator re-reads `stop_polling` at the top of each update, and the scan
# interval is applied straight onto `update_interval`.
#
# Anything NOT listed here reloads. That deliberately includes host, username
# and password: live-applying a connection change would leave the running API
# client pointed at the old device with the old credentials.
LIVE_OPTION_KEYS = frozenset({CONF_SCAN_INTERVAL, CONF_STOP_POLLING})

# Idle gap after which the client discards `stok` and re-logs in before sending,
# rather than waiting to be told the session is dead.
#
# Measured, not guessed: on an MC7010 (firmware V1.0.0B03, 2026-07-27) a session
# idle for 200s was already dead — the router answered 200 OK with every value
# blank. 150s therefore sits safely below the real boundary, and below the 180s
# default scan interval.
#
# Do not remove this in favour of relying on the reactive expiry detection in
# `_request`. Reacting costs *more*, not less: a failed request, then a login,
# then a retry — three round trips where preempting costs two. It is also the
# second line of defense on a router whose expired-session response is
# indistinguishable from success at the HTTP layer.
SESSION_IDLE_RESET_SECONDS = 150

# Proportion of the *requested* authenticated keys that may be missing from a
# response before the session classifier declines to rule on it.
#
# An expired session on this API echoes the requested keys back as empty
# strings; it does not drop them. Measured on MC7010 firmware
# `IRL_H3G_MC7010DV1.0.0B03` on 2026-08-30, where a cookieless read returned
# 80 of 80 core and 36 of 36 extended keys with none absent. Keys going
# *missing* is therefore a different fault — a truncated or refused request,
# or firmware key-name drift — and must not be read as a dead session.
#
# Not zero. An unknown `cmd` name is simply absent from the response rather
# than an error, so a device that omits the cross-model aliases instead of
# echoing them would trip a stricter rule on every healthy poll.
ABSENT_KEY_PROPORTION_LIMIT = 0.5

# A poll answering at or below this fraction of the most keys this entry has
# ever seen populated is reported on the health sensor. Relative rather than
# absolute: the reference MC7010 leaves 46 of 127 names legitimately empty,
# so a fixed floor would report it faulty every cycle, while the MC888 Pro in
# issue #56 polled successfully with 6 of 82 and nothing was said at all.
SPARSE_PAYLOAD_FRACTION = 0.25

# Below this the high-water mark is not yet a baseline worth judging against.
SPARSE_PAYLOAD_MIN_HISTORY = 20

# Consecutive failures tolerated before entities are marked unavailable
# (dev_standards Section 8 — the "3-strike" rule). Applied both globally and,
# independently, to each optional endpoint. Named to match
# `unifi_network_monitor`, which uses the same constant for the same purpose.
FETCH_STRIKE_LIMIT = 3

# Consecutive polls a contract-drift finding must persist before it counts.
# Split from FETCH_STRIKE_LIMIT so the two budgets can move independently: one
# counts a router that did not answer, the other a router that answered with
# nothing the integration recognises. They are the same number today, and the
# point of the split is that changing one no longer silently changes the other.
# Matches `huawei_router_5g`, `wifi_ssid_monitor` and `unifi_network_monitor`.
HEALTH_DRIFT_STRIKE_LIMIT = 3

# Consecutive failures before a Repair is raised for a router that is simply not
# answering. Deliberately far above FETCH_STRIKE_LIMIT: three strikes is a few
# minutes and would fire on every router reboot. Ten consecutive failures means
# the condition has stopped resolving itself, which is what makes it worth a
# Repair rather than just an unavailable entity (Section 19, second tier).
UNREACHABLE_STRIKE_LIMIT = 10

# The canonical repair keys, named to match `huawei_router_5g`. The Repairs
# panel carries only conditions that require the user to act and will not clear
# themselves; everything else — contract drift, degraded capabilities — belongs
# on the Integration Health sensor, and message-store capacity on a binary
# sensor.
REPAIR_AUTH_FAILED = "auth_failed"
REPAIR_CONN_ERROR = "conn_error"

# Number of APN profile slots requested and offered in the APN Profile select.
#
# The firmware exposes 20 (`APN_config0`..`APN_config19`) and an MC7010 in normal
# use populates two. Twenty slots cost 250 characters of the batch poll's
# ~2048-character URL budget — a fifth of the whole request — to carry eighteen
# empty strings.
#
# Ten is the compromise: still far more profiles than a CPE is configured with in
# practice, at half the cost. Raising it costs URL budget; see
# `test_batch_poll_url_stays_within_the_router_budget`.
APN_PROFILE_SLOTS = 10

# Targeted write confirmation (switch platform).
#
# A control's position is read back from the router straight after the write,
# rather than waiting for the coordinator's debounced poll — which can be up to
# ten seconds away and made the UI appear to toggle, revert, then correct
# itself. Measured on an MC7010: the write returns in ~112 ms and the read-back
# in ~16 ms (~38 ms worst case with a full poll in flight), so the confirmed
# round trip stays well inside the ~150 ms that reads as instant.
#
# No delay before the *first* read: the router applies these settings before it
# answers the write, so waiting would spend responsiveness on nothing. The
# delay exists only for a second attempt, so a slower model — or a future
# firmware that applies asynchronously — is not reported as a failed write on
# the strength of one early read.
WRITE_VERIFY_RETRY_DELAY = 0.2

# Kept well under the API's default 15 s. A confirmation that hangs must not
# hold the UI; past this the write is treated as *unverified* and left for the
# next poll, which is a different outcome from a write that was refused.
WRITE_VERIFY_TIMEOUT = 3

# Data-usage projection tuning.
#
# PROJECTION_CREDIBILITY_DAYS is the point at which this cycle's own usage rate
# and the previous cycle's are weighted equally. Three days is deliberate:
# usage is bursty, and a heavy weekend is not a new baseline, but waiting a
# fortnight would leave the projection lagging exactly when a user most wants
# warning that they are on course to exceed their allowance.
#
# It matters less than it looks. The blend applies only to the *unobserved*
# remainder of the cycle (see `helpers.project_cycle_usage`), so the prior's
# influence decays with the days left rather than with this constant.
PROJECTION_CREDIBILITY_DAYS = 3.0

# Confidence bands published as an attribute on the projection, expressed as
# thresholds on the credibility weight. The projection is always shown — an
# `unknown` on day one reads as a broken sensor, whereas a number carrying
# "confidence: low" is understood. The caveat belongs in the attributes, not in
# the state.
PROJECTION_CONFIDENCE_LOW = 0.4
PROJECTION_CONFIDENCE_MEDIUM = 0.75

# SMS length ceilings, by the encoding the message forces.
#
# A single SMS carries 160 GSM 03.38 septets, or 70 UCS-2 characters. Longer
# messages are split into concatenated segments, and each segment gives up
# space to a header: 153 septets or 67 characters. The MC7010 web UI advertises
# 765 for plain text, which is exactly 5 x 153 — so the router accepts at most
# five segments, and the Unicode equivalent is 5 x 67.
#
# Enforced in `async_send_sms` rather than the service schema, because which
# limit applies depends on the message content. Behavior past five segments is
# untested on hardware; these ceilings keep callers out of that zone.

SMS_SEGMENTS_MAX = 5
SMS_MAX_CHARS_GSM7 = 765
SMS_MAX_CHARS_UNICODE = 335

# Candidate `cmd` names harvested from `Kajkac/ZTE-MC-Home-assistant-repo`,
# which covers the MC801A, MC888 and MC889, minus everything this integration
# already requests and everything outside its scope (Wi-Fi, guest networks,
# DHCP, DNS, IPv6, battery, firmware upgrade state).
#
# Probed once per setup so a diagnostics download can show which of them a
# device populates. **Never joins the poll**: `docs/zte_how_to_access.md`
# records a probe carrying names outside the firmware's dictionary making a
# whole chunk time out and fall back to empty defaults, taking a genuinely
# populated key down with it. Chunked and individually tolerant for the same
# reason.
#
# Every name here is classified in `diagnostics.py` — see
# `DISCOVERY_VALUE_SAFE`. An unclassified candidate is not eligible for this
# list, because its value would be published.
# Names per discovery request. Small deliberately: a chunk carrying a name
# outside the firmware's dictionary can time out entirely, and a smaller chunk
# loses less when it does.
# Characters a single batch request may reach before it is split. The router
# bounds a GET by URL length rather than by name count, and the ceiling
# measured on an MC7010 is roughly 2,048 — but that is one device's, and a
# firmware with a lower one truncates the response rather than erroring, which
# presents as missing fields. The margin is deliberate.
#
# The list grows with every model supported, not with every feature added: a
# device that spells a concept differently needs both spellings requested.
BATCH_URL_BUDGET = 1600

DISCOVERY_CHUNK_SIZE = 16

# Mined names are unvalidated by definition, so their chunks are smaller: a
# chunk that times out returns empty defaults for every name in it, and a
# genuinely populated key inside is scored absent with no trace.
MINED_CHUNK_SIZE = 8

# Per-chunk timeout. A healthy 75-key batch answers in about 30 ms, so eight
# seconds is generous for a chunk that will succeed and short for one that
# will not.
DISCOVERY_CHUNK_TIMEOUT = 8

# Wall-clock ceiling for the whole discovery pass. A timed-out chunk clears
# the session, so the next pays a full login; without a ceiling a hostile
# firmware could make a diagnostics download take minutes.
DISCOVERY_BUDGET_SECONDS = 90

# Bundles the router serves for its own admin UI, which is a client of this
# same API. `docs/zte_how_to_access.md` names these as the sources the
# 2026-07-29 mining pass crawled to recover 175 `cmd` names.
JS_BUNDLES: tuple[str, ...] = (
    "js/service.js",
    "js/statusBar.js",
    "js/home.js",
    "js/main.js",
    "js/app.js",
)

DISCOVERY_CANDIDATES: list[str] = [
    "5g_rx0_rsrp",
    "5g_rx1_rsrp",
    "Lte_ca_status",
    "Z5g_dlEarfcn",
    "ZCELLINFO_band",
    "bandwidth",
    "cr_version",
    "dial_mode",
    "ecio",
    "ecio_1",
    "ecio_2",
    "ecio_3",
    "ecio_4",
    "flux_monthly_time",
    "lte_band",
    "lte_ca_pcell_arfcn",
    "lte_ca_pcell_freq",
    "lte_ca_scell_arfcn",
    "lte_ca_scell_info",
    "lte_earfcn_lock",
    "lte_multi_ca_scell_sig_info",
    "lte_pci_lock",
    "lte_rsrp_1",
    "lte_rsrp_2",
    "lte_rsrp_3",
    "lte_rsrp_4",
    "lte_snr_1",
    "lte_snr_2",
    "lte_snr_3",
    "lte_snr_4",
    "modem_main_state",
    "monthly_time",
    "network_information",
    "network_provider_fullname",
    "ngbr_cell_info",
    "nr5g_action_nsa_band",
    "nr5g_cell_id",
    "nr5g_nsa_band_lock",
    "nr5g_sa_band_lock",
    "nr_ca_pcell_band",
    "nr_ca_pcell_freq",
    "nr_multi_ca_scell_info",
    "pdp_type",
    "pdp_type_ui",
    "pin_status",
    "ppp_dial_conn_fail_counter",
    "pppoe_status",
    "roam_setting_option",
    "rscp_1",
    "rscp_2",
    "rscp_3",
    "rscp_4",
    "simcard_roam",
    "sms_received_flag",
    "spn_b1_flag",
    "spn_b2_flag",
    "spn_name_data",
    "static_wan_ipaddr",
    "static_wan_status",
    "sts_received_flag",
    "tx_power",
    "wa_version",
]

# Discovery candidates whose values may be published in the diagnostics
# download. Everything else is reported as shape and length only.
#
# `diagnostics._sanitize_payload` classifies by exact key name, and `_sweep`
# catches only address- and identifier-shaped strings — so a name it does not
# know falls through with its value intact. These are the names judged to
# carry radio telemetry, counters or enumerations rather than identity,
# location or third-party content. The excluded ones are: static WAN address,
# NR cell id, carrier long name, service-provider name data, two firmware
# version strings, and the two free-text blobs `network_information` and
# `ngbr_cell_info`, which carry neighbouring-cell detail.
DISCOVERY_VALUE_SAFE: frozenset[str] = frozenset(
    {
        "5g_rx0_rsrp",
        "5g_rx1_rsrp",
        "Lte_ca_status",
        "Z5g_dlEarfcn",
        "ZCELLINFO_band",
        "bandwidth",
        "dial_mode",
        "ecio",
        "ecio_1",
        "ecio_2",
        "ecio_3",
        "ecio_4",
        "flux_monthly_time",
        "lte_band",
        "lte_ca_pcell_arfcn",
        "lte_ca_pcell_freq",
        "lte_ca_scell_arfcn",
        "lte_ca_scell_info",
        "lte_earfcn_lock",
        "lte_multi_ca_scell_sig_info",
        "lte_pci_lock",
        "lte_rsrp_1",
        "lte_rsrp_2",
        "lte_rsrp_3",
        "lte_rsrp_4",
        "lte_snr_1",
        "lte_snr_2",
        "lte_snr_3",
        "lte_snr_4",
        "modem_main_state",
        "monthly_time",
        "nr5g_action_nsa_band",
        "nr5g_nsa_band_lock",
        "nr5g_sa_band_lock",
        "nr_ca_pcell_band",
        "nr_ca_pcell_freq",
        "nr_multi_ca_scell_info",
        "pdp_type",
        "pdp_type_ui",
        "pin_status",
        "ppp_dial_conn_fail_counter",
        "pppoe_status",
        "roam_setting_option",
        "rscp_1",
        "rscp_2",
        "rscp_3",
        "rscp_4",
        "simcard_roam",
        "sms_received_flag",
        "spn_b1_flag",
        "spn_b2_flag",
        "static_wan_status",
        "sts_received_flag",
        "tx_power",
    }
)
