# Diagnostic tools

Tools used to investigate faults that the integration cannot characterise from inside Home Assistant. They are not part of the integration, are never loaded by it, and nothing here runs unless a person deliberately runs it.

## `zte_write_capture_bookmarklet.txt`

A browser bookmarklet that records the request a ZTE router's own web interface sends when a person changes something through it, and offers that record as a JSON file to download.

Written for [issue #56](https://github.com/PlayFaster/ha-zte-router-5g-monitor/issues/56), where a ZTE MC888 Pro accepts every write, answers `{"result":"success"}`, and carries none of them out. Six versions of the temporary in-integration probe established what the router refuses without establishing why. The one artefact none of them could obtain is the request the router's own web page sends when the same operation succeeds, because that request is made by a browser this project has no access to.

### What it records

| Kept | Why |
| :-- | :-- |
| Requests to `goform_set_cmd_process` | The single URL the web interface uses to change anything |
| Their request body, status, response body and response headers | The form the router accepts, in full |
| Recent reads of version and token fields | The `RD` value a write's token is derived from, so the derivation can be checked |
| `rd0` and `rd1` as the page holds them | The token's operands, which are assigned at runtime and appear in no served file as literals |
| Whether `hex_md5` and `hex_sha256` are defined | Which digest the firmware actually implements |
| Firmware flags from the loader's `config/config` module | `ACCESSIBLE_ID_SUPPORT`, `PASSWORD_ENCODE_SHA256`, `MAX_LOGIN_COUNT` and similar |

### What it refuses to record

- **Login.** Any request whose body contains `goformId=LOGIN` is discarded before anything is stored, so a password cannot reach the file.
- **User data.** A read is kept only when every value it asks for is on a fixed allow-list of version and token fields. A read that would return messages, numbers, addresses or usage is ignored outright rather than filtered.
- **Cookies.** Not read and not stored.

Only firmware switches matching a fixed name pattern are taken from the configuration module; no setting belonging to the person running it is.

### What it cannot record

`Cookie`, `Referer`, `Origin` and `User-Agent` are attached by the browser after page script has run, so no tool of this kind can see them. `Origin` is the most consequential of those for issue #56: firmware that required it on writes would refuse Home Assistant every time while the two requests looked identical in every field that can be compared. Seeing those headers requires a HAR export or an intercepting proxy.

### Use

1. Log in to the router's web interface first.
2. Add a bookmark whose **URL** is the entire contents of the `.txt` file. It must go in a bookmark's URL field; browsers strip a `javascript:` prefix pasted into the address bar.
3. Open the router's web interface and click the bookmark. A panel appears at the top right showing a count and a download button.
4. Carry out the operation of interest — for issue #56, deleting one SMS.
5. Click **Download**. The file is written to the local downloads folder and can be read in any text editor before it is shared.

Running it a second time is refused rather than allowed to wrap the request machinery twice. The file it produces is a few kilobytes.

### Provenance

Built from a commented source file and collapsed to one line, with the body wrapped in `void` so the bookmarklet evaluates to `undefined` — a `javascript:` URL that evaluates to a value replaces the page with that value.

Rehearsed against the reference ZTE MC7010 on 2026-09-11, which confirmed that it records a write with its full response, pairs the preceding `RD` read with it, reports the page globals and firmware flags, excludes a read of SMS counters, and discards a request carrying a marker password.

That rehearsal produced the first arithmetic confirmation of this project's write token: from the capture's own values, `md5(md5(rd0 + rd1) + RD)` reproduces the `AD` the browser sent on a delete the router honoured. `[3.3.20-dev5]` in `docs/changelog_local.md` records the findings in full.
