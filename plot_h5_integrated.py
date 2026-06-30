#!/usr/bin/env python3
"""
Build and plot a 2D map from row-wise HDF5 spectra.

Each file is one scan row; the trailing number in the filename is the row index.
Data live at entry/data/data with shape (n_points, n_channels, n_bins).
Integrated counts per point = sum over spectrum bins, mean over channels.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import h5py
import matplotlib.pyplot as plt
import numpy as np

DATASET_PATHS = ("entry/data/data", "entry/data")


def row_index_from_name(path: Path) -> int:
    match = re.search(r"_(\d+)\.hdf5$", path.name, re.IGNORECASE)
    if not match:
        raise ValueError(f"cannot parse row index from filename: {path.name}")
    return int(match.group(1))


def load_dataset(h5_file: h5py.File) -> np.ndarray:
    for path in DATASET_PATHS:
        node = h5_file.get(path)
        if node is None:
            continue
        if isinstance(node, h5py.Dataset):
            return np.asarray(node)
        if isinstance(node, h5py.Group) and "data" in node:
            return np.asarray(node["data"])
    raise KeyError(f"no spectrum dataset found (tried {DATASET_PATHS})")


def integrated_counts(spectra: np.ndarray) -> np.ndarray:
    """Sum over energy bins, average over detector channels."""
    if spectra.ndim != 3:
        raise ValueError(f"expected 3D array (points, channels, bins), got {spectra.shape}")
    return spectra.sum(axis=2).mean(axis=1)


def decrement_spectra(current: np.ndarray, previous: np.ndarray | None) -> np.ndarray:
    """
    Remove cumulative counts from the previous row file.

    When point counts differ, subtract over the shared prefix; extra points in the
    current row are left unchanged (first row of a segment).
    """
    current = np.asarray(current, dtype=np.float64)
    if previous is None:
        return current
    previous = np.asarray(previous, dtype=np.float64)
    if current.shape == previous.shape:
        return np.maximum(current - previous, 0)
    n = min(current.shape[0], previous.shape[0])
    if current.shape[0] <= previous.shape[0]:
        return np.maximum(current - previous[:n], 0)
    out = current.copy()
    out[:n] = np.maximum(current[:n] - previous[:n], 0)
    return out


def load_scan_rows(data_dir: Path, pattern: str = "*.hdf5") -> tuple[np.ndarray, list[int]]:
    files = sorted(data_dir.glob(pattern), key=row_index_from_name)
    if not files:
        raise FileNotFoundError(f"no HDF5 files matching {pattern!r} in {data_dir}")

    rows: list[np.ndarray] = []
    row_indices: list[int] = []

    for path in files:
        row_idx = row_index_from_name(path)
        with h5py.File(path, "r") as f:
            spectra = load_dataset(f)
        rows.append(integrated_counts(spectra))
        row_indices.append(row_idx)

    n_rows = max(row_indices) + 1
    n_cols = max(r.size for r in rows)
    image = np.full((n_rows, n_cols), np.nan, dtype=np.float64)

    for row_idx, values in zip(row_indices, rows):
        image[row_idx, : values.size] = values

    return image, row_indices


def load_scan_rows_decremented(
    data_dir: Path, pattern: str = "*.hdf5"
) -> tuple[np.ndarray, list[int]]:
    """Like load_scan_rows, but subtracts the previous row's cumulative spectra first."""
    files = sorted(data_dir.glob(pattern), key=row_index_from_name)
    if not files:
        raise FileNotFoundError(f"no HDF5 files matching {pattern!r} in {data_dir}")

    rows: list[np.ndarray] = []
    row_indices: list[int] = []
    previous_spectra: np.ndarray | None = None

    for path in files:
        row_idx = row_index_from_name(path)
        with h5py.File(path, "r") as f:
            spectra = load_dataset(f)
        row_only = decrement_spectra(spectra, previous_spectra)
        rows.append(integrated_counts(row_only))
        row_indices.append(row_idx)
        previous_spectra = spectra

    n_rows = max(row_indices) + 1
    n_cols = max(r.size for r in rows)
    image = np.full((n_rows, n_cols), np.nan, dtype=np.float64)

    for row_idx, values in zip(row_indices, rows):
        image[row_idx, : values.size] = values

    return image, row_indices


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
    parser.add_argument("--cmap", default="viridis", help="matplotlib colormap")
    parser.add_argument("--title", default="Integrated counts (channel-averaged)", help="plot title")
    args = parser.parse_args()

    image, row_indices = load_scan_rows(args.data_dir)
    finite = image[np.isfinite(image)]
    vmin = float(finite.min()) if finite.size else 0.0
    vmax = float(finite.max()) if finite.size else 1.0

    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(
        image,
        origin="lower",
        aspect="auto",
        cmap=args.cmap,
        vmin=vmin,
        vmax=vmax,
        interpolation="nearest",
    )
    ax.set_xlabel("point index along row")
    ax.set_ylabel("row (from filename)")
    ax.set_title(args.title)
    fig.colorbar(im, ax=ax, label="integrated counts")
    fig.tight_layout()

    print(f"loaded {len(row_indices)} files, image shape {image.shape}")
    print(f"row indices: {min(row_indices)}..{max(row_indices)}")

    if args.output:
        fig.savefig(args.output, dpi=150, bbox_inches="tight")
        print(f"saved {args.output}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
