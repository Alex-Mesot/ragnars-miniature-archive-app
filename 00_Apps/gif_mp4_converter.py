#!/usr/bin/env python3
"""
Recreate MP4 files from matching GIF files and copy tags from JPG.

Run:
  python3 00_Apps/gif_mp4_converter.py

Run from archive root.
"""
import subprocess
from pathlib import Path

root = Path(".")

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
