# epics-tools

EPICS examples and related beamline config snippets.

---

## `epics_callback_example.py`

Monitor an EPICS PV and run a callback on each value change.

```bash
# Edit pv_name (default OPS:message7), then:
python epics_callback_example.py
```

Needs: `pip install pyepics` (and a working CA/PVA environment).

---

## Other files

- `XP3.xml` — Xspress3-related EPICS / caQtDM configuration fragment
- `standard_parameters.db` — EPICS database of standard parameters
