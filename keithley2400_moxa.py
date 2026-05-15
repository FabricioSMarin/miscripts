#!/usr/bin/env python3
"""
Control a Keithley 2400 SourceMeter via Moxa RS232 (TCP to NPort) or direct serial.

Connection options:
  - Moxa NPort (TCP): use host and port, e.g. host='192.168.1.100', port=4001
  - Direct serial: use port path, e.g. port='/dev/ttyUSB0' or 'COM3'

Requires: pyserial
  pip install pyserial
"""

import re
import time
from typing import Optional, Tuple, Union

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    raise ImportError("Install pyserial: pip install pyserial")


# Default RS-232 settings for Keithley 2400 (see instrument setup menu)
DEFAULT_BAUD = 9600
DEFAULT_BYTESIZE = serial.EIGHTBITS
DEFAULT_PARITY = serial.PARITY_NONE
DEFAULT_STOPBITS = serial.STOPBITS_ONE
DEFAULT_TIMEOUT = 2.0
DEFAULT_WRITE_TIMEOUT = 2.0

HOST = "10.54.113.9"


class Keithley2400Error(Exception):
    """Raised when the instrument reports an error or a command fails."""
    pass


class Keithley2400:
    """
    Control interface for Keithley 2400 SourceMeter over RS-232 (direct or via Moxa NPort).
    """

    def __init__(
        self,
        port: Optional[str] = None,
        host: Optional[str] = HOST,
        port_number: int = 4004,
        baudrate: int = DEFAULT_BAUD,
        bytesize: int = DEFAULT_BYTESIZE,
        parity: str = DEFAULT_PARITY,
        stopbits: float = DEFAULT_STOPBITS,
        timeout: float = DEFAULT_TIMEOUT,
        write_timeout: float = DEFAULT_WRITE_TIMEOUT,
    ):
        """
        Open connection to the Keithley 2400.

        For Moxa NPort (TCP):
          host='192.168.1.100', port_number=4001
          Do not set 'port'.

        For direct serial (local COM or USB-RS232):
          port='/dev/ttyUSB0' (Linux/Mac) or port='COM3' (Windows)
          Do not set host/port_number.
        """
        self._ser: Optional[serial.Serial] = None
        self._opened_here = False

        print(f"host: {host}")

        if host is not None:
            # Moxa NPort: connect via TCP socket (pyserial socket URL)
            url = f"socket://{host}:{port_number}"
            self._ser = serial.serial_for_url(
                url,
                baudrate=baudrate,
                bytesize=bytesize,
                parity=parity,
                stopbits=stopbits,
                timeout=timeout,
                write_timeout=write_timeout,
            )
            self._opened_here = True
        elif port is not None:
            self._ser = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=bytesize,
                parity=parity,
                stopbits=stopbits,
                timeout=timeout,
                write_timeout=write_timeout,
            )
            self._opened_here = True
        else:
            raise ValueError("Provide either port= (serial path) or host= (Moxa IP).")

        # Terminators: Keithley 2400 typically uses CR+LF or LF on RS-232
        self._ser.write_termination = "\r\n"
        self._ser.readline()  # discard any leftover data

    def close(self) -> None:
        """Close the serial/socket connection."""
        if self._ser and self._opened_here:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def __enter__(self) -> "Keithley2400":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def write(self, cmd: str) -> None:
        """Send a SCPI command (no response expected)."""
        if not cmd.endswith("\n") and "\n" not in cmd:
            cmd = cmd.strip() + "\r\n"
        self._ser.write(cmd.encode("ascii"))

    def query(self, cmd: str, strip: bool = True) -> str:
        """Send a SCPI query and return the response."""
        self.write(cmd)
        time.sleep(0.05)
        out = self._ser.readline().decode("ascii", errors="replace")
        if strip:
            out = out.strip()
        return out

    def idn(self) -> str:
        """Return instrument identification (*IDN?)."""
        return self.query("*IDN?")

    def reset(self) -> None:
        """Reset instrument to default state (*RST)."""
        self.write("*RST")
        time.sleep(0.5)

    def clear(self) -> None:
        """Clear status (*CLS)."""
        self.write("*CLS")

    def error_query(self) -> Tuple[int, str]:
        """Return next error in queue (0, 'No error') if none. Returns (code, message)."""
        s = self.query(":SYST:ERR?")
        # Format: "+0, No error" or "-123, Message"
        m = re.match(r"\s*([+-]?\d+)\s*,\s*(.+)", s)
        if m:
            return int(m.group(1)), m.group(2).strip()
        return 0, s

    def check_errors(self) -> None:
        """Raise Keithley2400Error if the instrument has an error in the queue."""
        code, msg = self.error_query()
        if code != 0:
            raise Keithley2400Error(f"Keithley 2400 error {code}: {msg}")

    # --- Source configuration ---

    def set_source_voltage(self, level_volts: float) -> None:
        """Set source function to voltage and set level (V)."""
        self.write(f":SOUR:FUNC VOLT")
        self.write(f":SOUR:VOLT:LEV {level_volts:.6e}")
        self.check_errors()

    def set_source_current(self, level_amps: float) -> None:
        """Set source function to current and set level (A)."""
        self.write(":SOUR:FUNC CURR")
        self.write(f":SOUR:CURR:LEV {level_amps:.6e}")
        self.check_errors()

    def set_compliance_voltage(self, volts: float) -> None:
        """Set voltage compliance limit when sourcing current (V)."""
        self.write(f":SENS:VOLT:PROT {volts:.6e}")
        self.check_errors()

    def set_compliance_current(self, amps: float) -> None:
        """Set current compliance limit when sourcing voltage (A)."""
        self.write(f":SENS:CURR:PROT {amps:.6e}")
        self.check_errors()

    def output_on(self) -> None:
        """Enable output."""
        self.write(":OUTP ON")
        self.check_errors()

    def output_off(self) -> None:
        """Disable output."""
        self.write(":OUTP OFF")
        self.check_errors()

    def set_output_state(self, on: bool) -> None:
        """Set output on (True) or off (False)."""
        self.write(":OUTP ON" if on else ":OUTP OFF")
        self.check_errors()

    # --- Measurement configuration ---

    def set_measure_voltage(self) -> None:
        """Configure to measure voltage."""
        self.write(':SENS:FUNC "VOLT"')
        self.check_errors()

    def set_measure_current(self) -> None:
        """Configure to measure current."""
        self.write(':SENS:FUNC "CURR"')
        self.check_errors()

    def set_format_elements(self, *elements: str) -> None:
        """Set reading format elements, e.g. ('VOLT', 'CURR') for voltage and current."""
        elem_str = ",".join(elements)
        self.write(f":FORM:ELEM {elem_str}")
        self.check_errors()

    def read(self) -> str:
        """Trigger one measurement and return the reading (string)."""
        return self.query(":READ?")

    def read_voltage_current(self) -> Tuple[float, float]:
        """Trigger one measurement; return (voltage_V, current_A). Configure format first if needed."""
        self.set_format_elements("VOLT", "CURR")
        s = self.read()
        parts = [float(x) for x in s.split(",")]
        if len(parts) >= 2:
            return parts[0], parts[1]
        if len(parts) == 1:
            return parts[0], 0.0
        raise Keithley2400Error(f"Unexpected READ? response: {s!r}")

    def ramp_to_voltage(self, target_v: float, steps: int = 30, pause: float = 0.02) -> None:
        """Ramp source voltage from current level to target_v over steps.
        Uses write-only commands per step (no query) so step delay matches pause."""
        current = self.query(":SOUR:VOLT:LEV?")
        try:
            start_v = float(current)
        except ValueError:
            start_v = 0.0
        self.write(":SOUR:FUNC VOLT")
        for i in range(1, steps + 1):
            v = start_v + (target_v - start_v) * i / steps
            self.write(f":SOUR:VOLT:LEV {v:.6e}")
            time.sleep(pause)
        self.check_errors()

    def ramp_to_current(self, target_a: float, steps: int = 30, pause: float = 0.02) -> None:
        """Ramp source current from current level to target_a over steps.
        Uses write-only commands per step (no query) so step delay matches pause."""
        current = self.query(":SOUR:CURR:LEV?")
        try:
            start_a = float(current)
        except ValueError:
            start_a = 0.0
        self.write(":SOUR:FUNC CURR")
        for i in range(1, steps + 1):
            a = start_a + (target_a - start_a) * i / steps
            self.write(f":SOUR:CURR:LEV {a:.6e}")
            time.sleep(pause)
        self.check_errors()

    def shutdown(self) -> None:
        """Ramp to zero and turn output off (safe shutdown)."""
        try:
            mode = self.query(":SOUR:FUNC?").strip().upper()
            if "CURR" in mode:
                self.ramp_to_current(0.0)
            else:
                self.ramp_to_voltage(0.0)
        except Exception:
            pass
        self.output_off()

    def get_source_voltage(self) -> float:
        """Return current source voltage level (V)."""
        return float(self.query(":SOUR:VOLT:LEV?"))

    def voltage_sweep(
        self,
        v_start: float,
        v_stop: float,
        steps: int,
        step_delay: float = 0.05,
        output_was_on: Optional[bool] = None,
    ) -> list:
        """
        Perform a voltage sweep: set source to voltage, then step from v_start to v_stop,
        trigger one reading at each step. Returns list of (voltage_V, current_A) tuples.

        If output_was_on is None, output is left as-is. If True/False, output is
        turned on at start and optionally restored at end.
        """
        self.set_source_voltage(v_start)
        self.set_format_elements("VOLT", "CURR")
        if output_was_on is not None:
            self.output_on()
            time.sleep(0.1)
        results = []
        for i in range(steps + 1):
            v = v_start + (v_stop - v_start) * i / max(steps, 1)
            self.write(f":SOUR:VOLT:LEV {v:.6e}")
            time.sleep(step_delay)
            v_read, i_read = self.read_voltage_current()
            results.append((v_read, i_read))
        if output_was_on is False:
            self.ramp_to_voltage(0.0)
            self.output_off()
        return results


def list_serial_ports() -> list:
    """Return list of (port, description) for available serial ports."""
    return [(p.device, p.description or p.device) for p in serial.tools.list_ports.comports()]


def _example_voltage_commands(smu: Keithley2400) -> None:
    """Example: issue voltage source commands (no output; safe to run)."""
    print("--- Voltage command examples ---")
    smu.reset()
    time.sleep(0.3)
    smu.set_source_voltage(0.0)
    print("Set voltage to 0 V")
    smu.set_source_voltage(1.0)
    print("Set voltage to 1.0 V")
    v = smu.get_source_voltage()
    print(f"  Query level: {v:.3f} V")
    smu.set_source_voltage(2.5)
    print("Set voltage to 2.5 V")
    smu.set_source_voltage(-0.5)
    print("Set voltage to -0.5 V")
    smu.ramp_to_voltage(0.0, steps=20, pause=0.02)
    print("Ramped back to 0 V")
    smu.set_source_voltage(0.0)
    print("Done (output was never turned on).")


def _example_measurements(smu: Keithley2400) -> None:
    """Example: source a voltage and take different kinds of measurements."""
    print("--- Measurement examples ---")
    smu.reset()
    time.sleep(0.3)
    smu.set_source_voltage(1.0)
    smu.set_compliance_current(0.1)
    smu.output_on()
    time.sleep(0.2)

    # Single reading: voltage and current
    smu.set_format_elements("VOLT", "CURR")
    v, i = smu.read_voltage_current()
    print(f"Single reading (V, I): V={v:.6f} V, I={i:.6e} A")

    # Voltage-only measurement
    smu.set_format_elements("VOLT")
    v_str = smu.read()
    print(f"Voltage only (raw): {v_str}")

    # Current-only measurement
    smu.set_format_elements("CURR")
    i_str = smu.read()
    print(f"Current only (raw): {i_str}")

    # Multiple readings
    smu.set_format_elements("VOLT", "CURR")
    print("Three readings:")
    for n in range(3):
        v, i = smu.read_voltage_current()
        print(f"  #{n+1}: V={v:.6f} V, I={i:.6e} A")
        time.sleep(0.05)

    smu.shutdown()
    print("Output off.")


def _example_voltage_sweep(smu: Keithley2400) -> None:
    """Example: voltage sweep from 0 V to 1 V, record current at each step."""
    print("--- Voltage sweep example (0 V -> 1 V, 11 steps) ---")
    smu.reset()
    time.sleep(0.3)
    smu.set_source_voltage(0.0)
    smu.set_compliance_current(0.1)
    smu.set_measure_current()

    results = smu.voltage_sweep(0.0, 1.0, steps=10, step_delay=0.05, output_was_on=False)
    smu.output_off()

    print("  V_set (V)    V_read (V)   I (A)")
    print("  " + "-" * 40)
    for (v_read, i_read) in results:
        print(f"  {v_read:10.4f}   {v_read:10.4f}   {i_read:.6e}")
    print(f"  ({len(results)} points)")
    print("Sweep done.")


def main() -> None:
    """Example: connect via Moxa (TCP) or serial, identify, then run chosen example."""
    import argparse
    parser = argparse.ArgumentParser(description="Keithley 2400 via Moxa RS232 or serial")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--port", "-p", help="Serial port (e.g. /dev/ttyUSB0 or COM3)")
    g.add_argument("--moxa", "-m", metavar="HOST", help="Moxa NPort IP (e.g. 192.168.1.100)")
    parser.add_argument("--moxa-port", type=int, default=4001, help="Moxa TCP port (default 4001)")
    parser.add_argument("--list", action="store_true", help="List serial ports and exit")
    parser.add_argument("--no-run", action="store_true", help="Only open, *IDN?, close (no source/measure)")
    parser.add_argument(
        "--example",
        choices=["default", "voltage_commands", "measurements", "sweep"],
        default="default",
        help="Which example to run: default (one V/I read), voltage_commands, measurements, sweep",
    )
    args = parser.parse_args()

    if args.list:
        for port, desc in list_serial_ports():
            print(f"  {port}: {desc}")
        return

    port = args.port
    host = args.moxa
    moxa_port: int = args.moxa_port

    try:
        if host:
            smu = Keithley2400(host=host, port_number=moxa_port)
        else:
            smu = Keithley2400(port=port)

        print("IDN:", smu.idn())
        smu.clear()
        smu.check_errors()

        if args.no_run:
            return

        if args.example == "default":
            # Original: source voltage, measure current, one read
            smu.reset()
            time.sleep(0.5)
            smu.set_source_voltage(0.0)
            smu.set_compliance_current(0.1)
            smu.set_measure_current()
            smu.output_on()
            time.sleep(0.2)
            v, i = smu.read_voltage_current()
            print(f"Reading: V={v:.6f} V, I={i:.6e} A")
            smu.shutdown()
        elif args.example == "voltage_commands":
            _example_voltage_commands(smu)
        elif args.example == "measurements":
            _example_measurements(smu)
        elif args.example == "sweep":
            _example_voltage_sweep(smu)
    except Keithley2400Error as e:
        print("Instrument error:", e)
        raise
    finally:
        if "smu" in dir() and smu is not None:
            smu.close()


if __name__ == "__main__":
    main()