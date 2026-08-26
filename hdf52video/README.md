# hdf52video

Convert areaDetector / NeXus HDF5 image stacks to MP4.

## Dependencies

```bash
pip install -r requirements-h5video.txt
```

Requires FFmpeg available to `imageio` (via `imageio[ffmpeg]`).

---

## `hdf5_to_video.py`

Scan a directory for HDF5 files and write MP4s. Frame rate is inferred from EPICS timestamps when present; otherwise uses `--default-fps`.

```bash
# One-shot conversion
python hdf5_to_video.py -i /path/to/hdf5_dir
python hdf5_to_video.py -i /path/to/hdf5_dir -o /path/to/mp4_dir --default-fps 10

# Watch for new files
python hdf5_to_video.py -i /path/to/hdf5_dir --watch --interval 5

# Force reconvert even if MP4 exists
python hdf5_to_video.py -i /path/to/hdf5_dir --force -v
```
