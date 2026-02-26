#!/usr/bin/env python3
import hashlib
import json
import urllib.error
import urllib.request
from urllib.parse import parse_qsl, urlparse, urlunparse, urlencode
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

STATE_FILE_NAME = ".archive_sync_state.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")


def fetch_json_url(url: str, timeout_seconds: int = 6) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "RagnarArchiveViewer/1.0"})
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def validate_manifest(manifest: dict) -> tuple[bool, str]:
    if not isinstance(manifest, dict):
        return False, "Manifest is not a JSON object"

    files = manifest.get("files")
    if not isinstance(files, list):
        return False, "Manifest must include a 'files' array"

    for row in files:
        if not isinstance(row, dict):
            return False, "Manifest file entry is invalid"
        if not row.get("path"):
            return False, "Each manifest file entry needs 'path'"
        if not row.get("url"):
            return False, "Each manifest file entry needs 'url'"

    deleted = manifest.get("deleted", [])
    if deleted is not None and not isinstance(deleted, list):
        return False, "Manifest 'deleted' must be an array"

    return True, "ok"


def compute_pending_changes(archive_root: Path, manifest: dict) -> dict:
    to_download: List[dict] = []

    for row in manifest.get("files", []):
        rel = row["path"]
        local = (archive_root / rel).resolve()
        local_ok = False

        if local.exists() and local.is_file():
            expected_sha = row.get("sha256")
            expected_size = row.get("size")

            if expected_sha:
                try:
                    local_ok = sha256_file(local).lower() == str(expected_sha).lower()
                except Exception:
                    local_ok = False
            elif expected_size is not None:
                try:
                    local_ok = local.stat().st_size == int(expected_size)
                except Exception:
                    local_ok = False
            else:
                local_ok = True

        if not local_ok:
            to_download.append(row)

    to_delete: List[str] = []
    for rel in manifest.get("deleted", []) or []:
        local = (archive_root / rel).resolve()
        if local.exists() and local.is_file():
            to_delete.append(rel)

    return {
        "to_download": to_download,
        "to_delete": to_delete,
        "download_count": len(to_download),
        "delete_count": len(to_delete),
    }


def check_updates(archive_root: Path, manifest_url: str, timeout_seconds: int = 6) -> dict:
    state_path = archive_root / STATE_FILE_NAME
    state = load_json(state_path, default={})

    try:
        manifest = fetch_json_url(manifest_url, timeout_seconds=timeout_seconds)
    except urllib.error.URLError as e:
        return {
            "ok": False,
            "offline": True,
            "error": str(e),
            "state": state,
        }
    except Exception as e:
        return {
            "ok": False,
            "offline": False,
            "error": str(e),
            "state": state,
        }

    valid, msg = validate_manifest(manifest)
    if not valid:
        return {
            "ok": False,
            "offline": False,
            "error": msg,
            "state": state,
        }

    pending = compute_pending_changes(archive_root, manifest)

    state["last_check_utc"] = utc_now_iso()
    state["last_manifest_version"] = manifest.get("archive_version")
    save_json(state_path, state)

    return {
        "ok": True,
        "offline": False,
        "manifest": manifest,
        "pending": pending,
        "state": state,
    }


def _download_file(url: str, dst: Path, timeout_seconds: int = 20) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "RagnarArchiveViewer/1.0"})
    dst.parent.mkdir(parents=True, exist_ok=True)

    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp, dst.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)


def add_cache_buster(url: str, token: str) -> str:
    if not token:
        return url
    parsed = urlparse(url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    pairs = [(k, v) for (k, v) in pairs if k != "v"]
    pairs.append(("v", token))
    new_query = urlencode(pairs)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def sync_updates(
    archive_root: Path,
    manifest: dict,
    pending: dict,
    remove_deleted: bool = False,
    timeout_seconds: int = 20,
    progress_callback=None,
    allow_mismatch_paths=None,
    should_cancel=None,
) -> dict:
    downloaded = 0
    removed = 0
    errors: List[str] = []
    warnings: List[str] = []
    cache_token = str(manifest.get("archive_version", "")).strip()
    allowed_mismatch = {str(x).replace("\\", "/").lower() for x in (allow_mismatch_paths or [])}
    cancelled = False

    rows_to_download = pending.get("to_download", [])
    total = len(rows_to_download)

    for idx, row in enumerate(rows_to_download, start=1):
        if should_cancel and should_cancel():
            cancelled = True
            break
        rel = row["path"]
        url = str(row.get("url", "")).strip()
        expected_sha = row.get("sha256")

        dst = (archive_root / rel).resolve()

        try:
            if progress_callback:
                progress_callback(
                    {
                        "phase": "downloading",
                        "index": idx,
                        "total": total,
                        "path": rel,
                    }
                )
            if not url:
                raise ValueError(f"No download URL available for {rel}")

            _download_file(add_cache_buster(url, cache_token), dst, timeout_seconds=timeout_seconds)
            if expected_sha:
                got = sha256_file(dst)
                if got.lower() != str(expected_sha).lower():
                    rel_norm = str(rel).replace("\\", "/").lower()
                    name_norm = Path(rel).name.lower()
                    if rel_norm in allowed_mismatch or name_norm in allowed_mismatch:
                        warnings.append(
                            f"Checksum mismatch tolerated for {rel} "
                            f"(expected {expected_sha}, got {got})"
                        )
                    else:
                        errors.append(
                            f"Checksum mismatch after download: {rel} "
                            f"(expected {expected_sha}, got {got})"
                        )
                        try:
                            dst.unlink(missing_ok=True)
                        except Exception:
                            pass
                        continue
            downloaded += 1
            if progress_callback:
                progress_callback(
                    {
                        "phase": "downloaded",
                        "index": idx,
                        "total": total,
                        "path": rel,
                    }
                )
        except Exception as e:
            errors.append(f"Download failed for {rel}: {e}")

    if remove_deleted:
        for rel in pending.get("to_delete", []):
            p = (archive_root / rel).resolve()
            try:
                p.unlink(missing_ok=True)
                removed += 1
            except Exception as e:
                errors.append(f"Could not delete {rel}: {e}")

    state_path = archive_root / STATE_FILE_NAME
    state = load_json(state_path, default={})
    if not errors:
        state["last_success_sync_utc"] = utc_now_iso()
        state["last_manifest_version"] = manifest.get("archive_version")
    state["last_sync_error_count"] = len(errors)
    save_json(state_path, state)

    return {
        "ok": (len(errors) == 0 and not cancelled),
        "cancelled": cancelled,
        "downloaded": downloaded,
        "removed": removed,
        "errors": errors,
        "warnings": warnings,
        "state": state,
    }
