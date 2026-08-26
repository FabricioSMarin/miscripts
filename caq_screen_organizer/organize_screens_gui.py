#!/usr/bin/env python3
"""Interactive GUI for organize_screens.py.

Paste caQtDM message-window logs, choose the extensionless beamline launcher
to update, then Generate. The existing launcher is copied to
`<name>_bak_YYYYMMDD_HHMMSS` before being replaced.

Usage:
    ./organize_screens_gui.py
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from organize_screens import build_launcher, summarize_screens, write_launcher


class OrganizeScreensApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("caQtDM screen organizer")
        self.minsize(720, 520)
        self.geometry("900x640")

        self.target_path = tk.StringVar(self)
        self.status = tk.StringVar(self, value="Paste caQtDM logs and select a beamline launcher.")

        self._build()

    def _build(self) -> None:
        pad = {"padx": 10, "pady": 6}
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        ttk.Label(root, text="caQtDM logs (paste here)").pack(anchor=tk.W)
        log_frame = ttk.Frame(root)
        log_frame.pack(fill=tk.BOTH, expand=True, **pad)
        self.log_text = tk.Text(log_frame, wrap=tk.NONE, undo=True)
        yscroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        xscroll = ttk.Scrollbar(log_frame, orient=tk.HORIZONTAL, command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        target_row = ttk.Frame(root)
        target_row.pack(fill=tk.X, **pad)
        ttk.Label(target_row, text="Beamline launcher:").pack(side=tk.LEFT)
        ttk.Entry(target_row, textvariable=self.target_path).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8)
        )
        ttk.Button(target_row, text="Browse…", command=self.browse_target).pack(side=tk.LEFT)

        btn_row = ttk.Frame(root)
        btn_row.pack(fill=tk.X, **pad)
        ttk.Button(btn_row, text="Generate", command=self.generate).pack(side=tk.LEFT)
        ttk.Label(btn_row, textvariable=self.status, wraplength=700).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 0)
        )

    def browse_target(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Select extensionless beamline launcher",
            filetypes=[
                ("Launcher / all files", "*"),
                ("Text files", "*.txt"),
            ],
        )
        if path:
            self.target_path.set(path)
            self.status.set(f"Selected {path}")

    def generate(self) -> None:
        log_text = self.log_text.get("1.0", tk.END)
        if not log_text.strip():
            messagebox.showerror("Missing logs", "Paste caQtDM logs into the text box first.")
            return

        target = Path(self.target_path.get().strip())
        if not target.as_posix() or target.as_posix() == ".":
            messagebox.showerror("Missing launcher", "Browse to the extensionless beamline file.")
            return
        if not target.is_file():
            messagebox.showerror("Missing launcher", f"File not found:\n{target}")
            return

        self.status.set("Running wmctrl and generating…")
        self.update_idletasks()

        try:
            script, screens, with_macro, without_macro = build_launcher(
                log_text,
                source_label=f"pasted log → {target.name}",
            )
            bak = write_launcher(target, script, make_backup=True)
        except Exception as exc:
            self.status.set("Generate failed.")
            messagebox.showerror("Generate failed", str(exc))
            return

        summary = summarize_screens(screens, with_macro, without_macro)
        bak_msg = f"\nBackup: {bak}" if bak else ""
        self.status.set(f"Updated {target.name} ({summary})")
        messagebox.showinfo(
            "Done",
            f"Wrote {target.resolve()}\n{summary}{bak_msg}",
        )


def main() -> int:
    app = OrganizeScreensApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
