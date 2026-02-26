# Ragnar's Miniature Archive
<img width="1536" height="1024" alt="splash_screen" src="https://github.com/user-attachments/assets/1e14ea3d-08c1-4b41-a4f1-fae394bfaf12" />

Local archive of painted D&D miniatures with:
- category-based media folders at repository root
- `miniatures.db` (SQLite metadata)
- tools in `00_Apps/`

## Core Paths

- intake folder: `02_to_tag/`
- staging folder: `00_to_archive/` inside each category/subcategory folder
- database: `miniatures.db` at archive root
- tag categories config: `00_Apps/categories.json`

## Folder Roles

- `00_Apps/`: main app and maintenance tools (viewer, tagger, DB updater, converters)
- `01_Build/`: build/release automation (packaging scripts, build artifacts, release helpers)
- `02_to_tag/`: intake queue for untagged files before running the tagger

## Database

`miniatures.db` stores searchable metadata for viewer and tooling.

Main table: `miniatures`
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `name` TEXT
- `path_media` TEXT (relative media path)
- `tags` TEXT (comma-separated)
- `creature_type` TEXT
- `humanoid_type` TEXT
- `colors` TEXT
- `equipment` TEXT
- `roles` TEXT (legacy DBs may have `role`)
- `body_type` TEXT
- `sizes` TEXT (legacy DBs may have `size`)

The viewer reads available columns dynamically, so legacy/current schemas are both supported.

## Tools

`00_Apps/Viewer.py`
- browses media and searches by name/tags/category columns
- supports tag-panel filtering
- uses `miniatures.db` as metadata source
- run with `python3 00_Apps/Viewer.py`

`00_Apps/Tagger.py`
- imports `.mp4` from `02_to_tag/` by default
- supports matching/selecting full-resolution image files
- writes metadata via `exiftool`
- moves tagged files into archive category paths
- inserts/updates metadata in `miniatures.db`
- copies new outputs into destination `00_to_archive/` for sync tracking
- staging copy is non-destructive: existing files are not overwritten; suffixes like `__new1` are used
- run with `python3 00_Apps/Tagger.py`

`00_Apps/Database_Updater.py`
- rebuilds/aligns DB schema from `categories.json`
- re-reads media metadata and updates DB rows
- removes rows for missing media files
- run with `python3 00_Apps/Database_Updater.py`

`00_Apps/Exif_Type_Fixer.py`
- normalizes body-type tags (`male`/`female` to `Masculine`/`Feminine`)
- run with `python3 00_Apps/Exif_Type_Fixer.py`

`00_Apps/gif_mp4_converter.py`
- recreates `.mp4` from `.gif` when matching `.jpg` exists
- transfers tags from `.jpg` to `.mp4`
- run with `python3 00_Apps/gif_mp4_converter.py`

`01_Build/scripts/build_mac.sh`
- builds macOS app bundle
- run with `./01_Build/scripts/build_mac.sh`

`01_Build/scripts/build_linux.sh`
- builds Linux app binary
- run with `./01_Build/scripts/build_linux.sh`

`01_Build/scripts/build_windows.bat`
- builds Windows app binary
- run with `01_Build\\scripts\\build_windows.bat`

`01_Build/scripts/publish_release.sh`
- generates/updates `manifest.json` from local archive files
- merges deleted-file list from previous manifest state
- run with `./01_Build/scripts/publish_release.sh`

`01_Build/scripts/sync_to_r2.sh`
- uploads archive content to Cloudflare R2 using `rclone copy`
- excludes app/build/development folders during sync
- run with `./01_Build/scripts/sync_to_r2.sh`

## Release

App release page:
- https://github.com/Alex-Mesot/ragnars-miniature-archive-app/releases/latest
