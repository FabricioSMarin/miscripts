#!/usr/bin/env python3
"""
Flag-event detectors for the EPICS scan monitor.

Each function evaluates a combination of PV values and returns True when the
corresponding fault condition is detected. This is where multi-PV logic lives:
the JSON config cannot express "fault when PV_a and PV_b disagree", so instead
the config lists each flag's input PVs and the monitor passes their current
values here as ``context`` (a dict keyed by the labels in the config).

``context`` keys for each flag match the ``inputs`` labels in
scan_monitor_config.json. ``beam_dump`` below is a worked example; the others
are stubs documenting their expected inputs until the calculations are filled
in. The monitor calls these on a polling interval and logs the flag_events PV
snapshot whenever a function returns True.
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
    """Struck 3820 still acquiring and missing triggers after stage motion done.

    context inputs: acquiring, nuse_all, current_channel, requested_position,
    actual_position.
    """

    if not context:
        return False
    acquiring = context.get(acquiring)
    nuse_all = context.get(nuse_all)
    current_channel = context.get(current_channel)
    requested_position = context.get(requested_position)
    actual_position = context.get(actual_position)
    scan_busy = context.get(scan_busy)
    dwell_time = context.get(dwell_time)
    elapsed_time = context.get(elapsed_time)

    missed_trigger = acquiring is not None and \
        nuse_all is not None and \
        current_channel is not None and \
        requested_position is not None and \
        scan_busy is not None and \
        dwell_time is not None and \
        elapsed_time is not None and \
        int(scan_busy) == 1 and \
        int(acquiring) == 1 and \
        int(current_channel) != int(nuse_all) and \
        int(current_channel) > 0 and \
        float(elapsed_time)+8 > dwell_time*nuse_all/1000

    return missed_trigger 

def struck_stuck_acquiring(context: Optional[dict[str, Any]] = None) -> bool:
    """Struck 3820 stuck acquiring after receiving all triggers.

    context inputs: acquiring, nuse_all, current_channel, scan_busy.
    """
    if not context:
        return False
    acquiring = context.get(acquiring)
    nuse_all = context.get(nuse_all)
    current_channel = context.get(current_channel)
    scan_busy = context.get(scan_busy)

    struck_stuck_acquiring = acquiring is not None and \
        nuse_all is not None and \
        current_channel is not None and \
        scan_busy is not None and \
        int(scan_busy) == 1 and \
        int(acquiring) == 1 and \
        int(current_channel) == int(nuse_all)

    return struck_stuck_acquiring 


def xspress3_miss_trigger(context: Optional[dict[str, Any]] = None) -> bool:
    """Xspress3 missed an expected acquisition trigger.

    context inputs: number_of_images, array_counter, detector_state,
    trigger_mode.
    """
        # {"label": "scan_busy", "pv": "8bmbsft:Fscan1.BUSY"},
        # {"label": "array_rate", "pv": "8bmbXP3:det1:ArrayRate_RBV"},
        # {"label": "array_num", "pv": "8bmbXP3:det1:NumImages_RBV"},
        # {"label": "array_counter", "pv": "8bmbXP3:det1:ArrayCounter_RBV"},
        # {"label": "num_frames", "pv": "8bmbXP3:HDF1:NumCapture_RBV"},
        # {"label": "saved_frames", "pv": "8bmbXP3:HDF1:NumCaptured_RBV"},
        # {"label": "detector_state", "pv": "8bmbXP3:det1:DetectorState_RBV"},
        # {"label": "struck_current", "pv": "8bmb:3820:CurrentChannel"},
        # {"label": "struck_all", "pv": "8bmb:3820:NuseAll"},
        # {"label": "struck_acquiring", "pv": "8bmb:3820:Acquiring"}
    if not context:
        return False
    acquiring = context.get(acquiring)
    nuse_all = context.get(nuse_all)
    current_channel = context.get(current_channel)
    scan_busy = context.get(scan_busy)

    struck_stuck_acquiring = acquiring is not None and \
        nuse_all is not None and \
        current_channel is not None and \
        scan_busy is not None and \
        int(scan_busy) == 1 and \
        int(acquiring) == 1 and \
        int(current_channel) == int(nuse_all)

    return struck_stuck_acquiring 


def xspress3_lost_frame(context: Optional[dict[str, Any]] = None) -> bool:
    """Xspress3 saved-frame count differs from received triggers while capturing.

    context inputs: number_of_images, array_counter, capture, num_captured.
    """
    return False


def filename_not_insync(context: Optional[dict[str, Any]] = None) -> bool:
    """Area detector / xspress3 filename PVs are out of sync with the scan."""
    return False


def beam_dump(context: Optional[dict[str, Any]] = None) -> bool:
    """Beam dump or beam-off condition detected.

    Worked example of a combination check. context inputs:
      - actual_mode:   S:ActualMode (4 == user/top-up operations)
      - desired_mode:  S:DesiredMode (1 == user operations)

    Fires when the ring leaves operations mode or and desired mode is user-operations.
    """
    if not context:
        return False
    actual_mode = context.get("actual_mode")
    desired_mode = context.get("desired_mode")

    mode_lost = actual_mode is not None and \
        desired_mode is not None and \
        int(actual_mode) != 4 and \
        int(desired_mode) == 1
  
    return mode_lost 


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
    """Sample stage motor not advancing while the scan expects motion.

    context inputs: requested_position, actual_position, velocity, scan_busy.
    """
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
