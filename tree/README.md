# tree

Quick viewers for common scientific file layouts. Edit the example path at the bottom of each script before running.

---

## `h5tree.py`

Print an HDF5 group/dataset tree.

```bash
# Edit the path passed to display_h5_structure(), then:
python h5tree.py
```

```python
from h5tree import display_h5_structure

display_h5_structure("/path/to/file.h5")
```

Needs: `pip install h5py`.

---

## `mdatree.py`

Load an MDA file via `mdaio` and print its shape.

```bash
# Edit the path in the script, then:
python mdatree.py
```

Needs: `mdaio` and `numpy`.

---

## `nctree.py`

Open a NetCDF file and print dimensions, variables, and data.

```bash
# Edit the path in the script, then:
python nctree.py
```

Needs: `pip install netCDF4`.
