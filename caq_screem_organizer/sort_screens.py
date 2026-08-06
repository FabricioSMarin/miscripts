#!/usr/bin/env python3
"""Reorganize a captured `wmctrl -l -G` listing.

Rows are sorted by workspace (desktop) number, then by window geometry so the
ordering is stable.  Rows whose title is not a caQtDM screen (i.e. the title
does not end in .ui or .adl) are moved to the very end of the file, keeping the
same workspace ordering among themselves.

Usage:
    ./sort_screens.py 2xfm_screens.txt [sorted_2xfm_screens.txt]
"""

import argparse
import sys
from pathlib import Path

SCREEN_SUFFIXES = (".ui", ".adl")

# wmctrl -l -G columns: id desktop x y w h client_machine title
_NFIELDS = 7


class Window:
    """One parsed row of `wmctrl -l -G` output."""

    def __init__(self, wid, desktop, x, y, width, height, machine, title, raw):
        self.wid = wid
        self.desktop = desktop
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.machine = machine
        self.title = title
        self.raw = raw

    @property
    def is_screen(self):
        return self.title.strip().endswith(SCREEN_SUFFIXES)

    @property
    def sort_key(self):
        return (self.desktop, self.x, self.y, self.title.lower())

    def format(self):
        return (
            f"{self.wid}  {self.desktop} {self.x:<4} {self.y:<4} "
            f"{self.width:<4} {self.height:<4} {self.machine:>23} {self.title}"
        )


def parse_line(line):
    """Return a Window for a wmctrl row, or None for prompt/blank lines."""
    stripped = line.rstrip("\n")
    if not stripped.strip():
        return None

    fields = stripped.split(None, _NFIELDS)
    if len(fields) < _NFIELDS:
        return None

    wid, desktop, x, y, width, height, machine = fields[:_NFIELDS]
    title = fields[_NFIELDS] if len(fields) > _NFIELDS else ""

    if not wid.startswith("0x"):
        return None
    try:
        nums = [int(v) for v in (desktop, x, y, width, height)]
    except ValueError:
        return None

    return Window(wid, *nums, machine, title, stripped)


def load(path):
    windows, skipped = [], []
    with open(path) as handle:
        for line in handle:
            window = parse_line(line)
            if window is None:
                if line.strip():
                    skipped.append(line.rstrip("\n"))
            else:
                windows.append(window)
    return windows, skipped


def organize(windows):
    screens = sorted((w for w in windows if w.is_screen), key=lambda w: w.sort_key)
    others = sorted((w for w in windows if not w.is_screen), key=lambda w: w.sort_key)
    return screens, others


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="file holding `wmctrl -l -G` output")
    parser.add_argument("output", type=Path, nargs="?",
                        help="destination file (default: <input stem>_sorted<suffix>)")
    parser.add_argument("--no-headers", action="store_true",
                        help="omit the '# workspace N' comment lines")
    args = parser.parse_args(argv)

    out_path = args.output or args.input.with_name(
        f"{args.input.stem}_sorted{args.input.suffix or '.txt'}")

    windows, skipped = load(args.input)
    if not windows:
        parser.error(f"no wmctrl rows found in {args.input}")

    screens, others = organize(windows)

    lines = []
    current_desktop = None
    for window in screens:
        if not args.no_headers and window.desktop != current_desktop:
            if lines:
                lines.append("")
            lines.append(f"# workspace {window.desktop}")
            current_desktop = window.desktop
        lines.append(window.format())

    if others:
        if not args.no_headers:
            lines.append("")
            lines.append("# non-screen windows (no .ui/.adl title)")
        for window in others:
            lines.append(window.format())

    out_path.write_text("\n".join(lines) + "\n")

    print(f"{len(screens)} screen windows, {len(others)} other windows "
          f"-> {out_path}")
    if skipped:
        print(f"ignored {len(skipped)} non-wmctrl line(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
