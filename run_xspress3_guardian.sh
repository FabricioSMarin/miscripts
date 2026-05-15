#!/usr/bin/env bash
set -euo pipefail

CONDA_PYTHON="/home/beams/USER8BMB/.conda/envs/batchpy/bin/python"
# Prefer the requested conda environment Python; allow override via $PYTHON_BIN.
PYTHON_BIN="${PYTHON_BIN:-$CONDA_PYTHON}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi
GUARDIAN="/home/beams/USER8BMB/python/xspress3_guardian.py"

CMD=(
  "$PYTHON_BIN" "$GUARDIAN"
  -s 8bmb_8ChXspress3
  -r "/net/s8bmdserv/xorApps/epics/synApps_6_3/ioc/8bmbxspress3/iocBoot/ioc8bmb_8ChXspress3/softioc/8bmb_8ChXspress3.pl restart"
  --start "/net/s8bmdserv/xorApps/epics/synApps_6_3/ioc/8bmbxspress3/iocBoot/ioc8bmb_8ChXspress3/softioc/8bmb_8ChXspress3.pl start"
  --prefix "8bmbsft:"
  --xp3 "8bmbXP3:"
  --xp3-setup "8bmbsft:userTran14.PROC"
  --flag-pv "8bmbsft:userCalc3.VAL"
)

run_in_new_terminal() {
  local title="xspress3_guardian"
  local joined
  printf -v joined '%q ' "${CMD[@]}"

  if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title="$title" -- bash -lc "$joined; echo; echo '[guardian exited] press Enter to close...'; read -r"
    return 0
  fi
  if command -v xfce4-terminal >/dev/null 2>&1; then
    xfce4-terminal --title="$title" --command "bash -lc $joined; echo; echo '[guardian exited] press Enter to close...'; read -r"
    return 0
  fi
  if command -v konsole >/dev/null 2>&1; then
    konsole --new-tab -p tabtitle="$title" -e bash -lc "$joined; echo; echo '[guardian exited] press Enter to close...'; read -r"
    return 0
  fi
  if command -v xterm >/dev/null 2>&1; then
    xterm -T "$title" -e bash -lc "$joined; echo; echo '[guardian exited] press Enter to close...'; read -r"
    return 0
  fi

  return 1
}

if run_in_new_terminal; then
  exit 0
fi

echo "No supported GUI terminal found; running in this shell."
exec "${CMD[@]}"
