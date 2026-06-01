"""
kiprim_dc605pro.py
==================
Python library for the Kiprim DC605Pro (and compatible DC310Pro / DC310S)
programmable DC power supply via USB-serial (SCPI-like protocol).

Compatible hardware
-------------------
- Kiprim DC605Pro  (0-60 V / 0-5 A)
- Kiprim DC310Pro  (0-30 V / 0-10 A)
- Kiprim DC310S    (0-30 V / 0-10 A)
- OWON SPE3103 / SPP3103 (same firmware)

Usage
-----
    from kiprim_dc605pro import DC605Pro

    with DC605Pro("COM3") as psu:          # or "/dev/ttyUSB0"
        psu.set_voltage(12.0)
        psu.set_current(1.5)
        psu.output_on()
        v = psu.measure_voltage()
        i = psu.measure_current()
        print(f"{v:.3f} V  {i:.3f} A  {v*i:.3f} W")
        psu.output_off()
"""

import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

try:
    import serial
except ImportError as exc:
    raise ImportError(
        "pyserial is required: pip install pyserial"
    ) from exc


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DC605ProError(Exception):
    """Base exception for all library errors."""


class CommunicationError(DC605ProError):
    """Raised when a serial command fails or returns ERR."""


class RangeError(DC605ProError):
    """Raised when a set-point is outside the device limits."""


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class DeviceInfo:
    manufacturer: str
    model: str
    serial_number: str
    firmware: str

    def __str__(self) -> str:
        return (
            f"{self.manufacturer} {self.model} | "
            f"S/N: {self.serial_number} | FW: {self.firmware}"
        )


@dataclass
class Measurement:
    voltage: float   # V
    current: float   # A
    power: float     # W  (computed from V × I)

    def __str__(self) -> str:
        return f"{self.voltage:.3f} V  {self.current:.3f} A  {self.power:.3f} W"


# ---------------------------------------------------------------------------
# Main driver class
# ---------------------------------------------------------------------------

class DC605Pro:
    """
    Driver for the Kiprim DC605Pro (and compatible) power supply.

    Parameters
    ----------
    port : str
        Serial port, e.g. ``"COM3"`` (Windows) or ``"/dev/ttyUSB0"`` (Linux).
    timeout : float
        Read timeout in seconds (default 2.0).
    voltage_max : float
        Soft-limit for voltage set-point (default 60.0 V for DC605Pro).
    current_max : float
        Soft-limit for current set-point (default 5.0 A for DC605Pro).
    """

    BAUD_RATE = 115200
    DEFAULT_TIMEOUT = 3.0

    def __init__(
        self,
        port: str,
        timeout: float = DEFAULT_TIMEOUT,
        voltage_max: float = 60.0,
        current_max: float = 5.0,
    ) -> None:
        self._port = port
        self._timeout = timeout
        self.voltage_max = voltage_max
        self.current_max = current_max
        self._lock = threading.Lock()
        self._ser: Optional[serial.Serial] = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the serial connection."""
        if self._ser and self._ser.is_open:
            return
        self._ser = serial.Serial(
            port=self._port,
            baudrate=self.BAUD_RATE,
            bytesize=8,
            parity=serial.PARITY_NONE,
            stopbits=1,
            timeout=self._timeout,
        )
        # Let the USB-CDC adapter enumerate and the device boot
        time.sleep(0.5)
        self._ser.reset_input_buffer()

    def disconnect(self) -> None:
        """Close the serial connection."""
        if self._ser and self._ser.is_open:
            self._ser.close()

    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    # Context-manager support
    def __enter__(self) -> "DC605Pro":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # Low-level I/O
    # ------------------------------------------------------------------

    def _send(self, command: str) -> None:
        """Send a command string (line-feed terminated, no response expected)."""
        with self._lock:
            if not self.is_connected():
                raise CommunicationError("Not connected. Call connect() first.")
            self._ser.reset_input_buffer()
            self._ser.write((command + "\n").encode("ascii"))
            # Give the device time to process before the next command
            time.sleep(0.05)

    def _query(self, command: str) -> str:
        """Send a command and return the stripped response line."""
        with self._lock:
            if not self.is_connected():
                raise CommunicationError("Not connected. Call connect() first.")
            self._ser.reset_input_buffer()
            self._ser.write((command + "\n").encode("ascii"))
            raw = self._ser.readline()
            if not raw:
                raise CommunicationError(
                    f"No response to command '{command}' (timeout)."
                )
            response = raw.decode("ascii", errors="replace").strip()
            if response.upper() == "ERR":
                raise CommunicationError(
                    f"Device returned ERR for command '{command}'."
                )
            return response

    def _query_float(self, command: str) -> float:
        """Query a command and parse the response as float."""
        response = self._query(command)
        try:
            return float(response)
        except ValueError:
            raise CommunicationError(
                f"Expected float for '{command}', got '{response}'."
            )

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------

    def identify(self) -> DeviceInfo:
        """
        Query ``*idn?`` and return a :class:`DeviceInfo` object.

        Returns
        -------
        DeviceInfo
            manufacturer, model, serial_number, firmware
        """
        raw = self._query("*idn?")
        parts = raw.split(",")
        if len(parts) < 4:
            raise CommunicationError(f"Unexpected IDN response: '{raw}'")
        manufacturer = parts[0].strip()
        model = parts[1].strip()
        serial_number = parts[2].strip()
        firmware = parts[3].strip()
        return DeviceInfo(manufacturer, model, serial_number, firmware)

    # ------------------------------------------------------------------
    # Output control
    # ------------------------------------------------------------------

    def output_on(self) -> None:
        """Enable the power supply output."""
        self._send("output 1")

    def output_off(self) -> None:
        """Disable the power supply output."""
        self._send("output 0")

    def set_output(self, enabled: bool) -> None:
        """Enable or disable the output."""
        self._send(f"output {1 if enabled else 0}")

    def get_output(self) -> bool:
        """
        Query whether the output is currently on.

        Returns
        -------
        bool
            ``True`` if output is ON.
        """
        response = self._query("output?")
        return response.upper() == "ON"

    # ------------------------------------------------------------------
    # Voltage control
    # ------------------------------------------------------------------

    def set_voltage(self, volts: float) -> None:
        """
        Set the output voltage.

        Parameters
        ----------
        volts : float
            Target voltage in V (0 to ``voltage_max``).
        """
        self._check_range("voltage", volts, 0.0, self.voltage_max)
        self._send(f"voltage {volts:.3f}")

    def get_voltage_setpoint(self) -> float:
        """Return the programmed (set-point) voltage in V."""
        return self._query_float("voltage?")

    def measure_voltage(self) -> float:
        """Return the actual measured output voltage in V."""
        return self._query_float("measure:voltage?")

    # ------------------------------------------------------------------
    # Current control
    # ------------------------------------------------------------------

    def set_current(self, amps: float) -> None:
        """
        Set the output current limit.

        Parameters
        ----------
        amps : float
            Target current in A (0 to ``current_max``).
        """
        self._check_range("current", amps, 0.0, self.current_max)
        self._send(f"current {amps:.3f}")

    def get_current_setpoint(self) -> float:
        """Return the programmed (set-point) current in A."""
        return self._query_float("current?")

    def measure_current(self) -> float:
        """Return the actual measured output current in A."""
        return self._query_float("measure:current?")

    # ------------------------------------------------------------------
    # Power measurement
    # ------------------------------------------------------------------

    def measure_power(self) -> float:
        """
        Return actual output power in W.

        Tries the ``measure:power?`` command first; falls back to V × I
        if the device does not support it.
        """
        try:
            return self._query_float("measure:power?")
        except CommunicationError:
            v = self.measure_voltage()
            i = self.measure_current()
            return round(v * i, 6)

    def measure_all(self) -> Measurement:
        """
        Return a :class:`Measurement` snapshot (voltage, current, power).

        Uses two serial round-trips; for tighter timing call
        :meth:`measure_voltage` and :meth:`measure_current` separately.
        """
        v = self.measure_voltage()
        i = self.measure_current()
        return Measurement(voltage=v, current=i, power=round(v * i, 6))

    # ------------------------------------------------------------------
    # Protection limits (OVP / OCP)
    # ------------------------------------------------------------------

    def set_voltage_limit(self, volts: float) -> None:
        """
        Set the over-voltage protection (OVP) threshold.

        Parameters
        ----------
        volts : float
            OVP threshold in V.
        """
        self._check_range("voltage limit", volts, 0.0, self.voltage_max)
        self._send(f"voltage:limit {volts:.3f}")

    def get_voltage_limit(self) -> float:
        """Return the OVP threshold in V."""
        return self._query_float("voltage:limit?")

    def set_current_limit(self, amps: float) -> None:
        """
        Set the over-current protection (OCP) threshold.

        Parameters
        ----------
        amps : float
            OCP threshold in A.
        """
        self._check_range("current limit", amps, 0.0, self.current_max)
        self._send(f"current:limit {amps:.3f}")

    def get_current_limit(self) -> float:
        """Return the OCP threshold in A."""
        return self._query_float("current:limit?")

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Send ``*RST`` to restore factory defaults (turns output off)."""
        self._send("*RST")
        time.sleep(0.5)   # allow the device to reinitialise

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def configure(
        self,
        voltage: float,
        current: float,
        ovp: Optional[float] = None,
        ocp: Optional[float] = None,
    ) -> None:
        """
        Set voltage, current and optionally protection limits in one call.

        Parameters
        ----------
        voltage : float
            Output voltage in V.
        current : float
            Output current in A.
        ovp : float, optional
            Over-voltage protection threshold in V.
        ocp : float, optional
            Over-current protection threshold in A.
        """
        self.set_voltage(voltage)
        self.set_current(current)
        if ovp is not None:
            self.set_voltage_limit(ovp)
        if ocp is not None:
            self.set_current_limit(ocp)
        # Allow the device to finish processing all set commands
        time.sleep(0.3)

    @contextmanager
    def powered(self, voltage: float, current: float):
        """
        Context manager that enables output for the duration of the block
        and ensures the output is turned off on exit.

        Example
        -------
        ::

            with psu.powered(5.0, 0.5):
                time.sleep(2)
                print(psu.measure_all())
        """
        self.set_voltage(voltage)
        self.set_current(current)
        self.output_on()
        try:
            yield self
        finally:
            self.output_off()

    def ramp_voltage(
        self,
        start: float,
        stop: float,
        duration: float,
        steps: int = 100,
        output_on: bool = True,
    ) -> None:
        """
        Linearly ramp the output voltage from *start* to *stop* over *duration* seconds.

        Parameters
        ----------
        start : float
            Starting voltage in V.
        stop : float
            Ending voltage in V.
        duration : float
            Total ramp time in seconds.
        steps : int
            Number of incremental steps (default 100).
        output_on : bool
            If True, enable output before ramping (default True).
        """
        if steps < 2:
            raise ValueError("steps must be >= 2")
        self.set_voltage(start)
        if output_on:
            self.output_on()
        delay = duration / (steps - 1)
        step_size = (stop - start) / (steps - 1)
        for i in range(steps):
            v = round(start + i * step_size, 3)
            self.set_voltage(v)
            if i < steps - 1:
                time.sleep(delay)

    def list_mode(
        self,
        steps: list[dict],
        repeat: int = 1,
    ) -> None:
        """
        Execute a simple software list mode (sequence of voltage/current steps).

        Each step is a dict with keys:
        - ``"voltage"`` (float, V)
        - ``"current"`` (float, A)
        - ``"duration"`` (float, seconds)

        Parameters
        ----------
        steps : list[dict]
            Sequence of step dicts.
        repeat : int
            Number of times to repeat the sequence (default 1).

        Example
        -------
        ::

            psu.list_mode([
                {"voltage": 5.0, "current": 1.0, "duration": 2.0},
                {"voltage": 12.0, "current": 0.5, "duration": 3.0},
                {"voltage": 0.0, "current": 0.1, "duration": 1.0},
            ], repeat=2)
        """
        self.output_on()
        for _ in range(repeat):
            for step in steps:
                self.set_voltage(step["voltage"])
                self.set_current(step["current"])
                time.sleep(step["duration"])
        self.output_off()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_range(self, name: str, value: float, lo: float, hi: float) -> None:
        if not (lo <= value <= hi):
            raise RangeError(
                f"{name} {value} is out of range [{lo}, {hi}]."
            )

    def __repr__(self) -> str:
        status = "connected" if self.is_connected() else "disconnected"
        return f"DC605Pro(port={self._port!r}, {status})"


# ---------------------------------------------------------------------------
# Quick-test / demo  (python kiprim_dc605pro.py COM3)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    port = sys.argv[1] if len(sys.argv) > 1 else "COM3"
    print(f"Connecting to {port} …")

    with DC605Pro(port) as psu:
        info = psu.identify()
        print(f"Device : {info}")
        print(f"Output : {'ON' if psu.get_output() else 'OFF'}")
        print(f"Set V  : {psu.get_voltage_setpoint():.3f} V")
        print(f"Set I  : {psu.get_current_setpoint():.3f} A")
        print(f"Meas   : {psu.measure_all()}")