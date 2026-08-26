#!/usr/bin/env python3
"""
Replace a string in file contents, filenames, and folder names under a directory.

Usage:
  python replace_string.py OLD_STRING NEW_STRING TOP_DIR [--dry-run] [--no-content] [--no-rename]

Options:
  --dry-run    Show what would be changed without making changes
  --no-content Skip replacing inside file contents
  --no-rename  Skip renaming files and folders
"""

import argparse
import os
import sys
from pathlib import Path


def get_all_paths(root: Path) -> tuple[list[Path], list[Path]]:
    """Walk root and return (dirs_depth_last, files). Dirs are ordered so deepest first for safe renames."""
    dirs = []
    files = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        p = Path(dirpath)
        dirs.append(p)
        for name in filenames:
            files.append(p / name)
    return dirs, files


def replace_in_file(path: Path, old: str, new: str, dry_run: bool) -> bool:
    """Replace old with new in file contents. Returns True if file was (or would be) modified."""
    try:
        raw = path.read_bytes()
    except (OSError, PermissionError) as e:
        print(f"  skip read: {path} - {e}", file=sys.stderr)
        return False

    # Skip binary: treat as binary if we see null bytes in first 8k
    sample = raw[:8192]
    if b"\x00" in sample:
        return False

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False

    if old not in text:
        return False

    new_text = text.replace(old, new)
    if new_text == text:
        return False

    if dry_run:
        print(f"  [content] {path}")
        return True

    path.write_text(new_text, encoding="utf-8")
    print(f"  [content] {path}")
    return True


def rename_path(path: Path, old: str, new: str, dry_run: bool) -> Path | None:
    """
    If path's name contains old, return the new Path it would have or was renamed to.
    Otherwise return None.
    """
    name = path.name
    if old not in name:
        return None
    new_name = name.replace(old, new)
    if new_name == name:
        return None
    new_path = path.parent / new_name
    if dry_run:
        print(f"  [rename] {path} -> {new_path}")
        return new_path
    try:
        path.rename(new_path)
        print(f"  [rename] {path} -> {new_path}")
        return new_path
    except (OSError, PermissionError) as e:
        print(f"  rename failed: {path} - {e}", file=sys.stderr)
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replace a string in file contents, filenames, and folder names."
    )
    parser.add_argument("old_string", help="String to find")
    parser.add_argument("new_string", help="String to replace with")
    parser.add_argument("top_dir", type=Path, help="Top directory to process")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print what would be changed",
    )
    parser.add_argument(
        "--no-content",
        action="store_true",
        help="Do not replace inside file contents",
    )
    parser.add_argument(
        "--no-rename",
        action="store_true",
        help="Do not rename files or folders",
    )
    args = parser.parse_args()

    old, new = args.old_string, args.new_string
    root = args.top_dir.resolve()

    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    if not old:
        print("old_string must be non-empty", file=sys.stderr)
        sys.exit(1)

    dirs, files = get_all_paths(root)

    # 1) Replace in file contents
    if not args.no_content:
        print("Replacing in file contents...")
        for f in files:
            replace_in_file(f, old, new, args.dry_run)

    if args.no_rename:
        if args.dry_run:
            print("\n[DRY RUN] No renames performed (--no-rename).")
        return

    # 2) Rename files (order doesn't matter for siblings)
    print("\nRenaming files...")
    for f in files:
        rename_path(f, old, new, args.dry_run)

    # 3) Rename dirs (deepest first is already the order from get_all_paths)
    print("Renaming folders...")
    for d in dirs:
        rename_path(d, old, new, args.dry_run)

    if args.dry_run:
        print("\n[DRY RUN] No changes were written.")


if __name__ == "__main__":
    main()
