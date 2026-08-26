"""DataUpdateCoordinator for the Savant CLI thermostat telemetry stream."""

import asyncio
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DEFAULT_PORT, DOMAIN, TIMEOUT

_LOGGER = logging.getLogger(__name__)


class SavantCLIData:
    """Parsed state for a single thermostat."""

    def __init__(self) -> None:
        self.temp: float | None = None
        self.temp_sp: float | None = None
        self.humidity: float | None = None
        self.humidity_sp: float | None = None
        self.hvac_mode: str = "01"
        self.hvac_state: str = "00"
        self.fan_mode: int = 0
        self.fan_stage: int = 0
        self.name: str = "Thermostat"
        self.temp_tolerance: float | None = None
        self.outside_temp: float | None = None
        self.relays: dict[str, bool] = {}
        self.btle_sensors: dict[str, dict[str, Any]] = {}
        self.available: bool = True


class SavantCLICoordinator(DataUpdateCoordinator[SavantCLIData]):
    """Coordinator that reads the Savant CLI telemetry stream via TCP."""

    def __init__(self, hass: HomeAssistant, host: str, port: int = DEFAULT_PORT) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{host}",
        )
        self.host = host
        self.port = port
        self._data = SavantCLIData()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._shutdown: bool = False

    @property
    def writer(self) -> asyncio.StreamWriter | None:
        """Return the current writer for sending commands."""
        return self._writer

    async def _async_setup(self) -> None:
        """Set up the coordinator."""
        await self._connect()

    async def _connect(self) -> None:
        """Connect to the telemetry stream."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=TIMEOUT,
            )
            _LOGGER.info("Connected to %s:%s", self.host, self.port)
            self._data.available = True
            self.hass.loop.create_task(self._read_loop())
        except Exception as ex:
            _LOGGER.warning(
                "Could not connect to %s:%s: %s", self.host, self.port, ex
            )
            self._data.available = False
            self._schedule_reconnect()

    async def _read_loop(self) -> None:
        """Read and parse lines from the telemetry stream."""
        buf = b""
        try:
            while not self._shutdown and self._reader is not None:
                try:
                    chunk = await asyncio.wait_for(
                        self._reader.read(4096),
                        timeout=TIMEOUT,
                    )
                except TimeoutError:
                    # heartbeat — send a keep-alive read timeout is normal
                    continue

                if not chunk:
                    break

                buf += chunk
                while b"\r\n" in buf:
                    line, buf = buf.split(b"\r\n", 1)
                    self._parse_line(line.strip())

                if len(buf) > 65536:
                    _LOGGER.warning("Buffer overflow, resetting")
                    buf = b""

            _LOGGER.info("Telemetry stream ended")
        except Exception as ex:
            _LOGGER.warning("Read error: %s", ex)
        finally:
            self._data.available = False
            self.async_set_updated_data(self._data)
            self._schedule_reconnect()

    def _parse_line(self, line: bytes) -> None:
        """Parse a single telemetry line."""
        if not line:
            return

        line = line.lstrip(b"\n").strip()
        if not line:
            return

        text = line.decode()

        if text.startswith("SET_RELAY="):
            self._data.relays[text[len("SET_RELAY="):]] = True
            self.async_set_updated_data(self._data)
            return
        if text.startswith("CLEAR_RELAY="):
            self._data.relays[text[len("CLEAR_RELAY="):]] = False
            self.async_set_updated_data(self._data)
            return

        parts = line.split(None, 1)

        if len(parts) >= 2:
            device = parts[0].decode()
            payload = parts[1].decode()

            m = re.match(r"SET_(\w+)=(\S+)", payload)
            if m:
                key = m.group(1)
                value = m.group(2)
                if device.startswith("TSTAT_"):
                    self._parse_tstat(device, key, value)
                    return
                if device.startswith("@"):
                    self._parse_btle(device[1:], key, value)
                    return
            return

        m = re.match(r"SET_(\w+)=(\S+)", text)
        if m:
            key = m.group(1)
            value = m.group(2)
            if key == "OUTSIDE_TEMP":
                self._data.outside_temp = self._parse_tenths(value)
            elif key == "RELAY":
                self._data.relays[value] = True
            self.async_set_updated_data(self._data)

    def _parse_tstat(self, device: str, key: str, value: str) -> None:
        """Parse a TSTAT record."""
        if key == "TEMP":
            self._data.temp = self._parse_tenths(value)
        elif key == "TEMP_SP":
            self._data.temp_sp = self._parse_tenths(value)
        elif key == "HUMIDITY":
            self._data.humidity = self._parse_tenths(value)
        elif key == "HUMIDITY_SP":
            self._data.humidity_sp = self._parse_tenths(value)
        elif key == "HVAC_MODE":
            self._data.hvac_mode = value
        elif key == "HVAC_STATE":
            self._data.hvac_state = value
        elif key == "FAN_MODE":
            self._data.fan_mode = int(value)
        elif key == "FAN_STAGE":
            self._data.fan_stage = int(value)
        elif key == "NAME":
            self._data.name = value
        elif key == "TEMP_TOLERANCE":
            self._data.temp_tolerance = self._parse_tenths(value)
        self.async_set_updated_data(self._data)

    def _parse_btle(self, mac: str, key: str, value: str) -> None:
        """Parse a BTLE sensor record."""
        if mac not in self._data.btle_sensors:
            self._data.btle_sensors[mac] = {"rssi": None, "batt": None}
        if key.endswith("RSSI"):
            self._data.btle_sensors[mac]["rssi"] = int(value)
        elif key.endswith("BATT"):
            volts = int(value) / 100.0
            self._data.btle_sensors[mac]["batt"] = volts
        self.async_set_updated_data(self._data)

    @staticmethod
    def _parse_tenths(value: str) -> float | None:
        """Parse a value stored as tenths (e.g. '0773' -> 77.3)."""
        try:
            return int(value) / 10.0
        except (TypeError, ValueError):
            return None

    def _schedule_reconnect(self) -> None:
        """Schedule a reconnection attempt."""
        if self._shutdown:
            return
        self._reconnect_task = self.hass.loop.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        """Reconnect with backoff."""
        delay = 5
        while not self._shutdown:
            _LOGGER.debug("Reconnecting in %d seconds", delay)
            await asyncio.sleep(delay)
            if self._shutdown:
                return
            try:
                await self._connect()
                return
            except Exception:
                delay = min(delay * 2, 300)

    async def send_command(self, command: str) -> None:
        """Send a command to the telemetry stream."""
        if not self._writer or self._writer.is_closing():
            _LOGGER.warning("Cannot send command: not connected")
            return
        cmd_bytes = f"{command}\r\n".encode()
        self._writer.write(cmd_bytes)
        await self._writer.drain()

    async def async_shutdown(self) -> None:
        """Shut down the coordinator."""
        self._shutdown = True
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._reader = None
