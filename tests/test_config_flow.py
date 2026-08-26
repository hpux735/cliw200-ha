"""Tests for the config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT

from custom_components.savant_cli.config_flow import (
    _is_cli_model,
    _is_ipv4,
    _discovery_host,
)
from custom_components.savant_cli.const import DEFAULT_PORT, DOMAIN


class TestHelpers:
    """Test helper functions."""

    def test_is_cli_model_w220(self) -> None:
        assert _is_cli_model({"mn": "CLI-W220W-00"}) is True

    def test_is_cli_model_w200(self) -> None:
        assert _is_cli_model({"mn": "CLI-W200-00"}) is True

    def test_is_cli_model_sem_rejected(self) -> None:
        assert _is_cli_model({"mn": "SEM-2016-00"}) is False

    def test_is_cli_model_pbc_rejected(self) -> None:
        assert _is_cli_model({"mn": "PBC-1000-00"}) is False

    def test_is_cli_model_lcb_rejected(self) -> None:
        assert _is_cli_model({"mn": "LCB-DMX1-01"}) is False

    def test_is_cli_model_empty_rejected(self) -> None:
        assert _is_cli_model({}) is False

    def test_is_ipv4_v4(self) -> None:
        assert _is_ipv4("192.168.3.45") is True

    def test_is_ipv4_v6(self) -> None:
        assert _is_ipv4("fd2d:c69e:d0eb:487e:9a84:e3ff:fe9b:2c5c") is False

    def test_is_ipv4_invalid(self) -> None:
        assert _is_ipv4("not-an-ip") is False

    def test_is_ipv4_none(self) -> None:
        assert _is_ipv4(None) is False

    def test_discovery_host_prefers_ipv4(self) -> None:
        """Test that IPv4 is preferred from ip_addresses."""
        info = MagicMock()
        info.ip_addresses = [
            "fd2d:c69e:d0eb:487e:9a84:e3ff:fe9b:2c5c",
            "192.168.3.45",
        ]
        assert _discovery_host(info) == "192.168.3.45"

    def test_discovery_host_ipv6_only(self) -> None:
        """Test that IPv6-only returns None."""
        info = MagicMock()
        info.ip_addresses = ["fd2d:c69e:d0eb:487e:9a84:e3ff:fe9b:2c5c"]
        assert _discovery_host(info) is None

    def test_discovery_host_fallback_ip_address(self) -> None:
        """Test fallback to ip_address attribute."""
        info = MagicMock()
        info.ip_addresses = []
        info.ip_address = "192.168.3.45"
        assert _discovery_host(info) == "192.168.3.45"

    def test_discovery_host_fallback_host(self) -> None:
        """Test fallback to host attribute."""
        info = MagicMock()
        info.ip_addresses = []
        info.ip_address = None
        info.host = "rpe-0945.local"
        assert _discovery_host(info) == "rpe-0945.local"


class TestConfigFlow:
    """Test the config flow."""

    @patch("custom_components.savant_cli.config_flow.SavantCLIConfigFlow.async_set_unique_id")
    async def _run_user_step(self, mock_unique_id, hass, host="192.168.3.45", port=DEFAULT_PORT):
        """Helper to run the user step."""
        flow = config_entries.ConfigFlow.__new__(config_entries.ConfigFlow)
        flow.hass = hass
        flow._async_current_entries = MagicMock(return_value=[])

        # Manually construct our flow
        from custom_components.savant_cli.config_flow import SavantCLIConfigFlow
        result = SavantCLIConfigFlow.async_step_user.__func__(
            flow, {CONF_HOST: host, CONF_PORT: port}
        )
        return result

    def test_user_step_shows_form(self) -> None:
        """Test that the user step shows the form when no input."""
        from custom_components.savant_cli.config_flow import SavantCLIConfigFlow, _STEP_USER_SCHEMA

        flow = MagicMock(spec=SavantCLIConfigFlow)
        # Mock the config flow to return a form

        result = SavantCLIConfigFlow.async_step_user.__func__(flow, None)
        assert result["type"] == "form"
        assert result["step_id"] == "user"
