# file-tools

Small filesystem utilities (search, rename, convert).

Most scripts use hardcoded paths near the top or in `__main__` — edit those before running.

---

## `findstl.py`

Recursively find `.stl` files under a root path.

```bash
# Edit search_path in __main__, then:
python findstl.py
```

Or from Python:

```python
from findstl import find_stl_files

for path in find_stl_files("/Volumes/Extreme SSD"):
    print(path)
```

---

## `toimg.py`

Rename extensionless paths listed in a text file to sequential `image_NNNN.jpeg` names in an output directory.

Edit `input_list_file` and `output_dir` at the top of `main()`, then:

```bash
python toimg.py
```

---

## `fixfailed.py`

Convert / remux a list of failed media files (images and videos) into a consistent output set. Needs Pillow and `ffmpeg` / `ffprobe` (paths set near the top of the file).

```bash
# Edit INPUT_LIST_FILE, OUTPUT_DIR, GIF_DIR, FFMPEG_PATH, FFPROBE_PATH, then:
python fixfailed.py
```

Suggested deps: `pip install Pillow`.

---

## `replace_string.py`

Replace a string in file contents, filenames, and folder names under a directory.

```bash
python replace_string.py OLD NEW /path/to/tree --dry-run
python replace_string.py OLD NEW /path/to/tree
python replace_string.py OLD NEW /path/to/tree --no-content   # rename only
python replace_string.py OLD NEW /path/to/tree --no-rename    # contents only
```
