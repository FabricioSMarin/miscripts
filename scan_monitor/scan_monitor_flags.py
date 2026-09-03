#!/usr/bin/env python3
"""
Flag-event detectors for the EPICS scan monitor.

Each function evaluates a combination of PV values and returns True when the
corresponding fault condition is detected. Beamline-specific PVs are listed in
the JSON config under each flag's ``inputs``. Detector-specific flags keep their
own logic (Xspress3 vs XMAP) rather than sharing one acquisition helper.
"""

from __future__ import annotations

import re
from functools import wraps
from types import SimpleNamespace
from typing import Any, Callable, Optional

# Flags that fire immediately on first positive check (no flag_confirm_s wait).
FLAGS_NO_CONFIRM = frozenset(
    {
        "scan_aborted",
        "scan_paused",
        "scan_unpaused",
        "beam_dump",
        "memory_high",
        "memory_critical",
    }
)

# Orange markers: aborted, paused, beam dump, or elevated system memory.
ORANGE_FLAGS = frozenset(
    {"scan_aborted", "beam_dump", "scan_paused", "scan_unpaused", "memory_high"}
)

# Red markers: all other flag events.
RED_FLAGS = frozenset(
    {
        "struck_miss_trigger",
        "struck_stuck_acquiring",
        "xspress3_miss_trigger",
        "xspress3_lost_frame",
        "xmap_miss_trigger",
        "xmap_lost_frames",
        "filename_not_insync",
        "ioc_is_down",
        "stage_stuck",
        "write_error",
        "memory_critical",
    }
)

# System memory thresholds (% used). Edge-triggered markers; each latch
# clears when usage drops back to or below its fire threshold.
MEMORY_HIGH_PCT = 50.0
MEMORY_CRITICAL_PCT = 75.0

ContextDict = dict[str, Any]
FlagLogic = Callable[[SimpleNamespace], bool]
FlagFunction = Callable[[Optional[ContextDict]], bool]


def _is_optional_flag_input(name: str) -> bool:
    """Step-scan extras (``*_step*`` labels) must not disable fly-scan flags if unread."""
    return "_step" in name


def flag_check(fn: FlagLogic) -> FlagFunction:
    """Wrap a flag body that takes a namespace of input PV values.

    The monitor passes whatever ``inputs`` labels are in the JSON for that flag.
    Returns False when context is missing or any required value is None (unread PV).
    Labels containing ``_step`` are optional so fly-scan flags still run if a
    step-scan PV is disconnected.
    """

    @wraps(fn)
    def wrapper(context: Optional[ContextDict] = None) -> bool:
        if not context:
            return False
        required = {k: v for k, v in context.items() if not _is_optional_flag_input(k)}
        if any(v is None for v in required.values()):
            return False
        return fn(SimpleNamespace(**context))

    return wrapper


def _any_int_match(
    ctx: SimpleNamespace,
    prefix: str,
    *,
    equals: int | None = None,
    nonzero: bool = False,
) -> bool:
    for name, value in vars(ctx).items():
        if not name.startswith(prefix) or value is None:
            continue
        try:
            iv = int(value)
        except (TypeError, ValueError):
            continue
        if equals is not None and iv == equals:
            return True
        if nonzero and iv != 0:
            return True
    return False


def _struck_done(ctx: SimpleNamespace) -> bool:
    return int(ctx.struck_acquiring) == 0 and int(ctx.struck_current) == int(ctx.struck_all)


def _lost_frames_trigger(
    ctx: SimpleNamespace,
    *,
    rate: str | None = "acq_rate",
) -> bool:
    if int(ctx.scan_busy) != 1:
        return False
    if rate is not None and int(getattr(ctx, rate)) != 0:
        return False
    return int(ctx.num_frames) != int(ctx.saved_frames) and _struck_done(ctx)


@flag_check
def struck_miss_trigger(ctx: SimpleNamespace) -> bool:
    """Struck 3820 still acquiring and missing triggers after stage motion done."""
    return (
        int(ctx.scan_busy) == 1
        and int(ctx.acquiring) == 1
        and int(ctx.current_channel) != int(ctx.nuse_all)
        and int(ctx.current_channel) > 0
        and float(ctx.elapsed_time) > (8 + ctx.dwell_time * ctx.nuse_all / 1000)
    )


@flag_check
def struck_stuck_acquiring(ctx: SimpleNamespace) -> bool:
    """Struck 3820 stuck acquiring after receiving all triggers."""
    return (
        int(ctx.scan_busy) == 1
        and int(ctx.acquiring) == 1
        and int(ctx.current_channel) == int(ctx.nuse_all)
    )


@flag_check
def xspress3_miss_trigger(ctx: SimpleNamespace) -> bool:
    """Xspress3 missed an expected acquisition trigger."""
    return (
        int(ctx.scan_busy) == 1
        and int(ctx.acquiring) == 1
        and int(ctx.acq_rate) == 0
        and int(ctx.acq_counter) != int(ctx.acq_target)
        and _struck_done(ctx)
    )


@flag_check
def xspress3_lost_frame(ctx: SimpleNamespace) -> bool:
    """Xspress3 saved-frame count differs from received triggers while capturing."""
    return (
        int(ctx.scan_busy) == 1
        and int(ctx.capturing) == 1
        and int(ctx.acq_rate) == 0
        and int(ctx.num_frames) != int(ctx.saved_frames)
        and _struck_done(ctx)
    )

@flag_check
def xmap_miss_trigger(ctx: SimpleNamespace) -> bool:
    """XMAP missed triggers: pixel counter lags pixels-per-run."""
    return (
        int(ctx.scan_busy) == 1
        and int(ctx.acq_counter) != int(ctx.acq_target)
        and _struck_done(ctx)
    )


@flag_check
def xmap_lost_frames(ctx: SimpleNamespace) -> bool:
    """XMAP saved-frame count differs from expected while scan is active."""
    return _lost_frames_trigger(ctx, rate=None)


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.rstrip("\x00")
    try:
        seq = value.tolist() if hasattr(value, "tolist") else value
        if isinstance(seq, (list, tuple)) and seq and isinstance(seq[0], (int, float)):
            return "".join(chr(int(c)) for c in seq if int(c) != 0)
    except (TypeError, ValueError):
        pass
    return str(value).rstrip("\x00")


def _scan_num_from_filename(name: Any) -> Optional[int]:
    """Extract scan index from detector filename PV (e.g. ``8bmb_0031`` -> 31)."""
    text = _as_text(name).strip()
    if not text:
        return None
    suffix = text.rsplit("_", 1)[-1]
    if suffix.isdigit():
        return int(suffix)
    matches = re.findall(r"\d+", text)
    if not matches:
        return None
    return int(matches[-1])


@flag_check
def write_error(ctx: SimpleNamespace) -> bool:
    """Detector writer error while scan is active."""
    return int(ctx.scan_busy) == 1 and int(ctx.write_status) == 1


@flag_check
def filename_not_insync(ctx: SimpleNamespace) -> bool:
    """Detector filename PVs are out of sync with the scan."""
    if int(ctx.scan_busy) != 1 or int(ctx.capture) != 1:
        return False
    expected_scan = int(ctx.next_scan_number) - 1
    line_mismatch = int(ctx.detector_file_number) - 1 != int(ctx.scan_line)
    name_num = _scan_num_from_filename(ctx.detector_file_name)
    if name_num is not None:
        name_mismatch = name_num != expected_scan
    else:
        # XMAP FileName stem has no scan suffix (e.g. 2xfm_XMAP); use FileNumber.
        name_mismatch = int(ctx.detector_file_number) != expected_scan
    return name_mismatch and line_mismatch


_beam_dump_initialized = False
_beam_dump_active = False


def _beam_is_down(ctx: SimpleNamespace) -> bool:
    return int(ctx.actual_mode) != 4 and int(ctx.desired_mode) == 1


@flag_check
def beam_dump(ctx: SimpleNamespace) -> bool:
    """Beam dump or beam-off: fire once when ring leaves ops; reset when back up."""
    global _beam_dump_initialized, _beam_dump_active
    is_down = _beam_is_down(ctx)
    if not _beam_dump_initialized:
        _beam_dump_initialized = True
        _beam_dump_active = is_down
        return False
    if not is_down:
        _beam_dump_active = False
        return False
    if _beam_dump_active:
        return False
    _beam_dump_active = True
    return True


def ioc_is_down(context: Optional[ContextDict] = None) -> bool:
    """Required IOC is unreachable or not running."""
    return False


@flag_check
def scan_aborted(ctx: SimpleNamespace) -> bool:
    """Scan record status message reports an abort (fly and/or step records)."""
    return any(
        "Abort," in _as_text(value)
        for name, value in vars(ctx).items()
        if name.startswith("message_") and value is not None
    )


_pause_state_initialized = False
_last_pause_state = False
_pause_edges_for_tick: tuple[tuple[Any, ...], bool, bool] | None = None


def begin_flag_poll() -> None:
    """Clear per-poll pause edge cache; call once at the start of each flag poll."""
    global _pause_edges_for_tick
    _pause_edges_for_tick = None


def _in_pause_state(ctx: SimpleNamespace) -> bool:
    return _any_int_match(ctx, "is_paused", equals=1) or _any_int_match(
        ctx, "is_wait", nonzero=True
    )


def _scan_is_busy(ctx: SimpleNamespace) -> bool:
    return _any_int_match(ctx, "scan_busy", equals=1)


def _pause_identity(ctx: SimpleNamespace) -> tuple[Any, ...]:
    keys: list[Any] = []
    for name in sorted(vars(ctx)):
        if not name.startswith(("is_paused", "is_wait", "scan_busy")):
            continue
        value = getattr(ctx, name)
        try:
            keys.append(int(value) if value is not None else None)
        except (TypeError, ValueError):
            keys.append(None)
    return tuple(keys)


def _pause_edges(ctx: SimpleNamespace) -> tuple[bool, bool]:
    """Return (paused_edge, unpaused_edge) once per poll tick."""
    global _pause_state_initialized, _last_pause_state, _pause_edges_for_tick
    tick = _pause_identity(ctx)
    if _pause_edges_for_tick is not None and _pause_edges_for_tick[0] == tick:
        return _pause_edges_for_tick[1], _pause_edges_for_tick[2]

    in_pause = _in_pause_state(ctx)
    if not _pause_state_initialized:
        _pause_state_initialized = True
        _last_pause_state = in_pause
        paused_edge, unpaused_edge = False, False
    else:
        paused_edge = in_pause and not _last_pause_state
        unpaused_edge = _last_pause_state and not in_pause and _scan_is_busy(ctx)
        _last_pause_state = in_pause

    _pause_edges_for_tick = (tick, paused_edge, unpaused_edge)
    return paused_edge, unpaused_edge


@flag_check
def scan_paused(ctx: SimpleNamespace) -> bool:
    """Scan entered a paused/wait state (edge-triggered; fly and/or step)."""
    return _pause_edges(ctx)[0]


@flag_check
def scan_unpaused(ctx: SimpleNamespace) -> bool:
    """Scan resumed after pause/wait while still busy (edge-triggered; fly and/or step)."""
    return _pause_edges(ctx)[1]


@flag_check
def stage_stuck(ctx: SimpleNamespace) -> bool:
    """Sample stage motor not advancing while the scan expects motion."""
    return False


_last_memory_percent: float | None = None
_memory_high_active = False
_memory_critical_active = False


def system_memory_percent() -> float | None:
    """Return OS memory used percent, or None if unavailable."""
    try:
        import psutil  # type: ignore

        return float(psutil.virtual_memory().percent)
    except Exception:
        pass

    try:
        meminfo: dict[str, int] = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    meminfo[parts[0].rstrip(":")] = int(parts[1])
        total = meminfo["MemTotal"]
        available = meminfo.get("MemAvailable", meminfo["MemFree"])
        if total <= 0:
            return None
        return 100.0 * (1.0 - available / total)
    except (OSError, KeyError, ValueError):
        pass

    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return float(status.dwMemoryLoad)
    except Exception:
        pass
    return None


def memory_high(context: Optional[ContextDict] = None) -> bool:
    """System memory above 50% (orange); fires once until usage drops to <=50%."""
    global _last_memory_percent, _memory_high_active
    usage = system_memory_percent()
    _last_memory_percent = usage
    if usage is None:
        return False
    if usage <= MEMORY_HIGH_PCT:
        _memory_high_active = False
        return False
    if usage > MEMORY_HIGH_PCT and not _memory_high_active:
        _memory_high_active = True
        return True
    return False


def memory_critical(context: Optional[ContextDict] = None) -> bool:
    """System memory above 75% (red); fires once until usage drops to <=75%."""
    global _last_memory_percent, _memory_critical_active
    usage = system_memory_percent()
    _last_memory_percent = usage
    if usage is None:
        return False
    if usage <= MEMORY_CRITICAL_PCT:
        _memory_critical_active = False
        return False
    if usage > MEMORY_CRITICAL_PCT and not _memory_critical_active:
        _memory_critical_active = True
        return True
    return False


FLAG_FUNCTIONS: dict[str, FlagFunction] = {
    "struck_miss_trigger": struck_miss_trigger,
    "struck_stuck_acquiring": struck_stuck_acquiring,
    "xspress3_miss_trigger": xspress3_miss_trigger,
    "xspress3_lost_frame": xspress3_lost_frame,
    "xmap_miss_trigger": xmap_miss_trigger,
    "xmap_lost_frames": xmap_lost_frames,
    "write_error": write_error,
    "filename_not_insync": filename_not_insync,
    "beam_dump": beam_dump,
    "ioc_is_down": ioc_is_down,
    "scan_aborted": scan_aborted,
    "scan_paused": scan_paused,
    "scan_unpaused": scan_unpaused,
    "stage_stuck": stage_stuck,
    "memory_high": memory_high,
    "memory_critical": memory_critical,
}


def marker_color(flag_name: str) -> str:
    """Return plot marker color for a flag event."""
    if flag_name in ORANGE_FLAGS:
        return "orange"
    return "red"

