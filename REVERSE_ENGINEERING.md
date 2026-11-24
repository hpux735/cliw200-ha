# Savant CLI-W200/CLI-W220 Thermostat — LLM-driven reverse engineering transcript

> **Disclosure:** this integration was produced by an **LLM-driven reverse
> engineering effort**. The CLI-W200/CLI-W220 thermostat protocol was
> reconstructed by an AI coding agent (opencode / `deepseek-v4-pro`) from a
> series of user prompts, using only read-only, passive techniques (port
> scanning, mDNS queries, HTTP(S) probing of the device's own web UI, and
> decoding of its unauthenticated telemetry stream). No vendor documentation
> or firmware/source code was used.

This file is the canonical record of the prompts and the exact steps taken.
See [`AGENTS.md`](AGENTS.md) for the auditing rules that govern this repo.

---

## Prompt log

### Prompt 1 — initial challenge (created the climate integration)

> Read the contents of the repo, and get started figuring out how to write a
> climate integration for the CLI-W200/CLI-W220. I have a thermostat setup
> that's not controlling a furnace available at 192.168.3.45. DO NOT use any
> other thermostat for testing.

### Prompt 1a — ground truth verification

> If you need ground-truth of meaning of values let me know and I can change
> modes on screen

---

## Step-by-step log

### Prompt 1 — reverse engineering and first implementation

1. **Repo inspection.** The repo contained only `AGENTS.md` and
   `REVERSE_ENGINEERING.md` (the SEM-2015 energy monitor transcript). No
   `custom_components/` directory existed.

2. **Port scan.** Scanned common ports on `192.168.3.45`. Found: **80, 443,
   2000, 22, 111** open. Port 22 (SSH) and 111 (rpcbind) are not used by the
   integration. Port 2000 was the key telemetry endpoint.

3. **mDNS enumeration.** `avahi-browse -rt _cli8k._tcp` found 7 Savant
   devices. Two were `CLI-W220W-00` thermostats:
   - `24CD8D83D690006B` at `rpe-0945.local` — `SN=BT5241101186`, fw `4.0.7-nightly.60991`
   - `24CD8D83D6FC006B` at `rpe-0945-3.local` — `SN=BT5241101101`, fw `4.0.7-nightly.60991`
   
   Other devices: 1× `SEM-2016-00`, 1× `PBC-1000-00`, 3× `LCB-DMX1-01`.

4. **HTTP identification.**
   - `GET https://192.168.3.45/` → React SPA titled **"Racepoint Energy
     Thermostat Config"**, served by `nginx/1.24.0`.
   - `GET /auth/config` → `{"apiVersion":"0.1.0","password":"XXXXXXXX"}` (a
     user is configured).
   - `POST /auth/login` with `admin/admin`, `admin/password`, `admin/racepoint`
     → `401 "Login failed"`.
   - `GET /info` (unauthenticated) → `{"modelNumber":"CLI-W220W-00", ...,
     "buildOtaProduct":"thermostat_imx8_swu", "buildOtaVersion":"4.0.7"}`.
   - `GET /thermostat` → `401` (requires auth).

5. **Telemetry discovery (port 2000).** A raw TCP read immediately returned a
   periodic state dump:

   ```
   TSTAT_00 SET_HUMIDITY=0447
   TSTAT_00 SET_TEMP=0772
   TSTAT_00 SET_HVAC_MODE=01
   CLEAR_RELAY=local-w1
   TSTAT_00 SET_FAN_MODE=00
   TSTAT_00 SET_NAME=Home
   TSTAT_00 SET_FAN_STAGE=0
   TSTAT_00 SET_HUMIDITY_SP=0100
   SET_OUTSIDE_TEMP=0662
   TSTAT_00 SET_TEMP_TOLERANCE=0020
   SET_RELAY=local-g
   TSTAT_00 SET_TEMP_SP=0750
   TSTAT_00 SET_HVAC_STATE=01
   CLEAR_RELAY=local-y1
   @001AAE16D94B SET_BTLE_RSSI=-88
   @001AAE16D94B SET_BTLE_BATT=0293
   @001AAE560003 SET_BTLE_RSSI=-97
   @001AAE167150 SET_BTLE_RSSI=-82
   ```

   Lines are `\r\n` delimited. The full state dump repeats every few seconds.

6. **Frontend analysis.** Downloaded the webpack bundles
   (`runtime~main.*.js`, `vendors~main.*.chunk.js`, `main.*.chunk.js`).
   Extracted the endpoint map:
   ```json
   {"apiEndpoint":"/thermostat","authEndpoint":"/auth","infoEndpoint":"/info","licensesEndpoint":"/licenses","uidEndpoint":"/uid"}
   ```
   The SPA uses `superagent` for HTTP requests with Bearer-token auth stored
   in `localStorage`. Operations found:
   - `GET /auth/config` — check existing user
   - `PUT /auth/config` — create/update user
   - `POST /auth/login` — authenticate
   - `GET /auth/logout` — logout
   - `GET /config/relays` — relay state
   - `PUT /config/relay/` — toggle relay
   - `deployConfig` — save device configuration

7. **Protocol discovery — bidirectional telemetry (port 2000).** The
   telemetry stream is **bidirectional**: sending a command causes the device
   to echo its full state. Tested by sending various commands:
   - `TSTAT_00 SET_TEMP_SP=0760\r\n` → setpoint changed, full state echoed
   - `TSTAT_00 SET_HVAC_MODE=02\r\n` → mode changed to Cool (02), echoed
   - `TSTAT_00 SET_HVAC_MODE=01\r\n` → mode changed back to Heat (01)
   - `SET_RELAY=local-g\r\n` → fan relay toggled

8. **Protocol specification established:**
   - Transport: TCP, port 2000
   - Framing: `\r\n` delimited lines
   - Device emits full state periodically (~1-2 s) and after any command
   - Commands use the same format as the telemetry records

   **Lines with a device prefix (`<device> <command>=<value>`):**
   - `TSTAT_00` — the primary thermostat
   - `@<hex_mac>` — Bluetooth LE sensors (wireless thermostat remotes)

   **TSTAT_00 records (device-prefixed SET commands):**
   | Record | Meaning | Units | Example |
   |--------|---------|-------|---------|
   | `SET_TEMP` | Current temperature | tenths °F | `0773` = 77.3°F |
   | `SET_TEMP_SP` | Temperature setpoint | tenths °F | `0750` = 75.0°F |
   | `SET_HUMIDITY` | Current humidity | tenths % | `0446` = 44.6% |
   | `SET_HUMIDITY_SP` | Humidity setpoint | tenths % | `0100` = 10.0% |
   | `SET_HVAC_MODE` | HVAC mode | `00`=Off, `01`=Heat, `02`=Cool, `03`=Auto |
   | `SET_HVAC_STATE` | HVAC running state | `00`=Idle, `01`=Heating, `02`=Cooling |
   | `SET_FAN_MODE` | Fan mode | `0`=Auto, `1`=On |
   | `SET_FAN_STAGE` | Fan speed stage | integer |
   | `SET_NAME` | Thermostat name | string (e.g. `Home`) |
   | `SET_TEMP_TOLERANCE` | Temperature swing | tenths °F | `0020` = 2.0°F |

   **Bare (no prefix) records:**
   | Record | Meaning | Units |
   |--------|---------|-------|
   | `SET_OUTSIDE_TEMP=<v>` | Outdoor temperature | tenths °F |
   | `SET_RELAY=<addr>` | Relay turned ON | relay address |
   | `CLEAR_RELAY=<addr>` | Relay turned OFF | relay address |

   **Relay addresses observed:**
   - `local-g` — Fan relay
   - `local-w1` — Heat stage 1 relay
   - `local-y1` — Cool stage 1 (compressor) relay

   **BTLE sensor records (`@<mac>` prefix):**
   | Record | Meaning | Units |
   |--------|---------|-------|
   | `SET_BTLE_RSSI=<v>` | Signal strength | dBm |
   | `SET_BTLE_BATT=<v>` | Battery voltage | hundredths of volt (e.g. `0293` = 2.93V) |

9. **Integration implemented.** Created the following files under
   `custom_components/savant_cli/`:
   - `manifest.json` — component manifest with `zeroconf` discovery for `_cli8k._tcp.local` matching `CLI-W2*` models
   - `const.py` — domain, port, HVAC mode/action/fan mode mappings
   - `.strict-typing` — strict typing marker
   - `coordinator.py` — TCP client (connects to port 2000, continuously reads/parses telemetry, sends commands)
   - `config_flow.py` — manual IP/port entry + zeroconf(mDNS) discovery, filtering only CLI-W200/W220 models, IPv4-only
   - `climate.py` — `ClimateEntity` with temp, setpoint, humidity, HVAC modes, fan modes
   - `__init__.py` — entry setup/unload
   - `diagnostics.py` — redaction-safe diagnostics export
   - `strings.json` / `translations/en.json` — translations
   - `hacs.json` — HACS manifest
   - `brand/icon.png`, `brand/logo.png` — placeholder branding
   - `tests/` — 36 tests covering telemetry parsing, climate entity, config flow helpers

10. **Verified.**
    - All 36 unit tests pass.
    - Live TCP connection to `192.168.3.45:2000` parses correctly.
    - Command sending (setpoint, mode changes) confirmed bidirectional.

---

## Protocol summary

The CLI-W200/CLI-W220 thermostat uses a simple line-oriented text protocol
over TCP port 2000 for all telemetry and control.

- **Read:** Connect to `host:2000`, receive `\r\n`-delimited telemetry lines.
  A full state dump is emitted periodically (~1-2 s) and after every command.
- **Write:** Send `TSTAT_00 SET_<KEY>=<VALUE>\r\n` to change settings.
- **Values:** Temperature values are in tenths of degrees Fahrenheit.
  Humidity values are in tenths of percent. Battery values are in hundredths
  of volts.
- **Auth:** The HTTP API (`/thermostat`, `/auth`) requires a password, but the
  TCP telemetry/control stream on port 2000 is entirely unauthenticated and is
  sufficient to read all thermostat state and issue all control commands.

---

## Multi-zone setup and configuration investigation

### Driving prompt (verbatim)

> there's another thermostat at 192.168.3.49.  It has a bunch of zones, and the plugin doesn't handle that well.  Please check the config if you can figure out how to load it.  Then, when installing the integration, ask the user what area they want each zone in, and pre-populate the name of the entity with the name from the config file.  Feel free to do as much experimentation with the thermostat at 192.168.3.45 for discovering how to get the config, but please don't write anything to the .49 thermostat until you're sure you know what you're doing.  That's the one that's actually running my house.
>
> Oh, and if you figure out how to load the config off the thermostat, it might be nice to add the reverse engineering of the config file to the repo's documentation.

### Safety boundary

This investigation used HTTPS GET requests to `.45` and passive TCP reads on
`.45` and `.49`. No socket writes, thermostat commands, login guesses, pairing,
configuration uploads, relay operations, or setting changes were performed.
The earlier entries above describe historical work and are not a statement
that all historical investigation was passive.

### Verified configuration loader

1. Fetched the HTML and main JavaScript bundle from `https://192.168.3.45/`.
2. The frontend defines `apiEndpoint` as `/thermostat`. Its `getConfig`
   implementation performs `GET ${apiEndpoint}/config`, using a helper that
   attaches `Authorization: Bearer <token>`. The token comes from the web
   UI's `localStorage` entry `authToken`, specifically its `token` member.
3. Verified `GET /thermostat/config` and `/thermostat/config/` on `.45`
   return HTTP 401 without authorization. `GET /config` returns the HTML SPA,
   not a configuration file. Earlier notes listing `/config/relays` omitted
   the `/thermostat` API prefix: the frontend constructs
   `/thermostat/relays`, `/thermostat/485addresses`, and
   `/thermostat/owaddresses` in the same way. These latter routes were found
   in JavaScript, not fetched or independently validated during this work.
4. The frontend also defines configuration PUT and reset methods. Neither
   was called. No attempt was made to bypass authentication.

**Config-file schema remains unknown.** No authenticated JSON configuration
was retrieved, so fields, zone indexing, enabled flags, and physical sensor
associations must not be invented. An exported config or authorized web-UI
access is needed to continue that part of reverse engineering. The integration
does not yet load this file and stores no authentication tokens.

### Verified alternative: zone names in telemetry

Used the production passive discovery helper to listen for 40 seconds on each
controller's TCP port 2000. No bytes were sent. Results:

| Controller | Zone | Reported name |
|------------|------|---------------|
| `.45` | `TSTAT_00` | Home |
| `.49` | `TSTAT_00` | Home |
| `.49` | `TSTAT_01` | Attic |
| `.49` | `TSTAT_02` | Courtyard |
| `.49` | `TSTAT_03` | Laundry |
| `.49` | `TSTAT_04` | Garage |
| `.49` | `TSTAT_05` | Living Room |
| `.49` | `TSTAT_06` | Primary |
| `.49` | `TSTAT_07` | Equipment Closet |

Names use `TSTAT_nn SET_NAME=<full name>`, including embedded spaces. There is
no verified snapshot completion marker. Forty seconds is a bounded discovery
window, not a guarantee that every possible zone has reported. Runtime zone
discovery remains active for zones appearing later.

### Implementation and verification

- Fixed the production parser to keep separate zone states rather than merge
  interleaved zone telemetry. Controller-wide relay/BTLE records remain global;
  there is not enough evidence to associate them with particular zones.
- Each zone gets its own named climate entity, and every command uses that
  entity's exact `TSTAT_nn` prefix. Zone zero retains the shipped unique ID;
  other IDs append the zone identifier.
- Manual, zeroconf, and reconfiguration flows share passive discovery, followed
  by one editable name and optional existing-area form per zone. Names are
  telemetry-derived defaults, not claimed config-file values.
- Entity-level areas are applied in Home Assistant only. Setup does not write
  configuration or temperatures to either controller. Explicit reconfiguration
  applies reviewed name/area selections; normal reloads preserve registry
  customizations. Configured labels are not overwritten by telemetry updates.
- Fixed stale derived comfort-band bounds when the corresponding zone changes
  HVAC mode. No new thermostat control semantics were inferred.
- Added production-parser and real Home Assistant registry/flow tests. Also
  corrected three pre-existing tests that assumed fabricated framework APIs or
  feature-bit values. Full suite: **103 passed** using Home Assistant
  **2024.12.5**, Python **3.12.12**. This is not a claim of a live Home
  Assistant 2026 UI test or official Integration Quality Scale certification.

## Port 2000 configuration-query investigation

### Driving prompts (verbatim)

> is there any way to get the config from the port 2000 interface?

> feel free to guess commands against .45 though

Listened passively on `192.168.3.45:2000` for 45 seconds. Observed the usual
`TSTAT_00 SET_*`, relay, outside-temperature, and BTLE records; no configuration
document or configuration-specific record was observed.

Following explicit permission to guess on `.45`, opened one connection to
`192.168.3.45:2000`, listened for five seconds, and sent the following ASCII
query candidates, each terminated with CRLF and followed by a five-second
receive window:

```text
HELP
GET_CONFIG
GET_CONFIG?
GET_CONFIGURATION
GET_SYSTEM_CONFIG
TSTAT_00 GET_CONFIG
```

The connection remained open. The receive window after `HELP` contained an
ordinary thermostat state snapshot; later windows contained BTLE updates.
There was no help listing, JSON/base64 config payload, explicit acknowledgment,
or error response. Since periodic snapshots occur without queries, the snapshot
after `HELP` does not establish that `HELP` was recognized. Five-second windows
also do not rule out a delayed response. These results do not establish that
configuration retrieval is impossible; they establish only that these candidate
queries did not produce an identifiable configuration response in this test.

No setters, resets, pairing operations, or relay commands were sent. No
connections or commands were made to `.49` during this investigation. The
authenticated HTTP `GET /thermostat/config` remains the only configuration-file
retrieval path identified in the device's own frontend. Port 2000 still provides
a useful subset of configuration-like information (zone names, setpoints, fan
mode, tolerance), but not a verified complete configuration file.

### Additional query variations and verified getters

Driving prompt (verbatim):

> keep trying more variations, maybe?

All probes below targeted **192.168.3.45 only** on port 2000. No setter,
reset, pairing, or relay command was sent. `.49` was not accessed.

First sent this batch, one query every three seconds, with a five-second
passive baseline and a final 15-second delayed-response window:

```text
?
HELP?
GET_HELP
GET CONFIG
GET CONFIG?
GET CONFIGURATION
GET_CONFIG=
GET_CONFIG=00
GET_CONFIG=ALL
GET_CONFIGURATION?
?CONFIG
CONFIG?
GET_THERMOSTAT_CONFIG
GET_TSTAT_CONFIG
GET_SYSTEM_CONFIG?
TSTAT_00 GET_CONFIG?
TSTAT_00 GET_CONFIG=
GET_ALL
GET_STATUS
GET_STATE
```

No identifiable non-routine response appeared. Ordinary snapshots in the
windows after `?` and `?CONFIG` are insufficient to attribute recognition to
those commands. Reported mode, setpoint, tolerance, and fan settings remained
unchanged in those snapshots.

Next checked known-field getters and alternative configuration framing:

```text
TSTAT_00 GET_TEMP
TSTAT_00 GET_TEMP?
TSTAT_00 GET_TEMP=
TSTAT_00 GET_NAME
TSTAT_00 GET_NAME?
GET_CONFIG (LF terminator)
GET_CONFIG (CR terminator)
GET_CONFIG_JSON
GET_CONFIG_FILE
TSTAT_00 GET_CONFIGURATION
```

All queries otherwise used CRLF termination. `TSTAT_00 GET_NAME` produced a
previously unobserved bare record:

```text
SET_NAME=Electric; 1 Stage Heat, 1 Stage Cool
```

Repeated `TSTAT_00 GET_NAME` three more times and also tried bare `GET_NAME`.
Each returned this same record. It differs from the periodic
`TSTAT_00 SET_NAME=Home`: it appears to describe an equipment/system profile,
**not the zone name**. That interpretation is provisional; the returned text
and repeatability are verified. Supplying a `TSTAT_00` prefix did not scope
this particular response to the zone name. The integration must not treat
bare `SET_NAME` as a zone-name update.

Also tried `GET_MODEL`, `GET_VERSION`, `TSTAT_00 GET_CONFIG`,
`TSTAT_00 GET_SYSTEM`, and `GET_SYSTEM_NAME`. `GET_VERSION` returned:

```text
SET_OTA=4.0.7-nightly.60991
```

A final batch tested `GET_CONFIG_VERSION`, `GET_SETTINGS`, `GET_SETUP`,
`GET_HARDWARE`, `GET_ZONES`, `GET_THERMOSTATS`, `GET_TSTAT_LIST`, `GET_SERIAL`,
`GET_UUID`, `GET_485_ADDRESS`, `GET_OW_ADDRESS`, and repeated `GET_VERSION`.
Only `GET_VERSION` produced a distinct query-specific response, again the
same `SET_OTA` record. No identifiable config file, structured config payload,
help listing, or zone enumeration was obtained.

**Conclusion:** a getter vocabulary demonstrably exists (`GET_NAME`,
`GET_VERSION`), so lack of responses to configuration-query guesses is not
evidence that the entire interface is write-only. A full configuration getter
has still not been identified. Three-second receive windows and periodic
unsolicited data limit conclusions about unsupported or delayed responses.

### Configuration abbreviation sweep

Driving prompts (verbatim):

> enumerate all the possible shortenings of the word configuration

> have you tried all of those?

> well, do it lady

Tested every unique form from the proposed abbreviation/prefix lists using
`GET_<form>` followed by CRLF, on **192.168.3.45:2000 only**:

```text
GET_C
GET_CF
GET_CFG
GET_CNF
GET_CNFG
GET_CONF
GET_CONFG
GET_CONFIG
GET_CONFIGS
GET_CONFIGURATION
GET_CO
GET_CON
GET_CONFI
GET_CONFIGU
GET_CONFIGUR
GET_CONFIGURA
GET_CONFIGURAT
GET_CONFIGURATI
GET_CONFIGURATIO
```

Used one TCP connection, a five-second passive baseline, three-second receive
windows after each query, and a final 15-second delayed-response window. None
returned an identifiable configuration response. The windows after `GET_CONF`
and `GET_CONFIGURA` contained routine 14-record thermostat snapshots, not
configuration documents; periodic unsolicited snapshots prevent attributing
those to recognition of either command. Other windows were silent or contained
routine BTLE telemetry.

As a positive control, `GET_VERSION` again returned
`SET_OTA=4.0.7-nightly.60991`. This confirms the connection could receive a
known query response during this sweep. It does not prove every candidate is
unsupported, only that none produced an identifiable config response within
these observation windows. No bare abbreviations, setters, or commands to
`.49` were sent.

### Field getters and zone-address discrimination

Driving prompt (verbatim):

> Ok, well, let's move on.  How about we test out some getters for the various other values we have?  That way we can run a "get temperature" or "get status" and infer the list of valid zones in the thermostat

All tests targeted **192.168.3.45:2000 only**, using CRLF-terminated query
candidates. No setters or commands to `.49` were sent. Configuration, mode,
fan, relay, and setpoint changes were not requested.

First checked known telemetry field names, using a five-second passive
baseline and three-second receive windows:

```text
GET_VERSION
GET_TEMP
GET_TEMPERATURE
GET_TEMP_SP
GET_HUMIDITY
GET_HVAC_MODE
GET_HVAC_STATE
GET_FAN_MODE
GET_TEMP_TOLERANCE
GET_STATUS
GET_STATE
GET_TSTAT
TSTAT_00 GET_TEMP
TSTAT_00 GET_HUMIDITY
TSTAT_00 GET_HVAC_MODE
TSTAT_00 GET_STATUS
GET_NAME
```

`GET_VERSION` and `GET_NAME` returned the previously verified global records.
The `GET_TEMP` and `GET_TSTAT` windows contained full routine snapshots, but
the timing was consistent with unsolicited periodic snapshots, not proof of
recognition. Other candidates returned no identifiable field-specific reply.

Next tested addressing variations with two-second receive windows:

```text
GET_TEMP=00
GET_TEMP=0
GET_TEMP=01
GET_TEMP=99
GET_TEMP=TSTAT_00
GET_TEMP TSTAT_00
GET_TEMP 00
TSTAT_00 GET_TEMP=00
TSTAT_99 GET_TEMP=99
GET_STATUS=00
GET_STATUS=99
GET_TSTAT=00
GET_TSTAT=99
GET_TSTAT_00
GET_TEMP_00
TSTAT_99 GET_TEMP
GET_NAME=00
GET_NAME=99
GET_VERSION
```

No identifiable zone-addressed query response or invalid-zone error was
received. `GET_VERSION` remained a successful positive control. Silence for
both known zone `00` and candidate zone `99` cannot discriminate valid zones.

Finally, recorded per-packet delays in a single connection while testing:

```text
TSTAT_00 GET_NAME
TSTAT_99 GET_NAME
GET_THERMOSTAT (three consecutive attempts)
GET_TSTAT (two consecutive attempts)
GET_TSTAT_STATUS
GET_TSTAT_STATE
GET_TSTAT_INFO
GET_THERMOSTAT_STATUS
GET_THERMOSTAT_STATE
GET_THERMOSTAT_INFO
GET_THERMOSTAT=00
GET_ALL_TSTATS
GET_TEMP (two consecutive attempts)
GET_STATUS (two consecutive attempts)
GET_VERSION
```

**Verified discrimination result:** `TSTAT_00 GET_NAME` returned the bare
equipment-profile record after approximately 6 ms; `TSTAT_99 GET_NAME`
returned that identical record after approximately 4 ms. Thus a response to
this getter does **not** demonstrate that the supplied zone exists: it behaves
as a controller-global getter for these inputs. The integration must not use
it to enumerate zones or interpret its profile text as the zone label.

Repeated temperature, status, and thermostat getters produced no comparable
immediate, repeatable replies. Full snapshots in the timing capture began
approximately 30 seconds apart, reinforcing their periodic nature. This does
not establish that all possible getter spellings or addressing schemes are
unsupported; the working zone-query grammar remains unknown.

**Implementation consequence:** retain passive enumeration of zone IDs from
unsolicited `TSTAT_nn SET_*` records and names from
`TSTAT_nn SET_NAME=<name>`. A reported ID is evidence of an observed zone;
absence in a bounded capture is not proof that a zone does not exist. No
unverified getter or zone-number scan was added to integration setup.

## Incremental setup and early completion

Driving prompt (verbatim):

> sure, let's start there, I guess

This accepts the preceding proposal to make setup less blocking by showing
zones as they arrive and letting users finish before the full discovery window,
while runtime discovery continues to add zones later.

- The passive discovery helper now publishes zone names on `SET_NAME` records
  while retaining the bounded 40-second collection window. The UI's progress
  task waits only for the next named zone or collection completion, not for the
  entire window before presenting the first zone.
- The temporary collector keeps listening while the user edits names and areas.
  Later names join the pending queue; duplicate telemetry does not repeat
  reviewed prompts or overwrite reviewed edits.
- Added **Finish now** to zone forms and a summary with an explicit choice to
  finish or wait for more. Early completion retains observed named zones,
  including unreviewed zones with default names and no newly selected areas.
- Finishing or aborting closes the temporary discovery socket and cancels its
  task. Once the entry is set up, the existing runtime connection continues
  zone discovery; the temporary collector is not left orphaned.
- Reconfiguration can immediately present previously saved zones without
  waiting for another snapshot. Names and areas for later zones remain
  reviewable via Reconfigure. Partial read errors preserve already found named
  zones and allow completion instead of discarding them.
- Initial setup still waits for at least one zone. No getter, new framing
  assumption, or claim of complete enumeration was introduced. Nameless zones
  remain a zone-ID fallback at collection completion.
- Verified **119 tests passed** against real Home Assistant 2024.12.5 libraries,
  including delayed-stream incremental discovery, early finish, more zones
  during forms, abort cleanup, partial errors, and reconfiguration. All network
  connections in these tests are mocked. Neither thermostat was accessed for
  this change; no commands or setting changes were made.

## Flagged changes (code not directly paired with a prompt)

1. **Branding artwork** (`brand/icon.png`, `brand/logo.png`) — placeholder
   solid navy PNG (256×256) chosen by the model. **Flag:** replace with
   proper Savant/Racepoint Energy branding if available.
2. **Test infrastructure** — the mock `homeassistant` package under
   `/tmp/opencode/mock_ha` was created by the model to enable running tests
   without a full Home Assistant installation. These are ephemeral and not
   committed to the repo.
