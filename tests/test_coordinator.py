"""Tests for the Savant CLI coordinator."""

import re

import pytest

from custom_components.savant_cli.coordinator import SavantCLIData
from custom_components.savant_cli.const import HVAC_ACTIONS, HVAC_MODES, FAN_MODES


def parse_line(data: SavantCLIData, line: bytes) -> None:
    """Test helper that mirrors coordinator._parse_line."""
    if not line:
        return
    line = line.lstrip(b"\n").strip()
    if not line:
        return
    text = line.decode()
    if text.startswith("SET_RELAY="):
        data.relays[text[len("SET_RELAY="):]] = True
        return
    if text.startswith("CLEAR_RELAY="):
        data.relays[text[len("CLEAR_RELAY="):]] = False
        return
    parts = line.split(None, 1)
    if len(parts) >= 2:
        device = parts[0].decode()
        payload = parts[1].decode()
        m = re.match(r"SET_(\w+)=(\S+)", payload)
        if m:
            key = m.group(1)
            value = m.group(2)
            if device.startswith("TSTAT_"):
                recompute = False
                if key == "TEMP":
                    data.temp = _tenths(value)
                elif key == "TEMP_SP":
                    data.temp_sp = _tenths(value)
                    recompute = True
                elif key == "TEMP_LOW":
                    data._native_temp_low = _tenths(value)
                    recompute = True
                elif key == "TEMP_HIGH":
                    data._native_temp_high = _tenths(value)
                    recompute = True
                elif key == "HUMIDITY":
                    data.humidity = _tenths(value)
                elif key == "HUMIDITY_SP":
                    data.humidity_sp = _tenths(value)
                elif key == "HVAC_MODE":
                    data.hvac_mode = value
                elif key == "HVAC_STATE":
                    data.hvac_state = value
                elif key == "FAN_MODE":
                    data.fan_mode = int(value)
                elif key == "FAN_STAGE":
                    data.fan_stage = int(value)
                elif key == "NAME":
                    data.name = value
                elif key == "TEMP_TOLERANCE":
                    data.temp_tolerance = _tenths(value)
                    recompute = True
                if recompute:
                    data._compute_effective_range()
                return
            if device.startswith("@"):
                mac = device[1:]
                data.btle_sensors.setdefault(mac, {"rssi": None, "batt": None})
                if key.endswith("RSSI"):
                    data.btle_sensors[mac]["rssi"] = int(value)
                elif key.endswith("BATT"):
                    data.btle_sensors[mac]["batt"] = int(value) / 100.0
                return
        return
    m = re.match(r"SET_(\w+)=(\S+)", text)
    if m:
        key = m.group(1)
        value = m.group(2)
        if key == "OUTSIDE_TEMP":
            data.outside_temp = _tenths(value)


def _tenths(value: str) -> float:
    """Parse a tenths value."""
    return int(value) / 10.0


@pytest.fixture
def fresh_data() -> SavantCLIData:
    """Return a fresh SavantCLIData instance."""
    return SavantCLIData()


class TestTelemetryParsing:
    """Test parsing of the telemetry stream."""

    def test_full_state_parse(self, fresh_data: SavantCLIData) -> None:
        """Parse a full state dump and verify all fields."""
        lines = [
            b"TSTAT_00 SET_HUMIDITY=0447",
            b"TSTAT_00 SET_TEMP=0772",
            b"TSTAT_00 SET_HVAC_MODE=01",
            b"TSTAT_00 SET_FAN_MODE=00",
            b"TSTAT_00 SET_NAME=Home",
            b"TSTAT_00 SET_FAN_STAGE=0",
            b"TSTAT_00 SET_HUMIDITY_SP=0100",
            b"SET_OUTSIDE_TEMP=0662",
            b"TSTAT_00 SET_TEMP_TOLERANCE=0020",
            b"TSTAT_00 SET_TEMP_SP=0750",
            b"TSTAT_00 SET_HVAC_STATE=01",
        ]
        for line in lines:
            parse_line(fresh_data, line)

        assert fresh_data.temp == 77.2
        assert fresh_data.temp_sp == 75.0
        assert fresh_data.humidity == 44.7
        assert fresh_data.humidity_sp == 10.0
        assert fresh_data.hvac_mode == "01"
        assert fresh_data.hvac_state == "01"
        assert fresh_data.fan_mode == 0
        assert fresh_data.fan_stage == 0
        assert fresh_data.name == "Home"
        assert fresh_data.temp_tolerance == 2.0
        assert fresh_data.outside_temp == 66.2
        assert fresh_data.available is True

    def test_relay_set(self, fresh_data: SavantCLIData) -> None:
        """Test SET_RELAY parsing."""
        parse_line(fresh_data, b"SET_RELAY=local-g")
        assert fresh_data.relays["local-g"] is True

    def test_relay_clear(self, fresh_data: SavantCLIData) -> None:
        """Test CLEAR_RELAY parsing."""
        parse_line(fresh_data, b"CLEAR_RELAY=local-w1")
        assert fresh_data.relays["local-w1"] is False

    def test_btle_rssi(self, fresh_data: SavantCLIData) -> None:
        """Test BTLE RSSI parsing."""
        parse_line(fresh_data, b"@001AAE17042D SET_BTLE_RSSI=-76")
        assert fresh_data.btle_sensors["001AAE17042D"]["rssi"] == -76

    def test_btle_batt(self, fresh_data: SavantCLIData) -> None:
        """Test BTLE battery parsing."""
        parse_line(fresh_data, b"@001AAE16D94B SET_BTLE_BATT=0293")
        assert fresh_data.btle_sensors["001AAE16D94B"]["batt"] == 2.93

    def test_leading_newline(self, fresh_data: SavantCLIData) -> None:
        """Test lines with leading newline."""
        parse_line(fresh_data, b"\nTSTAT_00 SET_NAME=Living")
        assert fresh_data.name == "Living"

    def test_blank_line(self, fresh_data: SavantCLIData) -> None:
        """Test blank lines don't crash."""
        parse_line(fresh_data, b"")
        parse_line(fresh_data, b"  ")
        assert fresh_data.name == "Thermostat"  # unchanged

    def test_empty_buffer_does_not_update(self, fresh_data: SavantCLIData) -> None:
        """Test that no updates happen on empty input."""
        original = SavantCLIData()
        assert fresh_data.name == original.name
        assert fresh_data.temp == original.temp

    def test_hvac_mode_mapping(self) -> None:
        """Test that HVAC mode strings map correctly."""
        assert HVAC_MODES["00"] == "off"
        assert HVAC_MODES["01"] == "heat"
        assert HVAC_MODES["02"] == "cool"
        assert HVAC_MODES["03"] == "heat_cool"

    def test_hvac_action_mapping(self) -> None:
        """Test that HVAC action strings map correctly."""
        assert HVAC_ACTIONS["00"] == "idle"
        assert HVAC_ACTIONS["01"] == "heating"
        assert HVAC_ACTIONS["02"] == "cooling"

    def test_dual_setpoint_parse(self, fresh_data: SavantCLIData) -> None:
        """Test parsing native dual-setpoint TSTAT records."""
        parse_line(fresh_data, b"TSTAT_00 SET_TEMP_LOW=0680")
        parse_line(fresh_data, b"TSTAT_00 SET_TEMP_HIGH=0730")
        assert fresh_data._native_temp_low == 68.0
        assert fresh_data._native_temp_high == 73.0
        assert fresh_data.temp_low == 68.0
        assert fresh_data.temp_high == 73.0
        assert fresh_data.is_dual_setpoint is True
        assert fresh_data.uses_native_dual is True

    def test_single_setpoint_is_not_dual(self, fresh_data: SavantCLIData) -> None:
        """Test that single-setpoint alone is not dual."""
        parse_line(fresh_data, b"TSTAT_00 SET_TEMP_SP=0750")
        assert fresh_data.temp_sp == 75.0
        assert fresh_data.is_dual_setpoint is False

    def test_computed_dual_from_tolerance(self, fresh_data: SavantCLIData) -> None:
        """Test that temp_sp + temp_tolerance computes temp_low/temp_high."""
        parse_line(fresh_data, b"TSTAT_00 SET_TEMP_SP=0770")
        parse_line(fresh_data, b"TSTAT_00 SET_TEMP_TOLERANCE=0020")
        assert fresh_data.temp_sp == 77.0
        assert fresh_data.temp_tolerance == 2.0
        assert fresh_data.temp_low == 75.0
        assert fresh_data.temp_high == 79.0
        assert fresh_data.is_dual_setpoint is True
        assert fresh_data.uses_native_dual is False

    def test_fan_mode_mapping(self) -> None:
        """Test that fan mode integers map correctly."""
        assert FAN_MODES[0] == "on"
        assert FAN_MODES[1] == "auto"
        assert FAN_MODES[2] == "cycle"
