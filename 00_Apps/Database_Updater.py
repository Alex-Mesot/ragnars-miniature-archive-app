#!/usr/bin/env python3
import sys
import json
import sqlite3
import subprocess
from pathlib import Path

DB_NAME = "miniatures.db"
CATEGORIES_FILE = "categories.json"


def load_categories(script_dir: Path) -> dict:
    cfg = script_dir / CATEGORIES_FILE
    if not cfg.exists():
        raise FileNotFoundError(f"categories.json not found at {cfg}")
    with open(cfg, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not data:
        raise ValueError("categories.json is empty or malformed.")
    return data


def run_exiftool(path: Path):
    cmd = ["exiftool", "-j", "-Subject", "-Keywords", "-Title", str(path)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[WARN] exiftool failed on {path}: {res.stderr.strip()}")
        return {}
    try:
        return json.loads(res.stdout)[0]
    except Exception as e:
        print(f"[WARN] Could not parse exiftool JSON for {path}: {e}")
        return {}


def as_list(val):
    if not val:
        return []
    if isinstance(val, list):
        return [str(v).strip() for v in val if str(v).strip()]
    if isinstance(val, str):
        return [v.strip() for v in val.split(",") if v.strip()]
    return []


def normalize_tags(tags: list[str]) -> list[str]:
    seen, out = set(), []
    for t in tags:
        t = t.strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def ensure_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    # base table if it doesn't exist at all
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS miniatures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            path_media TEXT UNIQUE,
            tags TEXT
        );
        """
    )
    conn.commit()
    return conn


def get_existing_columns(conn: sqlite3.Connection) -> list[str]:
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(miniatures)")
    return [row[1] for row in cur.fetchall()]  # row[1] = column name


def rebuild_table_if_needed(conn: sqlite3.Connection, categories: dict):
    """
    If the DB has columns that are NOT in JSON, rebuild the table so that
    it has ONLY: id, name, path_media, tags, and one column per JSON key.
    """
    existing_cols = get_existing_columns(conn)

    desired_cols = ["id", "name", "path_media", "tags"]
    # json keys -> columns (spaces to underscores)
    json_cols = [key.replace(" ", "_") for key in categories.keys()]
    desired_cols.extend(json_cols)

    # if there are any extra columns, we rebuild
    extras = [c for c in existing_cols if c not in desired_cols]
    if not extras and all(c in existing_cols for c in desired_cols):
        # perfect match, nothing to do
        return

    print("[INFO] Rebuilding table to match categories.json ...")

    cur = conn.cursor()
    # create new table
    cols_sql = []
    for col in desired_cols:
        if col == "id":
            cols_sql.append("id INTEGER PRIMARY KEY AUTOINCREMENT")
        elif col == "path_media":
            cols_sql.append("path_media TEXT UNIQUE")
        else:
            cols_sql.append(f'"{col}" TEXT')
    create_sql = f'CREATE TABLE miniatures_new ({", ".join(cols_sql)});'
    cur.execute(create_sql)

    # copy over overlapping columns
    overlap = [c for c in existing_cols if c in desired_cols]
    if overlap:
        col_list = ",".join(overlap)
        cur.execute(f'INSERT INTO miniatures_new ({col_list}) SELECT {col_list} FROM miniatures')

    # drop old, rename new
    cur.execute("DROP TABLE miniatures")
    cur.execute("ALTER TABLE miniatures_new RENAME TO miniatures")
    conn.commit()
    print("[INFO] Table rebuilt.")


def upsert_miniature(conn: sqlite3.Connection,
                     name: str,
                     rel_path: str,
                     all_tags: list[str],
                     categories: dict):
    # build column values per category
    per_column = {}
    for key, allowed_values in categories.items():
        col_name = key.replace(" ", "_")
        matches = [t for t in all_tags if t in allowed_values]
        per_column[col_name] = ",".join(matches)

    per_column["tags"] = ",".join(all_tags)

    cur = conn.cursor()
    cur.execute("SELECT id FROM miniatures WHERE path_media = ?", (rel_path,))
    row = cur.fetchone()

    if row:
        # update
        sets = ", ".join([f'{col} = ?' for col in per_column.keys()])
        values = list(per_column.values()) + [rel_path]
        cur.execute(f"UPDATE miniatures SET {sets} WHERE path_media = ?", values)
    else:
        # insert
        cols = ["name", "path_media"] + list(per_column.keys())
        qmarks = ",".join(["?"] * len(cols))
        values = [name, rel_path] + list(per_column.values())
        cur.execute(
            f'INSERT INTO miniatures ({",".join(cols)}) VALUES ({qmarks})',
            values
        )
    conn.commit()


def delete_rows_for_missing_files(conn: sqlite3.Connection, archive_root: Path):
    cur = conn.cursor()
    cur.execute("SELECT id, path_media FROM miniatures")
    rows = cur.fetchall()
    removed = 0
    for _id, rel in rows:
        if not (archive_root / rel).exists():
            cur.execute("DELETE FROM miniatures WHERE id = ?", (_id,))
            removed += 1
    if removed:
        conn.commit()
        print(f"[INFO] Removed {removed} entries for missing files.")


def main():
    # where the videos live
    if len(sys.argv) > 1:
        archive_root = Path(sys.argv[1]).expanduser().resolve()
    else:
        archive_root = Path(".").resolve()

    # where the script + json live
    script_dir = Path(__file__).resolve().parent
    categories = load_categories(script_dir)

    db_path = archive_root / DB_NAME
    conn = ensure_db(db_path)

    # make sure schema matches json (remove old columns, add missing ones)
    rebuild_table_if_needed(conn, categories)

    # walk the archive
    mp4_files = list(archive_root.rglob("*.mp4"))
    print(f"[INFO] Found {len(mp4_files)} mp4 files.")
    for mp4 in mp4_files:
        rel_path = mp4.relative_to(archive_root).as_posix()
        exif = run_exiftool(mp4)
        subjects = as_list(exif.get("Subject"))
        keywords = as_list(exif.get("Keywords"))
        all_tags = normalize_tags(subjects + [t for t in keywords if t not in subjects])
        title = exif.get("Title") or mp4.stem
        upsert_miniature(conn, title, rel_path, all_tags, categories)

    # remove rows for files that no longer exist
    delete_rows_for_missing_files(conn, archive_root)

    print("[DONE] Database synced with JSON and files.")


if __name__ == "__main__":
    main()
