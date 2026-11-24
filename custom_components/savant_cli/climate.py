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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import area_registry as ar
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
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Savant CLI climate entities from a config entry."""
    coordinator: SavantCLICoordinator = hass.data[DOMAIN][entry.entry_id]
    configured = entry.data.get("zones", {})
    for zone_id, config in configured.items():
        if zone_id not in coordinator.zones:
            coordinator.zones[zone_id] = (
                coordinator._data if zone_id == "TSTAT_00" else SavantCLIData()
            )
        if config.get("name") and coordinator.zones[zone_id].name == "Thermostat":
            coordinator.zones[zone_id].name = config["name"]

    registry = er.async_get(hass)
    added: set[str] = set()

    def add_zones() -> None:
        entities = []
        for zone_id in coordinator.zones:
            if zone_id in added:
                continue
            entity = SavantCLIClimate(coordinator, zone_id)
            entity._configured_name = configured.get(zone_id, {}).get("name")
            if registry.async_get_entity_id("climate", DOMAIN, entity.unique_id) is None:
                entity._initial_area_id = configured.get(zone_id, {}).get("area_id")
            added.add(zone_id)
            entities.append(entity)
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(add_zones))
    add_zones()


class SavantCLIClimate(ClimateEntity):
    """Climate entity for the Savant CLI thermostat."""

    _attr_has_entity_name = False
    _attr_name = None
    _attr_should_poll = False
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_hvac_modes = [HVACMode.HEAT_COOL, HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF]
    _attr_fan_modes = list(FAN_MODES.values())
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 40
    _attr_max_temp = 95

    def __init__(
        self, coordinator: SavantCLICoordinator, zone: str = "TSTAT_00"
    ) -> None:
        """Initialize the climate entity."""
        self.coordinator = coordinator
        self.zone = zone
        self._initial_area_id: str | None = None
        self._configured_name: str | None = None
        self._attr_unique_id = f"cli_climate_{coordinator.host}"
        if zone != "TSTAT_00":
            self._attr_unique_id += f"_{zone}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.host)},
            "name": "Savant CLI Thermostat",
            "manufacturer": "Racepoint Energy (Savant)",
            "model": "CLI-W200/CLI-W220",
        }

    @property
    def data(self) -> SavantCLIData:
        """Return parsed thermostat data."""
        if self.zone == "TSTAT_00":
            return self.coordinator._data
        return self.coordinator.zones[self.zone]

    @property
    def name(self) -> str:
        """Use the zone name without a shared controller name prefix."""
        return self._configured_name or (
            self.data.name if self.data.name != "Thermostat" else self.zone
        )

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
        return self.coordinator._data.available

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
        await super().async_added_to_hass()
        if (
            self._initial_area_id is not None
            and ar.async_get(self.hass).async_get_area(self._initial_area_id) is not None
        ):
            er.async_get(self.hass).async_update_entity(
                self.entity_id, area_id=self._initial_area_id
            )
            self._initial_area_id = None
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
                await self.coordinator.send_command(f"{self.zone} SET_TEMP_LOW={tenths:04d}")
            if high is not None:
                tenths = int(round(high * 10))
                await self.coordinator.send_command(f"{self.zone} SET_TEMP_HIGH={tenths:04d}")
        elif self.data.is_dual_setpoint:
            low = kwargs.get("target_temp_low")
            high = kwargs.get("target_temp_high")
            if low is not None and high is not None:
                center = round((low + high) / 2, 1)
                tolerance = round((high - low) / 2, 1)
                await self.coordinator.send_command(
                    f"{self.zone} SET_TEMP_SP={int(round(center * 10)):04d}"
                )
                await self.coordinator.send_command(
                    f"{self.zone} SET_TEMP_TOLERANCE={int(round(tolerance * 10)):04d}"
                )
            elif low is not None and self.data.temp_tolerance is not None:
                center = round(low + self.data.temp_tolerance, 1)
                await self.coordinator.send_command(
                    f"{self.zone} SET_TEMP_SP={int(round(center * 10)):04d}"
                )
            elif high is not None and self.data.temp_tolerance is not None:
                center = round(high - self.data.temp_tolerance, 1)
                await self.coordinator.send_command(
                    f"{self.zone} SET_TEMP_SP={int(round(center * 10)):04d}"
                )
        else:
            if ATTR_TEMPERATURE not in kwargs:
                return
            temp = kwargs[ATTR_TEMPERATURE]
            tenths = int(round(temp * 10))
            await self.coordinator.send_command(f"{self.zone} SET_TEMP_SP={tenths:04d}")

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set a new HVAC mode."""
        mode_map = {"off": "00", "heat": "01", "cool": "02", "heat_cool": "03"}
        mode = mode_map.get(hvac_mode, "01")
        await self.coordinator.send_command(f"{self.zone} SET_HVAC_MODE={mode}")

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set a new fan mode."""
        mode_val = FAN_MODE_REVERSE.get(fan_mode, 0)
        await self.coordinator.send_command(f"{self.zone} SET_FAN_MODE={mode_val:02d}")
