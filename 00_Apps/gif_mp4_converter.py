import subprocess
from pathlib import Path

root = Path(".")  # change this to your top folder

for jpg in root.rglob("*"):
    if not jpg.is_file():
        continue
    if jpg.suffix.lower() not in {".jpg", ".jpeg"}:
        continue
    stem = jpg.stem
    folder = jpg.parent
    gif = folder / f"{stem}.gif"
    mp4 = folder / f"{stem}.mp4"

    if not gif.exists():
        continue

    # 1) Recreate / overwrite existing MP4
    subprocess.run([
        "ffmpeg", "-y", "-i", str(gif),
        "-movflags", "faststart",
        "-pix_fmt", "yuv420p",
        str(mp4)
    ], check=True)

    # 2) Copy Subject from JPG → MP4 (and mirror it to common fields)
    subprocess.run([
        "exiftool",
        "-TagsFromFile", str(jpg),
        "-Subject",
        "-Keywords<Subject",
        "-Keys:Keywords<Subject",
        "-overwrite_original",
        str(mp4)
    ], check=True)
