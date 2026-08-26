# electronic-devices

Live plots and control utilities for lab instruments.

## Dependencies

```bash
pip install -r requirements-ids3010.txt      # IDS plotters (matplotlib)
pip install -r requirements-keithley2400.txt # Keithley (pyserial)
```

IDS plotters also need Tkinter (usually bundled with Python on macOS/Windows; on Linux install `python3-tk`).

---

## `ids3010_plotter.py`

GUI live plotter for an attocube IDS3010 interferometer (3 channels) over JSON-RPC on TCP port 9090.

```bash
python ids3010_plotter.py
```

Enter the device host in the GUI, connect, then acquire / export CSV as needed.

---

## `keithley2400_moxa.py`

Control a Keithley 2400 SourceMeter via Moxa NPort (TCP) or a local serial port.

```bash
# List serial ports (-p or -m is still required by the CLI)
python keithley2400_moxa.py -p /dev/ttyUSB0 --list

# Identify only (no source/measure)
python keithley2400_moxa.py -m 192.168.1.100 --no-run
python keithley2400_moxa.py -p /dev/ttyUSB0 --no-run

# Connect via Moxa, source voltage, measure current (demo run)
python keithley2400_moxa.py -m 192.168.1.100 --moxa-port 4001

# Direct serial
python keithley2400_moxa.py -p COM3
```

As a library:

```python
from keithley2400_moxa import Keithley2400

smu = Keithley2400(host="192.168.1.100", port_number=4001)
print(smu.idn())
smu.close()
```
