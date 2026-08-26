# caq_screen_organizer

Build caQtDM launcher scripts from open screen positions (`wmctrl`) and caQtDM message-window logs.

Requires `wmctrl` on the PATH when capturing live window geometry (or pass a saved capture with `-w`).

---

## `organize_screens.py`

Parse a caQtDM log, match open `.ui` / `.adl` windows, and write an extensionless launcher script next to the log.

```bash
python organize_screens.py 2idd_caqtdm_logs.txt
python organize_screens.py 2idd_caqtdm_logs.txt -w 2idd_screens.txt
```

Output is written as `<logfile_stem>` (no extension), e.g. `2idd_caqtdm_logs`.

---

## `organize_screens_gui.py`

Interactive GUI: paste caQtDM logs, pick the launcher to update, then Generate (backs up the existing launcher first).

```bash
python organize_screens_gui.py
```

---

## `sort_screens.py`

Reorganize a captured `wmctrl -l -G` listing by workspace and geometry; non-screen windows go last.

```bash
wmctrl -l -G > screens.txt
python sort_screens.py screens.txt
python sort_screens.py screens.txt screens_sorted.txt --no-headers
```

---

## Shell / sample data

- `template.sh` — launcher template filled by the organizers
- `2idd_*.sh` / `2xfm_*.sh` — example generated launchers
- `*.txt` — sample `wmctrl` captures and caQtDM logs
