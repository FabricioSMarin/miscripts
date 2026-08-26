#!/usr/bin/env python3
"""
Convert areaDetector / NeXus HDF5 image stacks to MP4 video.

Frame rate is inferred from per-frame EPICS timestamps when present
(``entry/instrument/NDAttributes/NDArrayEpicsTSSec`` and
``NDArrayEpicsTSnSec``). Otherwise falls back to ``NDArrayTimeStamp`` or
a user-supplied default.

Scan an input directory once, or watch it continuously for new HDF5 files.
Already-converted files are skipped unless the HDF5 is newer than the video
or ``--force`` is used.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path

import h5py
import imageio.v3 as iio
import numpy as np

LOG = logging.getLogger(__name__)

_URI_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

H5_EXTENSIONS = {".hdf5", ".h5", ".hdf"}


def normalize_path(path: Path) -> Path:
    """Expand ~ and resolve local paths; leave URI-style paths (e.g. smb:/) unchanged."""
    expanded = path.expanduser()
    if _URI_SCHEME.match(str(expanded)):
        return expanded
    return expanded.resolve()
DATASET_CANDIDATES = (
    "entry/data/data",
    "entry/instrument/detector/data",
    "data",
)
EPICS_SEC_PATH = "entry/instrument/NDAttributes/NDArrayEpicsTSSec"
EPICS_NSEC_PATH = "entry/instrument/NDAttributes/NDArrayEpicsTSnSec"
TIMESTAMP_PATH = "entry/instrument/NDAttributes/NDArrayTimeStamp"


def resolve_dataset(h5_file: h5py.File) -> h5py.Dataset:
    for path in DATASET_CANDIDATES:
        if path in h5_file:
            return h5_file[path]
    raise KeyError(
        "could not find image data; tried: "
        + ", ".join(DATASET_CANDIDATES)
    )


def _fps_from_epics(h5_file: h5py.File) -> float | None:
    if EPICS_SEC_PATH not in h5_file or EPICS_NSEC_PATH not in h5_file:
        return None

    sec = np.asarray(h5_file[EPICS_SEC_PATH][:], dtype=np.float64)
    nsec = np.asarray(h5_file[EPICS_NSEC_PATH][:], dtype=np.float64)
    if sec.shape != nsec.shape or sec.size < 2:
        return None

    timestamps = sec + nsec * 1e-9
    deltas = np.diff(timestamps)
    deltas = deltas[np.isfinite(deltas) & (deltas > 0)]
    if deltas.size == 0:
        return None

    fps = 1.0 / float(np.median(deltas))
    LOG.debug(
        "EPICS timestamps: median dt=%.6fs -> %.3f fps",
        float(np.median(deltas)),
        fps,
    )
    return fps


def _fps_from_nd_timestamp(h5_file: h5py.File) -> float | None:
    if TIMESTAMP_PATH not in h5_file:
        return None

    timestamps = np.asarray(h5_file[TIMESTAMP_PATH][:], dtype=np.float64)
    if timestamps.size < 2:
        return None

    deltas = np.diff(timestamps)
    deltas = deltas[np.isfinite(deltas) & (deltas > 0)]
    if deltas.size == 0:
        return None

    fps = 1.0 / float(np.median(deltas))
    LOG.debug(
        "NDArrayTimeStamp: median dt=%.6fs -> %.3f fps",
        float(np.median(deltas)),
        fps,
    )
    return fps


def infer_fps(h5_file: h5py.File, default_fps: float) -> float:
    for detector in (_fps_from_epics, _fps_from_nd_timestamp):
        fps = detector(h5_file)
        if fps is not None and fps > 0:
            return fps

    LOG.warning(
        "could not infer frame rate from metadata; using default %.3f fps",
        default_fps,
    )
    return default_fps


def frame_to_rgb(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return np.stack([frame, frame, frame], axis=-1)
    if frame.ndim == 3 and frame.shape[-1] in (3, 4):
        return frame[..., :3]
    raise ValueError(f"unsupported frame shape: {frame.shape}")


def output_path_for(h5_path: Path, output_dir: Path | None) -> Path:
    target_dir = output_dir if output_dir is not None else h5_path.parent
    return target_dir / f"{h5_path.stem}.mp4"


def needs_conversion(h5_path: Path, video_path: Path, force: bool) -> bool:
    if force:
        return True
    if not video_path.exists():
        return True
    return h5_path.stat().st_mtime > video_path.stat().st_mtime


def convert_hdf5(
    h5_path: Path,
    output_dir: Path | None = None,
    *,
    default_fps: float = 5.0,
    force: bool = False,
) -> Path | None:
    video_path = output_path_for(h5_path, output_dir)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    if not needs_conversion(h5_path, video_path, force):
        LOG.info("skip (up to date): %s", h5_path.name)
        return None

    with h5py.File(h5_path, "r") as h5_file:
        dataset = resolve_dataset(h5_file)
        frames = dataset[()]
        fps = infer_fps(h5_file, default_fps)

    if frames.ndim != 3:
        raise ValueError(
            f"{h5_path}: expected a 3D stack (frames, height, width); "
            f"got shape {frames.shape}"
        )

    rgb_frames = np.stack([frame_to_rgb(frames[i]) for i in range(frames.shape[0])])

    LOG.info(
        "writing %s (%d frames, %.3f fps) -> %s",
        h5_path.name,
        frames.shape[0],
        fps,
        video_path,
    )
    iio.imwrite(
        video_path,
        rgb_frames,
        fps=fps,
        codec="libx264",
        plugin="FFMPEG",
    )
    return video_path


def iter_hdf5_files(input_dir: Path) -> list[Path]:
    files = [
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in H5_EXTENSIONS
    ]
    return sorted(files)


def scan_directory(
    input_dir: Path,
    output_dir: Path | None,
    *,
    default_fps: float,
    force: bool,
) -> int:
    converted = 0
    for h5_path in iter_hdf5_files(input_dir):
        try:
            result = convert_hdf5(
                h5_path,
                output_dir,
                default_fps=default_fps,
                force=force,
            )
            if result is not None:
                converted += 1
        except Exception:
            LOG.exception("failed to convert %s", h5_path)
    return converted


def watch_directory(
    input_dir: Path,
    output_dir: Path | None,
    *,
    interval: float,
    default_fps: float,
    force: bool,
) -> None:
    LOG.info(
        "watching %s every %.1fs (Ctrl+C to stop)",
        input_dir,
        interval,
    )
    try:
        while True:
            scan_directory(
                input_dir,
                output_dir,
                default_fps=default_fps,
                force=force,
            )
            time.sleep(interval)
    except KeyboardInterrupt:
        LOG.info("stopped")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-i",
        "--input_dir",
        type=Path,
        help="directory to scan for HDF5 files",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="directory for MP4 files (default: same directory as each HDF5)",
    )
    parser.add_argument(
        "--default-fps",
        type=float,
        default=5.0,
        help="fallback frame rate when timestamps are missing (default: 5)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="keep scanning for new files instead of running once",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="seconds between scans in watch mode (default: 5)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="reconvert even when the MP4 already exists and is up to date",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable debug logging",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    input_dir = normalize_path(args.input_dir)
    if not input_dir.is_dir():
        LOG.error("input directory does not exist: %s", input_dir)
        return 1

    output_dir = (
        normalize_path(args.output_dir) if args.output_dir is not None else None
    )

    if args.watch:
        watch_directory(
            input_dir,
            output_dir,
            interval=args.interval,
            default_fps=args.default_fps,
            force=args.force,
        )
        return 0

    converted = scan_directory(
        input_dir,
        output_dir,
        default_fps=args.default_fps,
        force=args.force,
    )
    LOG.info("converted %d file(s)", converted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
