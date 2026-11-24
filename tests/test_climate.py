"""Tests for the Savant CLI climate entity."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from homeassistant.components.climate import ClimateEntityFeature

from custom_components.savant_cli.climate import SavantCLIClimate
from custom_components.savant_cli.coordinator import SavantCLIData


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Return a mock coordinator with preset data."""
    coordinator = MagicMock()
    data = SavantCLIData()
    data.temp = 77.2
    data.temp_sp = 75.0
    data.humidity = 44.7
    data.hvac_mode = "01"
    data.hvac_state = "00"
    data.fan_mode = 0
    data.name = "Home"
    data.available = True
    coordinator._data = data
    coordinator.host = "192.168.3.45"
    coordinator.send_command = AsyncMock()
    return coordinator


class TestSavantCLIClimate:
    """Test the climate entity."""

    def setup_method(self) -> None:
        self.coordinator = MagicMock()
        self.data = SavantCLIData()
        self.data.temp = 77.2
        self.data.temp_sp = 75.0
        self.data.humidity = 44.7
        self.data.hvac_mode = "01"
        self.data.hvac_state = "00"
        self.data.fan_mode = 0
        self.data.name = "Home"
        self.data.available = True
        self.coordinator._data = self.data
        self.coordinator.host = "192.168.3.45"
        self.coordinator.send_command = AsyncMock()

        # Patch the entity to provide unique_id and device_info (normally from HA base class)
        SavantCLIClimate.unique_id = PropertyMock()
        SavantCLIClimate.device_info = PropertyMock()
        self.climate = SavantCLIClimate(self.coordinator)
        # Restore normal behavior
        type(self.climate).unique_id = property(lambda self: self._attr_unique_id)
        type(self.climate).device_info = property(lambda self: self._attr_device_info)

    def _climate(self) -> SavantCLIClimate:
        return self.climate

    def test_current_temperature(self) -> None:
        assert self._climate().current_temperature == 77.2

    def test_target_temperature(self) -> None:
        assert self._climate().target_temperature == 75.0

    def test_current_humidity(self) -> None:
        assert self._climate().current_humidity == 44.7

    def test_hvac_mode_heat(self) -> None:
        assert self._climate().hvac_mode == "heat"

    def test_hvac_mode_off(self) -> None:
        self.data.hvac_mode = "00"
        assert self._climate().hvac_mode == "off"

    def test_hvac_mode_cool(self) -> None:
        self.data.hvac_mode = "02"
        assert self._climate().hvac_mode == "cool"

    def test_hvac_mode_heat_cool(self) -> None:
        self.data.hvac_mode = "03"
        assert self._climate().hvac_mode == "heat_cool"

    def test_hvac_action_heating(self) -> None:
        self.data.hvac_state = "03"
        assert self._climate().hvac_action == "heating"

    def test_hvac_action_fan_only(self) -> None:
        self.data.hvac_state = "01"
        assert self._climate().hvac_action == "fan"

    def test_hvac_action_unknown(self) -> None:
        self.data.hvac_state = "99"
        assert self._climate().hvac_action is None

    def test_hvac_action_cooling(self) -> None:
        self.data.hvac_state = "02"
        assert self._climate().hvac_action == "cooling"

    def test_hvac_action_idle(self) -> None:
        self.data.hvac_state = "00"
        assert self._climate().hvac_action == "idle"

    def test_hvac_action_off(self) -> None:
        self.data.hvac_mode = "00"
        assert self._climate().hvac_action == "off"

    def test_fan_mode_on(self) -> None:
        self.data.fan_mode = 0
        assert self._climate().fan_mode == "on"

    def test_fan_mode_auto(self) -> None:
        self.data.fan_mode = 1
        assert self._climate().fan_mode == "auto"

    def test_fan_mode_cycle(self) -> None:
        self.data.fan_mode = 2
        assert self._climate().fan_mode == "cycle"

    def test_available(self) -> None:
        assert self._climate().available is True

    def test_unavailable(self) -> None:
        self.data.available = False
        assert self._climate().available is False

    def test_set_temperature(self) -> None:
        async def go():
            await self._climate().async_set_temperature(**{"temperature": 76.5})
        asyncio.run(go())
        self.coordinator.send_command.assert_called_once_with(
            "TSTAT_00 SET_TEMP_SP=0765"
        )

    def test_set_temperature_rounds(self) -> None:
        async def go():
            await self._climate().async_set_temperature(**{"temperature": 76.54})
        asyncio.run(go())
        self.coordinator.send_command.assert_called_once_with(
            "TSTAT_00 SET_TEMP_SP=0765"
        )

    def test_set_hvac_mode_off(self) -> None:
        async def go():
            await self._climate().async_set_hvac_mode("off")
        asyncio.run(go())
        self.coordinator.send_command.assert_called_once_with(
            "TSTAT_00 SET_HVAC_MODE=00"
        )

    def test_set_hvac_mode_heat(self) -> None:
        async def go():
            await self._climate().async_set_hvac_mode("heat")
        asyncio.run(go())
        self.coordinator.send_command.assert_called_once_with(
            "TSTAT_00 SET_HVAC_MODE=01"
        )

    def test_set_hvac_mode_cool(self) -> None:
        async def go():
            await self._climate().async_set_hvac_mode("cool")
        asyncio.run(go())
        self.coordinator.send_command.assert_called_once_with(
            "TSTAT_00 SET_HVAC_MODE=02"
        )

    def test_set_hvac_mode_heat_cool(self) -> None:
        async def go():
            await self._climate().async_set_hvac_mode("heat_cool")
        asyncio.run(go())
        self.coordinator.send_command.assert_called_once_with(
            "TSTAT_00 SET_HVAC_MODE=03"
        )

    def test_set_fan_mode_auto(self) -> None:
        async def go():
            await self._climate().async_set_fan_mode("auto")
        asyncio.run(go())
        self.coordinator.send_command.assert_called_once_with(
            "TSTAT_00 SET_FAN_MODE=01"
        )

    def test_set_fan_mode_on(self) -> None:
        async def go():
            await self._climate().async_set_fan_mode("on")
        asyncio.run(go())
        self.coordinator.send_command.assert_called_once_with(
            "TSTAT_00 SET_FAN_MODE=00"
        )

    def test_set_fan_mode_cycle(self) -> None:
        async def go():
            await self._climate().async_set_fan_mode("cycle")
        asyncio.run(go())
        self.coordinator.send_command.assert_called_once_with(
            "TSTAT_00 SET_FAN_MODE=02"
        )

    def test_unique_id(self) -> None:
        assert self._climate().unique_id == "cli_climate_192.168.3.45"

    def test_device_info(self) -> None:
        info = self._climate().device_info
        assert info["manufacturer"] == "Racepoint Energy (Savant)"

    def test_dual_setpoint_target_temperature_returns_none(self) -> None:
        self.data.temp_low = 68.0
        self.data.temp_high = 73.0
        assert self._climate().target_temperature is None

    def test_dual_setpoint_low_high(self) -> None:
        self.data.temp_low = 68.0
        self.data.temp_high = 73.0
        climate = self._climate()
        assert climate.target_temperature_low == 68.0
        assert climate.target_temperature_high == 73.0

    def test_dual_setpoint_features(self) -> None:
        self.data.temp_low = 68.0
        self.data.temp_high = 73.0
        features = self._climate().supported_features
        assert features & ClimateEntityFeature.TARGET_TEMPERATURE_RANGE

    def test_single_setpoint_features(self) -> None:
        self.data.temp_sp = 75.0
        features = self._climate().supported_features
        assert features & ClimateEntityFeature.TARGET_TEMPERATURE

    def test_set_dual_temperature_native(self) -> None:
        self.data._native_temp_low = 70.0
        self.data._native_temp_high = 76.0
        self.data.temp_low = 70.0
        self.data.temp_high = 76.0

        async def go():
            await self._climate().async_set_temperature(
                target_temp_low=66.0, target_temp_high=74.0
            )
        asyncio.run(go())
        assert self.coordinator.send_command.call_count == 2
        self.coordinator.send_command.assert_any_call(
            "TSTAT_00 SET_TEMP_LOW=0660"
        )
        self.coordinator.send_command.assert_any_call(
            "TSTAT_00 SET_TEMP_HIGH=0740"
        )

    def test_set_dual_temperature_computed(self) -> None:
        self.data.hvac_mode = "03"
        self.data.temp_sp = 77.0
        self.data.temp_tolerance = 2.0
        self.data.temp_low = 75.0
        self.data.temp_high = 79.0

        async def go():
            await self._climate().async_set_temperature(
                target_temp_low=74.0, target_temp_high=80.0
            )
        asyncio.run(go())
        assert self.coordinator.send_command.call_count == 2
        self.coordinator.send_command.assert_any_call("TSTAT_00 SET_TEMP_SP=0770")
        self.coordinator.send_command.assert_any_call(
            "TSTAT_00 SET_TEMP_TOLERANCE=0030"
        )
