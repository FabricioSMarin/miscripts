#!/usr/bin/env python3
"""
Plot total integrated counts per HDF5 row file.

For each file: load spectra, average over channels, integrate over energy bins
per point, then sum over all points in that row.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import h5py
import matplotlib.pyplot as plt
import numpy as np

from plot_h5_integrated import integrated_counts, load_dataset, row_index_from_name


def total_counts_per_file(data_dir: Path, pattern: str = "*.hdf5") -> tuple[np.ndarray, np.ndarray, list[Path]]:
    files = sorted(data_dir.glob(pattern), key=row_index_from_name)
    if not files:
        raise FileNotFoundError(f"no HDF5 files matching {pattern!r} in {data_dir}")

    row_indices: list[int] = []
    totals: list[float] = []

    for path in files:
        with h5py.File(path, "r") as f:
            spectra = load_dataset(f)
        row_indices.append(row_index_from_name(path))
        totals.append(float(integrated_counts(spectra).sum()))

    order = np.argsort(row_indices)
    rows = np.asarray(row_indices, dtype=int)[order]
    counts = np.asarray(totals, dtype=np.float64)[order]
    sorted_files = [files[i] for i in order]
    return rows, counts, sorted_files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-d",
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "test",
        help="directory containing row HDF5 files",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="save figure to this path (default: show interactively)",
    )
    parser.add_argument("--title", default="Total counts per row file", help="plot title")
    args = parser.parse_args()

    rows, counts, files = total_counts_per_file(args.data_dir)

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(rows, counts, "o-", markersize=4, linewidth=1)
    ax.set_xlabel("row (from filename)")
    ax.set_ylabel("total integrated counts")
    ax.set_title(args.title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    print(f"loaded {len(files)} files, rows {rows.min()}..{rows.max()}")
    for path, row, total in zip(files, rows, counts):
        print(f"  {path.name}: row {row}, total {total:.0f}")

    if args.output:
        fig.savefig(args.output, dpi=150, bbox_inches="tight")
        print(f"saved {args.output}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
