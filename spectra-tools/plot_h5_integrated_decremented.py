#!/usr/bin/env python3
"""
Build and plot a 2D map from row-wise HDF5 spectra with cumulative correction.

Each file stores running totals; the previous row's spectra are subtracted before
integrating, so the heatmap shows per-row counts only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm

from plot_h5_integrated import load_scan_rows_decremented


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
    parser.add_argument(
        "--title",
        default="Integrated counts per row (previous row subtracted)",
        help="plot title",
    )
    args = parser.parse_args()

    image, row_indices = load_scan_rows_decremented(args.data_dir)
    finite = image[np.isfinite(image)]
    positive = finite[finite > 0]
    vmin = max(float(positive.min()), 1.0) if positive.size else 1.0
    vmax = float(finite.max()) if finite.size else 1.0

    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(
        image,
        origin="lower",
        aspect="auto",
        cmap=args.cmap,
        norm=LogNorm(vmin=vmin, vmax=vmax),
        interpolation="nearest",
    )
    ax.set_xlabel("point index along row")
    ax.set_ylabel("row (from filename)")
    ax.set_title(args.title)
    fig.colorbar(im, ax=ax, label="integrated counts (decremented, log scale)")
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
