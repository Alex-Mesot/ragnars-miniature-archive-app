#!/usr/bin/env python3
"""
Build manifest.json for archive sync distribution.

Run:
  python3 00_Apps/build_archive_manifest.py . --base-url "<public-base-url>" --output manifest.json
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

DEFAULT_INCLUDE_EXTS = {".mp4", ".jpg", ".jpeg", ".png", ".db", ".json"}
DEFAULT_SKIP_DIRS = {
    "00_Apps",
    ".venv",
    "__pycache__",
    ".git",
    "build",
    "dist",
    ".pyinstaller",
    ".state",
    "01_Build",
    ".github",
}
DEFAULT_SKIP_FILES = {"manifest.json", "manifest.new.json", "manifest.prev.json", ".archive_sync_state.json"}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def should_skip(path: Path, skip_dirs: set[str]) -> bool:
    return any(part in skip_dirs for part in path.parts)


def build_manifest(
    archive_root: Path,
    base_url: str,
    include_exts: set[str],
    skip_dirs: set[str],
    app_latest_version: str = "",
    app_download_url: str = "",
) -> dict:
    files = []

    for p in sorted(archive_root.rglob("*")):
        if not p.is_file():
            continue
        if should_skip(p.relative_to(archive_root), skip_dirs):
            continue
        if p.name in DEFAULT_SKIP_FILES:
            continue
        if p.suffix.lower() not in include_exts:
            continue

        rel = p.relative_to(archive_root).as_posix()
        url = base_url.rstrip("/") + "/" + quote(rel)
        files.append(
            {
                "path": rel,
                "size": p.stat().st_size,
                "sha256": sha256_file(p),
                "url": url,
            }
        )

    manifest = {
        "archive_version": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "files": files,
        "deleted": [],
    }
    if app_latest_version.strip():
        manifest["app"] = {
            "latest_version": app_latest_version.strip(),
            "download_url": app_download_url.strip(),
        }
    return manifest


def main():
    ap = argparse.ArgumentParser(description="Build manifest.json for Ragnar archive content sync")
    ap.add_argument("archive_root", nargs="?", default=".", help="Archive root")
    ap.add_argument("--base-url", required=True, help="Public base URL containing archive files")
    ap.add_argument("--output", default="manifest.json", help="Manifest output path")
    ap.add_argument("--include-ext", action="append", default=[], help="Add file extension to include")
    ap.add_argument("--skip-dir", action="append", default=[], help="Add directory name to skip")
    ap.add_argument("--app-latest-version", default="", help="Latest app version (e.g. 1.2.0)")
    ap.add_argument("--app-download-url", default="", help="Direct release page/installer URL for latest app")
    args = ap.parse_args()

    archive_root = Path(args.archive_root).expanduser().resolve()
    out = Path(args.output).expanduser().resolve()

    include_exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in args.include_ext} | DEFAULT_INCLUDE_EXTS
    skip_dirs = set(args.skip_dir) | DEFAULT_SKIP_DIRS

    manifest = build_manifest(
        archive_root,
        args.base_url,
        include_exts,
        skip_dirs,
        app_latest_version=args.app_latest_version,
        app_download_url=args.app_download_url,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"Wrote manifest: {out}")
    print(f"Files listed: {len(manifest['files'])}")


if __name__ == "__main__":
    main()
