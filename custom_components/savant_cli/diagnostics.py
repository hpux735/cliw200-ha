"""Diagnostics support for the Savant CLI integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import SavantCLICoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: SavantCLICoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator._data
    return {
        "host": coordinator.host,
        "port": coordinator.port,
        "available": data.available,
        "temperature": data.temp,
        "target_temperature": data.temp_sp,
        "humidity": data.humidity,
        "hvac_mode": data.hvac_mode,
        "hvac_state": data.hvac_state,
        "fan_mode": data.fan_mode,
        "fan_stage": data.fan_stage,
        "name": data.name,
        "outside_temp": data.outside_temp,
        "relays": data.relays,
        "btle_sensors": data.btle_sensors,
    }
