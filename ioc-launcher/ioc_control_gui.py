#!/usr/bin/env python3
"""GUI to start/stop/restart/status IOCs listed in master-launcher.sh."""

from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
SCRIPT_DIR = Path(__file__).resolve().parent
LAUNCHER_FILE = SCRIPT_DIR / "master-launcher.sh"
DEFAULT_IDENTITY = os.path.expanduser("~/.ssh/ioc_launcher")
SSH_TIMEOUT_S = 30
LOCAL_LAUNCH_WAIT_S = 2
SSH_ACTIONS = ("start", "stop", "restart", "status")

SSH_RE = re.compile(
    r"""
    ssh\s+
    (?:-i\s+(?P<identity>\S+)\s+)?
    (?P<user>[^\s@]+)@(?P<host>\S+)
    \s+
    ["'](?P<remote>.+?)["']
    """,
    re.VERBOSE | re.DOTALL,
)


@dataclass(frozen=True)
class IocEntry:
    user: str
    host: str
    remote_cmd: str  # full remote command ending with an action word
    identity: str

    @property
    def name(self) -> str:
        # last path component before action, e.g. .../2idbleps.pl start
        parts = self.remote_cmd.rsplit(None, 1)
        script = Path(parts[0]).name if parts else self.remote_cmd
        return Path(script).stem

    @property
    def host_short(self) -> str:
        return self.host.split(".", 1)[0]

    @property
    def script_path(self) -> str:
        base, _, _ = self.remote_cmd.rpartition(" ")
        return base or self.remote_cmd

    def command_for(self, action: str) -> str:
        return f"{self.script_path} {action}"


def parse_launcher(path: Path) -> list[IocEntry]:
    text = path.read_text()
    # Join line continuations so each ssh is one logical line
    joined = re.sub(r"\\\s*\n\s*", " ", text)
    entries: list[IocEntry] = []
    for match in SSH_RE.finditer(joined):
        identity = match.group("identity") or DEFAULT_IDENTITY
        identity = os.path.expanduser(identity)
        remote = " ".join(match.group("remote").split())
        entries.append(
            IocEntry(
                user=match.group("user"),
                host=match.group("host"),
                remote_cmd=remote,
                identity=identity,
            )
        )
    return entries


def group_by_host(entries: list[IocEntry]) -> OrderedDict[str, list[IocEntry]]:
    groups: OrderedDict[str, list[IocEntry]] = OrderedDict()
    for entry in entries:
        key = f"{entry.host_short}  |  {entry.user}@{entry.host}"
        groups.setdefault(key, []).append(entry)
    return groups


class IocControlApp(tk.Tk):
    def __init__(self, entries: list[IocEntry]) -> None:
        super().__init__()
        self.title("IOC Control")
        self.geometry("960x720")
        self.minsize(720, 480)

        self._log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._busy: set[str] = set()

        self._build_ui(entries)
        self.after(100, self._drain_log_queue)

    def _build_ui(self, entries: list[IocEntry]) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=3)
        self.rowconfigure(1, weight=2)

        # --- IOC list ---
        list_frame = ttk.Frame(self, padding=8)
        list_frame.grid(row=0, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def _resize_inner(event: tk.Event) -> None:
            canvas.itemconfigure(canvas_window, width=event.width)

        canvas.bind("<Configure>", _resize_inner)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        def _on_mousewheel(event: tk.Event) -> None:
            if event.delta:
                canvas.yview_scroll(int(-event.delta / 120), "units")
            elif event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", _on_mousewheel)
        canvas.bind_all("<Button-5>", _on_mousewheel)

        groups = group_by_host(entries)
        if not groups:
            ttk.Label(inner, text=f"No IOCs found in {LAUNCHER_FILE}").pack(anchor="w")
        for section_title, iocs in groups.items():
            self._add_host_section(inner, section_title, iocs)

        # --- Console ---
        console_frame = ttk.LabelFrame(self, text="Console / log", padding=8)
        console_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        console_frame.columnconfigure(0, weight=1)
        console_frame.rowconfigure(0, weight=1)

        self.console = tk.Text(
            console_frame,
            height=12,
            wrap="word",
            state="disabled",
            font=("Menlo", 11) if self._font_exists("Menlo") else ("Courier", 11),
        )
        console_scroll = ttk.Scrollbar(
            console_frame, orient="vertical", command=self.console.yview
        )
        self.console.configure(yscrollcommand=console_scroll.set)
        self.console.grid(row=0, column=0, sticky="nsew")
        console_scroll.grid(row=0, column=1, sticky="ns")

        self.console.tag_configure("cmd", foreground="#0b57d0")
        self.console.tag_configure("ok", foreground="#1b7f3a")
        self.console.tag_configure("err", foreground="#b00020")
        self.console.tag_configure("meta", foreground="#666666")

        btn_row = ttk.Frame(console_frame)
        btn_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(btn_row, text="Clear log", command=self._clear_log).pack(side="right")

        self._log(
            "meta",
            f"Loaded {len(entries)} IOC(s) from {LAUNCHER_FILE.name}. "
            "start/stop/restart/status run over SSH; caqtdm runs locally.",
        )

    @staticmethod
    def _font_exists(name: str) -> bool:
        try:
            import tkinter.font as tkfont

            return name in tkfont.families()
        except Exception:
            return False

    def _add_host_section(
        self, parent: ttk.Frame, title: str, iocs: list[IocEntry]
    ) -> None:
        section = ttk.LabelFrame(parent, text=title, padding=8)
        section.pack(fill="x", expand=False, pady=(0, 10))
        section.columnconfigure(0, weight=1)

        header = ttk.Frame(section)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        for action in SSH_ACTIONS:
            ttk.Button(
                header,
                text=f"{action.capitalize()} all",
                command=lambda a=action, items=iocs: self._run_many(items, a),
            ).pack(side="left", padx=(0, 6))

        for i, ioc in enumerate(iocs, start=1):
            row = ttk.Frame(section)
            row.grid(row=i, column=0, sticky="ew", pady=2)
            row.columnconfigure(0, weight=1)

            ttk.Label(row, text=ioc.name, font=("", 11, "bold")).grid(
                row=0, column=0, sticky="w"
            )
            ttk.Label(
                row,
                text=ioc.script_path,
                foreground="#555555",
            ).grid(row=1, column=0, sticky="w")

            btns = ttk.Frame(row)
            btns.grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))
            for action in SSH_ACTIONS:
                ttk.Button(
                    btns,
                    text=action.capitalize(),
                    width=9,
                    command=lambda e=ioc, a=action: self._run_one(e, a),
                ).pack(side="left", padx=2)
            ttk.Button(
                btns,
                text="CaQtdm",
                width=9,
                command=lambda e=ioc: self._run_one(e, "caqtdm"),
            ).pack(side="left", padx=2)

    def _run_one(self, ioc: IocEntry, action: str) -> None:
        key = f"{ioc.host}:{ioc.name}:{action}"
        if key in self._busy:
            self._log("meta", f"Already running: {ioc.name} {action}")
            return
        self._busy.add(key)

        if action == "caqtdm":
            local_cmd = [ioc.script_path, "caqtdm"]
            self._log("cmd", f"$ {' '.join(local_cmd)}  (local)")
            threading.Thread(
                target=self._local_worker,
                args=(local_cmd, key, ioc.name, action),
                daemon=True,
            ).start()
            return

        remote = ioc.command_for(action)
        ssh_cmd = [
            "ssh",
            "-i",
            ioc.identity,
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            f"{ioc.user}@{ioc.host}",
            remote,
        ]
        self._log("cmd", f"$ {' '.join(ssh_cmd)}")
        threading.Thread(
            target=self._ssh_worker,
            args=(ssh_cmd, key, ioc.name, action),
            daemon=True,
        ).start()

    def _run_many(self, iocs: list[IocEntry], action: str) -> None:
        for ioc in iocs:
            self._run_one(ioc, action)

    def _report_subprocess_result(
        self, proc: subprocess.CompletedProcess[str], name: str, action: str
    ) -> None:
        out = (proc.stdout or "").rstrip()
        err = (proc.stderr or "").rstrip()
        if proc.returncode == 0:
            msg = out or f"(exit 0, no output) — {name} {action}"
            self._log_queue.put(("ok", msg))
            if err:
                self._log_queue.put(("meta", f"stderr: {err}"))
        else:
            parts = [f"(exit {proc.returncode}) — {name} {action}"]
            if out:
                parts.append(out)
            if err:
                parts.append(err)
            self._log_queue.put(("err", "\n".join(parts)))

    def _ssh_worker(
        self, ssh_cmd: list[str], key: str, name: str, action: str
    ) -> None:
        try:
            proc = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=SSH_TIMEOUT_S,
            )
            self._report_subprocess_result(proc, name, action)
        except subprocess.TimeoutExpired:
            self._log_queue.put(
                ("err", f"Timeout after {SSH_TIMEOUT_S}s — {name} {action}")
            )
        except Exception as exc:
            self._log_queue.put(("err", f"{type(exc).__name__}: {exc}"))
        finally:
            self._busy.discard(key)

    def _local_worker(
        self, local_cmd: list[str], key: str, name: str, action: str
    ) -> None:
        try:
            proc = subprocess.Popen(
                local_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            time.sleep(LOCAL_LAUNCH_WAIT_S)
            if proc.poll() is None:
                self._log_queue.put(
                    (
                        "ok",
                        f"Launched {action} for {name} locally (pid {proc.pid})",
                    )
                )
                return

            out, err = proc.communicate()
            completed = subprocess.CompletedProcess(
                local_cmd, proc.returncode, out, err
            )
            self._report_subprocess_result(completed, name, action)
        except FileNotFoundError:
            self._log_queue.put(
                ("err", f"Script not found locally: {local_cmd[0]} — {name} {action}")
            )
        except Exception as exc:
            self._log_queue.put(("err", f"{type(exc).__name__}: {exc}"))
        finally:
            self._busy.discard(key)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                tag, text = self._log_queue.get_nowait()
                self._log(tag, text)
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)

    def _log(self, tag: str, text: str) -> None:
        self.console.configure(state="normal")
        self.console.insert("end", text + "\n", tag)
        self.console.see("end")
        self.console.configure(state="disabled")

    def _clear_log(self) -> None:
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")


def main() -> None:
    if not LAUNCHER_FILE.is_file():
        raise SystemExit(f"Missing launcher file: {LAUNCHER_FILE}")
    entries = parse_launcher(LAUNCHER_FILE)
    app = IocControlApp(entries)
    app.mainloop()


if __name__ == "__main__":
    main()
