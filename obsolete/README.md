# obsolete

Retired scripts kept for reference. Prefer current tools elsewhere in this repo.

---

## `xspress3_guardian.py`

Monitor an XSpress3 IOC screen session; on errors or crashes during a scan, pause, restart the IOC, reinitialize, and resume.

```bash
python xspress3_guardian.py \
  -s 2id_1ChXpress3 \
  -r "/path/to/ioc.pl restart" \
  --start "/path/to/ioc.pl start" \
  --prefix "fsm:" \
  --xp3 "XSP3_1Chan:" \
  --xp3-setup "fsm:userTran2.PROC"
```

Needs: `pip install pyepics`.

---

## `run_xspress3_guardian.sh`

Beamline wrapper that launches `xspress3_guardian.py` with 8-BM-B paths in a new terminal when possible.

```bash
./run_xspress3_guardian.sh
```

Edit `GUARDIAN`, `PYTHON_BIN`, and the PV / IOC arguments inside the script for your installation.
