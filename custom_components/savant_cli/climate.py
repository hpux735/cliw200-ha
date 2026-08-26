"""Climate platform for the Savant CLI-W200/CLI-W220 thermostat."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    FAN_MODES,
    FAN_MODE_REVERSE,
    HVAC_ACTIONS,
    HVAC_MODES,
)
from .coordinator import SavantCLICoordinator, SavantCLIData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Savant CLI climate entities from a config entry."""
    coordinator: SavantCLICoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SavantCLIClimate(coordinator)])


class SavantCLIClimate(ClimateEntity):
    """Climate entity for the Savant CLI thermostat."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_parallel_updates = 0
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_hvac_modes = [HVACMode.HEAT_COOL, HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF]
    _attr_fan_modes = list(FAN_MODES.values())
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 40
    _attr_max_temp = 95

    def __init__(self, coordinator: SavantCLICoordinator) -> None:
        """Initialize the climate entity."""
        self.coordinator = coordinator
        self._attr_unique_id = f"cli_climate_{coordinator.host}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.host)},
            "name": "Savant CLI Thermostat",
            "manufacturer": "Racepoint Energy (Savant)",
            "model": "CLI-W200/CLI-W220",
        }

    @property
    def data(self) -> SavantCLIData:
        """Return parsed thermostat data."""
        return self.coordinator._data

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return supported features."""
        features = (
            ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        if self.data.is_dual_setpoint:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        else:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        return features

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        return self.data.available

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.data.temp

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature (single-setpoint only)."""
        if self.data.is_dual_setpoint:
            return None
        return self.data.temp_sp

    @property
    def target_temperature_low(self) -> float | None:
        """Return the low target temperature (dual-setpoint, heat)."""
        if self.data.is_dual_setpoint:
            return self.data.temp_low
        return None

    @property
    def target_temperature_high(self) -> float | None:
        """Return the high target temperature (dual-setpoint, cool)."""
        if self.data.is_dual_setpoint:
            return self.data.temp_high
        return None

    @property
    def current_humidity(self) -> float | None:
        """Return the current humidity."""
        return self.data.humidity

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the current HVAC mode."""
        mode = self.data.hvac_mode
        if mode == "00":
            return HVACMode.OFF
        ha_mode = HVAC_MODES.get(mode, "off")
        return HVACMode(ha_mode)

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current HVAC action."""
        if self.data.hvac_mode == "00":
            return HVACAction.OFF
        action = HVAC_ACTIONS.get(self.data.hvac_state, "idle")
        return HVACAction(action)

    @property
    def fan_mode(self) -> str | None:
        """Return the current fan mode."""
        return FAN_MODES.get(self.data.fan_mode, "auto")

    async def async_added_to_hass(self) -> None:
        """Register for coordinator updates."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature(s)."""
        if self.data.is_dual_setpoint and self.data.uses_native_dual:
            low = kwargs.get("target_temp_low")
            high = kwargs.get("target_temp_high")
            if low is not None:
                tenths = int(round(low * 10))
                await self.coordinator.send_command(f"TSTAT_00 SET_TEMP_LOW={tenths:04d}")
            if high is not None:
                tenths = int(round(high * 10))
                await self.coordinator.send_command(f"TSTAT_00 SET_TEMP_HIGH={tenths:04d}")
        elif self.data.is_dual_setpoint:
            low = kwargs.get("target_temp_low")
            high = kwargs.get("target_temp_high")
            if low is not None and high is not None:
                center = round((low + high) / 2, 1)
                tolerance = round((high - low) / 2, 1)
                await self.coordinator.send_command(
                    f"TSTAT_00 SET_TEMP_SP={int(round(center * 10)):04d}"
                )
                await self.coordinator.send_command(
                    f"TSTAT_00 SET_TEMP_TOLERANCE={int(round(tolerance * 10)):04d}"
                )
            elif low is not None and self.data.temp_tolerance is not None:
                center = round(low + self.data.temp_tolerance, 1)
                await self.coordinator.send_command(
                    f"TSTAT_00 SET_TEMP_SP={int(round(center * 10)):04d}"
                )
            elif high is not None and self.data.temp_tolerance is not None:
                center = round(high - self.data.temp_tolerance, 1)
                await self.coordinator.send_command(
                    f"TSTAT_00 SET_TEMP_SP={int(round(center * 10)):04d}"
                )
        else:
            if ATTR_TEMPERATURE not in kwargs:
                return
            temp = kwargs[ATTR_TEMPERATURE]
            tenths = int(round(temp * 10))
            await self.coordinator.send_command(f"TSTAT_00 SET_TEMP_SP={tenths:04d}")

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set a new HVAC mode."""
        mode_map = {"off": "00", "heat": "01", "cool": "02", "heat_cool": "03"}
        mode = mode_map.get(hvac_mode, "01")
        await self.coordinator.send_command(f"TSTAT_00 SET_HVAC_MODE={mode}")

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set a new fan mode."""
        mode_val = FAN_MODE_REVERSE.get(fan_mode, 0)
        await self.coordinator.send_command(f"TSTAT_00 SET_FAN_MODE={mode_val:02d}")
