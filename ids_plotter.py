#!/usr/bin/env python3
"""
Live plotter for attocube IDS3010 interferometer (3 channels).

The device speaks JSON-RPC 2.0 on TCP port 9090. Absolute positions are read via
com.attocube.ids.displacement.getAbsolutePositions.
"""

from __future__ import annotations

import csv
import json
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

# --- IDS3010 JSON-RPC client -------------------------------------------------

IDS_PORT = 9090


def _parse_three_channels(result: list[Any]) -> tuple[float, float, float]:
    """Map RPC result array to three channel values (device raw units)."""
    if not isinstance(result, list) or len(result) < 4:
        raise ValueError(f"unexpected result array: {result!r}")
    # EPICS driver uses indices 1..3 of a 4-element array; longer arrays use the last three values.
    if len(result) == 4:
        return float(result[1]), float(result[2]), float(result[3])
    return float(result[-3]), float(result[-2]), float(result[-1])


class IDS3010Client:
    def __init__(self, host: str, port: int = IDS_PORT, timeout: float = 3.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._rpc_id = 0

    def connect(self) -> None:
        self.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect((self.host, self.port))
        self._sock = s

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def _call(self, method: str, params: list[Any] | None = None) -> Any:
        if self._sock is None:
            raise RuntimeError("not connected")
        self._rpc_id += 1
        req: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": self._rpc_id}
        if params is not None:
            req["params"] = params
        payload = json.dumps(req, separators=(",", ":")).encode("utf-8")
        with self._lock:
            self._sock.sendall(payload)
            return self._recv_one_response()

    def _recv_one_response(self) -> Any:
        assert self._sock is not None
        buf = b""
        dec = json.JSONDecoder()
        while True:
            try:
                chunk = self._sock.recv(16384)
            except socket.timeout as e:
                raise TimeoutError("read timeout") from e
            if not chunk:
                raise ConnectionError("connection closed by device")
            buf += chunk
            text = buf.decode("utf-8", errors="replace")
            start = text.find("{")
            if start < 0:
                buf = b""
                continue
            try:
                obj, end = dec.raw_decode(text, start)
            except json.JSONDecodeError:
                continue
            buf = text[end:].encode("utf-8")
            if "error" in obj:
                err = obj["error"]
                raise RuntimeError(f"device error: {err}")
            return obj["result"]

    def get_absolute_positions(self) -> tuple[float, float, float]:
        r = self._call("com.attocube.ids.displacement.getAbsolutePositions")
        return _parse_three_channels(r)

    def get_current_mode(self) -> str:
        r = self._call("com.attocube.ids.system.getCurrentMode")
        if isinstance(r, list) and r:
            return str(r[0])
        return str(r)

    def start_measurement(self) -> None:
        self._call("com.attocube.ids.system.startMeasurement")

    def stop_measurement(self) -> None:
        self._call("com.attocube.ids.system.stopMeasurement")


# --- GUI ---------------------------------------------------------------------

TIME_PRESETS_S = (6, 60, 600, 6000, 60000)


class PlotApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("IDS3010 — 3-channel live plot")
        self.geometry("1100x720")

        self._client: IDS3010Client | None = None
        self._poll_thread: threading.Thread | None = None
        self._stop_poll = threading.Event()
        self._sample_queue: queue.Queue[tuple[float, float, float, float]] = queue.Queue()
        self._offsets = (0.0, 0.0, 0.0)
        self._window_s = tk.DoubleVar(value=10.0)
        self._host = tk.StringVar(value="10.54.113.114")
        self._port = tk.IntVar(value=IDS_PORT)
        self._status = tk.StringVar(value="Disconnected")

        # Rolling history (absolute time.monotonic, raw ch0..2)
        self._t_hist: list[float] = []
        self._c0: list[float] = []
        self._c1: list[float] = []
        self._c2: list[float] = []

        self._acquire_active = threading.Event()
        self._acquire_lock = threading.Lock()
        self._acquire_t0: float | None = None
        self._acquire_duration_s: float = 10.0
        self._acquire_buf_t: list[float] = []
        self._acquire_buf_c0: list[float] = []
        self._acquire_buf_c1: list[float] = []
        self._acquire_buf_c2: list[float] = []

        self._build_ui()
        self.after(50, self._ui_tick)

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=6)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="Host").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(top, textvariable=self._host, width=16).pack(side=tk.LEFT)
        ttk.Label(top, text="Port").pack(side=tk.LEFT, padx=(8, 4))
        ttk.Entry(top, textvariable=self._port, width=6).pack(side=tk.LEFT)

        self._btn_connect = ttk.Button(top, text="Connect", command=self._on_connect)
        self._btn_connect.pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(top, text="Disconnect", command=self._on_disconnect).pack(side=tk.LEFT, padx=4)

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(top, text="Plot window").pack(side=tk.LEFT)
        self._combo_win = ttk.Combobox(
            top,
            width=8,
            state="readonly",
            values=[f"{s}s" for s in TIME_PRESETS_S],
        )
        self._combo_win.current(1)  # 10 s default
        self._combo_win.pack(side=tk.LEFT, padx=4)
        self._combo_win.bind("<<ComboboxSelected>>", self._on_window_preset)

        ttk.Button(top, text="Zero", command=self._on_zero).pack(side=tk.LEFT, padx=(12, 0))
        self._btn_acquire = ttk.Button(top, text="Acquire", command=self._on_acquire)
        self._btn_acquire.pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Export…", command=self._on_export).pack(side=tk.LEFT, padx=4)

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(top, text="Start measurement", command=self._on_start_meas).pack(
            side=tk.LEFT, padx=2
        )

        st = ttk.Label(top, textvariable=self._status, foreground="#333")
        st.pack(side=tk.RIGHT, padx=4)

        # Matplotlib
        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
        except ImportError as e:
            messagebox.showerror(
                "Missing matplotlib",
                "Install dependencies: pip install -r requirements-ids3010.txt\n\n" + str(e),
            )
            raise SystemExit(1) from e

        fig = Figure(figsize=(9, 5), dpi=100)
        self._fig = fig
        self._ax = fig.add_subplot(111)
        self._ax.set_xlabel("Time (s)")
        self._ax.set_ylabel("Position (device units, zeroed)")
        self._line0, = self._ax.plot([], [], label="Channel 1", lw=1.2)
        self._line1, = self._ax.plot([], [], label="Channel 2", lw=1.2)
        self._line2, = self._ax.plot([], [], label="Channel 3", lw=1.2)
        self._ax.legend(loc="upper right")
        self._ax.grid(True, alpha=0.35)

        canvas = FigureCanvasTkAgg(fig, master=self)
        canvas.draw()
        canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6, pady=6)
        self._canvas = canvas

    def _on_window_preset(self, _evt: object | None = None) -> None:
        sel = self._combo_win.get()
        if sel.endswith("s"):
            self._window_s.set(float(sel[:-1]))

    def _on_connect(self) -> None:
        self._on_disconnect()
        host = self._host.get().strip()
        port = int(self._port.get())
        c = IDS3010Client(host, port=port)
        try:
            c.connect()
            mode = c.get_current_mode()
            self._client = c
            self._status.set(f"Connected — {mode}")
        except Exception as e:
            c.close()
            self._status.set("Disconnected")
            messagebox.showerror("Connect failed", str(e))
            return

        self._stop_poll.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _on_disconnect(self) -> None:
        self._stop_poll.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=2.0)
            self._poll_thread = None
        if self._client is not None:
            self._client.close()
            self._client = None
        self._status.set("Disconnected")

    def _poll_loop(self) -> None:
        assert self._client is not None
        while not self._stop_poll.is_set():
            t0 = time.monotonic()
            try:
                p0, p1, p2 = self._client.get_absolute_positions()
            except Exception as e:
                self._sample_queue.put((time.monotonic(), float("nan"), float("nan"), float("nan")))
                self.after(0, lambda: self._status.set(f"Read error: {e}"))
                time.sleep(0.25)
                continue
            now = time.monotonic()
            self._sample_queue.put((now, p0, p1, p2))

            with self._acquire_lock:
                if self._acquire_active.is_set() and self._acquire_t0 is not None:
                    self._acquire_buf_t.append(now - self._acquire_t0)
                    self._acquire_buf_c0.append(p0)
                    self._acquire_buf_c1.append(p1)
                    self._acquire_buf_c2.append(p2)

            # modest pacing to avoid saturating device / UI
            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, 0.02 - elapsed))

    def _trim_history(self, now: float, win: float) -> None:
        cutoff = now - win
        i = 0
        while i < len(self._t_hist) and self._t_hist[i] < cutoff:
            i += 1
        if i > 0:
            del self._t_hist[:i]
            del self._c0[:i]
            del self._c1[:i]
            del self._c2[:i]

    def _ui_tick(self) -> None:
        drained = 0
        while drained < 500:
            try:
                ts, v0, v1, v2 = self._sample_queue.get_nowait()
            except queue.Empty:
                break
            drained += 1
            self._t_hist.append(ts)
            self._c0.append(v0)
            self._c1.append(v1)
            self._c2.append(v2)

        now = time.monotonic()
        win = float(self._window_s.get())
        self._trim_history(now, win)

        o0, o1, o2 = self._offsets
        if self._t_hist:
            tx = [t - now for t in self._t_hist]
            self._line0.set_data(tx, [x - o0 for x in self._c0])
            self._line1.set_data(tx, [x - o1 for x in self._c1])
            self._line2.set_data(tx, [x - o2 for x in self._c2])
            self._ax.set_xlim(-win, 0)
            self._ax.relim()
            self._ax.autoscale_view(scalex=False, scaley=True)
        self._canvas.draw_idle()

        # finish acquire if duration elapsed
        with self._acquire_lock:
            if self._acquire_active.is_set() and self._acquire_t0 is not None:
                if now - self._acquire_t0 >= self._acquire_duration_s:
                    self._acquire_active.clear()
                    n = len(self._acquire_buf_t)
                    self.after(0, lambda: self._status.set(f"Acquire done ({n} samples)"))
                    self.after(0, lambda: self._btn_acquire.configure(state=tk.NORMAL))

        self.after(50, self._ui_tick)

    def _on_zero(self) -> None:
        if not self._t_hist:
            messagebox.showinfo("Zero", "No samples yet.")
            return
        o0, o1, o2 = self._c0[-1], self._c1[-1], self._c2[-1]
        self._offsets = (o0, o1, o2)
        self._status.set("Zero set to current reading")

    def _on_acquire(self) -> None:
        if self._client is None or not self._client.connected:
            messagebox.showwarning("Acquire", "Connect first.")
            return
        win = float(self._window_s.get())
        with self._acquire_lock:
            self._acquire_buf_t.clear()
            self._acquire_buf_c0.clear()
            self._acquire_buf_c1.clear()
            self._acquire_buf_c2.clear()
            self._acquire_t0 = time.monotonic()
            self._acquire_duration_s = win
            self._acquire_active.set()
        self._btn_acquire.configure(state=tk.DISABLED)
        self._status.set(f"Acquiring for {win:g} s…")

    def _on_export(self) -> None:
        with self._acquire_lock:
            if not self._acquire_buf_t:
                messagebox.showinfo("Export", "Run Acquire first, or wait until it finishes.")
                return
            rows = list(
                zip(
                    self._acquire_buf_t,
                    self._acquire_buf_c0,
                    self._acquire_buf_c1,
                    self._acquire_buf_c2,
                )
            )
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
            title="Export acquired data",
        )
        if not path:
            return
        o0, o1, o2 = self._offsets
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(
                    [
                        "time_s",
                        "ch1_raw",
                        "ch2_raw",
                        "ch3_raw",
                        "ch1_zeroed",
                        "ch2_zeroed",
                        "ch3_zeroed",
                    ]
                )
                for t, a, b, c in rows:
                    w.writerow([t, a, b, c, a - o0, b - o1, c - o2])
        except OSError as e:
            messagebox.showerror("Export failed", str(e))
            return
        messagebox.showinfo("Export", f"Wrote {len(rows)} rows to:\n{path}")

    def _on_start_meas(self) -> None:
        if self._client is None or not self._client.connected:
            messagebox.showwarning("Measurement", "Connect first.")
            return
        try:
            self._client.start_measurement()
            self._status.set(f"Start sent — {self._client.get_current_mode()}")
        except Exception as e:
            messagebox.showerror("Start measurement", str(e))

    def destroy(self) -> None:
        self._on_disconnect()
        super().destroy()


def main() -> None:
    app = PlotApp()
    app.mainloop()


if __name__ == "__main__":
    main()