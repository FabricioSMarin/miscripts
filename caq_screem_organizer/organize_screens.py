#!/usr/bin/env python3
"""Build a caQtDM launcher .sh from open screen positions + caQtDM logs.

Runs `wmctrl -l -G`, keeps windows whose titles end in .ui/.adl, sorts them by
workspace then position, and fills in macros from caQtDM message-window logs
(`last file: ...ui, macro: ...`). Writes `<input_stem>` (no extension),
prefixed with the header from `template.sh`.

Usage:
    ./organize_screens.py 2idd_caqtdm_logs.txt
    ./organize_screens.py 2idd_caqtdm_logs.txt -w 2idd_screens.txt   # offline
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path

SCREEN_SUFFIXES = (".ui", ".adl")
SLEEP_SECONDS = 3
# wmctrl -l -G columns: id desktop x y w h client_machine title
_WMCTRL_NFIELDS = 7
SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = SCRIPT_DIR / "template.sh"
TEMPLATE_HEADER_LINES = 5

# 29-07-2026 12:20:03 last file: /path/scaler16_full.ui, macro: P=2idd:,S=scaler1
# 29-07-2026 11:49:36 last file: /path/2ida_hutch.ui
LAST_FILE_RE = re.compile(
    r"last file:\s*(?P<path>\S+\.(?:ui|adl))"
    r"(?:,\s*macro:\s*(?P<macro>.*))?$",
    re.IGNORECASE,
)

DEFAULT_HEADER = """\
#!/bin/csh
unsetenv MEDM_EXEC_LIST
unsetenv LD_LIBRARY_PATH /APSshare/caqtdm/lib
alias caQtDM "/APSshare/caqtdm/caqtdm-4.4.1/caQtDM_Binaries/rhel9-x86_64/caQtDM"
"""


def load_template_header() -> list[str]:
    """First TEMPLATE_HEADER_LINES of template.sh (fallback to DEFAULT_HEADER)."""
    if TEMPLATE_PATH.is_file():
        lines = TEMPLATE_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        header = lines[:TEMPLATE_HEADER_LINES]
        if header:
            return header
    return DEFAULT_HEADER.splitlines()


def is_screen_title(title: str) -> bool:
    return title.strip().endswith(SCREEN_SUFFIXES)


def read_text_file(path: Path) -> str:
    """Read text, tolerating UTF-8/UTF-16 and mixed newlines."""
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_wmctrl_lines(lines) -> list[dict]:
    """Parse `wmctrl -l -G` rows; ignore prompts/blank/non-window lines."""
    windows = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        fields = line.split(None, _WMCTRL_NFIELDS)
        if len(fields) < _WMCTRL_NFIELDS:
            continue
        wid, desktop, x, y, width, height, host = fields[:_WMCTRL_NFIELDS]
        title = fields[_WMCTRL_NFIELDS] if len(fields) > _WMCTRL_NFIELDS else ""
        if not wid.lower().startswith("0x"):
            continue
        try:
            workspace, xi, yi, wi, hi = (int(v) for v in (desktop, x, y, width, height))
        except ValueError:
            continue
        windows.append(
            {
                "wid": wid,
                "workspace": workspace,
                "x": xi,
                "y": yi,
                "w": wi,
                "h": hi,
                "host": host,
                "title": title,
            }
        )
    return windows


def _preview_lines(path: Path, text: str, limit: int = 3) -> str:
    samples = [ln for ln in text.splitlines() if ln.strip()][:limit]
    if not samples:
        return f"{path.resolve()} is empty ({path.stat().st_size} bytes)"
    shown = "\n".join(f"  | {ln[:120]}" for ln in samples)
    return (
        f"{path.resolve()} ({path.stat().st_size} bytes) has no lines matching "
        f"'0xID desktop x y w h host title'. First non-empty line(s):\n{shown}"
    )


def run_wmctrl() -> list[dict]:
    try:
        proc = subprocess.run(
            ["wmctrl", "-l", "-G"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("wmctrl not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"wmctrl failed: {err or exc}") from exc
    return parse_wmctrl_lines(proc.stdout.splitlines())


def parse_log_macros(lines) -> dict[str, list[str | None]]:
    """Map screen basename -> chronological macros from `last file:` lines."""
    macros: dict[str, list[str | None]] = defaultdict(list)
    for raw in lines:
        match = LAST_FILE_RE.search(raw.rstrip("\n"))
        if not match:
            continue
        screen = Path(match.group("path")).name
        macro = match.group("macro")
        if macro is not None:
            macro = macro.strip() or None
        macros[screen].append(macro)
    return macros


def screen_windows(windows: list[dict]) -> list[dict]:
    screens = [w for w in windows if is_screen_title(w["title"])]
    screens.sort(key=lambda w: (w["workspace"], w["x"], w["y"], w["title"].lower()))
    return screens


def assign_macros(screens: list[dict], macros: dict[str, list[str | None]]) -> tuple[int, int]:
    """Attach macros to screens. Uses the N most recent log opens per title.

    Returns (with_macro, without_macro).
    """
    needed = Counter(Path(w["title"].strip()).name for w in screens)
    pools: dict[str, deque[str | None]] = {}
    for name, count in needed.items():
        history = macros.get(name, [])
        recent = list(history[-count:]) if history else []
        if len(recent) < count:
            recent = [None] * (count - len(recent)) + recent
        pools[name] = deque(recent)

    for win in screens:
        name = Path(win["title"].strip()).name
        win["macro"] = pools[name].popleft()

    with_macro = sum(1 for w in screens if w.get("macro"))
    return with_macro, len(screens) - with_macro


def format_launch(win: dict, background: bool = True) -> str:
    title = Path(win["title"].strip()).name
    parts = ["caQtDM", "-x", "-attach", f"-dg +{win['x']}+{win['y']}"]
    if win.get("macro"):
        parts.append(f'-macro "{win["macro"]}"')
    parts.append(title)
    line = " ".join(parts)
    return f"{line} &" if background else line


def render_script(screens: list[dict], source_name: str) -> str:
    lines = list(load_template_header())
    # Ensure a blank line between header and workspace launches
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(f"# Generated by organize_screens.py from {source_name}")
    lines.append("")

    current_ws = None
    for win in screens:
        if win["workspace"] != current_ws:
            if current_ws is not None:
                lines.append("")
            current_ws = win["workspace"]
            lines.append(f"wmctrl -s {current_ws}")
        lines.append(format_launch(win))
        lines.append(f"sleep {SLEEP_SECONDS}")

    lines.append("")
    return "\n".join(lines)


def output_path_for(logfile: Path) -> Path:
    """Same directory/stem as the log, with no file extension."""
    return logfile.with_name(logfile.stem)


def build_launcher(
    log_text: str,
    *,
    windows: list[dict] | None = None,
    source_label: str = "caQtDM log",
) -> tuple[str, list[dict], int, int]:
    """Build launcher script text from caQtDM log + wmctrl windows.

    If *windows* is None, runs `wmctrl -l -G`.
    Returns (script_text, screens, with_macro_count, without_macro_count).
    """
    macros = parse_log_macros(log_text.splitlines())
    if not macros:
        raise ValueError("no 'last file:' entries found in caQtDM log")

    if windows is None:
        windows = run_wmctrl()

    screens = screen_windows(windows)
    if not screens:
        raise ValueError("no .ui/.adl screen windows found via wmctrl")

    with_macro, without_macro = assign_macros(screens, macros)
    script = render_script(screens, source_label)
    return script, screens, with_macro, without_macro


def backup_path(path: Path, when: datetime | None = None) -> Path:
    """Return `<name>_bak_YYYYMMDD_HHMMSS` beside *path*."""
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return path.with_name(f"{path.name}_bak_{stamp}")


def write_launcher(path: Path, content: str, *, make_backup: bool = True) -> Path | None:
    """Write *content* to *path*. If it exists, copy to `_bak_<datetime>` first.

    Returns the backup path (or None if no backup was made).
    """
    bak: Path | None = None
    if make_backup and path.is_file():
        bak = backup_path(path)
        shutil.copy2(path, bak)
    path.write_text(content, encoding="utf-8", newline="\n")
    try:
        path.chmod(path.stat().st_mode | 0o111)
    except OSError:
        pass
    return bak


def summarize_screens(screens: list[dict], with_macro: int, without_macro: int) -> str:
    by_ws = defaultdict(int)
    for win in screens:
        by_ws[win["workspace"]] += 1
    summary = ", ".join(f"ws{ws}={n}" for ws, n in sorted(by_ws.items()))
    return (
        f"{len(screens)} screens: {summary}; "
        f"{with_macro} with macros, {without_macro} without"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "logfile",
        type=Path,
        help="caQtDM message-window log (output is <stem>, no extension)",
    )
    parser.add_argument(
        "-w",
        "--wmctrl-file",
        type=Path,
        help="use this wmctrl -l -G capture instead of running wmctrl",
    )
    args = parser.parse_args(argv)

    if not args.logfile.is_file():
        parser.error(f"input file not found: {args.logfile}")

    log_text = read_text_file(args.logfile)

    windows = None
    if args.wmctrl_file:
        if not args.wmctrl_file.is_file():
            parser.error(f"wmctrl file not found: {args.wmctrl_file}")
        wmctrl_text = read_text_file(args.wmctrl_file)
        windows = parse_wmctrl_lines(wmctrl_text.splitlines())
        if not windows:
            parser.error(_preview_lines(args.wmctrl_file, wmctrl_text))

    try:
        script, screens, with_macro, without_macro = build_launcher(
            log_text,
            windows=windows,
            source_label=args.logfile.name,
        )
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))

    out_path = output_path_for(args.logfile)
    write_launcher(out_path, script, make_backup=False)
    print(f"wrote {out_path} ({summarize_screens(screens, with_macro, without_macro)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
