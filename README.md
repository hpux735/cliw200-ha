# Savant CLI-W200/CLI-W220 Thermostat — Home Assistant Integration

> **LLM-driven reverse engineering effort.** This integration was reconstructed
> by an AI coding agent (opencode / `deepseek-v4-pro`) from a series of user
> prompts, using only read-only, passive techniques. No vendor documentation,
> firmware, or source code was used. See
> [`REVERSE_ENGINEERING.md`](REVERSE_ENGINEERING.md) for the full transcript.

Climate integration for Savant/Racepoint Energy CLI-W200 and CLI-W220 wireless
thermostat systems. Communicates directly with the thermostat controller over
the unauthenticated TCP telemetry stream (port 2000).

## Features

- Current temperature and humidity
- Target temperature (single-setpoint) or heat/cool bounds (dual-setpoint)
- Comfort band (tolerance) on single-setpoint models exposed as heat/cool range
- HVAC modes: Off, Heat, Cool, Auto (heat/cool)
- Fan modes: On, Auto, Cycle
- Current HVAC action: idle, heating, cooling
- Automatic mDNS/zeroconf discovery
- Live push updates via persistent TCP stream (local push)

## Supported devices

- **CLI-W220W-00** — wireless thermostat controller
- **CLI-W200** — wireless thermostat controller

Both single-setpoint (one target temperature with comfort band) and
dual-setpoint (separate heat/cool thresholds) configurations are supported.

## Supported entities

| Entity | Type | Description |
|--------|------|-------------|
| Thermostat | `climate` | Temperature, setpoint(s), humidity, HVAC mode, fan mode |

The climate entity supports `target_temperature` for single-setpoint thermostats
and `target_temperature_low`/`target_temperature_high` for dual-setpoint and
comfort-band configurations.

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS
2. Search for "Savant CLI" and install
3. Restart Home Assistant
4. The thermostat should be auto-discovered via mDNS, or add manually by
   entering the IP address

### Manual

Copy `custom_components/savant_cli/` into your Home Assistant
`custom_components/` directory and restart.

## Removal

1. In Home Assistant, go to Settings → Devices & Services
2. Find the Savant CLI integration entry
3. Click the menu (three dots) → Delete

To fully remove the integration, delete the `savant_cli` directory from
`custom_components/`.

## Configuration parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| Host | IP address or hostname of the thermostat controller | (required) |
| Port | TCP port for the telemetry stream | 2000 |

These can be changed via the Reconfigure option on the integration entry.

## How data is updated

The integration opens a persistent TCP connection to the thermostat controller
on port 2000. The controller pushes full state updates every 1-30 seconds, and
also echoes state after any command is sent. The integration uses Home
Assistant's "local push" model — no polling, near-instant updates.

If the connection drops, the integration automatically reconnects with
exponential backoff (starting at 5 seconds, up to 5 minutes). The climate
entity shows as unavailable during disconnection.

## Discovery

The thermostat advertises itself via mDNS as `_cli8k._tcp.local` with a
model (`mn`) starting with `CLI-W2`. Home Assistant's zeroconf integration
will automatically discover it. If the device only advertises an IPv6 address
(common with these devices), you can enter the IPv4 address manually.

## Telemetry protocol

The thermostat controller exposes a line-oriented text protocol on TCP port
2000. All temperature and humidity values are in tenths (e.g. `0773` =
77.3°F). The stream is bidirectional — sending commands in the same format
changes settings. No authentication is required on the telemetry port.

See [`REVERSE_ENGINEERING.md`](REVERSE_ENGINEERING.md) for full protocol
documentation and the discovery process.

## Use cases

- **Home climate monitoring:** Track temperature and humidity in your home
- **HVAC control:** Adjust setpoints, switch between heat/cool/auto/off modes
- **Fan scheduling:** Control fan mode (on, auto, cycle) via automations
- **Multi-zone monitoring:** Both single-setpoint (comfort band) and multi-zone
  (dual-setpoint) thermostat configurations are supported

## Automation examples

### Set temperature based on time of day

```yaml
automation:
  - alias: "Set thermostat to 72F at 8 AM"
    trigger:
      - platform: time
        at: "08:00:00"
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.savant_cli_thermostat
        data:
          temperature: 72
```

### Turn off thermostat when away

```yaml
automation:
  - alias: "Turn off thermostat when away"
    trigger:
      - platform: state
        entity_id: person.me
        to: "not_home"
    action:
      - service: climate.set_hvac_mode
        target:
          entity_id: climate.savant_cli_thermostat
        data:
          hvac_mode: "off"
```

### Alert on high humidity

```yaml
automation:
  - alias: "Alert high humidity"
    trigger:
      - platform: numeric_state
        entity_id: climate.savant_cli_thermostat
        attribute: current_humidity
        above: 65
    action:
      - service: notify.mobile_app
        data:
          message: "Humidity is above 65%"
```

## Troubleshooting

### The thermostat is not discovered automatically

The device may only advertise an IPv6 address via mDNS, which is unreachable
from the telemetry stream. Add the thermostat manually using its IPv4 address.

To find the IPv4 address, scan your network for port 2000:

```bash
nmap -p 2000 192.168.1.0/24
```

Or use `avahi-browse -rt _cli8k._tcp` to list all Savant devices.

### The entity shows as unavailable

Check that the thermostat controller is powered on and reachable at the
configured IP address. The integration will automatically reconnect when
connectivity is restored.

### Connection errors in logs

The integration logs connection failures once, then suppresses repeated
messages. If you see a single "Could not connect" message, the device is
temporarily unreachable and will be retried.

## Known limitations

- The thermostat controller's HTTP API (`/thermostat`, `/auth`) is
  password-protected and not used by this integration. All data comes from
  the unauthenticated TCP telemetry stream on port 2000.
- Only one thermostat zone (TSTAT_00) is supported per controller.
  Multi-zone controllers will only expose the primary zone.
- IPv6 is not supported for telemetry. The device's IPv4 address must be
  used.
- Firmware updates are not supported through this integration.
- The integration has been tested with firmware version 4.0.7. Other
  versions may have different telemetry formats.
