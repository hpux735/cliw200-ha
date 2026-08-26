"""Config flow for Savant CLI-W200/CLI-W220 thermostat."""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.zeroconf import ZeroconfServiceInfo
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import DiscoveryInfoType

from .const import DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

_ZEROCONF_TXT_KEYS = {
    "model": "mn",
    "serial": "sn",
    "fw": "fw",
    "board_id": "board_id",
    "pn": "pn",
}

_STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
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


class SavantCLIConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Savant CLI thermostat."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._discovery_info: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step (manual entry)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            title = f"Savant CLI Thermostat ({host})"

            await self.async_set_unique_id(f"cli_{host}")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(title=title, data=user_input)

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
            return self.async_create_entry(
                title=self.context.get("title_placeholders", {}).get(
                    "name", "Savant CLI Thermostat"
                ),
                data={
                    CONF_HOST: self._discovery_info[CONF_HOST],
                    CONF_PORT: self._discovery_info[CONF_PORT],
                },
            )

        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={
                "name": self._discovery_info.get("model", "CLI-W2xx"),
                "host": self._discovery_info[CONF_HOST],
            },
        )
