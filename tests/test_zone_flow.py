"""Zone setup tests against Home Assistant, with all TCP access mocked."""

import asyncio
from ipaddress import ip_address
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import voluptuous as vol

from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.savant_cli import config_flow as cf
from custom_components.savant_cli.climate import async_setup_entry
from custom_components.savant_cli.const import DOMAIN
from custom_components.savant_cli.coordinator import SavantCLICoordinator


@pytest_asyncio.fixture
async def ha(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = ConfigEntries(hass, {})
    await ar.async_load(hass)
    await dr.async_load(hass)
    await er.async_load(hass)
    yield hass
    await hass.async_stop()


def make_flow(ha, source="user"):
    flow = cf.SavantCLIConfigFlow()
    flow.hass = ha
    flow.handler = DOMAIN
    flow.context = {"source": source}
    flow.init_step = source
    return flow


def socket_with(*chunks, eof=True):
    reader = asyncio.StreamReader()
    for chunk in chunks:
        reader.feed_data(chunk)
    if eof:
        reader.feed_eof()
    writer = MagicMock()
    writer.wait_closed = AsyncMock()
    return reader, writer


async def finish_discovery(flow):
    await flow._discovery_task
    if flow._progress_task is None:
        return await flow.async_step_zone_area()
    await flow._progress_task
    result = await flow.async_step_discover()
    assert result["type"] == FlowResultType.SHOW_PROGRESS_DONE
    return await getattr(flow, f"async_step_{result['step_id']}")()


@pytest.mark.parametrize("port", [0, -1, 65536, "abc"])
def test_port_bounds(port):
    with pytest.raises(vol.Invalid):
        cf._STEP_USER_SCHEMA({"host": "example.test", "port": port})


def test_helpers():
    assert cf._is_cli_model({"mn": "CLI-W220W-00"})
    assert not cf._is_cli_model({"mn": "SEM-2016"})
    assert cf._is_ipv4(ip_address("192.0.2.49"))
    assert not cf._is_ipv4("::1")
    assert cf._discovery_host(SimpleNamespace(
        ip_addresses=[ip_address("::1"), ip_address("192.0.2.49")]
    )) == "192.0.2.49"


@pytest.mark.asyncio
async def test_passive_parser_and_socket_close(ha):
    reader, writer = socket_with(
        b"@abcdef SET_BTLE_BATT=0293\r\nSET_RELAY=local-g\r\n",
        b"TSTAT_01 SET_NAME=Upstairs Bedroom\r",
        b"\nTSTAT_00 SET_TEMP=0700\r\nTSTAT_01 SET_NAME=Bedroom\r\n",
        b"TSTAT_04 SET_NAME=Thermostat\r\n",
        b"TSTAT_02 SET_NAME=\xff\r\nTSTAT_03 SET_NAME=incomplete",
    )
    with patch.object(cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))), patch.object(
        cf.SavantCLICoordinator, "_connect", AsyncMock()
    ) as connect:
        result = await cf._discover_zones(ha, "example.test", 2000)
    assert result == {"TSTAT_00": {"name": "TSTAT_00"}, "TSTAT_01": {"name": "Bedroom"}, "TSTAT_04": {"name": "Thermostat"}}
    connect.assert_not_called()
    writer.write.assert_not_called()
    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()


@pytest.mark.asyncio
async def test_collects_full_window_and_late_zone(ha):
    reader, writer = socket_with(b"TSTAT_00 SET_NAME=Home\r\n", eof=False)
    with patch.object(cf, "DISCOVERY_SECONDS", 0.05), patch.object(
        cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))
    ):
        task = asyncio.create_task(cf._discover_zones(ha, "example.test", 2000))
        await asyncio.sleep(0.01)
        assert not task.done()
        reader.feed_data(b"TSTAT_01 SET_NAME=Late Zone\r\n")
        result = await task
    assert result["TSTAT_01"]["name"] == "Late Zone"
    writer.close.assert_called_once()


@pytest.mark.parametrize("error", [OSError("unreachable"), TimeoutError()])
@pytest.mark.asyncio
async def test_connection_errors(ha, error):
    with patch.object(cf.asyncio, "open_connection", AsyncMock(side_effect=error)):
        with pytest.raises(type(error)):
            await cf._discover_zones(ha, "example.test", 2000)


@pytest.mark.asyncio
async def test_connection_deadline(ha):
    async def hang(*args):
        await asyncio.Future()

    with patch.object(cf, "DISCOVERY_SECONDS", 0.01), patch.object(
        cf.asyncio, "open_connection", hang
    ):
        with pytest.raises(TimeoutError):
            await cf._discover_zones(ha, "example.test", 2000)


@pytest.mark.asyncio
async def test_cancel_closes_socket(ha):
    reader, writer = socket_with(eof=False)
    started = asyncio.Event()

    async def opened(*args):
        started.set()
        return reader, writer

    with patch.object(cf.asyncio, "open_connection", opened):
        task = asyncio.create_task(cf._discover_zones(ha, "example.test", 2000))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeated_zone_area_and_deleted_area(ha):
    area = ar.async_get(ha).async_create("Bedroom")
    assigned_area = ar.async_get(ha).async_create("Downstairs")
    flow = make_flow(ha)
    zones = {"TSTAT_00": {"name": "Home"}, "TSTAT_01": {"name": "Bedroom"}}
    with patch.object(cf, "_discover_zones", AsyncMock(return_value=zones)) as discover:
        result = await flow.async_step_user({"host": "192.0.2.49", "port": 2000})
        assert result["type"] == FlowResultType.SHOW_PROGRESS
        assert result["progress_task"] is flow._progress_task
        assert result["progress_task"] is not flow._discovery_task
        result = await finish_discovery(flow)
        discover.assert_awaited_once_with(ha, "192.0.2.49", 2000, flow._zone_discovered)
    assert result["description_placeholders"] == {"zone_id": "TSTAT_00"}
    assert result["data_schema"]({}) == {"name": "Home", "finish_setup": False}
    assert flow.unique_id == "cli_192.0.2.49"
    result = await flow.async_step_zone_area({"name": "  Downstairs  ", "area_id": assigned_area.id})
    assert result["description_placeholders"] == {"zone_id": "TSTAT_01"}
    # The selector can submit a stale ID after an area is deleted elsewhere.
    ar.async_get(ha).areas.pop(area.id)
    result = await flow.async_step_zone_area({"name": "Bedroom", "area_id": area.id})
    assert result["errors"] == {"area_id": "invalid_area"}
    result = await flow.async_step_zone_area({"name": " "})
    assert result["errors"] == {"name": "invalid_name"}
    result = await flow.async_step_zone_area({"name": "Bedroom"})
    assert result["type"] == "create_entry"
    assert result["data"]["zones"] == {
        "TSTAT_00": {"name": "Downstairs", "area_id": assigned_area.id},
        "TSTAT_01": {"name": "Bedroom"},
    }
    assert list(ar.async_get(ha).async_list_areas()) == [assigned_area]


@pytest.mark.parametrize("discovered,error", [({}, "no_zones"), (OSError(), "cannot_connect"), (TimeoutError(), "cannot_connect")])
@pytest.mark.asyncio
async def test_discovery_error_and_retry(ha, discovered, error):
    flow = make_flow(ha)
    mock = AsyncMock(**({"side_effect": discovered} if isinstance(discovered, Exception) else {"return_value": discovered}))
    with patch.object(cf, "_discover_zones", mock):
        await flow.async_step_user({"host": "example.test", "port": 2000})
        try:
            await flow._discovery_task
        except (OSError, TimeoutError):
            pass
        await flow._progress_task
        result = await flow.async_step_discover()
        assert result["step_id"] == "discovery_error"
        result = await flow.async_step_discovery_error()
        assert result["errors"] == {"base": error}
        old_task = flow._discovery_task
        result = await flow.async_step_discovery_error({})
        assert result["type"] == FlowResultType.SHOW_PROGRESS
        assert flow._discovery_task is not old_task
        try:
            await flow._discovery_task
        except (OSError, TimeoutError):
            pass


@pytest.mark.asyncio
async def test_zeroconf_uses_same_discovery(ha):
    flow = make_flow(ha, "zeroconf")
    info = SimpleNamespace(properties={"mn": "CLI-W220W-00", "sn": "serial"}, ip_addresses=["192.0.2.49"])
    result = await flow.async_step_zeroconf(info)
    assert result["step_id"] == "zeroconf_confirm"
    with patch.object(cf, "_discover_zones", AsyncMock(return_value={"TSTAT_00": {"name": "Home"}})):
        assert (await flow.async_step_zeroconf_confirm({}))["type"] == FlowResultType.SHOW_PROGRESS
        await finish_discovery(flow)
    result = await flow.async_step_zone_area({"name": "Home"})
    assert result["title"] == "Savant CLI-W220W-00 (serial)"
    assert result["data"] == {"host": "192.0.2.49", "port": 2000, "zones": {"TSTAT_00": {"name": "Home"}}}
    assert flow.unique_id == "cli_192.0.2.49"


@pytest.mark.asyncio
async def test_reconfigure_merges_data_and_defaults(ha):
    area = ar.async_get(ha).async_create("Existing")
    entry = SimpleNamespace(data={
        "host": "old.test", "port": 2000, "custom": "preserve",
        "zones": {"TSTAT_00": {"name": "Custom name", "area_id": area.id, "extra": True},
                  "TSTAT_09": {"name": "Not in this dump"}},
    })
    flow = make_flow(ha, "reconfigure")
    with patch.object(flow, "_get_reconfigure_entry", return_value=entry), patch.object(
        cf, "_discover_zones", AsyncMock(return_value={"TSTAT_00": {"name": "Telemetry"}, "TSTAT_01": {"name": "New"}})
    ), patch.object(flow, "async_update_reload_and_abort", return_value={"type": "abort"}) as update:
        form = await flow.async_step_reconfigure()
        assert form["step_id"] == "reconfigure"
        assert (await flow.async_step_reconfigure({"host": "new.test", "port": 2001}))["step_id"] == "zone_area"
        form = await finish_discovery(flow)
        assert form["data_schema"]({})["name"] == "Custom name"
        area_key = next(key for key in form["data_schema"].schema if key == "area_id")
        assert area_key.description["suggested_value"] == area.id
        await flow.async_step_zone_area({"name": "Custom name"})
        await flow.async_step_zone_area({"name": "Not in this dump"})
        await flow.async_step_zone_area({"name": "New"})
    data = update.call_args.kwargs["data"]
    assert data["custom"] == "preserve"
    assert data["host"] == "new.test" and data["port"] == 2001
    assert data["zones"]["TSTAT_00"] == {"name": "Custom name", "extra": True}
    assert data["zones"]["TSTAT_09"] == {"name": "Not in this dump"}
    assert entry.data["zones"]["TSTAT_00"]["area_id"] == area.id


@pytest.mark.asyncio
async def test_reconfigure_updates_registry_and_reload_preserves_customizations(ha):
    areas = ar.async_get(ha)
    original = areas.async_create("Original")
    selected = areas.async_create("Selected")
    customized = areas.async_create("Customized")
    registry = er.async_get(ha)
    registered = {}
    zones = {}
    for zone_id in ("TSTAT_00", "TSTAT_01", "TSTAT_09"):
        unique_id = "cli_climate_controller.test"
        if zone_id != "TSTAT_00":
            unique_id += f"_{zone_id}"
        registered[zone_id] = registry.async_get_or_create(
            "climate", DOMAIN, unique_id, suggested_object_id=zone_id,
        )
        registered[zone_id] = registry.async_update_entity(
            registered[zone_id].entity_id, area_id=original.id, name=f"User {zone_id}",
        )
        zones[zone_id] = {"name": f"Stored {zone_id}", "area_id": original.id}
    entry = SimpleNamespace(
        entry_id="entry", data={"host": "controller.test", "port": 2000, "zones": zones},
        async_on_unload=MagicMock(),
    )
    flow = make_flow(ha, "reconfigure")
    with patch.object(flow, "_get_reconfigure_entry", return_value=entry), patch.object(
        cf, "_discover_zones", AsyncMock(return_value={
            "TSTAT_00": {"name": "Telemetry"}, "TSTAT_01": {"name": "Telemetry 1"},
        })
    ), patch.object(flow, "async_update_reload_and_abort", return_value={"type": "abort"}) as update:
        await flow.async_step_reconfigure({"host": "controller.test", "port": 2000})
        await finish_discovery(flow)
        await flow.async_step_zone_area({"name": "Selected Name", "area_id": selected.id})
        result = await flow.async_step_zone_area({"name": "Cleared Area Name", "finish_setup": True})
    assert result["type"] == "abort"
    for zone_id, name, area_id in (
        ("TSTAT_00", "Selected Name", selected.id),
        ("TSTAT_01", "Cleared Area Name", None),
        ("TSTAT_09", "User TSTAT_09", original.id),
    ):
        entity = registry.async_get(registered[zone_id].entity_id)
        assert (entity.name, entity.area_id) == (name, area_id)
    entry.data = update.call_args.kwargs["data"]
    assert entry.data["zones"]["TSTAT_09"] == zones["TSTAT_09"]
    assert entry.data["zones"]["TSTAT_00"] == {"name": "Selected Name", "area_id": selected.id}
    assert entry.data["zones"]["TSTAT_01"] == {"name": "Cleared Area Name"}

    # Ordinary reloads must not reapply setup values over later registry edits.
    for zone_id, area_id in (("TSTAT_00", None), ("TSTAT_01", customized.id)):
        registry.async_update_entity(
            registered[zone_id].entity_id, name=f"Later {zone_id}", area_id=area_id,
        )
    before_reload = {key: registry.async_get(value.entity_id) for key, value in registered.items()}
    coordinator = SavantCLICoordinator(ha, "controller.test")
    coordinator.send_command = AsyncMock()
    ha.data[DOMAIN] = {entry.entry_id: coordinator}
    entities = []
    with patch.object(coordinator, "async_add_listener", return_value=MagicMock()):
        await async_setup_entry(ha, entry, entities.extend)
        assert {entity.zone for entity in entities} == set(zones)
        for entity in entities:
            assert entity._initial_area_id is None
            entity.hass = ha
            entity.entity_id = registered[entity.zone].entity_id
            entity.async_on_remove = MagicMock()
            await entity.async_added_to_hass()
    assert {key: registry.async_get(value.entity_id) for key, value in registered.items()} == before_reload
    coordinator.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_climate_ignores_area_deleted_before_entity_added(ha):
    areas = ar.async_get(ha)
    area = areas.async_create("Deleted")
    coordinator = SavantCLICoordinator(ha, "controller.test")
    coordinator.send_command = AsyncMock()
    entry = SimpleNamespace(
        entry_id="entry", async_on_unload=MagicMock(),
        data={"zones": {"TSTAT_00": {"name": "Setup Name", "area_id": area.id}}},
    )
    ha.data[DOMAIN] = {entry.entry_id: coordinator}
    entities = []
    with patch.object(coordinator, "async_add_listener", return_value=MagicMock()):
        await async_setup_entry(ha, entry, entities.extend)
        entity = entities[0]
        assert entity._initial_area_id == area.id
        registered = er.async_get(ha).async_get_or_create("climate", DOMAIN, entity.unique_id)
        areas.async_delete(area.id)
        entity.hass = ha
        entity.entity_id = registered.entity_id
        entity.async_on_remove = MagicMock()
        with patch.object(er.async_get(ha), "async_update_entity", wraps=er.async_get(ha).async_update_entity) as update:
            await entity.async_added_to_hass()
        update.assert_not_called()
        entity.async_on_remove.assert_called_once()
    assert er.async_get(ha).async_get(entity.entity_id).area_id is None
    coordinator.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_flow_manager_progress_completion_and_abort(ha):
    flow = make_flow(ha)
    manager = ha.config_entries.flow
    reader, writer = socket_with(eof=False)
    with patch.object(manager, "async_create_flow", AsyncMock(return_value=flow)), patch.object(
        cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))
    ):
        result = await manager.async_init(DOMAIN, context={"source": "user"}, data={"host": "example.test", "port": 2000})
        await asyncio.sleep(0)
        manager.async_abort(result["flow_id"])
        with pytest.raises(asyncio.CancelledError):
            await flow._discovery_task
        writer.close.assert_called_once()

    flow = make_flow(ha)
    with patch.object(manager, "async_create_flow", AsyncMock(return_value=flow)), patch.object(
        cf, "_discover_zones", AsyncMock(return_value={"TSTAT_00": {"name": "Home"}})
    ):
        result = await manager.async_init(DOMAIN, context={"source": "user"}, data={"host": "example.test", "port": 2000})
        await ha.async_block_till_done()
        assert flow.cur_step["type"] == FlowResultType.SHOW_PROGRESS_DONE
        form = await manager.async_configure(result["flow_id"])
        assert form["step_id"] == "zone_area"
        manager.async_abort(result["flow_id"])


@pytest.mark.asyncio
async def test_invalid_port_never_connects(ha):
    flow = make_flow(ha)
    with patch.object(cf, "_discover_zones", AsyncMock()) as discover:
        result = await flow.async_step_user({"host": "example.test", "port": 0})
    assert result["errors"] == {"port": "invalid_port"}
    discover.assert_not_called()


@pytest.mark.asyncio
async def test_reconfigure_legacy_entry(ha):
    entry = SimpleNamespace(data={"host": "old.test", "custom": 42})
    flow = make_flow(ha, "reconfigure")
    with patch.object(flow, "_get_reconfigure_entry", return_value=entry), patch.object(
        cf, "_discover_zones", AsyncMock(return_value={"TSTAT_00": {"name": "Home"}})
    ), patch.object(flow, "async_update_reload_and_abort") as update:
        await flow.async_step_reconfigure({"host": "new.test"})
        await finish_discovery(flow)
        await flow.async_step_zone_area({"name": "Home"})
    assert update.call_args.kwargs["data"] == {
        "host": "new.test", "port": 2000, "custom": 42,
        "zones": {"TSTAT_00": {"name": "Home"}},
    }


@pytest.mark.asyncio
async def test_existing_identity_aborts_before_socket(ha):
    from homeassistant.data_entry_flow import AbortFlow

    flow = make_flow(ha)
    with patch.object(flow, "_abort_if_unique_id_configured", side_effect=AbortFlow("already_configured")), patch.object(
        cf, "_discover_zones", AsyncMock()
    ) as discover:
        with pytest.raises(AbortFlow):
            await flow.async_step_user({"host": "192.0.2.49", "port": 2000})
    assert flow.unique_id == "cli_192.0.2.49"
    discover.assert_not_called()


@pytest.mark.asyncio
async def test_socket_close_error_is_handled(ha):
    reader, writer = socket_with(b"TSTAT_00 SET_NAME=Home\r\n")
    writer.wait_closed.side_effect = OSError("reset")
    with patch.object(cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))):
        assert await cf._discover_zones(ha, "example.test", 2000) == {"TSTAT_00": {"name": "Home"}}
    writer.close.assert_called_once()


@pytest.mark.asyncio
async def test_overlong_record_does_not_grow_buffer(ha):
    reader, writer = socket_with(b"x" * 70000 + b"\r\nTSTAT_00 SET_NAME=Home\r\n")
    with patch.object(cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))):
        assert await cf._discover_zones(ha, "example.test", 2000) == {"TSTAT_00": {"name": "Home"}}
    writer.close.assert_called_once()


async def next_zone_form(flow):
    """Advance the progress waiter without waiting for the collector."""
    await asyncio.wait_for(asyncio.shield(flow._progress_task), 1)
    result = await flow.async_step_discover()
    assert result["type"] == FlowResultType.SHOW_PROGRESS_DONE
    return await getattr(flow, f"async_step_{result['step_id']}")()


@pytest.mark.asyncio
async def test_streaming_names_and_finish_includes_unreviewed(ha):
    reader, writer = socket_with(eof=False)
    flow = make_flow(ha)
    with patch.object(cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))), patch.object(
        cf.SavantCLICoordinator, "send_command", AsyncMock()
    ) as command:
        result = await flow.async_step_user({"host": "example.test", "port": 2000})
        assert result["progress_task"] is not flow._discovery_task
        reader.feed_data(b"TSTAT_00 SET_TEMP=0700\r\n")
        await asyncio.sleep(0)
        assert not flow._progress_task.done()
        reader.feed_data(b"TSTAT_00 SET_NAME=Home\r\n")
        form = await next_zone_form(flow)
        assert form["data_schema"]({})["name"] == "Home"
        assert not flow._discovery_task.done()
        # New names continue to arrive while the original form is open.
        reader.feed_data(b"TSTAT_01 SET_NAME=Bedroom\r\nTSTAT_02 SET_NAME=Attic\r\n")
        await asyncio.sleep(0)
        result = await asyncio.wait_for(flow.async_step_zone_area({
            "name": "My Home", "finish_setup": True,
        }), 1)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["zones"] == {
        "TSTAT_00": {"name": "My Home"},
        "TSTAT_01": {"name": "Bedroom"},
        "TSTAT_02": {"name": "Attic"},
    }
    assert flow._discovery_task.cancelled()
    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()
    writer.write.assert_not_called()
    command.assert_not_called()


@pytest.mark.asyncio
async def test_streaming_wait_for_more_preserves_reviewed_edits(ha):
    reader, writer = socket_with(eof=False)
    flow = make_flow(ha)
    area = ar.async_get(ha).async_create("Chosen")
    with patch.object(cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))):
        await flow.async_step_user({"host": "example.test", "port": 2000})
        reader.feed_data(b"TSTAT_00 SET_NAME=Home\r\n")
        await next_zone_form(flow)
        review = await flow.async_step_zone_area({"name": "Custom", "area_id": area.id})
        assert review["step_id"] == "discovery_review"
        assert review["data_schema"]({}) == {"finish_setup": True}
        assert "Custom (TSTAT_00)" in review["description_placeholders"]["zones"]
        result = await flow.async_step_discovery_review({"finish_setup": False})
        assert result["type"] == FlowResultType.SHOW_PROGRESS
        assert not flow._progress_task.done()
        reader.feed_data(b"TSTAT_00 SET_NAME=Changed\r\nTSTAT_01 SET_NAME=Bedroom\r\nTSTAT_01 SET_NAME=Bedroom\r\n")
        form = await next_zone_form(flow)
        assert form["description_placeholders"] == {"zone_id": "TSTAT_01"}
        assert flow._pending_zones == ["TSTAT_01"]
        review = await flow.async_step_zone_area({"name": "Bedroom"})
        assert review["step_id"] == "discovery_review"
        result = await asyncio.wait_for(flow.async_step_discovery_review({"finish_setup": True}), 1)
    assert result["data"]["zones"]["TSTAT_00"] == {"name": "Custom", "area_id": area.id}
    writer.close.assert_called_once()


@pytest.mark.asyncio
async def test_new_zone_during_review_included_on_finish(ha):
    reader, writer = socket_with(b"TSTAT_00 SET_NAME=Home\r\n", eof=False)
    flow = make_flow(ha)
    with patch.object(cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))):
        await flow.async_step_user({"host": "example.test", "port": 2000})
        await next_zone_form(flow)
        await flow.async_step_zone_area({"name": "Home"})
        reader.feed_data(b"TSTAT_01 SET_NAME=Late\r\n")
        await asyncio.sleep(0)
        result = await flow.async_step_discovery_review({"finish_setup": True})
    assert result["data"]["zones"]["TSTAT_01"] == {"name": "Late"}
    writer.close.assert_called_once()


@pytest.mark.parametrize("named", [False, True])
@pytest.mark.asyncio
async def test_stream_deadline_and_nameless_fallback(ha, named):
    reader, writer = socket_with(eof=False)
    flow = make_flow(ha)
    with patch.object(cf, "DISCOVERY_SECONDS", 0.01), patch.object(
        cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))
    ):
        await flow.async_step_user({"host": "example.test", "port": 2000})
        if named:
            reader.feed_data(b"TSTAT_03 SET_TEMP=0710\r\n")
        form = await next_zone_form(flow)
        if named:
            assert form["data_schema"]({})["name"] == "TSTAT_03"
            result = await flow.async_step_zone_area({"name": "Fallback"})
            assert result["type"] == FlowResultType.CREATE_ENTRY
        else:
            assert form["step_id"] == "discovery_error"
            assert form["errors"] == {"base": "no_zones"}
        assert flow._discovery_task.done()
    writer.close.assert_called_once()


@pytest.mark.parametrize("form_step", ["zone_area", "discovery_review", "discover"])
@pytest.mark.asyncio
async def test_manager_abort_streaming_forms(ha, form_step):
    reader, writer = socket_with(eof=False)
    flow = make_flow(ha)
    manager = ha.config_entries.flow
    with patch.object(manager, "async_create_flow", AsyncMock(return_value=flow)), patch.object(
        cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))
    ):
        result = await manager.async_init(DOMAIN, context={"source": "user"}, data={"host": "example.test", "port": 2000})
        reader.feed_data(b"TSTAT_00 SET_NAME=Home\r\n")
        await flow._progress_task
        # Let HA's progress completion callback update the current step.
        for _ in range(5):
            await asyncio.sleep(0)
        form = await manager.async_configure(result["flow_id"])
        assert form["step_id"] == "zone_area"
        if form_step != "zone_area":
            form = await manager.async_configure(result["flow_id"], {"name": "Home"})
            assert form["step_id"] == "discovery_review"
        if form_step == "discover":
            form = await manager.async_configure(result["flow_id"], {"finish_setup": False})
            assert form["type"] == FlowResultType.SHOW_PROGRESS
        manager.async_abort(result["flow_id"])
        await asyncio.gather(flow._discovery_task, return_exceptions=True)
        if flow._progress_task is not None:
            await asyncio.gather(flow._progress_task, return_exceptions=True)
    assert flow._discovery_task.cancelled()
    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()


@pytest.mark.asyncio
async def test_progress_waiter_cancel_closes_collector(ha):
    reader, writer = socket_with(eof=False)
    flow = make_flow(ha)
    with patch.object(cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))):
        await flow.async_step_user({"host": "example.test", "port": 2000})
        flow._progress_task.cancel()
        await asyncio.gather(flow._progress_task, return_exceptions=True)
    assert flow._discovery_task.cancelled()
    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconfigure_known_zones_without_snapshot(ha):
    reader, writer = socket_with(eof=False)
    entry = SimpleNamespace(data={
        "host": "old.test", "port": 2000, "custom": 42,
        "zones": {"TSTAT_00": {"name": "Saved"}, "TSTAT_01": {"name": "Also saved"}},
    })
    flow = make_flow(ha, "reconfigure")
    with patch.object(flow, "_get_reconfigure_entry", return_value=entry), patch.object(
        cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))
    ), patch.object(flow, "async_update_reload_and_abort", return_value={"type": "abort"}) as update:
        form = await flow.async_step_reconfigure({"host": "new.test", "port": 2001})
        assert form["step_id"] == "zone_area"
        assert form["data_schema"]({})["name"] == "Saved"
        assert not flow._discovery_task.done()
        # Yield until the mocked connection is open, without any telemetry.
        await asyncio.sleep(0)
        await asyncio.wait_for(flow.async_step_zone_area({"name": "Edited", "finish_setup": True}), 1)
    assert update.call_args.kwargs["data"] == {
        **entry.data, "host": "new.test", "port": 2001,
        "zones": {"TSTAT_00": {"name": "Edited"}, "TSTAT_01": {"name": "Also saved"}},
    }
    writer.close.assert_called_once()


@pytest.mark.parametrize("before_form", [False, True])
@pytest.mark.asyncio
async def test_read_error_after_partial_discovery_keeps_finish_path(ha, before_form):
    reader, writer = socket_with(eof=False)
    flow = make_flow(ha)
    with patch.object(cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))):
        await flow.async_step_user({"host": "example.test", "port": 2000})
        reader.feed_data(b"TSTAT_00 SET_NAME=Home\r\n")
        await asyncio.sleep(0)
        if before_form:
            reader.set_exception(OSError("connection reset"))
            await flow._discovery_task
        await next_zone_form(flow)
        if not before_form:
            reader.set_exception(OSError("connection reset"))
        await flow._discovery_task
        result = await flow.async_step_zone_area({"name": "Kept"})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["zones"] == {"TSTAT_00": {"name": "Kept"}}
    writer.close.assert_called_once()


@pytest.mark.asyncio
async def test_walk_live_pending_then_wait_until_completion(ha):
    reader, writer = socket_with(eof=False)
    flow = make_flow(ha)
    with patch.object(cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))):
        await flow.async_step_user({"host": "example.test", "port": 2000})
        reader.feed_data(b"TSTAT_00 SET_NAME=Home\r\n")
        await next_zone_form(flow)
        reader.feed_data(b"TSTAT_01 SET_NAME=Bedroom\r\n")
        await asyncio.sleep(0)
        form = await flow.async_step_zone_area({"name": "Home"})
        assert form["description_placeholders"] == {"zone_id": "TSTAT_01"}
        review = await flow.async_step_zone_area({"name": "Bedroom"})
        assert review["step_id"] == "discovery_review"
        await flow.async_step_discovery_review({"finish_setup": False})
        reader.feed_eof()
        result = await next_zone_form(flow)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert set(result["data"]["zones"]) == {"TSTAT_00", "TSTAT_01"}
    assert not flow._discovery_task.cancelled()
    writer.close.assert_called_once()


@pytest.mark.asyncio
async def test_review_wait_uses_zone_arrived_while_review_open(ha):
    reader, writer = socket_with(b"TSTAT_00 SET_NAME=Home\r\n", eof=False)
    flow = make_flow(ha)
    with patch.object(cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))):
        await flow.async_step_user({"host": "example.test", "port": 2000})
        await next_zone_form(flow)
        await flow.async_step_zone_area({"name": "Home"})
        reader.feed_data(b"TSTAT_01 SET_NAME=Bedroom\r\n")
        await asyncio.sleep(0)
        form = await flow.async_step_discovery_review({"finish_setup": False})
        assert form["step_id"] == "zone_area"
        assert form["data_schema"]({})["name"] == "Bedroom"
        await flow.async_step_zone_area({"name": "Bedroom", "finish_setup": True})
    writer.close.assert_called_once()


@pytest.mark.asyncio
async def test_early_finish_awaits_socket_cleanup(ha):
    reader, writer = socket_with(b"TSTAT_00 SET_NAME=Home\r\n", eof=False)
    close_started = asyncio.Event()
    allow_close = asyncio.Event()

    async def close():
        close_started.set()
        await allow_close.wait()

    writer.wait_closed.side_effect = close
    flow = make_flow(ha)
    with patch.object(cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))):
        await flow.async_step_user({"host": "example.test", "port": 2000})
        await next_zone_form(flow)
        finish = asyncio.create_task(flow.async_step_zone_area({"name": "Home", "finish_setup": True}))
        await asyncio.wait_for(close_started.wait(), 1)
        assert not finish.done()
        allow_close.set()
        result = await asyncio.wait_for(finish, 1)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()


@pytest.mark.asyncio
async def test_discovery_callback_only_publishes_valid_names(ha):
    reader, writer = socket_with(
        b"TSTAT_00 SET_TEMP=0700\r\nTSTAT_00 SET_NAME=\r\n",
        b"TSTAT_01 SET_NAME=Bedroom\r\nTSTAT_02 SET_NAME=\xff\r\n",
    )
    publish = MagicMock()
    with patch.object(cf.asyncio, "open_connection", AsyncMock(return_value=(reader, writer))):
        zones = await cf._discover_zones(ha, "example.test", 2000, publish)
    publish.assert_called_once_with("TSTAT_01", {"name": "Bedroom"})
    assert zones == {"TSTAT_00": {"name": "TSTAT_00"}, "TSTAT_01": {"name": "Bedroom"}}
    writer.write.assert_not_called()
