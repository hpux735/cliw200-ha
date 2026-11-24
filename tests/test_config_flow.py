"""Tests for the config flow."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.savant_cli.config_flow import (
    _is_cli_model,
    _is_ipv4,
    _discovery_host,
)


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
        info = SimpleNamespace(
            ip_addresses=["fd2d:c69e:d0eb:487e:9a84:e3ff:fe9b:2c5c"],
            ip_address="fd2d:c69e:d0eb:487e:9a84:e3ff:fe9b:2c5c",
            host="fd2d:c69e:d0eb:487e:9a84:e3ff:fe9b:2c5c",
        )
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

    @pytest.mark.asyncio
    async def test_user_step_shows_form(self) -> None:
        """Test that the user step shows the form when no input."""
        from custom_components.savant_cli.config_flow import SavantCLIConfigFlow

        flow = SavantCLIConfigFlow()
        result = await flow.async_step_user()
        assert result["type"] == "form"
        assert result["step_id"] == "user"
