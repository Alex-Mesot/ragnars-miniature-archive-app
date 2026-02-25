#!/usr/bin/env python3
import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageOps  # pillow


# ---------- Config ----------
VIDEO_EXTS = {".mp4"}   # treat these as "video"
FULL_IMG_EXTS = {".jpg", ".jpeg"}  # acceptable full-res sources
THUMB_EXTS = {".jpg", ".jpeg"}          # thumbs will be written as jpg by default

DEFAULT_THUMB_SIZE = 512
DEFAULT_THUMB_QUALITY = 85


# ---------- Helpers ----------
def run_exiftool_json(path: Path) -> Optional[dict]:
    """
    Returns exiftool JSON dict for the file, or None on failure.
    Requires exiftool in PATH.
    """
    try:
        out = subprocess.check_output(
            ["exiftool", "-j", "-n", str(path)],
            stderr=subprocess.STDOUT,
            text=True,
        )
        data = json.loads(out)
        if isinstance(data, list) and data:
            return data[0]
        return None
    except Exception:
        return None


def has_any_tags(meta: dict) -> bool:
    """
    Decide whether MP4 has meaningful tagging metadata.
    We accept any non-empty Subject or Keywords (and a few common alternatives).
    """
    if not meta:
        return False

    # exiftool sometimes returns:
    # - "Subject": ["a","b"] or "a, b"
    # - "Keywords": ["a","b"] or "a, b"
    # - or XMP:Subject / XMP:Keywords (but exiftool JSON usually flattens)
    candidates = [
        "Subject",
        "Keywords",
        "XMP:Subject",
        "XMP:Keywords",
        "IPTC:Keywords",
    ]

    for k in candidates:
        v = meta.get(k)
        if not v:
            continue
        if isinstance(v, list) and any(str(x).strip() for x in v):
            return True
        if isinstance(v, str) and v.strip():
            return True

    return False

def extract_tags(meta: dict) -> List[str]:
    """
    Extract tags from exiftool JSON into a flat list of strings.
    Looks at Subject and Keywords (and common variants).
    """
    if not meta:
        return []

    candidates = [
        "Subject",
        "Keywords",
        "XMP:Subject",
        "XMP:Keywords",
        "IPTC:Keywords",
    ]

    tags: List[str] = []
    for k in candidates:
        v = meta.get(k)
        if not v:
            continue
        if isinstance(v, list):
            tags.extend([str(x).strip() for x in v if str(x).strip()])
        elif isinstance(v, str):
            # Might be "a, b, c"
            parts = [p.strip() for p in v.replace(";", ",").split(",") if p.strip()]
            tags.extend(parts)

    # de-dup preserve order (case-insensitive)
    out: List[str] = []
    seen = set()
    for t in tags:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def write_tags_to_mp4(mp4_path: Path, tags: List[str]) -> Tuple[bool, str]:
    """
    Write tags to MP4 Subject and Keywords using exiftool.
    """
    if not tags:
        return False, "No tags provided"

    tag_string = ",".join(tags)

    try:
        # Write both Subject and Keywords, separated properly
        subprocess.check_output(
            [
                "exiftool",
                "-overwrite_original",
                "-P",
                f"-Subject={tag_string}",
                f"-Keywords={tag_string}",
                "-sep",
                ",",
                str(mp4_path),
            ],
            stderr=subprocess.STDOUT,
            text=True,
        )
        return True, f"Copied tags to MP4: {mp4_path.name}"
    except subprocess.CalledProcessError as e:
        return False, f"exiftool write failed for {mp4_path}: {e.output}"
    except Exception as e:
        return False, f"exiftool write failed for {mp4_path}: {e}"



def is_hidden_or_system(part) -> bool:
    name = part.name if hasattr(part, "name") else str(part)
    return name.startswith(".") or name in {"__MACOSX"}



def make_thumb(full_img_path: Path, thumb_path: Path, size: int, quality: int) -> Tuple[bool, str]:
    """
    Create a square 512x512 thumbnail (letterboxed, no crop) named *_thumb.jpg by default.
    Returns (success, message).
    """
    try:
        thumb_path.parent.mkdir(parents=True, exist_ok=True)

        img = Image.open(full_img_path)
        img = ImageOps.exif_transpose(img)  # respect orientation
        img = img.convert("RGB")

        # Fit inside square while keeping aspect ratio (no crop)
        img.thumbnail((size, size), Image.Resampling.LANCZOS)

        # Letterbox to square
        canvas = Image.new("RGB", (size, size), (0, 0, 0))
        x = (size - img.size[0]) // 2
        y = (size - img.size[1]) // 2
        canvas.paste(img, (x, y))

        canvas.save(thumb_path, format="JPEG", quality=quality, optimize=True, progressive=True)
        return True, f"Generated thumbnail: {thumb_path}"
    except Exception as e:
        return False, f"Thumbnail generation failed for {full_img_path}: {e}"


def stem_key(p: Path) -> str:
    """
    'Goblin_King_thumb.jpg' -> 'Goblin_King'
    'Goblin_King.jpg' -> 'Goblin_King'
    'Goblin_King.mp4' -> 'Goblin_King'
    """
    s = p.stem
    if s.endswith("_thumb"):
        s = s[:-6]
    return s


@dataclass
class Entry:
    stem: str
    folder: Path
    videos: List[Path]
    full_imgs: List[Path]
    thumbs: List[Path]


def collect_entries(root: Path, skip_dirs: set) -> Dict[Tuple[Path, str], Entry]:
    """
    Collect files grouped by (folder, stem).
    """
    entries: Dict[Tuple[Path, str], Entry] = {}

    for p in root.rglob("*"):
        if p.is_dir():
            continue

        # skip hidden/system
        if any(is_hidden_or_system(x) for x in p.parts):
            continue

        # skip specific dirs by name
        if any(part in skip_dirs for part in p.parts):
            continue

        ext = p.suffix.lower()
        if ext not in (VIDEO_EXTS | FULL_IMG_EXTS | THUMB_EXTS):
            continue

        kstem = stem_key(p)
        key = (p.parent, kstem)

        if key not in entries:
            entries[key] = Entry(stem=kstem, folder=p.parent, videos=[], full_imgs=[], thumbs=[])

        # classify
        if ext in VIDEO_EXTS:
            entries[key].videos.append(p)
        elif ext in FULL_IMG_EXTS:
            if p.stem.endswith("_thumb"):
                entries[key].thumbs.append(p)
            else:
                entries[key].full_imgs.append(p)

    return entries


# ---------- Main service ----------
def main():
    ap = argparse.ArgumentParser(description="Miniature Archive Service Checker")
    ap.add_argument("archive_root", nargs="?", default="..", help="Archive root folder")
    ap.add_argument("--thumb-size", type=int, default=DEFAULT_THUMB_SIZE, help="Thumbnail size (square)")
    ap.add_argument("--thumb-quality", type=int, default=DEFAULT_THUMB_QUALITY, help="Thumbnail JPEG quality 1-95")
    ap.add_argument("--report", default="archive_service_report.txt", help="Report filename (written in current dir)")
    ap.add_argument("--skip-dir", action="append", default=["00_Apps"], help="Directory name to skip (repeatable)")
    ap.add_argument("--remove-orphan-thumbs", action="store_true", help="Delete thumbs that have no full-res image")
    args = ap.parse_args()

    root = Path(args.archive_root).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()

    issues: List[str] = []
    actions: List[str] = []

    if not root.exists():
        raise SystemExit(f"Archive root not found: {root}")

    entries = collect_entries(root, skip_dirs=set(args.skip_dir))

    # Track duplicates and weirdness
    for (folder, st), e in entries.items():
        # 1) MP4 existence
        if len(e.videos) == 0:
            issues.append(f"[MISSING MP4] {folder}/{st}  (no video found)")
        elif len(e.videos) > 1:
            issues.append(f"[MULTIPLE MP4] {folder}/{st}  (videos: {', '.join(v.name for v in e.videos)})")

        # 2) full-res image existence
        if len(e.full_imgs) == 0:
            issues.append(f"[MISSING FULL IMG] {folder}/{st}  (no full-res image found: {sorted(FULL_IMG_EXTS)})")
        elif len(e.full_imgs) > 1:
            issues.append(f"[MULTIPLE FULL IMG] {folder}/{st}  (images: {', '.join(i.name for i in e.full_imgs)})")

        # 3) thumbnail existence; generate if missing
        if len(e.thumbs) == 0:
            if len(e.full_imgs) >= 1:
                full_img = sorted(e.full_imgs, key=lambda p: p.suffix.lower() != ".jpg")[0]
                thumb_path = full_img.with_name(full_img.stem + "_thumb.jpg")
                ok, msg = make_thumb(full_img, thumb_path, args.thumb_size, args.thumb_quality)
                if ok:
                    actions.append(msg)
                else:
                    issues.append(f"[THUMB FAIL] {folder}/{st}  {msg}")
            else:
                issues.append(f"[MISSING THUMB] {folder}/{st}  (no thumb and no full-res to generate from)")
        elif len(e.thumbs) > 1:
            issues.append(f"[MULTIPLE THUMBS] {folder}/{st}  (thumbs: {', '.join(t.name for t in e.thumbs)})")

        # 4) MP4 metadata check
        if len(e.videos) >= 1:
            # If multiple videos, check them all
            for v in e.videos:
                copied = False
                meta = run_exiftool_json(v)
                if meta is None:
                    issues.append(f"[EXIFTOOL FAIL] {v}  (could not read metadata)")
                    continue
                if not has_any_tags(meta):
                    # Try to copy tags from the accompanying full-res image (if any)
                    if len(e.full_imgs) >= 1:
                        # Choose a "best" full image (prefer .jpg/.jpeg if present)
                        full_img = sorted(e.full_imgs, key=lambda p: (p.suffix.lower() not in [".jpg", ".jpeg"], p.name.lower()))[0]
                        img_meta = run_exiftool_json(full_img)
                        img_tags = extract_tags(img_meta)

                        if img_tags:
                            ok, msg = write_tags_to_mp4(v, img_tags)
                            if ok:
                                actions.append(f"[TAGS COPIED] {folder}/{st}  {msg}  (from {full_img.name})")
                                copied = True
                            else:
                                issues.append(f"[TAG COPY FAIL] {v}  {msg}")
                    if not copied:
                        issues.append(f"[MISSING TAGS] {v}  (no Subject/Keywords found and no usable tags on full-res image)")


        # 5) Optional: orphan thumbs removal
        if args.remove_orphan_thumbs and len(e.full_imgs) == 0 and len(e.thumbs) > 0:
            for t in e.thumbs:
                try:
                    t.unlink()
                    actions.append(f"Deleted orphan thumb: {t}")
                except Exception as ex:
                    issues.append(f"[ORPHAN THUMB DELETE FAIL] {t}  {ex}")

    # Also catch files that don’t fit pattern: orphan full image without mp4 etc are already covered by entry checks.

    # Write report
    lines = []
    lines.append(f"Archive root: {root}")
    lines.append("")
    lines.append("=== ACTIONS ===")
    lines.extend(actions if actions else ["(none)"])
    lines.append("")
    lines.append("=== ISSUES ===")
    lines.extend(issues if issues else ["(none)"])
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote report: {report_path}")
    print(f"Actions: {len(actions)} | Issues: {len(issues)}")


if __name__ == "__main__":
    main()
