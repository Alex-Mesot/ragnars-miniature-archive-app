#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

SKIP_DELETED = {"manifest.json", "manifest.new.json", "manifest.prev.json", ".archive_sync_state.json"}


def load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Manifest is not a JSON object: {path}")
    if "files" not in data or not isinstance(data["files"], list):
        raise ValueError(f"Manifest missing 'files' list: {path}")
    return data


def file_paths(manifest: dict) -> set[str]:
    out = set()
    for row in manifest.get("files", []):
        if isinstance(row, dict) and row.get("path"):
            out.add(str(row["path"]))
    return out


def deleted_paths(old_manifest: dict, new_manifest: dict, keep_existing_deleted: bool) -> list[str]:
    old_paths = file_paths(old_manifest)
    new_paths = file_paths(new_manifest)

    removed = sorted(old_paths - new_paths, key=str.lower)
    removed = [p for p in removed if Path(p).name not in SKIP_DELETED]

    if keep_existing_deleted:
        existing = {
            str(p) for p in new_manifest.get("deleted", [])
            if isinstance(p, str) and p.strip()
        }
        kept_existing = {p for p in existing if Path(p).name not in SKIP_DELETED}
        removed = sorted(kept_existing | set(removed), key=str.lower)

    return removed


def main():
    ap = argparse.ArgumentParser(
        description="Auto-fill manifest.deleted by comparing previous and new manifests"
    )
    ap.add_argument("--old", required=True, help="Previous manifest path")
    ap.add_argument("--new", required=True, help="New manifest path")
    ap.add_argument(
        "--out",
        default="",
        help="Output path (default: overwrite --new)",
    )
    ap.add_argument(
        "--replace",
        action="store_true",
        help="Replace deleted array completely (default keeps and merges existing deleted entries)",
    )
    args = ap.parse_args()

    old_path = Path(args.old).expanduser().resolve()
    new_path = Path(args.new).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve() if args.out else new_path

    old_manifest = load_manifest(old_path)
    new_manifest = load_manifest(new_path)

    new_manifest["deleted"] = deleted_paths(
        old_manifest,
        new_manifest,
        keep_existing_deleted=not args.replace,
    )

    out_path.write_text(json.dumps(new_manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Wrote updated manifest: {out_path}")
    print(f"Deleted entries: {len(new_manifest['deleted'])}")


if __name__ == "__main__":
    main()
