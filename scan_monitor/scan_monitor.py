#!/usr/bin/env python3
"""
Monitor EPICS scan orchestration and log PV snapshots for each 2D scan.

Reads PV definitions from a JSON config with these sections:
  - scan_started: PVs whose state change marks the start of a 2D scan
  - scan_parameters: PVs logged once per scan at scan start
  - flags: per-flag input PVs; read each poll and passed as the context
    dict to the matching function in scan_monitor_flags.py, which applies
    the multi-PV calculation and returns True on a fault
  - flag_events: diagnostic-snapshot PVs logged when any flag fires
  - environment_variables: process env vars applied before EPICS connects

Outputs (written to output_dir from config):
  - scan_monitor.log          session text log
  - scans.csv                 one row per completed 2D scan
  - flag_events.jsonl         one record per flag event
  - spreadsheet_view.png      tabular view of scans.csv
  - event_time_plot.png       timeline of scan starts and flag events
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

from scan_monitor_flags import FLAG_FUNCTIONS, marker_color

epics: Any = None


@dataclass
class ScanRecord:
    timestamp: float
    iso_time: str
    scan_number: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class TimelineEvent:
    timestamp: float
    iso_time: str
    kind: str
    label: str
    color: str
    scan_number: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def utc_now() -> tuple[float, str]:
    dt = datetime.now(timezone.utc)
    return dt.timestamp(), dt.isoformat(timespec="milliseconds")


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        config = json.load(f)
    for section in ("scan_started", "scan_parameters", "flag_events"):
        if section not in config:
            raise ValueError(f"config missing required section {section!r}")
    return config


def apply_environment_variables(env: dict[str, Any] | None) -> None:
    if not env:
        return
    for key, value in env.items():
        if value is not None:
            os.environ[str(key)] = str(value)


def ensure_epics() -> Any:
    global epics
    if epics is None:
        try:
            import epics as epics_mod
        except ImportError as exc:
            raise RuntimeError("pyepics is not installed") from exc
        epics = epics_mod
    return epics


def coerce_pv_string(value: Any) -> str:
    """Decode EPICS string/waveform PV values to a plain str."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.rstrip("\x00")
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace").rstrip("\x00")
    try:
        seq = value.tolist() if hasattr(value, "tolist") else value
        if isinstance(seq, (list, tuple)) and seq and isinstance(seq[0], (int, float)):
            return "".join(chr(int(c)) for c in seq if int(c) != 0)
    except (TypeError, ValueError):
        pass
    return str(value).rstrip("\x00")


def pv_value(pv_name: str, *, as_string: bool = False) -> Any:
    ep = ensure_epics()
    if as_string:
        value = ep.caget(pv_name, timeout=2.0, as_string=True)
    else:
        value = ep.caget(pv_name, timeout=2.0)
    if value is None:
        raise RuntimeError(f"failed to read PV {pv_name!r}")
    if as_string:
        return coerce_pv_string(value)
    return value


def read_labeled_pvs(entries: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for entry in entries:
        label = entry.get("label") or entry["pv"]
        out[label] = pv_value(entry["pv"], as_string=entry.get("as") == "string")
    return out


def trigger_matches(previous: Any, current: Any, rule: dict[str, Any]) -> bool:
    when = rule.get("when", "changed")
    expected = rule.get("value")

    if when == "changed":
        return previous != current
    if when == "eq":
        return current == expected and previous != expected
    if when == "ne":
        return current != expected and previous == expected
    if when == "rising":
        try:
            return float(previous) < float(expected) <= float(current)
        except (TypeError, ValueError):
            return False
    if when == "falling":
        try:
            return float(previous) >= float(expected) > float(current)
        except (TypeError, ValueError):
            return False
    raise ValueError(f"unknown scan_started trigger {when!r}")


class ScanMonitor:
    def __init__(self, config: dict[str, Any], output_dir: Path) -> None:
        self.config = config
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.scan_number_pv = config.get("scan_number_pv", "SCAN:NN")
        self.scans: list[ScanRecord] = []
        self.timeline: list[TimelineEvent] = []
        self._lock = threading.Lock()
        self._last_scan_started_values: dict[str, Any] = {}
        self._last_flag_fire: dict[str, float] = {}
        self._pvs: list[Any] = []
        self.flag_cooldown_s = float(config.get("flag_cooldown_s", 5.0))
        self.flag_poll_s = float(config.get("flag_poll_s", 1.0))

        self.log_path = self.output_dir / "scan_monitor.log"
        self.scans_csv_path = self.output_dir / "scans.csv"
        self.flag_events_path = self.output_dir / "flag_events.jsonl"
        self.spreadsheet_path = self.output_dir / "spreadsheet_view.png"
        self.event_plot_path = self.output_dir / "event_time_plot.png"

        self._setup_logging()

    def _setup_logging(self) -> None:
        self.logger = logging.getLogger("scan_monitor")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        fh = logging.FileHandler(self.log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        self.logger.addHandler(fh)
        self.logger.addHandler(sh)

    def _append_timeline(self, event: TimelineEvent) -> None:
        with self._lock:
            self.timeline.append(event)

    def _read_scan_number(self) -> str:
        try:
            value = pv_value(self.scan_number_pv)
        except RuntimeError:
            value = "?"
        return str(value)

    def on_scan_started(self) -> None:
        ts, iso_time = utc_now()
        parameters = read_labeled_pvs(self.config["scan_parameters"])
        scan_number = str(parameters.get("scan_number", self._read_scan_number()))

        record = ScanRecord(
            timestamp=ts,
            iso_time=iso_time,
            scan_number=scan_number,
            parameters=parameters,
        )
        with self._lock:
            self.scans.append(record)

        self.logger.info("scan started: scan_number=%s parameters=%s", scan_number, parameters)
        self._append_timeline(
            TimelineEvent(
                timestamp=ts,
                iso_time=iso_time,
                kind="scan_started",
                label=f"scan {scan_number}",
                color="green",
                scan_number=scan_number,
            )
        )
        self.write_outputs()

    def on_flag_event(self, flag_name: str, flag_values: dict[str, Any]) -> None:
        ts, iso_time = utc_now()
        scan_number = self._read_scan_number()
        color = marker_color(flag_name)

        event = TimelineEvent(
            timestamp=ts,
            iso_time=iso_time,
            kind="flag",
            label=flag_name,
            color=color,
            scan_number=scan_number,
            details=flag_values,
        )
        self._append_timeline(event)

        record = {
            "timestamp": ts,
            "iso_time": iso_time,
            "flag": flag_name,
            "scan_number": scan_number,
            "values": flag_values,
        }
        with self.flag_events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        self.logger.warning(
            "flag event: %s scan_number=%s values=%s",
            flag_name,
            scan_number,
            flag_values,
        )
        self.write_outputs()

    def evaluate_flags(self) -> None:
        """Poll each configured flag.

        For every flag listed in the config's ``flags`` section, its ``inputs``
        PVs are read and passed as the ``context`` dict (keyed by label) to the
        matching function in ``scan_monitor_flags.py``. The function applies the
        multi-PV calculation and returns True when the fault condition is met.
        """
        now = time.time()
        flag_specs = self.config.get("flags", {})
        for flag_name, spec in flag_specs.items():
            check = FLAG_FUNCTIONS.get(flag_name)
            if check is None:
                self.logger.warning("no flag function defined for %r; skipping", flag_name)
                continue

            last = self._last_flag_fire.get(flag_name, 0.0)
            if now - last < self.flag_cooldown_s:
                continue

            try:
                context = read_labeled_pvs(spec.get("inputs", []))
            except RuntimeError as exc:
                self.logger.warning("could not read inputs for %s: %s", flag_name, exc)
                continue

            try:
                fired = check(context)
            except Exception as exc:
                self.logger.exception("flag check failed for %s: %s", flag_name, exc)
                continue
            if not fired:
                continue

            self._last_flag_fire[flag_name] = now
            flag_values = read_labeled_pvs(self.config["flag_events"])
            self.on_flag_event(flag_name, flag_values)

    def write_scans_csv(self) -> None:
        with self._lock:
            scans = list(self.scans)
        if not scans:
            if self.scans_csv_path.exists():
                self.scans_csv_path.unlink()
            return

        fieldnames = ["iso_time", "scan_number"]
        for key in scans[-1].parameters:
            if key not in fieldnames:
                fieldnames.append(key)

        with self.scans_csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for scan in scans:
                row = {"iso_time": scan.iso_time, "scan_number": scan.scan_number}
                row.update({k: scan.parameters.get(k, "") for k in fieldnames if k not in row})
                writer.writerow(row)

    def write_spreadsheet_view(self) -> None:
        if not self.scans_csv_path.exists():
            if self.spreadsheet_path.exists():
                self.spreadsheet_path.unlink()
            return

        with self.scans_csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        if len(rows) <= 1:
            return

        fig, ax = plt.subplots(figsize=(max(8, len(rows[0]) * 1.2), max(3, len(rows) * 0.45)))
        ax.axis("off")
        table = ax.table(cellText=rows[1:], colLabels=rows[0], loc="center", cellLoc="left")
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1.0, 1.3)
        fig.suptitle("Scan parameter log", fontsize=12, y=0.98)
        fig.tight_layout()
        fig.savefig(self.spreadsheet_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def write_event_time_plot(self) -> None:
        with self._lock:
            events = list(self.timeline)

        fig, ax = plt.subplots(figsize=(11, 4))
        if not events:
            ax.text(0.5, 0.5, "No events yet", ha="center", va="center", transform=ax.transAxes)
        else:
            t0 = events[0].timestamp
            for event in events:
                x = event.timestamp - t0
                ax.scatter([x], [0], c=event.color, s=80, zorder=3)
                ax.annotate(
                    event.label,
                    (x, 0),
                    textcoords="offset points",
                    xytext=(0, 10 if event.color == "green" else -14),
                    ha="center",
                    fontsize=8,
                    color=event.color if event.color != "green" else "darkgreen",
                )

        ax.set_yticks([])
        ax.set_xlabel("time since first event (s)")
        ax.set_title("Scan and flag event timeline")
        ax.grid(True, axis="x", alpha=0.3)
        fig.tight_layout()
        fig.savefig(self.event_plot_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

    def write_outputs(self) -> None:
        self.write_scans_csv()
        self.write_spreadsheet_view()
        self.write_event_time_plot()

    def _scan_started_callback(self, pvname: str, value: Any) -> None:
        previous = self._last_scan_started_values.get(pvname)
        self._last_scan_started_values[pvname] = value
        if previous is None:
            return

        rules = [r for r in self.config["scan_started"] if r["pv"] == pvname]
        for rule in rules:
            if trigger_matches(previous, value, rule):
                self.logger.debug(
                    "scan_started trigger matched on %s: %s -> %s",
                    pvname,
                    previous,
                    value,
                )
                self.on_scan_started()
                return

    def start_epics_monitoring(self) -> None:
        ep = ensure_epics()

        pvs = {rule["pv"] for rule in self.config["scan_started"]}
        for entry in self.config["scan_parameters"]:
            pvs.add(entry["pv"])
        for spec in self.config.get("flags", {}).values():
            for entry in spec.get("inputs", []):
                pvs.add(entry["pv"])
        for entry in self.config["flag_events"]:
            pvs.add(entry["pv"])
        pvs.add(self.scan_number_pv)

        started_pvs = {r["pv"] for r in self.config["scan_started"]}
        for pv_name in sorted(pvs):
            initial = ep.caget(pv_name, timeout=2.0)
            if pv_name in started_pvs:
                self._last_scan_started_values[pv_name] = initial
            self._pvs.append(ep.PV(pv_name, callback=self._make_callback(pv_name)))

        self.logger.info("monitoring %d PVs; outputs in %s", len(pvs), self.output_dir)

    def _make_callback(self, pvname: str) -> Any:
        started_pvs = {r["pv"] for r in self.config["scan_started"]}

        def callback(**kwargs: Any) -> None:
            value = kwargs.get("value")
            if pvname in started_pvs:
                self._scan_started_callback(pvname, value)

        return callback

    def run(self) -> None:
        self.start_epics_monitoring()
        self.logger.info("scan monitor running; Ctrl+C to stop")
        try:
            while True:
                self.evaluate_flags()
                time.sleep(self.flag_poll_s)
        except KeyboardInterrupt:
            self.logger.info("stopped by user")


def run_demo(output_dir: Path) -> None:
    """Simulate a short session to validate logging and plots without EPICS.

    The PV names, labels, and flag names mirror scan_monitor_config.json (8-BM
    Fscan / Struck 3820 / Xspress3 setup) so the demo outputs match what a live
    session would produce.
    """
    config = {
        "scan_number_pv": "8bmbsft:saveData_scanNumber",
        "scan_started": [{"pv": "8bmbsft:Fscan1.BUSY", "when": "eq", "value": 1}],
        "scan_parameters": [
            {"label": "scan_number", "pv": "8bmbsft:saveData_scanNumber"},
            {"label": "Xnpts", "pv": "8bmbsft:FscanH.NPTS"},
            {"label": "Ynpts", "pv": "8bmbsft:FscanH.NPTS"},
            {"label": "Xstart", "pv": "8bmbsft:FscanH.P1SP"},
            {"label": "Xend", "pv": "8bmbsft:FscanH.P1EP"},
            {"label": "Xstep", "pv": "8bmbsft:FscanH.P1SI"},
            {"label": "Xcenter", "pv": "8bmbsft:FscanH.P1CP"},
            {"label": "Ystart", "pv": "8bmbsft:FscanH.P2SP"},
            {"label": "Yend", "pv": "8bmbsft:FscanH.P2EP"},
            {"label": "Ystep", "pv": "8bmbsft:FscanH.P2SI"},
            {"label": "Ycenter", "pv": "8bmbsft:FscanH.P2CP"},
            {"label": "saveData_message", "pv": "8bmbsft:saveData_message"},
        ],
        "flag_events": [
            {"label": "beam_current", "pv": "S:SRcurrentAI"},
            {"label": "acquiring", "pv": "8bmbsft:3820.Acquiring"},
            {"label": "nuse_all", "pv": "8bmbsft:3820.NuseAll"},
            {"label": "current_channel", "pv": "8bmbsft:3820.CurrentChannel"},
            {"label": "array_counter", "pv": "8bmbXP3:det1:ArrayCounter_RBV"},
            {"label": "detector_state", "pv": "8bmbXP3:det1:DetectorState_RBV"},
            {"label": "actual_position", "pv": "8bmbsft:m27.RBV"},
        ],
    }
    monitor = ScanMonitor(config, output_dir)
    monitor.logger.info("demo mode (no EPICS)")

    base, _ = utc_now()
    for i, scan_num in enumerate([101, 102, 103], start=1):
        ts = base + i * 30
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds")
        center = round(-0.5 + 0.5 * (i - 1), 3)
        monitor.scans.append(
            ScanRecord(
                timestamp=ts,
                iso_time=iso,
                scan_number=str(scan_num),
                parameters={
                    "scan_number": scan_num,
                    "Xnpts": 101,
                    "Ynpts": 51,
                    "Xstart": round(center - 0.5, 3),
                    "Xend": round(center + 0.5, 3),
                    "Xstep": 0.01,
                    "Xcenter": center,
                    "Ystart": round(center - 0.25, 3),
                    "Yend": round(center + 0.25, 3),
                    "Ystep": 0.01,
                    "Ycenter": center,
                    "saveData_message": "scan complete",
                },
            )
        )
        monitor.timeline.append(
            TimelineEvent(
                timestamp=ts,
                iso_time=iso,
                kind="scan_started",
                label=f"scan {scan_num}",
                color="green",
                scan_number=str(scan_num),
            )
        )

    # (offset_s, flag_name, color, fault-snapshot values logged for the event)
    demo_flags = [
        (
            base + 45,
            "beam_dump",
            "orange",
            {
                "beam_current": 0.03,
                "acquiring": 1,
                "nuse_all": 5151,
                "current_channel": 2287,
                "array_counter": 2287,
                "detector_state": "Acquire",
                "actual_position": 0.118,
            },
        ),
        (
            base + 75,
            "struck_stuck_acquiring",
            "red",
            {
                "beam_current": 102.4,
                "acquiring": 1,
                "nuse_all": 5151,
                "current_channel": 5151,
                "array_counter": 5151,
                "detector_state": "Acquire",
                "actual_position": 0.5,
            },
        ),
        (
            base + 95,
            "stage_stuck",
            "red",
            {
                "beam_current": 102.3,
                "acquiring": 1,
                "nuse_all": 3060,
                "current_channel": 3060,
                "array_counter": 3060,
                "detector_state": "Acquire",
                "actual_position": 0.201,
            },
        ),
    ]
    for ts, name, color, values in demo_flags:
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds")
        monitor.timeline.append(
            TimelineEvent(
                timestamp=ts,
                iso_time=iso,
                kind="flag",
                label=name,
                color=color,
                scan_number="102",
                details=values,
            )
        )
        with monitor.flag_events_path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "timestamp": ts,
                        "iso_time": iso,
                        "flag": name,
                        "scan_number": "102",
                        "values": values,
                    }
                )
                + "\n"
            )

    monitor.write_outputs()
    monitor.logger.info(
        "demo outputs written: %s, %s, %s",
        monitor.scans_csv_path,
        monitor.spreadsheet_path,
        monitor.event_plot_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path(__file__).resolve().parent / "scan_monitor_config.json",
        help="JSON file with scan_started, scan_parameters, and flag_events sections",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="override output_dir from config",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="write sample log/plots without connecting to EPICS",
    )
    args = parser.parse_args()

    if args.demo:
        output_dir = args.output_dir or Path("scan_monitor_output_demo")
        run_demo(output_dir)
        return

    config = load_config(args.config)
    apply_environment_variables(config.get("environment_variables"))
    output_dir = args.output_dir or Path(config.get("output_dir", "scan_monitor_output"))
    monitor = ScanMonitor(config, output_dir)
    monitor.run()


if __name__ == "__main__":
    main()
