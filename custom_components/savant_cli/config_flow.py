"""Config flow for Savant CLI-W200/CLI-W220 thermostat."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import ipaddress
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

if TYPE_CHECKING:
    try:
        from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
    except ImportError:
        from homeassistant.components.zeroconf import (  # type: ignore[no-redef]
            ZeroconfServiceInfo,
        )

from .const import DEFAULT_PORT, DOMAIN, TIMEOUT
from .coordinator import SavantCLICoordinator

DISCOVERY_SECONDS = 40

_STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
    }
)


def _is_cli_model(txt: dict) -> bool:
    """Return True if the mDNS TXT record indicates a CLI-W200/W220 thermostat."""
    model = txt.get("mn", "")
    return model.startswith("CLI-W2")


def _is_ipv4(addr: Any) -> bool:
    """Return True if addr is an IPv4 address (object or string)."""
    try:
        if isinstance(addr, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            return addr.version == 4
        return ipaddress.ip_address(str(addr)).version == 4
    except (ValueError, TypeError):
        return False


def _discovery_host(info: ZeroconfServiceInfo) -> str | None:
    """Extract a reachable IPv4 host from zeroconf discovery info."""
    for raw in getattr(info, "ip_addresses", []):
        addr = str(raw).split("%")[0]
        try:
            if ipaddress.ip_address(addr).version == 4:
                return addr
        except ValueError:
            pass

    if hasattr(info, "ip_address") and info.ip_address:
        try:
            if ipaddress.ip_address(str(info.ip_address)).version == 4:
                return str(info.ip_address)
        except ValueError:
            pass

    if hasattr(info, "host") and info.host:
        host = str(info.host).strip("[]").split("%")[0]
        try:
            if ipaddress.ip_address(host).version == 4:
                return host
        except ValueError:
            return host

    return None


async def _discover_zones(
    hass: HomeAssistant,
    host: str,
    port: int,
    zone_callback: Callable[[str, dict[str, str]], None] | None = None,
) -> dict[str, dict[str, str]]:
    """Listen passively for a bounded window; the stream has no end marker."""
    coordinator = SavantCLICoordinator(hass, host, port)
    named_zones: set[str] = set()
    writer = None
    try:
        async with asyncio.timeout(DISCOVERY_SECONDS):
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=TIMEOUT
            )
            while True:
                try:
                    line = await reader.readuntil(b"\r\n")
                except asyncio.IncompleteReadError:
                    break
                except asyncio.LimitOverrunError as ex:
                    await reader.readexactly(ex.consumed)
                    continue
                line = line.strip()
                if not line.startswith(b"TSTAT_"):
                    continue
                try:
                    coordinator._parse_line(line)
                except (UnicodeError, ValueError):
                    continue
                parts = line.split(None, 1)
                if (
                    len(parts) == 2
                    and parts[1].startswith(b"SET_NAME=")
                    and parts[1][9:]
                ):
                    zone_id = parts[0].decode()
                    if zone_id in coordinator.zones:
                        named_zones.add(zone_id)
                        if zone_callback is not None:
                            zone_callback(
                                zone_id, {"name": coordinator.zones[zone_id].name}
                            )
    except TimeoutError:
        if writer is None:
            raise
    finally:
        if writer is not None:
            writer.close()
            try:
                async with asyncio.timeout(1):
                    await writer.wait_closed()
            except (OSError, TimeoutError):
                pass
    return {
        zone_id: {"name": data.name if zone_id in named_zones else zone_id}
        for zone_id, data in sorted(coordinator.zones.items())
    }


class SavantCLIConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Savant CLI thermostat."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._discovery_info: dict[str, Any] = {}
        self._data: dict[str, Any] = {}
        self._title = "Savant CLI Thermostat"
        self._discovery_task: asyncio.Task | None = None
        self._progress_task: asyncio.Task | None = None
        self._zone_available = asyncio.Event()
        self._zones: dict[str, dict[str, Any]] = {}
        self._pending_zones: list[str] = []
        self._reviewed_zones: set[str] = set()
        self._discovery_error: str | None = None

    @callback
    def async_remove(self) -> None:
        """Stop passive discovery even when removed from a form."""
        if (
            self._discovery_task is not None
            and not self._discovery_task.done()
            and not self._discovery_task.cancelling()
        ):
            self._discovery_task.cancel()
        if (
            self._progress_task is not None
            and not self._progress_task.done()
            and not self._progress_task.cancelling()
        ):
            self._progress_task.cancel()
        super().async_remove()

    def _zone_discovered(self, zone_id: str, zone: dict[str, str]) -> None:
        """Merge live names without replacing saved or reviewed choices."""
        if zone_id in self._reviewed_zones:
            return
        previous = self._data.get("zones", {}).get(zone_id, {})
        self._zones[zone_id] = {**zone, **previous}
        if zone_id not in self._pending_zones:
            self._pending_zones.append(zone_id)
        self._zone_available.set()

    async def _collect_zones(self) -> None:
        """Keep listening while the user reviews names and areas."""
        try:
            discovered = await _discover_zones(
                self.hass,
                self._data[CONF_HOST],
                self._data[CONF_PORT],
                self._zone_discovered,
            )
            for zone_id, zone in discovered.items():
                self._zone_discovered(zone_id, zone)
            self._discovery_error = None if self._zones else "no_zones"
        except (OSError, TimeoutError):
            self._discovery_error = "cannot_connect"
        finally:
            self._zone_available.set()

    async def _wait_for_zone(self) -> None:
        """Wait for new work or completion, not the entire discovery window."""
        try:
            await self._zone_available.wait()
        except asyncio.CancelledError:
            if self._discovery_task is not None and not self._discovery_task.done():
                if not self._discovery_task.cancelling():
                    self._discovery_task.cancel()
                await asyncio.gather(self._discovery_task, return_exceptions=True)
            raise

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step (manual entry)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                data = _STEP_USER_SCHEMA(user_input)
            except vol.Invalid:
                errors[CONF_PORT] = "invalid_port"
            else:
                host = data[CONF_HOST]
                await self.async_set_unique_id(f"cli_{host}")
                self._abort_if_unique_id_configured()
                self._data = data
                self._title = f"Savant CLI Thermostat ({host})"
                return await self.async_step_discover()

        return self.async_show_form(
            step_id="user",
            data_schema=_STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle zeroconf/mDNS discovery."""
        txt = dict(discovery_info.properties)
        if not _is_cli_model(txt):
            return self.async_abort(reason="not_cli_device")

        host = _discovery_host(discovery_info)
        if host is None:
            return self.async_abort(reason="no_ipv4")

        model = txt.get("mn", "CLI-W2xx")
        serial = txt.get("sn", "")
        title = f"Savant {model} ({serial or host})"

        await self.async_set_unique_id(f"cli_{host}")
        self._abort_if_unique_id_configured(
            updates={
                CONF_HOST: host,
                CONF_PORT: DEFAULT_PORT,
            }
        )

        self._discovery_info = {
            CONF_HOST: host,
            CONF_PORT: DEFAULT_PORT,
            "model": model,
            "serial": serial,
            "fw": txt.get("fw", ""),
            "board_id": txt.get("board_id", ""),
            "pn": txt.get("pn", ""),
        }
        self.context["title_placeholders"] = {"name": title}

        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm zeroconf discovery."""
        if user_input is not None:
            self._title = self.context.get("title_placeholders", {}).get(
                "name", "Savant CLI Thermostat"
            )
            self._data = {
                CONF_HOST: self._discovery_info[CONF_HOST],
                CONF_PORT: self._discovery_info[CONF_PORT],
            }
            return await self.async_step_discover()

        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={
                "name": self._discovery_info.get("model", "CLI-W2xx"),
                "host": self._discovery_info[CONF_HOST],
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            try:
                data = _STEP_USER_SCHEMA(user_input)
            except vol.Invalid:
                errors[CONF_PORT] = "invalid_port"
            else:
                self._data = {**reconfigure_entry.data, **data}
                self._title = f"Savant CLI Thermostat ({data[CONF_HOST]})"
                return await self.async_step_discover()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _STEP_USER_SCHEMA,
                {
                    CONF_HOST: reconfigure_entry.data.get(CONF_HOST, ""),
                    CONF_PORT: reconfigure_entry.data.get(CONF_PORT, DEFAULT_PORT),
                },
            ),
            errors=errors,
        )

    async def async_step_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Share one passive discovery task across all setup routes."""
        if self._discovery_task is None:
            self._zones = {
                key: dict(value) for key, value in self._data.get("zones", {}).items()
            }
            self._pending_zones = list(self._zones)
            known_zones = bool(self._pending_zones)
            self._zone_available.clear()
            self._discovery_task = self.hass.async_create_task(self._collect_zones())
            if known_zones:
                return await self.async_step_zone_area()
        if self._progress_task is not None and self._progress_task.done():
            self._progress_task = None
            return self.async_show_progress_done(
                next_step_id="zone_area" if self._zones else "discovery_error"
            )
        if self._progress_task is None:
            self._zone_available.clear()
            if self._pending_zones or self._discovery_task.done():
                self._zone_available.set()
            self._progress_task = self.hass.async_create_task(self._wait_for_zone())
        return self.async_show_progress(
            step_id="discover",
            progress_action="discover_zones",
            progress_task=self._progress_task,
        )

    async def async_step_discovery_error(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer a retry without creating an empty entry."""
        if user_input is not None:
            self._discovery_task = None
            self._progress_task = None
            return await self.async_step_discover()
        return self.async_show_form(
            step_id="discovery_error",
            data_schema=vol.Schema({}),
            errors={"base": self._discovery_error},
        )

    async def async_step_zone_area(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name and optionally assign an existing area to each discovered zone."""
        if not self._pending_zones:
            return await self.async_step_discovery_review()
        zone_id = self._pending_zones[0]
        defaults = self._zones[zone_id]
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input.get("name", "").strip()
            area_id = user_input.get("area_id")
            if not name:
                errors["name"] = "invalid_name"
            if area_id and ar.async_get(self.hass).async_get_area(area_id) is None:
                errors["area_id"] = "invalid_area"
            if not errors:
                zone = {**defaults, "name": name}
                zone.pop("area_id", None)
                if area_id:
                    zone["area_id"] = area_id
                self._zones[zone_id] = zone
                self._reviewed_zones.add(zone_id)
                self._pending_zones.pop(0)
                if user_input.get("finish_setup", False):
                    return await self._finish_setup()
                if self._pending_zones:
                    return await self.async_step_zone_area()
                return await self.async_step_discovery_review()
            defaults = user_input
        schema = vol.Schema(
            {
                vol.Required("name", default=defaults.get("name", zone_id)): str,
                vol.Optional("area_id"): selector.AreaSelector(),
                vol.Optional("finish_setup", default=False): bool,
            }
        )
        return self.async_show_form(
            step_id="zone_area",
            data_schema=self.add_suggested_values_to_schema(schema, defaults),
            description_placeholders={"zone_id": zone_id},
            errors=errors,
        )

    async def async_step_discovery_review(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user finish or wait for another zone."""
        if user_input is not None and user_input.get("finish_setup", True):
            return await self._finish_setup()
        if self._pending_zones:
            return await self.async_step_zone_area()
        if self._discovery_task.done():
            return await self._finish_setup()
        if user_input is not None:
            return await self.async_step_discover()
        return self.async_show_form(
            step_id="discovery_review",
            data_schema=vol.Schema({vol.Optional("finish_setup", default=True): bool}),
            description_placeholders={
                "zones": ", ".join(
                    f"{zone['name']} ({zone_id})"
                    for zone_id, zone in self._zones.items()
                )
            },
        )

    async def _finish_setup(self) -> ConfigFlowResult:
        """Close discovery before saving all observed zones."""
        if self._discovery_task is not None:
            if not self._discovery_task.done() and not self._discovery_task.cancelling():
                self._discovery_task.cancel()
            await asyncio.gather(self._discovery_task, return_exceptions=True)
        self._data["zones"] = self._zones
        if self.source == "reconfigure":
            registry = er.async_get(self.hass)
            old_host = self._get_reconfigure_entry().data[CONF_HOST]
            for configured_id, configured in self._zones.items():
                if configured_id not in self._reviewed_zones:
                    continue
                unique_id = f"cli_climate_{old_host}"
                if configured_id != "TSTAT_00":
                    unique_id += f"_{configured_id}"
                entity_id = registry.async_get_entity_id("climate", DOMAIN, unique_id)
                if entity_id is not None:
                    registry.async_update_entity(
                        entity_id,
                        area_id=configured.get("area_id"),
                        name=configured["name"],
                    )
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), title=self._title, data=self._data
            )
        return self.async_create_entry(title=self._title, data=self._data)
