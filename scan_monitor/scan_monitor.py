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
  - linux_data_mount: optional local mount prefix aligned with output_dir_pv

Outputs (written under ``<output_dir_pv>/scan_monitor_output`` unless overridden):
  - scan_monitor.log          session text log
  - scans.csv                 one row per completed 2D scan
  - flag_events.jsonl         one record per flag event
  - spreadsheet_view.png      tabular view of scans.csv
  - event_time_plot.png       timeline of scan starts and flag events

At launch an interactive timeline window can show events in real time (optional).
The saved PNG always includes all events, including those loaded from prior runs.
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

import matplotlib

if not os.environ.get("MPLBACKEND"):
    for _backend in ("TkAgg", "Qt5Agg", "GTK3Agg"):
        try:
            matplotlib.use(_backend)
            break
        except ImportError:
            continue

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.widgets import CheckButtons

from scan_monitor_flags import FLAG_FUNCTIONS, FLAGS_NO_CONFIRM, begin_flag_poll, marker_color

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


def _path_parts(path: str) -> list[str]:
    """Split a filesystem path into non-empty components."""
    return [part for part in path.replace("\\", "/").split("/") if part]


def combine_linux_mount_path(linux_mount: str, remote_path: str) -> Path:
    """Map a PV filesystem path onto the local Linux mount.

    When the PV returns a Windows/UNC path (e.g. ``//micdata/data1/2ide/...``) and
    the monitor runs on Linux (e.g. ``/mnt/micdata1/2ide/``), align on the longest
    matching path-component sequence and keep the Linux prefix plus any trailing
    PV suffix. Example::

        /mnt/micdata1/2ide/  +  //micdata/data1/2ide/2026-2/Plant-As2
        -> /mnt/micdata1/2ide/2026-2/Plant-As2
    """
    mount_parts = _path_parts(linux_mount)
    remote_parts = _path_parts(remote_path)
    if not mount_parts:
        return Path(remote_path).expanduser()
    if not remote_parts:
        return Path(linux_mount).expanduser()

    for overlap in range(min(len(mount_parts), len(remote_parts)), 0, -1):
        suffix = mount_parts[-overlap:]
        for start in range(len(remote_parts) - overlap + 1):
            if remote_parts[start : start + overlap] == suffix:
                combined = mount_parts + remote_parts[start + overlap :]
                return Path("/" + "/".join(combined))

    return Path(linux_mount).expanduser() / Path(*remote_parts)


def read_output_base_path(config: dict[str, Any]) -> Path | None:
    """Read the filesystem base path from ``output_dir_pv``, or None if unset."""
    output_dir_pv = config.get("output_dir_pv")
    if not output_dir_pv:
        return None
    remote = coerce_pv_string(pv_value(str(output_dir_pv), as_string=True))
    linux_mount = config.get("linux_data_mount")
    if linux_mount:
        return combine_linux_mount_path(str(linux_mount), remote)
    return Path(remote).expanduser()


def resolve_output_dir(config: dict[str, Any], override: Path | None = None) -> Path:
    """Return the monitor output directory, creating it if needed.

    Default: read ``output_dir_pv`` from *config*, append ``scan_monitor_output``,
    and mkdir -p. *override* bypasses the PV lookup (for ``--output-dir``).
    """
    if override is not None:
        output_dir = override
    else:
        base = read_output_base_path(config)
        if base is not None:
            output_dir = base / "scan_monitor_output"
        else:
            output_dir = Path(config.get("output_dir", "scan_monitor_output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


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


def load_past_timeline_events(output_dir: Path) -> list[TimelineEvent]:
    """Rebuild timeline entries from prior output files in *output_dir*."""
    events: list[TimelineEvent] = []

    scans_csv = output_dir / "scans.csv"
    if scans_csv.exists():
        with scans_csv.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                iso_time = row.get("iso_time", "")
                if not iso_time:
                    continue
                try:
                    timestamp = datetime.fromisoformat(iso_time).timestamp()
                except ValueError:
                    continue
                scan_number = row.get("scan_number", "?")
                events.append(
                    TimelineEvent(
                        timestamp=timestamp,
                        iso_time=iso_time,
                        kind="scan_started",
                        label=f"scan {scan_number}",
                        color="green",
                        scan_number=scan_number,
                    )
                )

    flag_events_path = output_dir / "flag_events.jsonl"
    if flag_events_path.exists():
        with flag_events_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                flag_name = record.get("flag", "?")
                events.append(
                    TimelineEvent(
                        timestamp=float(record["timestamp"]),
                        iso_time=record.get("iso_time", ""),
                        kind="flag",
                        label=flag_name,
                        color=marker_color(flag_name),
                        scan_number=record.get("scan_number"),
                        details=record.get("values", {}),
                    )
                )

    events.sort(key=lambda event: event.timestamp)
    return events


def load_past_scans(output_dir: Path) -> list[ScanRecord]:
    """Rebuild scan records from a prior ``scans.csv`` in *output_dir*."""
    scans_csv = output_dir / "scans.csv"
    if not scans_csv.exists():
        return []

    scans: list[ScanRecord] = []
    with scans_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            iso_time = row.get("iso_time", "")
            if not iso_time:
                continue
            try:
                timestamp = datetime.fromisoformat(iso_time).timestamp()
            except ValueError:
                continue
            scan_number = str(row.get("scan_number", "?"))
            parameters = {
                k: v for k, v in row.items() if k not in ("iso_time", "scan_number")
            }
            scans.append(
                ScanRecord(
                    timestamp=timestamp,
                    iso_time=iso_time,
                    scan_number=scan_number,
                    parameters=parameters,
                )
            )
    return scans


def draw_event_timeline(ax: Any, events: list[TimelineEvent], *, title: str) -> None:
    ax.clear()
    ax.set_facecolor("white")
    if not events:
        ax.text(
            0.5,
            0.5,
            "No events yet",
            ha="center",
            va="center",
            transform=ax.transAxes,
            color="black",
        )
    else:
        for event in events:
            t = datetime.fromtimestamp(event.timestamp, tz=timezone.utc)
            ax.scatter([t], [0], c=event.color, s=80, zorder=3)
            ax.annotate(
                event.label,
                (t, 0),
                textcoords="offset points",
                xytext=(0, 10 if event.color == "green" else -14),
                ha="center",
                fontsize=8,
                color=event.color if event.color != "green" else "darkgreen",
            )
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M"))
        for label in ax.get_xticklabels():
            label.set_rotation(30)
            label.set_ha("right")

    ax.set_yticks([])
    ax.set_xlabel("time (UTC)", color="black")
    ax.set_title(title, color="black")
    ax.tick_params(colors="black")
    ax.grid(True, axis="x", alpha=0.3)


class ScanMonitor:
    def __init__(
        self,
        config: dict[str, Any],
        output_dir: Path,
        *,
        live_plot: bool = True,
        live_plot_show_past: bool = False,
        output_dir_override: bool = False,
    ) -> None:
        self.config = config
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._output_dir_override = output_dir_override
        if output_dir_override or not config.get("output_dir_pv"):
            self._output_base_path = None
        else:
            self._output_base_path = output_dir.parent.resolve()

        self.scan_number_pv = config.get("scan_number_pv", "SCAN:NN")
        self.scans: list[ScanRecord] = []
        self.timeline: list[TimelineEvent] = []
        self._lock = threading.Lock()
        self._last_scan_started_values: dict[str, Any] = {}
        self._last_flag_fire: dict[str, float] = {}
        self._flag_confirm_pending: dict[str, float] = {}
        self._pvs: list[Any] = []
        self.flag_cooldown_s = float(config.get("flag_cooldown_s", 5.0))
        self.flag_confirm_s = float(config.get("flag_confirm_s", 5.0))
        self.flag_poll_s = float(config.get("flag_poll_s", 1.0))
        self.live_plot_enabled = live_plot
        self._live_show_past = live_plot_show_past
        self.session_start = 0.0
        self._live_fig: Any = None
        self._live_ax: Any = None
        self._plot_needs_update = False
        self._outputs_pending = False

        self._update_output_paths()
        self._load_past_session()
        self._setup_logging()

    def _load_past_scans(self) -> None:
        past = load_past_scans(self.output_dir)
        if not past:
            return
        with self._lock:
            self.scans.extend(past)

    def _load_past_timeline(self) -> None:
        past = load_past_timeline_events(self.output_dir)
        if not past:
            return
        with self._lock:
            self.timeline.extend(past)
            self.timeline.sort(key=lambda event: event.timestamp)

    def _load_past_session(self) -> None:
        self._load_past_scans()
        self._load_past_timeline()

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

    def _update_output_paths(self) -> None:
        self.log_path = self.output_dir / "scan_monitor.log"
        self.scans_csv_path = self.output_dir / "scans.csv"
        self.flag_events_path = self.output_dir / "flag_events.jsonl"
        self.spreadsheet_path = self.output_dir / "spreadsheet_view.png"
        self.event_plot_path = self.output_dir / "event_time_plot.png"

    def _switch_output_dir(self, base: Path) -> None:
        """Point outputs at *base*/scan_monitor_output and start a fresh session there."""
        new_output_dir = base / "scan_monitor_output"
        new_output_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self.output_dir = new_output_dir
            self._output_base_path = base
            self.scans.clear()
            self.timeline.clear()
        self._update_output_paths()
        self._load_past_session()
        self._setup_logging()
        self._plot_needs_update = True
        self.logger.info("switched output directory to %s", self.output_dir)

    def _maybe_switch_output_dir_on_scan_start(self) -> None:
        """When ``output_dir_pv`` changes, relocate outputs on the next scan start."""
        if self._output_dir_override or not self.config.get("output_dir_pv"):
            return
        try:
            base = read_output_base_path(self.config)
        except RuntimeError as exc:
            self.logger.warning("could not read output_dir_pv on scan start: %s", exc)
            return
        if base is None:
            return
        if self._output_base_path is not None and base.resolve() == self._output_base_path.resolve():
            return
        self._switch_output_dir(base)

    def _append_timeline(self, event: TimelineEvent) -> None:
        with self._lock:
            self.timeline.append(event)

    def _read_scan_number(self) -> str:
        try:
            value = pv_value(self.scan_number_pv)
        except RuntimeError:
            value = "?"
        return str(value)

    def _scan_active_now(self) -> bool:
        """True when scan_started PVs indicate a scan is already in progress."""
        for rule in self.config["scan_started"]:
            pv = rule["pv"]
            when = rule.get("when", "changed")
            expected = rule.get("value")
            current = self._last_scan_started_values.get(pv)
            if current is None:
                try:
                    current = pv_value(pv)
                except RuntimeError:
                    return False
            if when == "eq":
                if current != expected:
                    return False
            else:
                return False
        return bool(self.config["scan_started"])

    def _maybe_record_ongoing_scan_at_launch(self) -> None:
        """If a scan is already running when the monitor starts, log it once."""
        if not self._scan_active_now():
            return
        scan_number = self._read_scan_number()
        with self._lock:
            if any(scan.scan_number == scan_number for scan in self.scans):
                self.logger.info(
                    "ongoing scan %s at launch already present in scans.csv", scan_number
                )
                return
        self.logger.info("ongoing scan detected at launch: scan_number=%s", scan_number)
        self.on_scan_started()

    def on_scan_started(self) -> None:
        self._maybe_switch_output_dir_on_scan_start()
        ts, iso_time = utc_now()
        parameters = read_labeled_pvs(self.config["scan_parameters"])
        scan_number = str(parameters.get("next_scan_number", self._read_scan_number()))

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
        self.request_outputs()

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
        self.request_outputs()

    def evaluate_flags(self) -> None:
        """Poll each configured flag with two-check confirmation.

        For every flag listed in the config's ``flags`` section, its ``inputs``
        PVs are read and passed as the ``context`` dict (keyed by label) to the
        matching function in ``scan_monitor_flags.py``. When a check returns
        True, the same flag is re-checked after ``flag_confirm_s`` seconds;
        the event is logged only if both checks pass.
        """
        now = time.time()
        begin_flag_poll()
        flag_specs = self.config.get("flags", {})
        for flag_name, spec in flag_specs.items():
            check = FLAG_FUNCTIONS.get(flag_name)
            if check is None:
                self.logger.warning("no flag function defined for %r; skipping", flag_name)
                continue

            inputs = spec.get("inputs", [])
            if not inputs:
                continue

            last = self._last_flag_fire.get(flag_name, 0.0)
            if now - last < self.flag_cooldown_s:
                continue

            try:
                context = read_labeled_pvs(inputs)
            except RuntimeError as exc:
                self.logger.warning("could not read inputs for %s: %s", flag_name, exc)
                continue

            try:
                fired = check(context)
            except Exception as exc:
                self.logger.exception("flag check failed for %s: %s", flag_name, exc)
                continue

            pending_since = self._flag_confirm_pending.get(flag_name)
            if not fired:
                if pending_since is not None:
                    self.logger.debug(
                        "flag %s failed before confirmation; discarding", flag_name
                    )
                    del self._flag_confirm_pending[flag_name]
                continue

            if flag_name in FLAGS_NO_CONFIRM:
                self._last_flag_fire[flag_name] = now
                flag_values = read_labeled_pvs(self.config["flag_events"])
                self.on_flag_event(flag_name, flag_values)
                continue

            if pending_since is None:
                self._flag_confirm_pending[flag_name] = now
                self.logger.debug(
                    "flag %s passed first check; confirming in %.0fs",
                    flag_name,
                    self.flag_confirm_s,
                )
                continue

            if now - pending_since < self.flag_confirm_s:
                continue

            del self._flag_confirm_pending[flag_name]
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

        fig = Figure(figsize=(max(8, len(rows[0]) * 1.2), max(3, len(rows) * 0.45)))
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        ax.axis("off")
        table = ax.table(cellText=rows[1:], colLabels=rows[0], loc="center", cellLoc="left")
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1.0, 1.3)
        fig.suptitle("Scan parameter log", fontsize=12, y=0.98)
        fig.tight_layout()
        fig.savefig(self.spreadsheet_path, dpi=150, bbox_inches="tight")

    def write_event_time_plot(self) -> None:
        with self._lock:
            events = list(self.timeline)

        fig = Figure(figsize=(11, 4))
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(111)
        draw_event_timeline(ax, events, title="Scan and flag event timeline")
        fig.tight_layout()
        fig.savefig(self.event_plot_path, dpi=150, bbox_inches="tight")

    def _events_for_live_plot(self) -> list[TimelineEvent]:
        with self._lock:
            events = list(self.timeline)
        if not self._live_show_past:
            events = [event for event in events if event.timestamp >= self.session_start]
        return events

    def start_live_plot(self) -> None:
        if not self.live_plot_enabled:
            return
        try:
            plt.ion()
            self._live_fig = plt.figure(figsize=(11, 4), facecolor="white")
            # Fixed axes positions: tight_layout breaks when CheckButtons is present.
            self._live_ax = self._live_fig.add_axes([0.07, 0.20, 0.93, 0.72])
            ax_check = self._live_fig.add_axes([0.07, 0.03, 0.22, 0.10])
            ax_check.set_facecolor("#f0f0f0")
            check = CheckButtons(ax_check, ["Past events"], [self._live_show_past])
            check.on_clicked(self._on_live_past_events_toggle)
            self.update_live_plot()
            plt.show(block=False)
            self._live_fig.canvas.draw()
            self._live_fig.canvas.flush_events()
            plt.pause(0.05)
            self.logger.info("live plot opened (matplotlib backend %s)", matplotlib.get_backend())
        except Exception as exc:
            self.logger.warning("could not open live plot window: %s", exc)
            self.live_plot_enabled = False
            self._live_fig = None
            self._live_ax = None

    def _on_live_past_events_toggle(self, _label: str) -> None:
        self._live_show_past = not self._live_show_past
        self.update_live_plot()

    def update_live_plot(self) -> None:
        if not self.live_plot_enabled or self._live_ax is None or self._live_fig is None:
            return
        title = "Scan and flag event timeline (live)"
        if not self._live_show_past:
            title += " — this session"
        draw_event_timeline(self._live_ax, self._events_for_live_plot(), title=title)
        self._live_fig.canvas.draw_idle()
        self._live_fig.canvas.flush_events()

    def request_outputs(self) -> None:
        """Schedule file/PNG writes on the main thread (safe from EPICS callbacks)."""
        self._outputs_pending = True

    def write_outputs(self) -> None:
        self.write_scans_csv()
        self.write_spreadsheet_view()
        self.write_event_time_plot()
        self._plot_needs_update = True

    def _process_pending_work(self) -> None:
        if self._outputs_pending:
            try:
                self.write_outputs()
            except Exception:
                self.logger.exception("failed to write outputs")
            self._outputs_pending = False
        if self.live_plot_enabled and self._plot_needs_update:
            try:
                self.update_live_plot()
            except Exception:
                self.logger.exception("failed to update live plot")
            self._plot_needs_update = False
        if self.live_plot_enabled and self._live_fig is not None:
            plt.pause(0.001)

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
        self.session_start = time.time()
        if self.live_plot_enabled:
            self.start_live_plot()
        self.start_epics_monitoring()
        self._maybe_record_ongoing_scan_at_launch()
        self.logger.info("scan monitor running; Ctrl+C to stop")
        try:
            while True:
                self._process_pending_work()
                self.evaluate_flags()
                self._process_pending_work()
                time.sleep(self.flag_poll_s)
        except KeyboardInterrupt:
            self.logger.info("stopped by user")
            if self.live_plot_enabled and self._live_fig is not None:
                plt.close(self._live_fig)


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
            {"label": "next_scan_number", "pv": "8bmbsft:saveData_scanNumber"},
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
    monitor = ScanMonitor(config, output_dir, live_plot=False)
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
                    "next_scan_number": scan_num,
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
        help="override output directory (default: <output_dir_pv>/scan_monitor_output)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="write sample log/plots without connecting to EPICS",
    )
    parser.add_argument(
        "--no-live-plot",
        action="store_true",
        help="do not open the interactive timeline window at launch",
    )
    parser.add_argument(
        "--plot-past-events",
        action="store_true",
        help="live plot includes events from prior runs in the output dir (default: this session only)",
    )
    args = parser.parse_args()

    if args.demo:
        output_dir = args.output_dir or Path("scan_monitor_output_demo")
        run_demo(output_dir)
        return

    config = load_config(args.config)
    apply_environment_variables(config.get("environment_variables"))
    output_dir = resolve_output_dir(config, args.output_dir)
    monitor = ScanMonitor(
        config,
        output_dir,
        live_plot=not args.no_live_plot,
        live_plot_show_past=args.plot_past_events,
        output_dir_override=args.output_dir is not None,
    )
    monitor.run()


if __name__ == "__main__":
    main()
