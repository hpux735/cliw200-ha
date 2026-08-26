"""Constants for the Savant CLI-W200/CLI-W220 thermostat integration."""

DOMAIN = "savant_cli"
DEFAULT_PORT = 2000
DEFAULT_NAME = "Savant CLI Thermostat"
TIMEOUT = 15

HVAC_MODES = {
    "00": "off",
    "01": "heat",
    "02": "cool",
    "03": "heat_cool",
}

HVAC_ACTIONS = {
    "00": "idle",
    "01": "heating",
    "02": "cooling",
}

FAN_MODES = {
    0: "auto",
    1: "on",
}

FAN_MODE_REVERSE = {v: k for k, v in FAN_MODES.items()}

_ZEROCONF_TXT_KEYS = {
    "model": "mn",
    "serial": "sn",
    "fw": "fw",
    "board_id": "board_id",
    "pn": "pn",
}
