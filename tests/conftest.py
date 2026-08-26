"""Conftest for Savant CLI tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_hass() -> MagicMock:
    """Return a mocked HomeAssistant instance."""
    hass = MagicMock()
    hass.loop = MagicMock()
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass
