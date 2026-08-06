#!/usr/bin/env python3
"""Organize `wmctrl -l -G` output by workspace (desktop) number.

The input is a capture of `wmctrl -l -G`, optionally including the surrounding
shell prompt lines.  Each window row looks like:

    0x01e0008c  0 11   82   1000 388  host.example.gov  2ida_hutch.ui
    ^window id  ^ws ^x   ^y   ^w   ^h  ^host             ^title

Rows are grouped by the workspace number and printed under a header for each
workspace, aligned into columns.

Usage:
    ./organize_screens.py 2xfm_screens.txt
    ./organize_screens.py 2xfm_screens.txt -s position -o sorted.txt
    wmctrl -l -G | ./organize_screens.py
"""

import argparse
import re
import sys
from collections import defaultdict

# window-id  desktop  x  y  width  height  host  title
ROW_RE = re.compile(
    r"^\s*(?P<wid>0x[0-9a-fA-F]+)\s+"
    r"(?P<workspace>-?\d+)\s+"
    r"(?P<x>-?\d+)\s+(?P<y>-?\d+)\s+"
    r"(?P<w>-?\d+)\s+(?P<h>-?\d+)\s+"
    r"(?P<host>\S+)\s*"
    r"(?P<title>.*?)\s*$"
)

FIELDS = ("wid", "workspace", "x", "y", "w", "h", "host", "title")


def parse(lines):
    """Split lines into (windows, skipped) where windows are dicts of FIELDS."""
    windows, skipped = [], []
    for line in lines:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        match = ROW_RE.match(line)
        if match:
            win = match.groupdict()
            for key in ("workspace", "x", "y", "w", "h"):
                win[key] = int(win[key])
            windows.append(win)
        else:
            skipped.append(line)
    return windows, skipped


def sort_key(mode):
    if mode == "title":
        return lambda w: (w["title"].lower(), w["x"], w["y"])
    if mode == "position":
        return lambda w: (w["x"], w["y"])
    if mode == "size":
        return lambda w: (-(w["w"] * w["h"]), w["title"].lower())
    return lambda w: w["wid"]  # "id"


def format_groups(windows, mode, show_host):
    """Render windows grouped by workspace as a list of output lines."""
    groups = defaultdict(list)
    for win in windows:
        groups[win["workspace"]].append(win)

    cols = ["wid", "x", "y", "w", "h"] + (["host"] if show_host else []) + ["title"]
    widths = {c: max((len(str(w[c])) for w in windows), default=0) for c in cols}

    out = []
    for workspace in sorted(groups):
        members = sorted(groups[workspace], key=sort_key(mode))
        if out:
            out.append("")
        out.append(f"=== workspace {workspace} ({len(members)} windows) ===")
        for win in members:
            cells = [f"{str(win[c]):<{widths[c]}}" for c in cols[:-1]]
            cells.append(win["title"])
            out.append("  " + " ".join(cells).rstrip())
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("infile", nargs="?", type=argparse.FileType("r"),
                        default=sys.stdin, help="wmctrl -l -G capture (default: stdin)")
    parser.add_argument("-o", "--outfile", type=argparse.FileType("w"),
                        default=sys.stdout, help="output file (default: stdout)")
    parser.add_argument("-s", "--sort", choices=("id", "title", "position", "size"),
                        default="title", help="sort order within a workspace (default: title)")
    parser.add_argument("--no-host", action="store_true",
                        help="omit the host column")
    parser.add_argument("--show-skipped", action="store_true",
                        help="report lines that did not parse as window rows")
    args = parser.parse_args(argv)

    windows, skipped = parse(args.infile)
    if not windows:
        parser.error("no wmctrl window rows found in input")

    for line in format_groups(windows, args.sort, not args.no_host):
        print(line, file=args.outfile)

    if args.show_skipped and skipped:
        print("\n=== skipped lines ===", file=args.outfile)
        for line in skipped:
            print("  " + line, file=args.outfile)

    return 0


if __name__ == "__main__":
    sys.exit(main())
