# Ragnar's Miniature Archive

A local archive of painted Dungeons & Dragons miniatures with a PyQt6 viewer, tagging tools, and a SQLite database.

This repo currently contains:
- Media files organized by creature type (and humanoid subtype).
- A SQLite database (`miniatures.db`) containing searchable tags.
- PyQt6 tools for tagging, viewing, and syncing the DB.

## Quick Start

1) Install dependencies
- Python 3.10+
- PyQt6
- `exiftool` (used to read/write tags on media)
- `ffmpeg` (only needed for GIF -> MP4 conversion)

2) Run the viewer
```bash
python3 00_Apps/Viewer.py
```
Optionally pass the archive root path:
```bash
python3 00_Apps/Viewer.py /path/to/Ragnar's_Miniature_Archive
```

## Content Updates (No Reinstall)

The viewer now supports a manifest-based content sync model:
- App launches immediately with local/offline files.
- On startup it checks a remote `manifest.json`.
- If updates exist, `Download latest archive` becomes enabled.
- `Download app update` appears only if manifest reports a newer app version.
- If offline or unreachable, app stays usable and shows `Offline`.

### Configure update source
Create:
- `00_Apps/config/archive_update_config.json`

Starting template:
```json
{
  "manifest_url": "https://your-public-host.example.com/ragnar/manifest.json",
  "app_release_url": "https://your-public-host.example.com/ragnar/releases",
  "check_on_startup": true,
  "request_timeout_seconds": 6,
  "download_timeout_seconds": 20,
  "remove_deleted": false
}
```

Notes:
- `manifest_url` must be publicly readable (no user login).
- `app_release_url` is used by the `Check app update` button.
- If config is missing, viewer runs in offline-only mode.

### Build/publish a manifest
Use:
```bash
python3 00_Apps/build_archive_manifest.py . \
  --base-url "https://your-public-host.example.com/ragnar" \
  --app-latest-version "1.0.1" \
  --app-download-url "https://your-public-host.example.com/ragnar/releases" \
  --output manifest.json
```

Then upload:
- New/changed files
- `manifest.json`

The viewer downloads only missing/changed files using `sha256` (or file size fallback if no hash).
Each manifest file entry can use either:
- `url` (direct file URL), or
- `folder_url` (pCloud shared folder URL). In this mode, the app resolves the file by exact filename.

Manifest app update block example:
```json
"app": {
  "latest_version": "1.0.1",
  "download_url": "https://your-public-host.example.com/ragnar/releases"
}
```

Manifest pCloud folder-link file example:
```json
{
  "path": "Humanoid/Human/Athena.mp4",
  "sha256": "....",
  "size": 9876543,
  "folder_url": "https://e.pcloud.link/publink/show?code=YOUR_FOLDER_SHARE_CODE"
}
```

### Recommended publish layout
Keep paths stable. Example:
- `https://host/ragnar/manifest.json`
- `https://host/ragnar/Humanoid/Elf/Sylvan Archer.mp4`
- `https://host/ragnar/miniatures.db`

### Removal policy
- Put removed paths in manifest `deleted`.
- If `remove_deleted` is true, client deletes those local files.
- If false, removed files remain local (safe mode).

## App Updates (Code/Features)

Content sync avoids reinstall for media/db changes.  
For app code updates (new features/bug fixes), use versioned installers.

Recommended model:
- Host installers on a release page (GitHub Releases or your site).
- Add a lightweight in-app `Check for app update` action that opens the latest installer URL.
- Keep content updates separate via manifest sync (already implemented above).

Cross-platform fully automatic binary self-updating is possible but adds significant complexity and signing requirements per OS.

## How It Works

### Media layout
Media lives in category folders at the repo root. Example:
- `Humanoid/Elf/Deepwood Sentinel.mp4`
- `Beast/Giant Eagle.gif`
- `Undead/Old-Burg Captain.jpg`

When tagging new media, the Tagger uses:
- `creature_type` to choose the top-level folder.
- If `creature_type` is `Humanoid` and a `humanoid_type` is selected, it stores under `Humanoid/<humanoid_type>/`.

### Database
The SQLite DB is stored at `miniatures.db` in the archive root.

Schema (from `00_Apps/Tagger.py` and `00_Apps/Database_Updater.py`):
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `name` TEXT
- `path_media` TEXT (relative path, unique)
- `tags` TEXT (comma-separated)
- Category columns (comma-separated per column). Current or legacy column names:
- `creature_type`
- `humanoid_type`
- `colors`
- `equipment`
- `roles` (or `role` in older DBs)
- `body_type`
- `sizes` (or `size` in older DBs)

The viewer dynamically checks which columns exist and only shows those tag panels.

### Categories
Tag options are defined in `00_Apps/categories.json`.

If `categories.json` changes, run the DB updater to rebuild the schema and resync tags from media metadata:
```bash
python3 00_Apps/Database_Updater.py
```

### Tools

#### Viewer
`00_Apps/Viewer.py`
- Search by text (name + tags + category columns)
- Filter by tag panels (exact/contains matching within a column)
- Preview up to 15 MP4s as looping thumbnails

#### Tagger (MP4 Importer)
`00_Apps/Tagger.py`
- Imports MP4s from a source folder
- Lets you rename and tag them
- Writes tags to the file using `exiftool`
- Moves files into the archive folder structure
- Inserts rows in `miniatures.db`

Usage:
```bash
python3 00_Apps/Tagger.py /path/to/source_mp4s /path/to/Ragnar's_Miniature_Archive
```

#### Database Updater
`00_Apps/Database_Updater.py`
- Rebuilds the DB schema based on `categories.json`
- Reads tags from each MP4 using `exiftool`
- Inserts/updates DB rows
- Removes rows for missing files

Usage:
```bash
python3 00_Apps/Database_Updater.py /path/to/Ragnar's_Miniature_Archive
```

#### EXIF Type Fixer
`00_Apps/Exif_Type_Fixer.py`
- Normalizes `male`/`female` tags to `Masculine`/`Feminine` on MP4s

Usage:
```bash
python3 00_Apps/Exif_Type_Fixer.py
```

#### GIF -> MP4 Converter
`00_Apps/gif_mp4_converter.py`
- For each `.jpg` with a matching `.gif`, recreates `.mp4` with `ffmpeg`
- Copies tags from JPG to MP4 using `exiftool`

Usage:
```bash
python3 00_Apps/gif_mp4_converter.py
```

## Current Structure (Stable)

This project currently uses:
- Archive/media folders at repo root (for compatibility with existing tools).
- App and utility scripts under `00_Apps/`.
- Build/release scripts under `01_Build/scripts/`.
- Build outputs in `01_Build/dist/` and build cache in `01_Build/build/`.
- Local helper/state files in `01_Build/.state/` (generated by `01_Build/scripts/publish_release.sh`).

Recent cleanup rules:
- Manifest generation skips `01_Build/`, `.venv`, and other dev-only folders.
- R2 sync excludes app/build/dev files so only archive content + publish files are uploaded.

## GitHub Setup (Recommended)

Use GitHub for code/process files, and keep archive media hosted in R2.

1) Create a new empty GitHub repository.
2) In this folder, initialize git:
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```
3) Keep `.gitignore` as provided. It already excludes build/cache/state files.
4) Decide whether to version media in Git:
- If `yes`: keep as-is (repo will be large).
- If `no` (recommended): uncomment media/db lines in `.gitignore` before your first commit.
5) Continue using R2 for archive distribution (`manifest.json`, `miniatures.db`, mp4/jpg/png).

Notes:
- Avoid committing secrets/tokens (R2 keys, local config with secrets).
- GitHub is best for code versioning and collaboration, not large binary media storage.
