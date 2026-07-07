#!/usr/bin/env python3
"""
Flag-event detectors for the EPICS scan monitor.

Each function evaluates a combination of PV values and returns True when the
corresponding fault condition is detected. This is where multi-PV logic lives:
the JSON config cannot express "fault when PV_a and PV_b disagree", so instead
the config lists each flag's input PVs and the monitor passes their current
values here as ``context`` (a dict keyed by the labels in the config).

``context`` keys are defined only in scan_monitor_config.json under each flag's
``inputs``; the monitor builds the dict each poll. The ``@flag_check`` decorator
converts that dict to a namespace so flag bodies use dot access (``ctx.scan_busy``).
"""

from __future__ import annotations

from functools import wraps
from types import SimpleNamespace
from typing import Any, Callable, Optional

# Flags that fire immediately on first positive check (no flag_confirm_s wait).
FLAGS_NO_CONFIRM = frozenset({"scan_aborted", "scan_paused", "scan_unpaused"})

# Orange markers: aborted, paused, or beam dump on the event-time plot.
ORANGE_FLAGS = frozenset({"scan_aborted", "beam_dump", "scan_paused", "scan_unpaused"})

# Red markers: all other flag events.
RED_FLAGS = frozenset(
    {
        "struck_miss_trigger",
        "struck_stuck_acquiring",
        "xspress3_miss_trigger",
        "xspress3_lost_frame",
        "filename_not_insync",
        "ioc_is_down",
        "stage_stuck",
    }
)

ContextDict = dict[str, Any]
FlagLogic = Callable[[SimpleNamespace], bool]
FlagFunction = Callable[[Optional[ContextDict]], bool]


def flag_check(fn: FlagLogic) -> FlagFunction:
    """Wrap a flag body that takes a namespace of input PV values.

    The monitor passes whatever ``inputs`` labels are in the JSON for that flag.
    Returns False when context is missing or any value is None (unread PV).
    """

    @wraps(fn)
    def wrapper(context: Optional[ContextDict] = None) -> bool:
        if not context or any(v is None for v in context.values()):
            return False
        return fn(SimpleNamespace(**context))

    return wrapper


@flag_check
def struck_miss_trigger(ctx: SimpleNamespace) -> bool:
    """Struck 3820 still acquiring and missing triggers after stage motion done."""
    return (
        int(ctx.scan_busy) == 1
        and int(ctx.acquiring) == 1
        and int(ctx.current_channel) != int(ctx.nuse_all)
        and int(ctx.current_channel) > 0
        and (float(ctx.elapsed_time)) > (8 + ctx.dwell_time * ctx.nuse_all / 1000)
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
        and int(ctx.array_rate) == 0
        and int(ctx.array_counter) != int(ctx.array_num)
        and int(ctx.struck_acquiring) == 0
        and int(ctx.struck_current) == int(ctx.struck_all)
    )


@flag_check
def xspress3_lost_frame(ctx: SimpleNamespace) -> bool:
    """Xspress3 saved-frame count differs from received triggers while capturing."""
    return (
        int(ctx.scan_busy) == 1
        and int(ctx.array_rate) == 0
        and int(ctx.num_frames) != int(ctx.saved_frames)
        and int(ctx.struck_acquiring) == 0
        and int(ctx.struck_current) == int(ctx.struck_all)
    )

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


def _scan_num_from_filename(name: Any) -> int:
    suffix = str(name).rsplit("_", 1)[-1]
    return int(suffix)

@flag_check
def write_error(ctx: SimpleNamespace) -> bool:
    """Xspress3 write error: the detector is in an error state and the HDF writer is not capturing."""
    return int(ctx.scan_busy) == 1 and int(ctx.write_status) != 0


@flag_check
def filename_not_insync(ctx: SimpleNamespace) -> bool:
    """Area detector / xspress3 filename PVs are out of sync with the scan."""
    return (
        int(ctx.scan_busy) == 1
        and int(ctx.capture) == 1
        and _scan_num_from_filename(ctx.xp3_file_name) != int(ctx.next_scan_number) - 1
        and int(ctx.xp3_file_number) - 1 != int(ctx.scan_line)
    )


@flag_check
def beam_dump(ctx: SimpleNamespace) -> bool:
    """Beam dump or beam-off: ring left operations mode during user operations."""
    return int(ctx.actual_mode) != 4 and int(ctx.desired_mode) == 1


def ioc_is_down(context: Optional[ContextDict] = None) -> bool:
    """Required IOC is unreachable or not running."""
    return False


@flag_check
def scan_aborted(ctx: SimpleNamespace) -> bool:
    """Scan record status message reports an abort."""
    return "Abort," in _as_text(ctx.message_outer) or "Abort," in _as_text(ctx.message_inner)


_pause_state_initialized = False
_last_pause_state = False
_pause_edges_for_tick: tuple[tuple[int, int, int, int], bool, bool] | None = None


def begin_flag_poll() -> None:
    """Clear per-poll pause edge cache; call once at the start of each flag poll."""
    global _pause_edges_for_tick
    _pause_edges_for_tick = None


def _in_pause_state(ctx: SimpleNamespace) -> bool:
    return (
        int(ctx.is_paused) == 1
        or int(ctx.is_wait_inner) != 0
        or int(ctx.is_wait_outer) != 0
    )


def _pause_edges(ctx: SimpleNamespace) -> tuple[bool, bool]:
    """Return (paused_edge, unpaused_edge) once per poll tick."""
    global _pause_state_initialized, _last_pause_state, _pause_edges_for_tick
    tick = (
        int(ctx.is_paused),
        int(ctx.is_wait_inner),
        int(ctx.is_wait_outer),
        int(ctx.scan_busy),
    )
    if _pause_edges_for_tick is not None and _pause_edges_for_tick[0] == tick:
        return _pause_edges_for_tick[1], _pause_edges_for_tick[2]

    in_pause = _in_pause_state(ctx)
    if not _pause_state_initialized:
        _pause_state_initialized = True
        _last_pause_state = in_pause
        paused_edge, unpaused_edge = False, False
    else:
        paused_edge = in_pause and not _last_pause_state
        unpaused_edge = _last_pause_state and not in_pause and int(ctx.scan_busy) == 1
        _last_pause_state = in_pause

    _pause_edges_for_tick = (tick, paused_edge, unpaused_edge)
    return paused_edge, unpaused_edge


@flag_check
def scan_paused(ctx: SimpleNamespace) -> bool:
    """Scan entered a paused/wait state (edge-triggered)."""
    return _pause_edges(ctx)[0]


@flag_check
def scan_unpaused(ctx: SimpleNamespace) -> bool:
    """Scan resumed after pause/wait while still busy (edge-triggered)."""
    return _pause_edges(ctx)[1]


@flag_check
def stage_stuck(ctx: SimpleNamespace) -> bool:
    """Sample stage motor not advancing while the scan expects motion."""
    return False


FLAG_FUNCTIONS: dict[str, FlagFunction] = {
    "struck_miss_trigger": struck_miss_trigger,
    "struck_stuck_acquiring": struck_stuck_acquiring,
    "xspress3_miss_trigger": xspress3_miss_trigger,
    "xspress3_lost_frame": xspress3_lost_frame,
    "filename_not_insync": filename_not_insync,
    "beam_dump": beam_dump,
    "ioc_is_down": ioc_is_down,
    "scan_aborted": scan_aborted,
    "scan_paused": scan_paused,
    "scan_unpaused": scan_unpaused,
    "stage_stuck": stage_stuck,
}


def marker_color(flag_name: str) -> str:
    """Return plot marker color for a flag event."""
    if flag_name in ORANGE_FLAGS:
        return "orange"
    return "red"
