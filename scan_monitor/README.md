# scan_monitor

Monitor EPICS 2D scan orchestration, log PV snapshots, and plot flag events.

## Dependencies

```bash
pip install -r requirements-scan-monitor.txt
```

---

## `scan_monitor.py`

Main monitor. Reads PV definitions from a JSON config (`scan_started`, `scan_parameters`, `flags`, `flag_events`, …).

```bash
# Live monitor with default config (scan_monitor_config.json)
python scan_monitor.py

# Beamline-specific config
python scan_monitor.py -c scan_monitor_config_2idd.json
python scan_monitor.py -c scan_monitor_config_8bmb.json -o /tmp/scan_monitor_out

# Demo outputs without EPICS
python scan_monitor.py --demo

# Live plot only (no log/CSV/JSONL/PNG writes)
python scan_monitor.py --plot-only

# Headless logging (no interactive timeline window)
python scan_monitor.py --no-live-plot

# Check whether a monitor for this config/beamline is already running
python scan_monitor.py -c scan_monitor_config_2idd.json --check
```

---

## `scan_monitor_flags.py`

Flag-event detectors imported by `scan_monitor.py`. Not meant to be run directly; each function returns `True` when a fault condition is detected from the PV context dict supplied by the monitor.

Configure which detectors run via the `flags` section of the JSON config.
