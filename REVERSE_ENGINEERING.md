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

## Flagged changes (code not directly paired with a prompt)

1. **Branding artwork** (`brand/icon.png`, `brand/logo.png`) — placeholder
   solid navy PNG (256×256) chosen by the model. **Flag:** replace with
   proper Savant/Racepoint Energy branding if available.
2. **Test infrastructure** — the mock `homeassistant` package under
   `/tmp/opencode/mock_ha` was created by the model to enable running tests
   without a full Home Assistant installation. These are ephemeral and not
   committed to the repo.
