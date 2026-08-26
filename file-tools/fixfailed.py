import os
import shutil
import subprocess
from PIL import Image, ImageSequence
import json

# -------------------------------
# Settings
# -------------------------------
INPUT_LIST_FILE = "/Volumes/Extreme 4T/other/failist.txt"
OUTPUT_DIR = "/Volumes/Extreme 4T/other/outputs2"
GIF_DIR = "/Volumes/Extreme 4T/other/gifs"
FFMPEG_PATH = "/opt/homebrew/bin/ffmpeg"
FFPROBE_PATH = "/opt/homebrew/bin/ffprobe"

# Create output directories
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(GIF_DIR, exist_ok=True)

def has_transparency(img):
    """Check if image has transparency."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        alpha = img.getchannel("A")
        return any(pixel < 255 for pixel in alpha.getdata())
    return False

def is_animated_gif(path):
    """Return True if GIF has more than 1 frame."""
    try:
        with Image.open(path) as img:
            frames = sum(1 for _ in ImageSequence.Iterator(img))
            return frames > 1
    except:
        return False

def convert_image(input_path, output_path, force_jpg=False):
    """Convert image to JPEG or PNG for Apple Photos."""
    with Image.open(input_path) as img:
        if not force_jpg and has_transparency(img):
            img.save(output_path, "PNG")
        else:
            rgb_img = img.convert("RGB")
            rgb_img.save(output_path, "JPEG", quality=95)

def convert_video_or_audio(input_path, output_path):
    """Convert video/audio to Apple Photos–friendly format using ffmpeg."""
    cmd = [
        FFMPEG_PATH,
        "-i", input_path,
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "slow",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ]
    subprocess.run(cmd, check=True)

def remux_video(input_path, output_path):
    """Losslessly remux video to MP4 without re-encoding."""
    cmd = [
        FFMPEG_PATH,
        "-i", input_path,
        "-c", "copy",
        "-movflags", "+faststart",
        output_path
    ]
    result = subprocess.run(cmd)
    return result.returncode == 0

def is_h264_aac(input_path):
    """Check if video has H.264 video + AAC audio codecs."""
    cmd = [
        FFPROBE_PATH,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "json",
        input_path
    ]
    try:
        video_info = json.loads(subprocess.check_output(cmd).decode("utf-8"))
        video_codec = video_info["streams"][0]["codec_name"].lower()
    except:
        return False

    cmd = [
        FFPROBE_PATH,
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name",
        "-of", "json",
        input_path
    ]
    try:
        audio_info = json.loads(subprocess.check_output(cmd).decode("utf-8"))
        audio_codec = audio_info["streams"][0]["codec_name"].lower()
    except:
        audio_codec = None  # allow videos with no audio

    return (video_codec == "h264") and (audio_codec in ["aac", None])

def main():
    with open(INPUT_LIST_FILE, "r") as f:
        files = [line.strip() for line in f if line.strip()]

    for file_path in files:
        if not os.path.exists(file_path):
            print(f"❌ Skipping (missing): {file_path}")
            continue

        ext = os.path.splitext(file_path)[1].lower()
        base_name = os.path.splitext(os.path.basename(file_path))[0]

        try:
            # --- GIF Handling ---
            if ext == ".gif":
                if is_animated_gif(file_path):
                    dest_path = os.path.join(GIF_DIR, os.path.basename(file_path))
                    shutil.copy2(file_path, dest_path)
                    print(f"📂 Moved animated GIF: {file_path} → {dest_path}")
                else:
                    out_file = os.path.join(
                        OUTPUT_DIR,
                        base_name + (".png" if has_transparency(Image.open(file_path)) else ".jpg")
                    )
                    convert_image(file_path, out_file, force_jpg=False)
                    print(f"🖼 Converted static GIF: {file_path} → {out_file}")

            # --- PNG Handling ---
            elif ext == ".png":
                out_file = os.path.join(
                    OUTPUT_DIR,
                    base_name + (".png" if has_transparency(Image.open(file_path)) else ".jpg")
                )
                convert_image(file_path, out_file, force_jpg=False)
                print(f"🖼 Converted PNG: {file_path} → {out_file}")

            # --- Other Images ---
            elif ext in [".jpg", ".jpeg", ".tif", ".tiff"]:
                out_file = os.path.join(OUTPUT_DIR, base_name + ".jpg")
                convert_image(file_path, out_file, force_jpg=True)
                print(f"✅ Converted image: {file_path} → {out_file}")

            # --- Video Handling ---
            elif ext in [".mp4", ".mov", ".mts", ".mkv", ".avi", ".wmv"]:
                out_file = os.path.join(OUTPUT_DIR, base_name + ".mp4")
                if is_h264_aac(file_path):
                    if remux_video(file_path, out_file):
                        print(f"⚡ Remuxed (lossless): {file_path} → {out_file}")
                    else:
                        print(f"🔄 Remux failed, re-encoding: {file_path}")
                        convert_video_or_audio(file_path, out_file)
                else:
                    convert_video_or_audio(file_path, out_file)
                    print(f"🎬 Re-encoded video: {file_path} → {out_file}")

            # --- Audio Handling ---
            elif ext in [".wav", ".flac", ".aiff", ".ogg", ".m4a", ".mp3"]:
                out_file = os.path.join(OUTPUT_DIR, base_name + ".m4a")
                convert_video_or_audio(file_path, out_file)
                print(f"🎵 Converted audio: {file_path} → {out_file}")

            else:
                print(f"⚠️ Skipping unsupported format: {file_path}")

        except Exception as e:
            print(f"❗ Error converting {file_path}: {e}")

if __name__ == "__main__":
    main()