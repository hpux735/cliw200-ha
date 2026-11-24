"""Multi-zone regressions using the production telemetry parser."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.savant_cli.climate import (
    PARALLEL_UPDATES,
    SavantCLIClimate,
    async_setup_entry,
)
from custom_components.savant_cli.const import DOMAIN
from custom_components.savant_cli.coordinator import SavantCLICoordinator


@pytest.fixture
def coordinator(mock_hass):
    """Create a real coordinator without opening a connection."""
    instance = SavantCLICoordinator(mock_hass, "controller.test")
    instance.send_command = AsyncMock()
    return instance


def test_zone_isolation_and_controller_state(coordinator):
    assert coordinator.zones == {}
    for line in (
        b"TSTAT_01 SET_TEMP=0685",
        b"TSTAT_01 SET_NAME=Main Bedroom Suite",
        b"TSTAT_01 SET_HUMIDITY=0450",
        b"TSTAT_01 SET_HVAC_MODE=02",
        b"TSTAT_01 SET_HVAC_STATE=02",
        b"TSTAT_01 SET_FAN_MODE=02",
        b"TSTAT_00 SET_TEMP=0720",
        b"TSTAT_00 SET_NAME=Living Room",
        b"SET_OUTSIDE_TEMP=0500",
        b"SET_RELAY=local-g",
        b"@001AAE17042D SET_BTLE_RSSI=-76",
    ):
        coordinator._parse_line(line)
    assert coordinator.zones["TSTAT_00"] is coordinator._data
    first = SavantCLIClimate(coordinator)
    second = SavantCLIClimate(coordinator, "TSTAT_01")
    assert first.current_temperature == 72
    assert second.current_temperature == 68.5
    assert first.name == "Living Room"
    assert second.name == "Main Bedroom Suite"
    assert second.current_humidity == 45
    assert second.hvac_mode == "cool"
    assert second.hvac_action == "cooling"
    assert second.fan_mode == "cycle"
    assert first.unique_id == "cli_climate_controller.test"
    assert second.unique_id == "cli_climate_controller.test_TSTAT_01"
    assert first.device_info == second.device_info
    assert coordinator._data.outside_temp == 50
    assert coordinator._data.relays == {"local-g": True}
    assert coordinator._data.btle_sensors["001AAE17042D"]["rssi"] == -76
    assert second.data.outside_temp is None
    coordinator._data.available = False
    assert not first.available
    assert not second.available
    coordinator._data.available = True
    assert first.available and second.available
    assert PARALLEL_UPDATES == 0
    assert first.should_poll is False


@pytest.mark.parametrize("mode", ["00", "01", "02"])
def test_mode_switch_recomputes_only_own_range(coordinator, mode):
    for zone in ("TSTAT_00", "TSTAT_02"):
        for record in ("TEMP_SP=0720", "TEMP_TOLERANCE=0020", "HVAC_MODE=03"):
            coordinator._parse_line(f"{zone} SET_{record}".encode())
    entity = SavantCLIClimate(coordinator, "TSTAT_02")
    assert entity.target_temperature_low == 70
    coordinator._parse_line(f"TSTAT_02 SET_HVAC_MODE={mode}".encode())
    assert entity.target_temperature_low is None
    assert entity.target_temperature_high is None
    assert entity.target_temperature == 72
    assert coordinator._data.temp_low == 70
    coordinator._parse_line(b"TSTAT_02 SET_HVAC_MODE=03")
    assert entity.target_temperature_low == 70
    assert entity.target_temperature_high == 74


def test_native_range_survives_mode_switch(coordinator):
    for record in ("TEMP_LOW=0680", "TEMP_HIGH=0760", "HVAC_MODE=01"):
        coordinator._parse_line(f"TSTAT_03 SET_{record}".encode())
    entity = SavantCLIClimate(coordinator, "TSTAT_03")
    assert entity.target_temperature_low == 68
    assert entity.target_temperature_high == 76


@pytest.mark.parametrize(
    ("records", "kwargs", "commands"),
    [
        ([], {"temperature": 71.5}, ["SET_TEMP_SP=0715"]),
        (["TEMP_LOW=0680", "TEMP_HIGH=0760"],
         {"target_temp_low": 69, "target_temp_high": 75},
         ["SET_TEMP_LOW=0690", "SET_TEMP_HIGH=0750"]),
        (["TEMP_SP=0720", "TEMP_TOLERANCE=0020", "HVAC_MODE=03"],
         {"target_temp_low": 69, "target_temp_high": 75},
         ["SET_TEMP_SP=0720", "SET_TEMP_TOLERANCE=0030"]),
        (["TEMP_SP=0720", "TEMP_TOLERANCE=0020", "HVAC_MODE=03"],
         {"target_temp_low": 69}, ["SET_TEMP_SP=0710"]),
        (["TEMP_SP=0720", "TEMP_TOLERANCE=0020", "HVAC_MODE=03"],
         {"target_temp_high": 75}, ["SET_TEMP_SP=0730"]),
    ],
)
def test_commands_target_entity_zone(coordinator, records, kwargs, commands):
    coordinator._parse_line(b"TSTAT_04 SET_NAME=Office")
    for record in records:
        coordinator._parse_line(f"TSTAT_04 SET_{record}".encode())
    entity = SavantCLIClimate(coordinator, "TSTAT_04")

    async def run():
        await entity.async_set_temperature(**kwargs)
        await entity.async_set_hvac_mode("cool")
        await entity.async_set_fan_mode("auto")

    asyncio.run(run())
    assert coordinator.send_command.call_args_list == [
        call(f"TSTAT_04 {command}")
        for command in commands + ["SET_HVAC_MODE=02", "SET_FAN_MODE=01"]
    ]


@pytest.mark.asyncio
async def test_platform_discovery_config_names_and_area_once(coordinator, mock_hass):
    entry = MagicMock()
    entry.entry_id = "entry"
    entry.data = {"zones": {"TSTAT_05": {"name": "Guest Suite", "area_id": "guest"}}}
    mock_hass.data = {DOMAIN: {entry.entry_id: coordinator}}
    added = []
    registry = MagicMock()
    registry.async_get_entity_id.return_value = None
    # Exercise coordinator notifications without scheduling HA debounced refreshes.
    listeners = []
    coordinator.async_add_listener = lambda listener: listeners.append(listener) or MagicMock()
    coordinator.async_set_updated_data = lambda data: [listener() for listener in list(listeners)]
    with patch("custom_components.savant_cli.climate.er.async_get", return_value=registry), patch(
        "custom_components.savant_cli.climate.ar.async_get"
    ) as areas:
        areas.return_value.async_get_area.return_value = MagicMock(id="guest")
        await async_setup_entry(mock_hass, entry, added.extend)
        assert [entity.zone for entity in added] == ["TSTAT_05"]
        entity = added[0]
        assert entity.name == "Guest Suite"
        entity.hass = mock_hass
        entity.entity_id = "climate.guest_suite"
        entity.async_on_remove = MagicMock()
        entity.async_write_ha_state = MagicMock()
        await entity.async_added_to_hass()
        areas.return_value.async_get_area.assert_called_once_with("guest")
        registry.async_update_entity.assert_called_once_with(
            "climate.guest_suite", area_id="guest"
        )
        await entity.async_added_to_hass()
        assert registry.async_update_entity.call_count == 1
        coordinator._parse_line(b"TSTAT_06 SET_NAME=Upstairs Office")
        coordinator._parse_line(b"TSTAT_06 SET_TEMP=0700")
        assert [entity.zone for entity in added] == ["TSTAT_05", "TSTAT_06"]
        assert added[1].name == "Upstairs Office"
        coordinator._parse_line(b"TSTAT_05 SET_NAME=Guest Bedroom")
        assert entity.name == "Guest Suite"
        assert entity.data.name == "Guest Bedroom"
        # An existing registry entry may have a user-selected or cleared area.
        registry.async_get_entity_id.return_value = "climate.guest_suite"
        reloaded = []
        await async_setup_entry(mock_hass, entry, reloaded.extend)
        assert all(entity._initial_area_id is None for entity in reloaded)
    coordinator.send_command.assert_not_called()
    assert "TSTAT_00" not in coordinator.zones
    entry.async_on_unload.assert_called()


@pytest.mark.asyncio
async def test_empty_platform_waits_for_observed_zone(coordinator, mock_hass):
    entry = MagicMock(data={})
    mock_hass.data = {DOMAIN: {entry.entry_id: coordinator}}
    add = MagicMock()
    with patch("custom_components.savant_cli.climate.er.async_get"):
        await async_setup_entry(mock_hass, entry, add)
    add.assert_not_called()
    coordinator.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_configured_zone_zero_uses_legacy_data(coordinator, mock_hass):
    entry = MagicMock(data={"zones": {"TSTAT_00": {"name": "Main Floor"}}})
    mock_hass.data = {DOMAIN: {entry.entry_id: coordinator}}
    added = []
    with patch("custom_components.savant_cli.climate.er.async_get"):
        await async_setup_entry(mock_hass, entry, added.extend)
    assert coordinator.zones["TSTAT_00"] is coordinator._data
    assert added[0].name == "Main Floor"
    coordinator._parse_line(b"TSTAT_00 SET_TEMP=0710")
    assert added[0].current_temperature == 71


@pytest.mark.asyncio
async def test_observed_zones_added_without_overwriting_telemetry(coordinator, mock_hass):
    coordinator._parse_line(b"TSTAT_07 SET_NAME=Live Zone Name")
    coordinator._parse_line(b"TSTAT_08 SET_TEMP=0730")
    entry = MagicMock(data={"zones": {
        "TSTAT_07": {"name": "Stored Name"},
        "TSTAT_08": {"name": "Stored Zone Name"},
    }})
    mock_hass.data = {DOMAIN: {entry.entry_id: coordinator}}
    added = []
    with patch("custom_components.savant_cli.climate.er.async_get"):
        await async_setup_entry(mock_hass, entry, added.extend)
    assert [entity.zone for entity in added] == ["TSTAT_07", "TSTAT_08"]
    assert [entity.name for entity in added] == ["Stored Name", "Stored Zone Name"]
    assert coordinator.zones["TSTAT_07"].name == "Live Zone Name"
    coordinator._parse_line(b"TSTAT_07 SET_NAME=Updated Live Name")
    assert added[0].name == "Stored Name"
    assert added[0].data.name == "Updated Live Name"
    assert added[1].current_temperature == 73
    coordinator.send_command.assert_not_called()
