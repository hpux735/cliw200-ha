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

## Discovery

The thermostat advertises itself via mDNS as `_cli8k._tcp.local` with a
model (`mn`) starting with `CLI-W2`. Home Assistant's zeroconf integration
will automatically discover it. If the device only advertises an IPv6 address
(common with these devices), you can enter the IPv4 address manually.

## Supported devices

- **CLI-W220W-00** — wireless thermostat controller
- **CLI-W200** — wireless thermostat controller

Both single-setpoint (one target temperature with comfort band) and
dual-setpoint (separate heat/cool thresholds) configurations are supported.

## Telemetry protocol

The thermostat controller exposes a line-oriented text protocol on TCP port
2000. All temperature and humidity values are in tenths (e.g. `0773` =
77.3°F). The stream is bidirectional — sending commands in the same format
changes settings. No authentication is required on the telemetry port.

See [`REVERSE_ENGINEERING.md`](REVERSE_ENGINEERING.md) for full protocol
documentation.
