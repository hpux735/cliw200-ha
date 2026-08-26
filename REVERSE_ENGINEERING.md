# Savant SEM-2015 — LLM-driven reverse engineering transcript

> **Disclosure:** this integration was produced by an **LLM-driven reverse
> engineering effort**. The device protocol was reconstructed by an AI coding
> agent (opencode / `deepseek-v4-pro`) from a series of user prompts, using
> only read-only, passive techniques (port scanning, mDNS queries, HTTP(S)
> probing of the device's own web UI, and decoding of its unauthenticated
> telemetry stream). No vendor documentation or firmware/source code was used.

This file is the canonical record of the prompts and the exact steps taken.
See [`AGENTS.md`](AGENTS.md) for the auditing rules that govern this repo.

---

## Prompt log

### Prompt 1 — initial challenge (created the integration)

> In this repo, create a home assistant plugin for the Savant SEM-2015 energy
> monitor. I have one available at 192.168.5.226. You can find them via mDNS
> using the _cli8k._tcp service name. Use port scan to test for open ports and
> see if you can figure out the rest. This is a challenge for you. Good luck.

### Prompt 2 — Integration Quality Scale

> Follow the documentation for the integration quality scale and try to get
> this code in such a shape that it would be eligible for the highest possible
> score https://developers.home-assistant.io/docs/core/integration-quality-scale/

### Prompt 3 — GitHub identity / no self-certification

> my github account is @hpux735. I don't know if we're allowed to self-certify
> platinum (I'm basically certain you can't). So, I don't think we can have the
> quality scale. But, I'm glad we're tracking that for quality

### Prompt 4 — provenance and auditability (this file)

> Ensure that it's mentioned that this was an LLM-driven reverse engineering
> effort. Provide a transcript of the prompts I've used and the steps taken in
> the process of reverse engineering. Detail the precise steps you took since
> the first prompt through completion. Create an AGENTS.md file that captures
> this intent, and the importance of auditing changes to the repo, including the
> prompt that implemented the change. Any code that isn't paired with a prompt
> needs to be flagged.

### Prompt 5 — HACS compatibility

> HACS is presenting an error when this repo is to be added. Ensure that the
> project structure matches what's expected for use with HACS.

### Prompt 6 — discovery resolves to an unreachable IPv6 address

> No entities are found, and for some reason it's apparently looking for IPv6
> addresses. Also, the device is not automatically discovered using mDNS on the
> main devices screen.
>
> Savant SEM-2015 (fd2d:c69e:d0eb:487e:9a84:e3ff:fe9b:2c5c)
> Failed setup, will retry: Could not read telemetry from
> fd2d:c69e:d0eb:487e:9a84:e3ff:fe9b:2c5c:2000: [Errno 111] Connect call failed
> ('fd2d:c69e:d0eb:487e:9a84:e3ff:fe9b:2c5c', 2000, 0, 0)

### Prompt 7 — only create entries for SEM devices; stop using IPv6

> You're also creating a ton of entries with non-compatible devices
> (PBC-1000-00, CLI-W220W-00, etc.). It's important that you only create
> entries for SEM devices. Also, it's still attempting to create entries via
> IPv6
>
> (follow-up) if it helps, I've added avahi-utils

### Prompt 8 — use device-assigned names for sensors

> all the entities/sensors are just named "energy" or "power".  The names
> you've learned from the device should be used so we know what each sensor
> actually means

### Prompt 9 — combine same-named channels into one entity

> Oh, and when there's more than one entry with the same name, they should be
> combined into one entitiy

> (clarification, when asked how to aggregate the combined readings) Sum
> current and average voltage

### Prompt 10 — commit and push after every prompt

> always commit and push at the end of a prompt

### Prompt 11 — investigate the PBC device for energy monitoring

> I think the PBC device has some energy monitoring functions, too.  See if
> they can be used with this integrations.  They're on mDNS, too.  I don't
> know the IP.

---

## Step-by-step log

### Prompt 1 — reverse engineering and first implementation

1. **Repo inspection.** Listed the (empty) repo; confirmed it was not a git
   repository yet.
2. **Tool inventory.** Checked available tooling: no `nmap`, `avahi-browse`,
   `dns-sd`, or `avahi-resolve`; `nc`, `curl`, and Python 3.13 were available.
3. **Network context.** Noted the host was on `192.168.10.33/16`, so the device
   at `192.168.5.226` was reachable within the `/16`; raw `ping` was blocked
   (missing `cap_net_raw`).
4. **Connectivity probe.** A Python socket confirmed port **80** was open.
5. **mDNS (multicast).** A `_cli8k._tcp.local` PTR query to `224.0.0.251:5353`
   timed out — multicast is not routed across the subnets here.
6. **Port scan (Python).** Scanned common ports; found **80, 443, 2000** open.
7. **HTTP identification.** `GET http://192.168.5.226/` → `301` to HTTPS,
   `Server: nginx/1.16.1`.
8. **HTTPS identification.** `curl -k https://192.168.5.226/` served a React
   SPA titled **"SEM-2015 Configuration"**; the self-signed TLS certificate
   showed `CN=sem`, `O=Racepoint Energy, LLC`.
9. **Telemetry discovery.** A raw TCP read of port **2000** immediately returned
   `\nSET_ENERGY=<base64…>`; the stream kept flowing regardless of input
   (sending `GET / HTTP/1.0` did not error).
10. **Frontend analysis.** Downloaded `main.*.chunk.js`, `vendors~main`,
    `runtime~main`; extracted the API route strings (`/auth`, `/config`,
    `/licenses`, `/login`, `/logout`, `/meter`, `/user`, `/users`) and the
    endpoint map
    `{"apiEndpoint":"/meter","authEndpoint":"/auth","licensesEndpoint":"/licenses"}`.
11. **HTTP API probing.**
    - `/meter/` → `401` (nginx)
    - `/auth/` → `404` (Go backend), `/licenses/` → `404`
    - `GET /auth/config` → `{"apiVersion":"0.1.0","password":"XXXXXXXX"}`
      (a user already exists)
    - `POST /auth/login` (empty, then `admin`/`admin`) → `401 "Login failed"`
12. **Telemetry decode.** Base64-decoded the `SET_ENERGY` records → JSON with
    `address: "com.racepointenergy.MeterAgent1"` and a `presentDemands` array of
    15 channels (`channel`, `name`, `group`, `classification`, `power`,
    `current`, `voltage`, `energy`, `percentCommanded`, `dimmable`).
13. **Framing verification.** Confirmed records are `SET_ENERGY=<b64>\r\n`; a
    20 s capture split on `\r\n` produced 20 complete records plus 1 partial
    (end-of-stream) record.
14. **mDNS (unicast, authoritative).** Queried `192.168.5.226:5353` directly and
    decoded the full records:
    - `_cli8k._tcp.local` → instance `10082C7F922C007A`, **SRV port 2000**,
      target `rpe-am335x.local`, `A = 192.168.5.226`, plus AAAA records.
    - TXT: `pn=068-0737-00 mn=SEM-2016-00 sn=000-0000-00 fw=2.8.0-dev.43182
      board_id=217`.
    - `_http._tcp.local` → SRV port 80.
    - Derived MAC `10:08:2c:7f:92:2c` from the instance name / IPv6 EUI-64.
15. **Unit determination (empirical).** Sampled `energy` at two times and
    correlated Δenergy with average `power` × Δt, cross-checked against
    `current` × `voltage`. Concluded:
    - `power` is in **kilowatts** (×1000 → watts),
    - `current` in amps, `voltage` in volts,
    - `energy` in **microwatt-hours**, cumulative (÷1e9 → kWh).
16. **Implemented integration v1**: `manifest.json`, `const.py`, `__init__.py`,
    `config_flow.py`, `sensor.py`, `strings.json`, `README.md`.
17. **Verified.** `py_compile` clean; live end-to-end parse against the device
    (15 channels, e.g. `Steam Power = 104.6 W`, `Steam Energy = 1439.75 kWh`,
    total power ≈ 14.3 kW).

### Prompt 2 — Integration Quality Scale (Platinum-target refactor)

1. Fetched the IQS overview and the rule checklist.
2. Refactored per the checklist:
   - split the TCP client/coordinator into `coordinator.py`,
   - `ConfigEntry.runtime_data` + full type annotations (`strict-typing`),
   - `has_entity_name` + translated/icon names + `{channel_name}` placeholders,
   - `EntityCategory.DIAGNOSTIC` + disabled-by-default for current/voltage,
   - config-flow `data_description`, a **reconfigure** flow, and
     **discovery-update-info** (re-discovery updates host/port),
   - a `diagnostics.py` platform,
   - log-once unavailable/reconnected, `entity-unavailable`, `parallel_updates`,
   - branding `icon.png`/`logo.png`, `quality_scale.yaml`, `.strict-typing`,
     `pyproject.toml`, `requirements_test.txt`,
   - a pytest suite (`tests/`) and expanded end-user docs.
3. Verified: `py_compile`, `pyflakes` (zero issues), stub-import smoke test,
   and a live parse against the device.

### Prompt 3 — GitHub identity / no self-certification

1. Set `codeowners` to `@hpux735` and the documentation URL to
   `https://github.com/hpux735/sem2015-ha`.
2. Removed `"quality_scale": "platinum"` from `manifest.json` (custom
   components are not graded and the tier cannot be self-certified).
3. Added a self-assessment header to `quality_scale.yaml` and clarified the
   README accordingly.

### Prompt 4 — provenance and auditability (this transcript)

1. Wrote this transcript (`REVERSE_ENGINEERING.md`).
2. Wrote `AGENTS.md` capturing the LLM-driven intent and the prompt-pairing
   auditing rule.
3. Added the LLM-driven disclosure to `README.md`.

### Prompt 5 — HACS compatibility

1. Reviewed the HACS publishing requirements.
2. Added the missing required `manifest.json` keys `version` and `issue_tracker`.
3. Added a root `hacs.json` (the HACS manifest) with a `name`.
4. Moved brand assets to `brand/icon.png` and `brand/logo.png` (the HACS
   location; previously inside the integration directory).
5. Added HACS installation/removal instructions to `README.md`.

### Prompt 6 — prefer IPv4 during zeroconf discovery

1. **Root cause (IPv6).** `_discovery_host` returned
   `discovery_info.ip_address`, which HA's `ZeroconfServiceInfo` populates with
   the *most recently updated* address. The SEM advertises both an A record
   (`192.168.5.226`) and an AAAA record, and the AAAA (a ULA
   `fd2d:c69e:d0eb:487e:9a84:e3ff:fe9b:2c5c`) was being chosen. The telemetry
   stream is only reachable over IPv4, so `asyncio.open_connection` to the IPv6
   literal failed with `Errno 111`, the entry never set up, and no entities
   were created. A stale failed entry also suppresses a fresh discovery offer.
2. **Fix.** Added `_is_ipv4` and rewrote `_discovery_host` to prefer an IPv4
   address from `discovery_info.ip_addresses` before falling back to
   `ip_address` and then the legacy `host` attribute. Handles both
   `ipaddress.IPv4Address`/`IPv6Address` objects and plain strings.
3. **TXT key mismatch (found while tracing).** The flow read TXT keys `model`
   and `serial`, but the device advertises `mn` and `sn` (documented in the
   README and step 14 of Prompt 1). Added `_ZEROCONF_TXT_KEYS` mapping
   (`model`→`mn`, `serial`→`sn`, `fw`→`fw`, `board_id`→`board_id`) so the
   stored model/serial are correct (title now shows `SEM-2016-00` rather than
   the `SEM-2015` default).
4. **Tests.** Added `test_zeroconf_flow_prefers_ipv4`; the existing
   `test_zeroconf_flow` model assertion (`SEM-2016-00`) now passes thanks to
   the TXT mapping fix.
5. **Verified.** `py_compile` clean; standalone check that the IPv4 address is
   selected from a mixed IPv6/IPv4 `ip_addresses` list (both object and string
   forms).

### Prompt 7 — filter non-SEM devices; stop creating IPv6 entries

1. **Live enumeration.** With `avahi-browse -rt _cli8k._tcp`, found **seven**
   `_cli8k._tcp.local` devices on the network, of which only one is an SEM:
   `SEM-2016-00` (the target), three `LCB-DMX1-01`, one `PBC-1000-00`, and two
   `CLI-W220W-00`. Every device announces only its IPv6 ULA address.
2. **IPv6 is a dead end.** Confirmed the SEM serves telemetry only on IPv4 —
   `192.168.5.226:2000` is open, while its ULA and global IPv6 addresses refuse
   connections (`Errno 111`). Its mDNS responder answers with the A record only
   when queried **over IPv4 transport**; over IPv6 (multicast *and* unicast) it
   returns only AAAA records. A fresh `zeroconf` `AsyncZeroconf` (dual-stack and
   V4-only) confirmed no IPv4 address is discoverable via mDNS, so
   `discovery_info.ip_addresses` contains only IPv6 and Prompt 6's prefer-IPv4
   fix had nothing to choose.
3. **Fix — model filter.** Added `_is_sem_model` (matches `mn` starting with
   `SEM`) and abort non-SEM discoveries with `not_sem_device`. Also narrowed the
   manifest zeroconf matcher to
   `{"type": "_cli8k._tcp.local.", "properties": {"mn": "sem*"}}` so HA does
   not even offer the flow for other Savant devices.
4. **Fix — no broken IPv6 entries.** `async_step_zeroconf` now auto-creates the
   entry only when discovery yields an IPv4 address; otherwise it shows a
   `zeroconf_confirm` form (host pre-filled with the mDNS hostname) so the user
   supplies the reachable IPv4 address. Rediscovery updates identity metadata
   but never overwrites a working host with IPv6.
5. **Tests.** Updated the zeroconf tests to carry `mn`; added
   `test_zeroconf_non_sem_device_aborts` and
   `test_zeroconf_ipv6_only_confirm_flow`.
6. **Verified.** `py_compile` clean; manifest/strings JSON valid; standalone
   checks of `_is_sem_model`, `_is_ipv4`, and `_discovery_host` (object and
   string forms, legacy `addresses` field).

### Prompt 8 — device-assigned sensor names; Prompt 9 — combine same-named channels

1. **Live enumeration.** Re-decoded a `SET_ENERGY` record from the live device
   (`192.168.5.226:2000`) and confirmed every channel carries a meaningful
   `name` (`Steam`, `Car Charger`, `A/C`, `Oven`, `Equipment`,
   `Office Under-desk`, `Office/Bath`, `Furnace`, `Bedroom`, `Primary`), and
   that several names repeat across two channels (`Steam` 0+1, `Car Charger`
   2+3, `A/C` 4+5, `Oven` 6+7, `Equipment` 8+9) — the two poles of 240 V
   breakers.
2. **Root cause of the "energy"/"power" names.** The entity names were defined
   in `strings.json`, which Home Assistant does **not** read at runtime for
   custom components; translations live in `translations/en.json`. Without the
   runtime file HA fell back to the raw `translation_key` (`power`, `energy`,
   …), so every sensor displayed as just "power"/"energy". Fix: added
   `translations/en.json` (config flow + entity names) and removed the invalid
   `icon` keys from `strings.json` so it mirrors the runtime file.
3. **Combine same-named channels.** Reworked `sensor.py` to group channels by
   device name and expose one set of sensors per name instead of one per
   channel. Power and energy are summed, current is summed and voltage is
   averaged (per the user's clarification). Entity unique IDs are now derived
   from the channel name slug (e.g. `…_steam_power`) rather than the raw
   channel number.
4. **Tests.** Updated `tests/test_sensor.py` and `tests/test_init.py` to the new
   unique IDs, added `test_same_name_channels_combined` and a friendly-name
   assertion (`Savant SEM-2015 Steam Power`), and fixed the pre-existing,
   never-runnable test infrastructure so the suite actually collects and
   passes (see "Flagged changes"): added `tests/__init__.py`, made
   `FakeStreamReader` block instead of returning EOF, corrected the
   `ConfigEntryNotReady` test to call `async_setup_entry` directly, and fixed
   the unload test's assertion (entity registry entries persist across
   unload).
5. **Verified.** `py_compile` clean; a standalone smoke test of the
   grouping/slug/aggregation logic; and the full pytest suite (18 tests)
   passes against a real `homeassistant` install (`pytest-homeassistant-custom-component`).

### Prompt 10 — commit and push after every prompt

1. Added a "Commit and push at the end of each prompt" convention to
   `AGENTS.md` and committed/pushed the Prompt 8/9 work in two commits
   (`4ebf639`, `aa5b131`).

### Prompt 11 — investigate the PBC device for energy monitoring

1. **mDNS enumeration.** Re-ran `avahi-browse -rt _cli8k._tcp`; the **7**
   devices this time were `SEM-2016-00`, `PBC-1000-00` (instance
   `38D2695023D30074`, hostname `rpe-am335x-2.local`), 3× `LCB-DMX1-01`, and
   2× `CLI-W220W-00`. Every record advertised only a global IPv6 address.
2. **PBC identity.** Queried the PBC over IPv6 (its global address
   `2600:a821:7202:2800:3ad2:69ff:fe50:23d3`) — the same `sem` platform as the
   SEM: nginx/1.16.1, the shared self-signed cert (`CN=sem`,
   `O=Racepoint Energy, LLC`), `GET /auth/config` →
   `{"apiVersion":"0.1.0","password":"XXXXXXXX"}`, `POST /auth/login` → 401.
3. **New endpoint discovered — `/info`.** Both devices serve an unauthenticated
   `GET /info`:
   - SEM: `buildOtaProduct: "am335x_sem2015"`, `buildOtaVersion: "2.8.0"`.
   - PBC: `buildOtaProduct: "am335x_pbc"`, `buildOtaVersion: "3.2.0"`,
     `modelNumber: "PBC-1000-00"`, `uuid: "38D2695023D30074"`.
4. **No `/meter` route on the PBC.** The SEM's `GET /meter` returns 401/301
   (auth'd metering endpoint); the PBC returns 404 for `/meter` and every other
   probed route, and serves no web frontend (root → 404).
5. **Finding the IPv4.** mDNS never returns an A record over IPv6 transport
   (same behaviour as the SEM), and the PBC was **not** in `192.168.5.0/24`
   (verified by ARP sweep). A `/16` scan for open port **2000** located the
   Savant devices spread across two subnets: `192.168.3.9`/`.38`/`.96` and
   `192.168.5.96`/`.226`. A unicast mDNS query confirmed **`192.168.3.38` is
   the PBC-1000-00**.
6. **No SET_ENERGY telemetry from the PBC.** Its port 2000 accepts connections
   but sends **zero bytes** (10 s, regardless of input), unlike the SEM which
   begins pushing `SET_ENERGY` within ~0.4 s (~40 KB/10 s). Extra open ports on
   the PBC are 80/111/443 (IPv6) and 80/111/443/2000/2693/8644 (IPv4); 2693 and
   8644 are also silent, and rpcbind (111) only registers the portmapper
   itself.
7. **Conclusion.** The PBC shares the `sem` software stack but does **not**
   expose the unauthenticated `SET_ENERGY` stream (nor any `/meter`-style API)
   this integration relies on, so it cannot be driven by the current
   integration. No code changes were made; this prompt is investigation only.

---

## Flagged changes (code not directly paired with a prompt)

Every committed file traces to prompts 1–5 above. The following are the only
items added on the model's own judgment (within a prompted scope) and are
flagged here for review:

1. **Branding artwork** (`icon.png`, `logo.png`) — the *requirement* for
   branding assets came from Prompt 2's `brands` rule (and their relocation to
   `brand/` from Prompt 5), but the actual design (navy background + amber
   lightning bolt) is placeholder art chosen by the model. **Flag:** replace
   with proper vendor branding if available.
2. **Documentation URL / codeowner handle** — these are identity fields. The
   handle was initially guessed (`@wdillon`) and corrected to `@hpux735` in
   Prompt 3. **Flag:** verify the final repository URL.
3. **Reverse-engineering helper scripts** — the Python snippets used for port
   scanning, mDNS decoding, and base64/JSON parsing were ephemeral and were
   never committed to the repository. **Flag:** noted for completeness only.
4. **Test-infrastructure repairs (Prompt 8/9, model-initiated).** To run the
   pytest suite against a real `homeassistant` install I had to fix the
   previously-never-collected test scaffolding, none of which is traceable to a
   user prompt: added `tests/__init__.py` (required for the tests' relative
   `from .conftest` imports), changed `FakeStreamReader.read()` to block rather
   than return EOF (so the coordinator stays "connected" instead of flipping
   every sensor to unavailable), rewrote `test_setup_entry_not_ready` to call
   `async_setup_entry` directly (HA swallows `ConfigEntryNotReady` during
   entry setup), and corrected `test_unload_entry`'s assertion (entity
   registry entries persist across unload; only the live state is removed).
   **Flag:** review these test-only edits; they change no production behavior.
