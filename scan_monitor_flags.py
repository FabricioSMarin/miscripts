#!/usr/bin/env python3
"""
Flag-event detectors for the EPICS scan monitor.

Each function is a placeholder for future callback logic that evaluates PV
combinations. Functions return True when the corresponding fault condition is
detected. The monitor calls them on a polling interval and logs flag-event PVs
when a function returns True.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

# Orange markers: aborted, paused, or beam dump on the event-time plot.
ORANGE_FLAGS = frozenset({"scan_aborted", "beam_dump", "scan_paused"})

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


def struck_miss_trigger(context: Optional[dict[str, Any]] = None) -> bool:
    """Struck detector missed an expected trigger."""
    return False


def struck_stuck_acquiring(context: Optional[dict[str, Any]] = None) -> bool:
    """Struck detector stuck in acquiring state."""
    return False


def xspress3_miss_trigger(context: Optional[dict[str, Any]] = None) -> bool:
    """Xspress3 missed an expected acquisition trigger."""
    return False


def xspress3_lost_frame(context: Optional[dict[str, Any]] = None) -> bool:
    """Xspress3 dropped or failed to deliver a frame."""
    return False


def filename_not_insync(context: Optional[dict[str, Any]] = None) -> bool:
    """Area detector / xspress3 filename PVs are out of sync with the scan."""
    return False


def beam_dump(context: Optional[dict[str, Any]] = None) -> bool:
    """Beam dump or beam-off condition detected."""
    return False


def ioc_is_down(context: Optional[dict[str, Any]] = None) -> bool:
    """Required IOC is unreachable or not running."""
    return False


def scan_aborted(context: Optional[dict[str, Any]] = None) -> bool:
    """Scan record reports an abort."""
    return False


def scan_paused(context: Optional[dict[str, Any]] = None) -> bool:
    """Scan record reports a pause."""
    return False


def stage_stuck(context: Optional[dict[str, Any]] = None) -> bool:
    """Sample stage motor stuck while scan expects motion."""
    return False


FlagFunction = Callable[[Optional[dict[str, Any]]], bool]

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
    "stage_stuck": stage_stuck,
}


def marker_color(flag_name: str) -> str:
    """Return plot marker color for a flag event."""
    if flag_name in ORANGE_FLAGS:
        return "orange"
    return "red"
