#!/usr/bin/env python3
"""
Normalize body-type tags written to media metadata.

Run:
  python3 00_Apps/Exif_Type_Fixer.py
"""
import subprocess
from pathlib import Path
import json

REPLACEMENTS = {
    "male": "Masculine",
    "female": "Feminine",
}

def read_tags(mp4_path: Path):
    """
    Read Subject and Keywords via exiftool -j
    Returns (subjects:list[str], keywords:list[str])
    """
    cmd = [
        "exiftool",
        "-j",
        "-Subject",
        "-Keywords",
        str(mp4_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[WARN] Could not read tags from {mp4_path}: {res.stderr.strip()}")
        return [], []

    data = json.loads(res.stdout)[0]

    # Subjects are often already a list
    subjects = data.get("Subject", [])
    if isinstance(subjects, str):
        # if someone stored "a,b,c" in Subject, split it too
        subjects = [s.strip() for s in subjects.split(",") if s.strip()]

    # Keywords can be either a list OR a single comma string
    keywords = data.get("Keywords", [])
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    return subjects, keywords


def replace_tags(tags):
    """
    Replace exact 'male'/'female' (case-insensitive) with 'masculine'/'feminine'.
    """
    new_tags = []
    changed = False
    for t in tags:
        low = t.lower()
        if low in REPLACEMENTS:
            new_tags.append(REPLACEMENTS[low])
            changed = True
        else:
            new_tags.append(t)
    return new_tags, changed


def write_tags(mp4_path: Path, subjects, keywords):
    """
    Write updated Subject and Keywords back to the file using exiftool.
    """
    subj_str = ",".join(subjects)
    keyw_str = ",".join(keywords)

    cmd = [
        "exiftool",
        "-overwrite_original",
        "-sep", ",",
        f"-Subject={subj_str}",
        f"-Keywords={keyw_str}",
        str(mp4_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[WARN] Could not write tags to {mp4_path}: {res.stderr.strip()}")
    else:
        print(f"[OK] Updated {mp4_path}")


def main():
    root = Path(".").resolve()
    for mp4 in root.rglob("*.mp4"):
        subjects, keywords = read_tags(mp4)

        new_subjects, sub_changed = replace_tags(subjects)
        new_keywords, key_changed = replace_tags(keywords)

        if sub_changed or key_changed:
            write_tags(mp4, new_subjects, new_keywords)
        # else: nothing to change


if __name__ == "__main__":
    main()
