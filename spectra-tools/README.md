# spectra-tools

HDF5 / NetCDF helpers for XRF spectra and scan maps.

## Dependencies

```bash
pip install -r requirements-h5plot.txt
```

`XMAPnc_reader.py` also needs SciPy (`scipy`).

---

## `plot_h5_integrated_decremented.py`

Build a 2D heatmap from row-wise HDF5 spectra. Each file stores cumulative totals; the previous row is subtracted before integrating so the map shows per-row counts.

```bash
python plot_h5_integrated_decremented.py -d /path/to/row_hdf5_dir
python plot_h5_integrated_decremented.py -d /path/to/data -o map.png --cmap viridis
```

Requires helper module `plot_h5_integrated` (same directory) for `load_scan_rows_decremented`.

---

## `plot_h5_totals_decremented.py`

Plot total integrated counts per row after removing cumulative spectra (same decrement logic as above).

```bash
python plot_h5_totals_decremented.py -d /path/to/row_hdf5_dir
python plot_h5_totals_decremented.py -d /path/to/data -o totals.png
```

---

## `XMAPnc_reader.py`

Read XIA xMAP NetCDF buffers from EPICS mapping mode and plot MCA spectra.

Edit `base_dir` at the bottom of the file, then:

```bash
python XMAPnc_reader.py
```

Or from Python:

```python
from XMAPnc_reader import plot_spectra, process_directory

plot_spectra("scan_0001.nc", save_path="scan_0001.png")
process_directory("/path/to/nc_dir", include_summed=False)
```
