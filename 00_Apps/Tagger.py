#!/usr/bin/env python3
import sys
import os
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QMessageBox, QGroupBox, QGridLayout, QFileDialog
)
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import QUrl, Qt
from PIL import Image, ImageOps

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ARCHIVE_ROOT = SCRIPT_DIR.parent
DEFAULT_SOURCE_DIRNAME = "02_to_tag"
DEFAULT_STAGING_SUBFOLDER = "00_to_archive"

"""
Tagger.py

Usage:
    python3 00_Apps/Tagger.py
    python3 00_Apps/Tagger.py /path/to/source_mp4s "/path/to/Ragnars Miniature Archive"

What it does:
- Iterates over all `.mp4` files in `source_mp4s`
- Shows each video for review
- Lets you rename and tag each miniature
- Moves files into the archive folder structure
- Writes MP4 metadata with `exiftool`
- Updates `<archive_root>/miniatures.db`

Paths used by this script:
- Default archive root: parent folder of `00_Apps` (this repository root)
- Default source folder: `<archive_root>/02_to_tag` (auto-created if missing)
- Categories config: `00_Apps/categories.json` (same folder as this script)
- SQLite DB: `<archive_root>/miniatures.db`
- Destination media folders:
  - `<archive_root>/<CreatureType>/...`
  - `<archive_root>/Humanoid/<HumanoidType>/...` (when creature type is Humanoid)
- New-item staging folder (for R3 copy tracking):
  - `<destination_folder>/00_to_archive/`
"""

# ---------------------------------------------------------------------
# 1. defaults for tags (used if no categories.json is found)
# ---------------------------------------------------------------------
# DEFAULT_CATEGORIES = {
#     "creature_type": [
#         "Aberration", "Beast", "Celestial", "Construct", "Dragon",
#         "Elemental", "Fey", "Fiend", "Giant", "Humanoid",
#         "Monstrosity", "Ooze", "Plant", "Undead", "Object"
#     ],
#     "humanoid_type": [
#         "Aasimar", "Bugbear", "Birdfolk", "Catfolk", "Dragonborn", "Drow",
#         "Duergar", "Dwarf", "Elf", "Firbolg", "Fishfolk", "Githyanki",
#         "Goblin", "Goliath", "Half-Elf", "Halfling", "Human", "Kobold",
#         "Lizardfolk", "Swampfolk", "Orc", "Tiefling", "Triton",
#         "Warforged", "Werefolk", "Yuan-Ti"
#     ],
#     "colors": [
#         "Black", "Blue", "Brown", "Gold", "Green", "Grey",
#         "Metal", "Orange", "Pink", "Purple", "Red", "White", "Yellow"
#     ],
#     "equipment": [
#         "Armor", "Helmet", "Shield", "Sword", "Mace", "Dagger", "Axe",
#         "Hammer", "Spear", "Whip", "Claw", "Fang", "Unarmed", "Bow",
#         "Arrow", "Crossbow", "Firearm", "Spell", "Lightning", "Fire",
#         "Water", "Earth", "Air", "Ice", "Poison", "Book", "Focus", "Backpack"
#     ],
#     "roles": ["Melee", "Ranged", "Mount", "Magic", "Siege", "Flying", "Swimming"],
#     "bodyType": ["Masculine", "Feminine"],
#     "sizes": ["Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan"]
# }

def load_categories() -> dict:
    """
    Load categories.json from the same folder as this script (00_Apps).
    Raise if missing or invalid.
    """
    script_dir = SCRIPT_DIR
    cfg_file = script_dir / "categories.json"

    if not cfg_file.exists():
        raise FileNotFoundError(f"categories.json not found in {script_dir}")

    try:
        with open(cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise ValueError(f"Could not parse categories.json: {e}")

    return data




# ---------------------------------------------------------------------
# 2. database helpers
# ---------------------------------------------------------------------
def init_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS miniatures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            path_media TEXT,
            tags TEXT
        );
        """
    )
    conn.commit()

    # Ensure columns exist (non-destructive)
    cur.execute("PRAGMA table_info(miniatures)")
    existing = {row[1] for row in cur.fetchall()}

    needed = [
        ("creature_type", "TEXT"),
        ("humanoid_type", "TEXT"),
        ("colors", "TEXT"),
        ("equipment", "TEXT"),
        ("roles", "TEXT"),      # plural
        ("body_type", "TEXT"),
        ("sizes", "TEXT"),      # plural
    ]

    for col, typ in needed:
        if col not in existing:
            cur.execute(f"ALTER TABLE miniatures ADD COLUMN {col} {typ}")

    conn.commit()
    return conn



def upsert_miniature(conn, name, rel_path, tags,
                     creature_type, humanoid_type,
                     colors, equipment, roles, body_type, sizes):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO miniatures
        (name, path_media, tags, creature_type, humanoid_type, colors, equipment, roles, body_type, sizes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            rel_path,
            ",".join(tags),
            creature_type,
            humanoid_type,                 # already a comma-joined string in your call
            ",".join(colors),
            ",".join(equipment),
            ",".join(roles),
            body_type,
            sizes,                         # store single size string
        )
    )
    conn.commit()



# ---------------------------------------------------------------------
# 3. tagging GUI
# ---------------------------------------------------------------------
class TaggerWindow(QWidget):
    def __init__(self, source_dir: Path, archive_root: Path):
        super().__init__()
        self.setWindowTitle("Miniature Tagger")
        self.source_dir = source_dir
        self.archive_root = archive_root
        self.categories = load_categories()
        self.ensure_archive_staging_folders()

        self.files = sorted([p for p in self.source_dir.iterdir() if p.suffix.lower() == ".mp4"])
        self.current_index = 0

        # DB
        self.db_path = self.archive_root / "miniatures.db"
        self.conn = init_db(self.db_path)

        # UI setup
        self.player = QMediaPlayer()
        self.video_widget = QVideoWidget()
        self.player.setVideoOutput(self.video_widget)
        self.player.setPlaybackRate(0.5)

        self.name_edit = QLineEdit()

        # list widgets for multi-select
        self.creature_list = QListWidget()
        self.creature_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        for t in self.categories["creature_type"]:
            self.creature_list.addItem(t)

        self.humanoid_list = QListWidget()
        self.humanoid_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for t in self.categories["humanoid_type"]:
            self.humanoid_list.addItem(t)

        self.color_list = QListWidget()
        self.color_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for c in self.categories["colors"]:
            self.color_list.addItem(c)

        self.equipment_list = QListWidget()
        self.equipment_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for e in self.categories["equipment"]:
            self.equipment_list.addItem(e)

        self.role_list = QListWidget()
        self.role_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for r in self.categories["roles"]:
            self.role_list.addItem(r)

        self.body_type_list = QListWidget()
        self.body_type_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        for g in self.categories["body_type"]:
            self.body_type_list.addItem(g)

        self.size_list = QListWidget()
        self.size_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        for s in self.categories["sizes"]:
            self.size_list.addItem(s)

        self.save_button = QPushButton("Save & Next")
        self.skip_button = QPushButton("Skip")

        self.save_button.clicked.connect(self.save_and_next)
        self.skip_button.clicked.connect(self.next_video)
        # self.player.mediaStatusChanged.connect(self.loop_video)

        self.player.positionChanged.connect(self.check_loop)
        self.player.durationChanged.connect(self.save_duration)
        self._video_duration = 0

        # layout
        main_layout = QHBoxLayout(self)

        # left: video
        left_layout = QVBoxLayout()
        left_layout.addWidget(self.video_widget)
        main_layout.addLayout(left_layout, 2)

        # right: form
        right_layout = QVBoxLayout()

        right_layout.addWidget(QLabel("New name (without .mp4):"))
        right_layout.addWidget(self.name_edit)

        # Full-res image selection
        self.fullres_path: Path | None = None
        self.fullres_label = QLabel("Full-res image: (auto-detect or choose)")
        self.pick_fullres_btn = QPushButton("Select full-res image…")
        self.pick_fullres_btn.clicked.connect(self.pick_fullres_image)

        right_layout.addWidget(self.fullres_label)
        right_layout.addWidget(self.pick_fullres_btn)


        grid = QGridLayout()

        grid.addWidget(self.group_box("Creature Type", self.creature_list), 0, 0)
        grid.addWidget(self.group_box("Humanoid Type (if Humanoid)", self.humanoid_list), 0, 1)
        grid.addWidget(self.group_box("Colors (top 3)", self.color_list), 1, 0)
        grid.addWidget(self.group_box("Equipment", self.equipment_list), 1, 1)
        grid.addWidget(self.group_box("Role", self.role_list), 2, 0)
        grid.addWidget(self.group_box("Body Type (if applicable)", self.body_type_list), 2, 1)
        grid.addWidget(self.group_box("Size", self.size_list), 3, 0)

        right_layout.addLayout(grid)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.save_button)
        btn_layout.addWidget(self.skip_button)
        right_layout.addLayout(btn_layout)

        main_layout.addLayout(right_layout, 3)

        # load first video
        if self.files:
            self.load_current_video()
        else:
            QMessageBox.information(self, "Info", "No .mp4 files found in source folder.")

    def group_box(self, title, widget):
        box = QGroupBox(title)
        v = QVBoxLayout()
        v.addWidget(widget)
        box.setLayout(v)
        return box

    def load_current_video(self):
        if self.current_index < 0 or self.current_index >= len(self.files):
            QMessageBox.information(self, "Done", "No more files.")
            return
        current_file = self.files[self.current_index]
        self.name_edit.setText(current_file.stem)
        self.clear_selections()
        self.player.setSource(QUrl.fromLocalFile(str(current_file)))
        self.player.play()
        self.setWindowTitle(f"Miniature Tagger - {current_file.name}")

        # Auto-detect full-res image for this mp4
        self.fullres_path = self.auto_find_fullres(current_file)
        if self.fullres_path:
            self.fullres_label.setText(f"Full-res image: {self.fullres_path.name}")
        else:
            self.fullres_label.setText("Full-res image: (missing) — click to select")


    def clear_selections(self):
        for lw in [self.creature_list, self.humanoid_list, self.color_list,
                   self.equipment_list, self.role_list, self.body_type_list, self.size_list]:
            lw.clearSelection()

    def get_selected(self, lw: QListWidget):
        items = lw.selectedItems()
        return [i.text() for i in items]

    #def loop_video(self, status):
    #    from PyQt6.QtMultimedia import QMediaPlayer
    #    if status == QMediaPlayer.MediaStatus.EndOfMedia:
    #        self.player.setPosition(0)
    #        self.player.play()

    def save_duration(self, dur):
    # duration in ms
        self._video_duration = dur

    def check_loop(self, pos):
    # pos and duration are in ms
    # jump back a tiny bit before the end (150 ms) to avoid the black frame
        if self._video_duration > 0 and pos >= self._video_duration - 125:
            # don't stop, just seek
            self.player.setPosition(0)


    def save_and_next(self):
        if self.current_index < 0 or self.current_index >= len(self.files):
            return

        src_file = self.files[self.current_index]
        new_name = self.name_edit.text().strip()
        if not new_name:
            QMessageBox.warning(self, "Error", "Please enter a name.")
            return

        creature_type = self.get_selected(self.creature_list)
        creature_type = creature_type[0] if creature_type else "Uncategorized"

        humanoid_type = self.get_selected(self.humanoid_list)
        colors = self.get_selected(self.color_list)
        equipment = self.get_selected(self.equipment_list)
        roles = self.get_selected(self.role_list)
        body_type = self.get_selected(self.body_type_list)
        body_type = body_type[0] if body_type else ""
        size = self.get_selected(self.size_list)
        size = size[0] if size else ""

        # build tag list
        tag_list = []
        tag_list.append(creature_type)
        tag_list.extend(humanoid_type)
        tag_list.extend(colors)
        tag_list.extend(equipment)
        tag_list.extend(roles)
        if body_type:
            tag_list.append(body_type)
        if size:
            tag_list.append(size)

        # decide destination folder
        dest_dir = self.get_destination_folder(creature_type, humanoid_type)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / f"{new_name}.mp4"

        # move file
        shutil.move(str(src_file), dest_file)

        # Move/rename full-res image too (if available)
        dest_full_img = None
        thumb_path = None
        if self.fullres_path and self.fullres_path.exists():
            ext = self.fullres_path.suffix.lower()
            # store full-res as .jpg if you want consistency, or keep ext:
            dest_full_img = dest_dir / f"{new_name}{ext}"
            shutil.move(str(self.fullres_path), dest_full_img)

            # Generate thumbnail next to it
            thumb_path = dest_dir / f"{new_name}_thumb.jpg"
            try:
                self.make_thumb_512(dest_full_img, thumb_path)
            except Exception as e:
                QMessageBox.warning(self, "Thumbnail error", f"Could not create thumbnail:\n{e}")
        else:
            # if missing, you may want to warn but still allow tagging mp4
            pass


        # write metadata to mp4
        self.write_metadata(dest_file, new_name, tag_list)

        # update db (store relative path)
        rel_path = dest_file.relative_to(self.archive_root).as_posix()
        upsert_miniature(
            self.conn,
            name=new_name,
            rel_path=rel_path,
            tags=tag_list,
            creature_type=creature_type,
            humanoid_type=",".join(humanoid_type),
            colors=colors,
            equipment=equipment,
            roles=roles,
            body_type=body_type,
            sizes=size
        )

        # copy newly-tagged assets into a per-folder staging area for archive sync
        self.copy_assets_to_staging(dest_dir, [dest_file, dest_full_img, thumb_path])

        # go next
        self.current_index += 1
        if self.current_index < len(self.files):
            self.load_current_video()
        else:
            QMessageBox.information(self, "Done", "All files processed.")
            self.player.stop()

    def get_destination_folder(self, creature_type: str, humanoid_type: list) -> Path:
        """
        Recreates your structure:
        - if Humanoid and a humanoid_type selected: archive_root/Humanoid/<humanoid_type>/
        - else: archive_root/<CreatureType>/
        """
        if creature_type == "Humanoid" and humanoid_type:
            return self.archive_root / "Humanoid" / humanoid_type[0]
        else:
            return self.archive_root / creature_type

    def write_metadata(self, file_path: Path, title: str, tags: list[str]):
        """
        Calls exiftool to write subject/keywords into mp4
        """
        tag_string = ",".join(tags)
        # exiftool -overwrite_original -Subject="..." -Title="..." file.mp4
        cmd = [
             "exiftool",
            "-overwrite_original",
            "-sep", ",",
            # Write to both QuickTime and XMP namespaces
            f"-XMP:Subject={tag_string}",
            f"-XMP:Keywords={tag_string}",
            f"-QuickTime:Keywords={tag_string}",
            f"-Title={title}",
            str(file_path)
        ]

        try:
            subprocess.run(cmd, check=True)
        except Exception as e:
            QMessageBox.warning(self, "Exiftool error", f"Could not write metadata:\n{e}")

    def next_video(self):
        self.current_index += 1
        if self.current_index < len(self.files):
            self.load_current_video()
        else:
            QMessageBox.information(self, "Done", "All files processed.")
            self.player.stop()

    def auto_find_fullres(self, mp4_path: Path) -> Optional[Path]:
        # Look in source folder for same stem
        exts = [".jpg", ".jpeg", ".png", ".webp"]
        for ext in exts:
            p = mp4_path.with_suffix(ext)
            if p.exists() and not p.stem.endswith("_thumb"):
                return p
        return None

    def pick_fullres_image(self):
        start_dir = str(self.source_dir)
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select full-res image",
            start_dir,
            "Images (*.jpg *.jpeg *.png *.webp)"
        )
        if file_path:
            self.fullres_path = Path(file_path)
            self.fullres_label.setText(f"Full-res image: {self.fullres_path.name}")

    def make_thumb_512(self, full_img_path: Path, thumb_path: Path):
        img = Image.open(full_img_path)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")

        size = 512
        img.thumbnail((size, size), Image.Resampling.LANCZOS)

        canvas = Image.new("RGB", (size, size), (0, 0, 0))
        x = (size - img.size[0]) // 2
        y = (size - img.size[1]) // 2
        canvas.paste(img, (x, y))

        # Use high-quality JPEG with 4:4:4 chroma to avoid soft-looking thumbnails.
        canvas.save(
            thumb_path,
            "JPEG",
            quality=95,
            optimize=True,
            progressive=False,
            subsampling=0,
        )

    def copy_assets_to_staging(self, destination_folder: Path, paths: list[Optional[Path]]):
        staging_dir = destination_folder / DEFAULT_STAGING_SUBFOLDER
        staging_dir.mkdir(parents=True, exist_ok=True)
        for p in paths:
            if p and p.exists():
                target = self.next_available_staging_name(staging_dir, p.name)
                shutil.copy2(p, target)

    def next_available_staging_name(self, staging_dir: Path, filename: str) -> Path:
        target = staging_dir / filename
        if not target.exists():
            return target

        stem = Path(filename).stem
        suffix = Path(filename).suffix
        i = 1
        while True:
            candidate = staging_dir / f"{stem}__new{i}{suffix}"
            if not candidate.exists():
                return candidate
            i += 1

    def ensure_archive_staging_folders(self):
        # Create staging folders up front in every creature folder and humanoid subtype folder.
        for creature in self.categories.get("creature_type", []):
            creature_dir = self.archive_root / creature
            creature_dir.mkdir(parents=True, exist_ok=True)
            (creature_dir / DEFAULT_STAGING_SUBFOLDER).mkdir(parents=True, exist_ok=True)

            if creature == "Humanoid":
                for subtype in self.categories.get("humanoid_type", []):
                    subtype_dir = creature_dir / subtype
                    subtype_dir.mkdir(parents=True, exist_ok=True)
                    (subtype_dir / DEFAULT_STAGING_SUBFOLDER).mkdir(parents=True, exist_ok=True)

                # Also cover any already-existing custom humanoid subtype folders.
                for sub in creature_dir.iterdir():
                    if sub.is_dir() and sub.name != DEFAULT_STAGING_SUBFOLDER:
                        (sub / DEFAULT_STAGING_SUBFOLDER).mkdir(parents=True, exist_ok=True)



def main():
    source_dir = (
        Path(sys.argv[1]).expanduser().resolve()
        if len(sys.argv) >= 2
        else (DEFAULT_ARCHIVE_ROOT / DEFAULT_SOURCE_DIRNAME)
    )
    archive_root = (
        Path(sys.argv[2]).expanduser().resolve()
        if len(sys.argv) >= 3
        else DEFAULT_ARCHIVE_ROOT
    )

    if not archive_root.exists():
        print(f"Archive folder does not exist: {archive_root}")
        sys.exit(1)

    # Auto-create default intake folder so new files can just be dropped in.
    if source_dir == (DEFAULT_ARCHIVE_ROOT / DEFAULT_SOURCE_DIRNAME) and not source_dir.exists():
        source_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created source folder: {source_dir}")

    if not source_dir.exists():
        print(f"Source folder does not exist: {source_dir}")
        sys.exit(1)

    app = QApplication(sys.argv)
    win = TaggerWindow(source_dir, archive_root)
    win.resize(1400, 800)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
