#!/usr/bin/env python3
"""
Desktop viewer for archive media and tag search.

Run:
  python3 00_Apps/Viewer.py
"""
import sys
import os
import random
import sqlite3
import shlex
import json
import webbrowser
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QListWidget, QLabel, QMessageBox,
    QGridLayout, QGroupBox, QSizePolicy, QSpacerItem, QScrollArea, QToolButton, QCompleter, QProgressDialog, QSplashScreen,
)
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import QUrl, Qt, QTimer, QStringListModel, pyqtSignal
from PyQt6.QtGui import QPixmap, QFontMetrics, QPainter, QGuiApplication, QCursor

if ".venv" not in sys.executable:
    print("   Reminder: You are NOT running inside the .venv")
    print("   Run: source .venv/bin/activate")

from archive_sync import check_updates, sync_updates

APP_VERSION = "1.0.0"


def _version_tuple(v: str) -> tuple[int, ...]:
    cleaned = v.strip().lower().lstrip("v")
    parts = []
    for chunk in cleaned.split("."):
        num = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts) if parts else (0,)


def is_remote_version_newer(local_version: str, remote_version: str) -> bool:
    local_t = _version_tuple(local_version)
    remote_t = _version_tuple(remote_version)
    n = max(len(local_t), len(remote_t))
    local_padded = local_t + (0,) * (n - len(local_t))
    remote_padded = remote_t + (0,) * (n - len(remote_t))
    return remote_padded > local_padded


def get_default_archive_root() -> Path:
    app_folder = "RagnarsMiniatureArchive"
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else (Path.home() / "AppData" / "Roaming")
    else:
        base = Path.home() / ".local" / "share"
    return base / app_folder / "archive"


class ClickableThumb(QLabel):
    index: int = -1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent;")
        self.setScaledContents(False)
        self._orig_pix = None

    def set_thumb_pixmap(self, pix: QPixmap):
        self._orig_pix = pix
        self._rebuild_thumb()

    def _rebuild_thumb(self):
        if self._orig_pix is None or self._orig_pix.isNull():
            return

        side = max(1, min(self.width(), self.height()))
        dpr = max(1.0, float(self.devicePixelRatioF()))
        px_side = max(1, int(round(side * dpr)))

        # Scale in physical pixels to keep thumbnails crisp on HiDPI displays.
        scaled = self._orig_pix.scaled(
            px_side,
            px_side,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)

        # Letterbox into a square canvas so QLabel never clips anything.
        canvas = QPixmap(px_side, px_side)
        canvas.setDevicePixelRatio(dpr)
        canvas.fill(Qt.GlobalColor.transparent)

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        scaled_logical = scaled.deviceIndependentSize()
        x = int((side - scaled_logical.width()) / 2)
        y = int((side - scaled_logical.height()) / 2)
        painter.drawPixmap(x, y, scaled)
        painter.end()

        self.setPixmap(canvas)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild_thumb()

    def mousePressEvent(self, event):
        # Walk up parents to find the viewer container; avoids fragile parent().parent() assumptions.
        parent = self.parentWidget()
        while parent is not None:
            cb = getattr(parent, "preview_clicked", None)
            if callable(cb):
                cb(self.index)
                break
            parent = parent.parentWidget()
        super().mousePressEvent(event)


class LockedSplashScreen(QSplashScreen):
    def mousePressEvent(self, event):
        # Prevent default QSplashScreen behavior of hiding on click.
        event.ignore()




    

class FlowLayout(QHBoxLayout):
    """
    Simple wrap-like layout using a horizontal layout inside a scroll area is usually enough.
    If you want true wrapping, we can replace this with a real FlowLayout later.
    """
    pass


class ChipButton(QToolButton):
    def __init__(self, text: str, kind: str = "tag"):
        super().__init__()
        self.kind = kind  # "tag" or "op"
        self.value = text
        self.setText(f"{text}  ✕" if kind == "tag" else text)
        self.setCheckable(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        if kind == "op":
            # operator chip look
            self.setStyleSheet("""
                QToolButton {
                    padding: 4px 10px;
                    border-radius: 12px;
                    border: 1px solid palette(mid);
                    background: palette(base);
                    color: palette(text);
                    font-weight: 600;
                }
                QToolButton:hover { background: palette(alternate-base); }
            """)
        else:
            # tag chip look
            self.setStyleSheet("""
                QToolButton {
                    padding: 4px 10px;
                    border-radius: 12px;
                    background: palette(highlight);
                    color: palette(highlighted-text);
                    font-weight: 500;
                }
                QToolButton:hover { filter: brightness(0.95); }
            """)

        # make chips not ridiculously wide
        fm = QFontMetrics(self.font())
        self.setMaximumWidth(max(80, min(260, fm.horizontalAdvance(self.text()) + 18)))


class ChipLineEdit(QWidget):
    """
    A line edit with removable chips displayed inside the same "bar".
    - Chips are on the left.
    - Text entry is on the right.
    """
    chipRemoved = pyqtSignal(int)   # index
    chipClicked = pyqtSignal(int)   # optional, not used yet
    deleteLastChip = pyqtSignal()
    commitToken = pyqtSignal(str)




    def __init__(self, parent=None):
        super().__init__(parent)

        self.chip_widgets: list[QWidget] = []
        self.chips: list[dict] = []

        self.container = QWidget(self)
        self.container_layout = QHBoxLayout(self.container)
        self.container_layout.setContentsMargins(6, 4, 6, 4)
        self.container_layout.setSpacing(6)
        # Clicking empty space in the chip area sets insertion at the end
        self.container.mousePressEvent = self._container_clicked


        self.edit = QLineEdit(self)
        self.edit.installEventFilter(self)
        self.edit.setFrame(False)  # important: looks like one bar
        self.edit.setPlaceholderText("Type a tag, press Enter. Use AND / OR between tags.")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self.container, 0)
        root.addWidget(self.edit, 1)

        # make widget look like a single search bar
        self.setStyleSheet("""
            ChipLineEdit {
                border: 1px solid palette(mid);
                border-radius: 8px;
                background: palette(base);
            }
        """)

    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
                # If the text box is empty, treat backspace/delete as "remove last chip"
                if self.edit.text() == "" and len(self.chips) > 0:
                    self.deleteLastChip.emit()
                    return True  # consume event
                
            # SPACE: commit current token as a chip
            if key == Qt.Key.Key_Space:
                txt = self.edit.text()

                # If we're inside an unmatched quote, allow typing spaces normally
                if txt.count('"') % 2 == 1:
                    return False

                token = txt.strip()
                if token:
                    self.commitToken.emit(token)
                    self.edit.clear()
                    return True
                return False
            
        return super().eventFilter(obj, event)


    def text(self) -> str:
        return self.edit.text()

    def clearText(self):
        self.edit.clear()

    def setCompleter(self, completer):
        completer.setWidget(self.edit)
        self.edit.setCompleter(completer)

    def returnPressedConnect(self, fn):
        self.edit.returnPressed.connect(fn)

    def textChangedConnect(self, fn):
        self.edit.textChanged.connect(fn)

    def setFocusToEdit(self):
        self.edit.setFocus()

    def setPlaceholderText(self, text: str):
        self.edit.setPlaceholderText(text)

    def _container_clicked(self, event):
        # Click in empty space: insert at end
        self.setFocusToEdit()


    def setChips(self, chips: list[dict]):
        self.chips = chips

        for w in self.chip_widgets:
            w.deleteLater()
        self.chip_widgets.clear()

        for idx, tok in enumerate(chips):
            btn = QToolButton(self.container)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

            # display text (no ✕)
            btn.setText(tok["value"])

            if tok["kind"] == "op":
                btn.setStyleSheet("""
                    QToolButton {
                        padding: 2px 10px;
                        border-radius: 10px;
                        border: 1px solid palette(mid);
                        background: palette(alternate-base);
                        color: palette(text);
                        font-weight: 600;
                    }
                    QToolButton:hover { background: palette(base); }
                """)
            elif tok["kind"] == "text":
                btn.setStyleSheet("""
                    QToolButton {
                        padding: 2px 10px;
                        border-radius: 10px;
                        border: 1px solid palette(mid);
                        background: transparent;
                        color: palette(text);
                        font-weight: 500;
                    }
                    QToolButton:hover { background: palette(alternate-base); }
                """)
            else:
                btn.setStyleSheet("""
                    QToolButton {
                        padding: 2px 10px;
                        border-radius: 10px;
                        background: palette(highlight);
                        color: palette(highlighted-text);
                        font-weight: 500;
                    }
                """)

            # clicking chip removes it
            btn.clicked.connect(lambda _, i=idx: self.chipRemoved.emit(i))

            self.container_layout.addWidget(btn)
            self.chip_widgets.append(btn)







class MiniViewer(QWidget):
    def __init__(self, archive_root: Path, splash: QSplashScreen | None = None):
        super().__init__()
        self.setWindowTitle("Ragnar's Miniature Archive")
        self.setMinimumSize(1020, 700)
        self.archive_root = archive_root
        self.splash = splash
        self.update_cfg = self.load_update_config()
        self.categories_cfg = self.load_categories_config()
        self.last_update_check = None

        # db
        self.db_path = self.archive_root / "miniatures.db"
        if not self.db_path.exists():
            ok, reason = self.bootstrap_archive_if_needed()
            if not ok:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Database not found at {self.db_path}\n\n{reason}",
                )
                sys.exit(1)
        self.conn = sqlite3.connect(self.db_path)

        # get actual columns so we don't query stuff that doesn't exist
        self.existing_columns = self.get_existing_columns()

        # housekeeping
        self.prune_missing_files()

        self.tag_to_columns = {}  # tag -> set(columns)
        self.all_tags_for_autocomplete = []


        # keep track of active tag filters: {column_name: set(tags)}
        self.active_tag_filters: dict[str, set[str]] = {}


        # -------------------- LEFT SIDE --------------------
        # --- search input with completer ---
        self.search_bar = ChipLineEdit()
        self.search_bar.setPlaceholderText("Tags, Logic Operators, Names (red flying OR beast deepwood)")

        # completer from all known tags
        self.completer_model = QStringListModel(self.all_tags_for_autocomplete)
        self.completer = QCompleter(self.completer_model, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchStartsWith)
        self.completer.setCompletionMode(QCompleter.CompletionMode.InlineCompletion)
        self.search_bar.setCompleter(self.completer)

        def _show_completions(_text: str):
            prefix = self.search_bar.text().strip()
            self.completer.setCompletionPrefix(prefix)
            if prefix:
                self.completer.complete()  # show popup

        self.search_bar.textChangedConnect(_show_completions)


        # Enter creates chip
        self.search_bar.returnPressedConnect(self.on_search_enter)
        self.search_bar.commitToken.connect(self.commit_token_from_space)


        # Chip interactions
        self.search_bar.chipRemoved.connect(self.remove_chip_at)
        self.search_bar.deleteLastChip.connect(self.remove_last_chip)


        search_layout = QHBoxLayout()
        search_layout.addWidget(self.search_bar)

        self.chips = []  # list of token dicts: {"kind":"tag"|"op", "value":str}

        self.update_status_label = QLabel("Offline mode (no update source configured)")
        self.download_updates_btn = QPushButton("Download latest archive")
        self.download_updates_btn.setEnabled(False)
        self.download_updates_btn.clicked.connect(self.download_latest_archive)
        self.app_update_btn = QPushButton("Download app update")
        self.app_update_btn.clicked.connect(self.open_app_update_page)
        self.app_update_btn.setEnabled(False)
        self.app_update_btn.setVisible(False)
        self.app_update_url = ""

        # tag panels
        self.tag_lists = {}
        tag_grid = QGridLayout()
        tag_grid.setSpacing(6)

        # we’ll define categories, but some may not exist in the DB
        # for role/size we'll test both singular/plural
        raw_categories = [
            ("Creature type", "creature_type"),
            ("Humanoid type", "humanoid_type"),
            ("Colors", "colors"),
            ("Equipment", "equipment"),
            ("Role", ["role", "roles"]),
            ("Body type", "body_type"),
            ("Size", ["size", "sizes"]),
        ]

        # Explicit placement so Equipment gets more vertical room:
        # - row/col are 0-based
        # - Equipment sits at row 2, col 1 and spans 2 rows
        placements = {
            "creature_type": (0, 0, 1, 1),
            "humanoid_type": (0, 1, 1, 1),
            "colors": (1, 0, 1, 1),
            "body_type": (1, 1, 1, 1),
            "role": (2, 0, 1, 1),
            "roles": (2, 0, 1, 1),
            "equipment": (2, 1, 2, 1),
            "size": (3, 0, 1, 1),
            "sizes": (3, 0, 1, 1),
        }

        fallback_row = 0
        fallback_col = 0
        rendered_boxes = 0
        for label, field in raw_categories:
            # allow list of possible column names
            if isinstance(field, list):
                db_col = None
                for f in field:
                    if f in self.existing_columns:
                        db_col = f
                        break
                if not db_col:
                    continue
                field = db_col
            else:
                if field not in self.existing_columns:
                    continue

            values = self.get_distinct_values(field)
            if not values:
                values = self.get_category_values_from_config(field)
            if not values:
                continue

            for vtag in values:
                self.tag_to_columns.setdefault(vtag, set()).add(field)

            self.all_tags_for_autocomplete = sorted(self.tag_to_columns.keys(), key=str.lower)
            #print("Autocomplete tags:", len(self.all_tags_for_autocomplete))


            box = QGroupBox(label)
            v = QVBoxLayout()
            lw = QListWidget()
            # multi select so we can toggle
            lw.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
            if field == "equipment":
                lw.setMinimumHeight(170)
            else:
                lw.setMaximumHeight(80)
            lw.addItems(values)

            # Keep each box wide enough to show at least the longest word in its list.
            fm = QFontMetrics(lw.font())
            longest_word_width = 0
            for val in values:
                words = val.split()
                if not words:
                    words = [val]
                for word in words:
                    longest_word_width = max(longest_word_width, fm.horizontalAdvance(word))
            min_list_width = max(120, min(180, longest_word_width + 44))  # cap so app can shrink on smaller displays
            lw.setMinimumWidth(min_list_width)

            # we need to know which column this list belongs to
            lw.itemClicked.connect(lambda item, colname=field: self.category_tag_clicked(colname, item))
            v.addWidget(lw)
            box.setLayout(v)
            box.setMinimumWidth(min_list_width + 8)

            if field in placements:
                row, col, row_span, col_span = placements[field]
            else:
                row, col, row_span, col_span = fallback_row, fallback_col, 1, 1
                fallback_col += 1
                if fallback_col >= 2:
                    fallback_col = 0
                    fallback_row += 1

            tag_grid.addWidget(box, row, col, row_span, col_span)
            self.tag_lists[field] = lw
            rendered_boxes += 1

        if rendered_boxes == 0:
            generic_values = self.get_distinct_values("tags")
            if generic_values:
                box = QGroupBox("Tags")
                v = QVBoxLayout()
                lw = QListWidget()
                lw.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
                lw.setMaximumHeight(170)
                lw.addItems(generic_values[:300])
                lw.itemClicked.connect(lambda item, colname="tags": self.category_tag_clicked(colname, item))
                v.addWidget(lw)
                box.setLayout(v)
                tag_grid.addWidget(box, 0, 0, 1, 2)
                self.tag_lists["tags"] = lw

        # results at the bottom, give it more space
        self.results_list = QListWidget()
        self.results_list.currentItemChanged.connect(self.show_selected)
        self.results_list.setMinimumHeight(200)

        # reset button
        self.reset_btn = QPushButton("Reset filters")
        self.reset_btn.clicked.connect(self.reset_all_filters)
        reset_layout = QHBoxLayout()
        reset_layout.addItem(QSpacerItem(10, 10, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        reset_layout.addWidget(self.reset_btn)

        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(search_layout)
        left_layout.addLayout(tag_grid)
        left_layout.addLayout(reset_layout)
        self.results_header = QLabel("Results")
        left_layout.addWidget(self.results_header)
        left_layout.addWidget(self.results_list, 1)
        self.left_panel.setMinimumWidth(340)


        # -------------------- RIGHT SIDE --------------------


        # main video / image
        self.player = QMediaPlayer()
        self.video_widget = QVideoWidget()
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video_widget.setMinimumSize(340, 200)

        self.player.setVideoOutput(self.video_widget)
        self.player.setPlaybackRate(0.5)
        self.player.positionChanged.connect(self.check_loop_main)
        self.player.durationChanged.connect(self.save_main_duration)
        self._main_duration = 0
        self.video_widget.setStyleSheet("background: palette(base);")

        self.top_container = QWidget()
        self.top_container.setStyleSheet("background: palette(base);")
        self.top_container.setMinimumHeight(200)
        top_layout = QHBoxLayout(self.top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)
        top_layout.addWidget(self.video_widget, 1)


        self.image_label = QLabel("No item selected")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setScaledContents(True)
        self.image_label.hide()
        self.video_widget.hide()

        # dynamic previews (thumbnails)
        self.preview_container = QWidget()
        self.preview_layout = QGridLayout(self.preview_container)
        self.preview_layout.setContentsMargins(8, 8, 8, 8)
        self.preview_layout.setSpacing(10)

        self.preview_widgets = []
        self.max_previews = 60
        self.current_results = []
        self.thumb_side = 158
        self.preview_rows_min = 1
        self.preview_rows_max = 2

        # Keep preview strip bounded so top video area remains dominant,
        # while allowing one row to collapse on smaller windows.
        m = self.preview_layout.contentsMargins()
        spacing = self.preview_layout.spacing()
        one_row_h = self.thumb_side + m.top() + m.bottom()
        two_rows_h = (self.thumb_side * 2) + spacing + m.top() + m.bottom()
        self.preview_container.setMinimumHeight(one_row_h)
        self.preview_container.setMaximumHeight(two_rows_h)

        for i in range(self.max_previews):
            w = ClickableThumb(self.preview_container)
            w.index = i
            w.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            w.setFixedSize(self.thumb_side, self.thumb_side)
            w.hide()
            self.preview_widgets.append(w)

        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.top_container, 5)
        right_layout.addWidget(self.image_label, 0)      # keep for non-video files if you want
        right_layout.addWidget(self.preview_container, 5)

        update_footer = QHBoxLayout()
        update_footer.addWidget(self.update_status_label, 1)
        update_footer.addWidget(self.download_updates_btn, 0)
        update_footer.addWidget(self.app_update_btn, 0)
        right_layout.addLayout(update_footer, 0)
        self.right_panel.setMinimumWidth(540)

        # main layout
        main_layout = QHBoxLayout(self)
        main_layout.addWidget(self.left_panel, 2)
        main_layout.addWidget(self.right_panel, 3)

        # startup sync (for splash-driven first launch / auto-update)
        self.startup_auto_update_with_splash()

        # initial
        self.show_random_home()
        if self.update_cfg and self.update_cfg.get("check_on_startup", True):
            QTimer.singleShot(150, self.check_for_content_updates)



    def show_random_home(self):
        cur = self.conn.cursor()

        # Pull a random set (keep your humanoid bias if you want; here is simple random)
        # Increase LIMIT if you want more in the left list while home is active
        limit = 100
        cur.execute(
            "SELECT id, name, path_media, tags FROM miniatures ORDER BY RANDOM() LIMIT ?",
            (limit,)
        )
        rows = cur.fetchall()

        self.current_results = []
        for _id, name, path_media, tags in rows:
            self.current_results.append({"id": _id, "name": name, "path_media": path_media, "tags": tags})

        # Populate FULL results list on the left (scrollable)
        self.results_list.blockSignals(True)
        self.results_list.clear()
        for item in self.current_results:
            self.results_list.addItem(item["name"])
        self.results_list.blockSignals(False)

        # Header: show total in DB, and show how many are in this random set
        total = cur.execute("SELECT COUNT(*) FROM miniatures").fetchone()[0]
        shown = len(self.current_results)
        if total == 1:
            self.results_header.setText("1 Result")
        else:
            self.results_header.setText(f"{total} Results (showing {shown} random)")

        # Show previews for this random set (will pick a window around selection)
        self.update_previews()

        # Select first result so video starts
        if self.results_list.count() > 0:
            self.results_list.setCurrentRow(0)
        else:
            self.player.stop()
            self.video_widget.hide()
            self.image_label.setText("No item selected")
            self.image_label.show()

    def tokenize_user_input(self, s: str) -> list[str]:
        """
        Split user input into tokens while respecting quotes.
        """
        s = s.strip()
        if not s:
            return []
        try:
            return shlex.split(s)  # respects quotes
        except ValueError:
            # unmatched quote, just fall back to raw
            return [s]


    def commit_token_from_space(self, token: str):
        parts = self.tokenize_user_input(token)

        for raw in parts:
            t = raw.strip()
            if not t:
                continue

            # Power user: -foo  => NOT foo
            negate = False
            if t.startswith("-") and len(t) > 1:
                negate = True
                t = t[1:].strip()

            if not t:
                continue

            # Operators
            if t.upper() in ("AND", "OR", "NOT"):
                # If user typed -AND etc. ignore the negate for operators
                self.add_chip("op", t.upper())
                continue

            # Determine tag vs free-text
            chosen = next((x for x in self.all_tags_for_autocomplete if x.lower() == t.lower()), None)
            if chosen:
                if negate:
                    self.add_chip("op", "NOT")
                self.add_chip("tag", chosen)
            else:
                if negate:
                    self.add_chip("op", "NOT")
                self.add_chip("text", t)



    # -------------------- DB utils --------------------
    def get_existing_columns(self):
        cols = set()
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(miniatures)")
        for row in cur.fetchall():
            cols.add(row[1])
        return cols

    def prune_missing_files(self):
        cur = self.conn.cursor()
        cur.execute("SELECT id, path_media FROM miniatures")
        rows = cur.fetchall()
        removed = 0
        for _id, path_media in rows:
            media_path = (self.archive_root / path_media).resolve()
            if not media_path.exists():
                cur.execute("DELETE FROM miniatures WHERE id = ?", (_id,))
                removed += 1
        if removed:
            self.conn.commit()

    def get_distinct_values(self, column: str):
        if column not in self.existing_columns:
            return []
        cur = self.conn.cursor()
        cur.execute(
            f"SELECT DISTINCT {column} FROM miniatures "
            f"WHERE {column} IS NOT NULL AND {column} <> ''"
        )
        rows = cur.fetchall()
        values = set()
        for (val,) in rows:
            if not val:
                continue
            parts = [p.strip() for p in val.split(",") if p.strip()]
            values.update(parts)
        return sorted(values, key=str.lower)

    # -------------------- Tag clicks --------------------
    def category_tag_clicked(self, column_name: str, item):
        tag = item.text()

        # toggle chip
        existing_idx = next((i for i, t in enumerate(self.chips)
                            if t["kind"] == "tag" and t["value"].lower() == tag.lower()), None)
        if existing_idx is not None:
            self.remove_chip_at(existing_idx)
        else:
            self.add_chip("tag", tag)


    def reset_all_filters(self):
        # 1) clear chips
        self.chips.clear()
        self.search_bar.setChips(self.chips)

        # 2) clear any highlighted selections in the tag lists
        for lw in self.tag_lists.values():
            lw.clearSelection()

        # 3) clear the typing area
        self.search_bar.clearText()
        self.search_bar.setFocusToEdit()

        # 4) show fresh random home selection
        self.show_random_home()


    # -------------------- Search --------------------
    def run_search(self):

        if not self.chips:
            self.show_random_home()
            return

        sql = "SELECT id, name, path_media, tags FROM miniatures"
        params = []
        conditions = []

        # chips expression: tags and free text
        groups = self.parse_chip_expression()
        if groups:
            or_clauses = []
            for group in groups:
                and_clauses = []
                for term in group:
                    if term["kind"] == "tag":
                        cols = sorted(self.tag_to_columns.get(term["value"], set()))
                        candidate_cols = [c for c in ["tags"] + cols if c in self.existing_columns]
                        if not candidate_cols and "tags" in self.existing_columns:
                            candidate_cols = ["tags"]

                        sub = []
                        p = []
                        for col in candidate_cols:
                            c_sql, c_p = self.sql_match_tag_in_csv_column(col, term["value"])
                            sub.append(c_sql)
                            p.extend(c_p)
                        if sub:
                            clause = "(" + " OR ".join(sub) + ")"
                        else:
                            clause, p = ("(name LIKE ?)", [f"%{term['value']}%"])
                    elif term["kind"] == "text":
                        text_cols = ["name"]
                        for col in ("tags", "creature_type", "humanoid_type", "colors", "equipment", "roles", "role", "body_type", "sizes", "size"):
                            if col in self.existing_columns and col not in text_cols:
                                text_cols.append(col)
                        sub = []
                        p = []
                        for col in text_cols:
                            sub.append(f"({col} LIKE ?)")
                            p.append(f"%{term['value']}%")
                        clause = "(" + " OR ".join(sub) + ")"
                    else:
                        continue

                    if term.get("neg"):
                        clause = f"(NOT {clause})"

                    and_clauses.append(clause)
                    params.extend(p)

                if and_clauses:
                    or_clauses.append("(" + " AND ".join(and_clauses) + ")")

            if or_clauses:
                conditions.append("(" + " OR ".join(or_clauses) + ")")

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY name COLLATE NOCASE"

        cur = self.conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()

        # Build full results list (scrollable)
        self.results_list.blockSignals(True)
        self.results_list.clear()

        self.current_results = []
        for _id, name, path_media, tags in rows:
            self.current_results.append({"id": _id, "name": name, "path_media": path_media, "tags": tags})
            self.results_list.addItem(name)

        self.results_list.blockSignals(False)

        total = len(self.current_results)
        self.results_header.setText(f"{total} Result" if total == 1 else f"{total} Results")

        self.update_previews()

        if self.results_list.count() > 0:
            self.results_list.setCurrentRow(0)
        else:
            self.player.stop()
            self.video_widget.hide()
            self.image_label.setText("No item selected")
            self.image_label.show()


    # -------------------- Previews --------------------

    def load_random_start_set(self, n: int = 30):
        """
        Load a random initial result set.
        Guarantee at least half are humanoids if humanoid_type column exists.
        """
        cur = self.conn.cursor()

        # Helper: fetch random rows with optional where clause
        def fetch_random(where_sql="", params=(), limit=10):
            sql = "SELECT id, name, path_media, tags FROM miniatures "
            if where_sql:
                sql += f"WHERE {where_sql} "
            sql += "ORDER BY RANDOM() LIMIT ?"
            cur.execute(sql, (*params, limit))
            return cur.fetchall()

        humanoid_rows = []
        other_rows = []

        if "humanoid_type" in self.existing_columns:
            humanoid_rows = fetch_random("humanoid_type IS NOT NULL AND humanoid_type <> ''", (), limit=n)
            other_rows = fetch_random("(humanoid_type IS NULL OR humanoid_type = '')", (), limit=n)
        else:
            # fallback: no humanoid_type column -> just random
            rows = fetch_random(limit=n)
            return rows

        # Build final set with at least half humanoids
        target_h = max(n // 2, 1)
        selected = []

        random.shuffle(humanoid_rows)
        random.shuffle(other_rows)

        selected.extend(humanoid_rows[:min(target_h, len(humanoid_rows))])
        remaining = n - len(selected)
        selected.extend(other_rows[:min(remaining, len(other_rows))])

        # If we still don’t have enough, top up from humanoids again (or vice versa)
        if len(selected) < n:
            pool = humanoid_rows[target_h:] + other_rows[remaining:]
            random.shuffle(pool)
            selected.extend(pool[: (n - len(selected))])

        random.shuffle(selected)
        return selected


    def update_previews(self):
        # hide all thumbnails
        for w in self.preview_widgets:
            w.hide()
            w.clear()

        n = min(len(self.current_results), self.max_previews)

        for i in range(n):
            media_rel = self.current_results[i]["path_media"]
            media_path = (self.archive_root / media_rel).resolve()

            snap_path = None

            # 1) Prefer thumbnail: Foo_thumb.jpg / Foo_thumb.jpeg
            for ext in (".jpg", ".jpeg"):
                p = media_path.with_name(media_path.stem + "_thumb" + ext)
                if p.exists():
                    snap_path = p
                    break

            # 2) Fallback: full-res Foo.jpg / Foo.jpeg
            if snap_path is None:
                for ext in (".jpg", ".jpeg"):
                    p = media_path.with_suffix(ext)
                    if p.exists():
                        snap_path = p
                        break

            if snap_path is not None and snap_path.exists():
                pix = QPixmap(str(snap_path))
                if not pix.isNull():
                    self.preview_widgets[i].set_thumb_pixmap(pix)
                    self.preview_widgets[i].show()
                else:
                    self.preview_widgets[i].setText("Bad image")
                    self.preview_widgets[i].show()
            else:
                self.preview_widgets[i].setText("No thumbnail")
                self.preview_widgets[i].show()

        self.relayout_previews()



    def relayout_previews(self):
        # Clear layout
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(self.preview_container)

        # How many previews exist (based on search results), not visibility state
        n_total = min(len(self.current_results), self.max_previews)
        if n_total <= 0:
            return

        W = max(1, self.preview_container.width())
        H = max(1, self.preview_container.height())
        spacing = self.preview_layout.spacing()

        # Keep a stable fixed side length to avoid resize oscillation.
        side = self.thumb_side
        cols = max(1, (W + spacing) // (side + spacing))

        # Rows from height and how many we can show.
        rows_fit = max(1, (H + spacing) // (side + spacing))
        rows = max(self.preview_rows_min, min(self.preview_rows_max, rows_fit))
        max_visible = max(1, cols * rows)

        # Keep at least two thumbnails visible (if we have at least two results).
        if n_total >= 2:
            max_visible = max(2, max_visible)

        n_show = min(n_total, max_visible)

        # Apply sizing and visibility
        for i in range(n_total):
            w = self.preview_widgets[i]
            w.setFixedSize(side, side)

            if i < n_show:
                w.show()
            else:
                w.hide()

        # Add only the visible ones to layout
        r = c = 0
        for i in range(n_show):
            w = self.preview_widgets[i]
            self.preview_layout.addWidget(w, r, c)

            # Refresh pixmap for new size if your thumb widget supports it
            if hasattr(w, "_rebuild_thumb"):
                w._rebuild_thumb()

            c += 1
            if c >= cols:
                c = 0
                r += 1







    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Defer relayout until Qt has applied the new geometry
        QTimer.singleShot(0, self.relayout_previews)






    def preview_clicked(self, idx):
        if idx < len(self.current_results):
            name = self.current_results[idx]["name"]
            items = self.results_list.findItems(name, Qt.MatchFlag.MatchExactly)
            if items:
                self.results_list.setCurrentItem(items[0])

    # -------------------- Show selected --------------------
    def show_selected(self, current, previous):
        if current is None:
            return
        name = current.text()
        entry = None
        for d in self.current_results:
            if d["name"] == name:
                entry = d
                break
        if entry is None:
            return

        media_path = (self.archive_root / entry["path_media"]).resolve()
        if not media_path.exists():
            QMessageBox.warning(self, "Missing file", f"File not found:\n{media_path}")
            return

        suffix = media_path.suffix.lower()

        self.player.stop()
        self.video_widget.hide()
        self.image_label.hide()

        if suffix in [".mp4", ".mov", ".m4v"]:
            self.video_widget.show()
            self.player.setSource(QUrl.fromLocalFile(str(media_path)))
            self.player.play()

        elif suffix in [".jpg", ".jpeg", ".png"]:
            self.image_label.show()
            pix = QPixmap(str(media_path))
            self.image_label.setPixmap(pix)
        else:
            self.image_label.show()
            self.image_label.setText(f"Cannot preview this format: {suffix}")

    # -------------------- main video loop --------------------
    def save_main_duration(self, dur):
        self._main_duration = dur

    def check_loop_main(self, pos):
        if self._main_duration > 0 and pos >= self._main_duration - 150:
            self.player.setPosition(0)


    def add_chip(self, kind: str, value: str):
        value = value.strip()
        if not value:
            return

        if kind == "op":
            value_up = value.upper()
            if value_up not in ("AND", "OR", "NOT"):
                return
            value = value_up
        
        if kind == "text":
            # avoid duplicate text chips (case-insensitive)
            if any(t["kind"] == "text" and t["value"].lower() == value.lower() for t in self.chips):
                self.run_search()
                return


        # prevent duplicate operator spam like AND AND AND
        if kind == "op" and self.chips and self.chips[-1]["kind"] == "op":
            self.chips[-1]["value"] = value
            self.search_bar.setChips(self.chips)
            self.search_bar.setFocusToEdit()
            self.run_search()
            return


        # avoid duplicate tag chips
        if kind == "tag":
            if any(t["kind"] == "tag" and t["value"].lower() == value.lower() for t in self.chips):
                self.highlight_tag_in_lists(value)
                self.run_search()
                return

        self.chips.append({"kind": kind, "value": value})

        self.search_bar.setChips(self.chips)
        self.search_bar.setFocusToEdit()

        if kind == "tag":
            self.highlight_tag_in_lists(value)

        self.run_search()


    def remove_chip_at(self, idx: int):
        if idx < 0 or idx >= len(self.chips):
            return
        removed = self.chips.pop(idx)


        self.search_bar.setChips(self.chips)
        self.search_bar.setFocusToEdit()

        # if tag chip removed, also unselect it in lists (best effort)
        if removed["kind"] == "tag":
            self.unhighlight_tag_in_lists(removed["value"])

        self.run_search()


    def highlight_tag_in_lists(self, tag: str):
        # highlight the tag in whichever list(s) contain it
        for col, lw in self.tag_lists.items():
            matches = lw.findItems(tag, Qt.MatchFlag.MatchFixedString)
            if matches:
                # MultiSelection list: select item without clearing others
                matches[0].setSelected(True)


    def unhighlight_tag_in_lists(self, tag: str):
        for col, lw in self.tag_lists.items():
            matches = lw.findItems(tag, Qt.MatchFlag.MatchFixedString)
            if matches:
                matches[0].setSelected(False)

    def on_search_enter(self):
        text = self.search_bar.text().strip()
        if not text:
            return
        self.search_bar.clearText()
        self.commit_token_from_space(text)


    def parse_chip_expression(self):
        """
        Returns list of OR groups, each group is a list of term dicts (ANDed).
        Term dict format: {"kind": "tag"|"text", "value": "...", "neg": bool}
        Operators supported: AND, OR, NOT (NOT applies to the next term only).
        """
        groups: list[list[dict]] = [[]]
        pending_op = "AND"
        negate_next = False

        for tok in self.chips:
            if tok["kind"] == "op":
                op = tok["value"].upper()
                if op == "NOT":
                    negate_next = True
                else:
                    pending_op = op  # AND / OR
                continue

            term = {"kind": tok["kind"], "value": tok["value"], "neg": negate_next}
            negate_next = False

            if pending_op == "OR":
                groups.append([term])
            else:
                groups[-1].append(term)

            pending_op = "AND"

        return [g for g in groups if g]




    def sql_match_tag_in_csv_column(self, col: str, tag: str):
        # exact match in comma-separated list: col = tag OR startswith OR endswith OR contains
        return f"""(
            {col} = ?
            OR {col} LIKE ?
            OR {col} LIKE ?
            OR {col} LIKE ?
        )""", [tag, f"{tag},%", f"%,{tag}", f"%,{tag},%"]
    
    def remove_last_chip(self):
        if not self.chips:
            return
        self.remove_chip_at(len(self.chips) - 1)

    def load_update_config(self):
        candidates = []
        script_dir = Path(__file__).resolve().parent
        candidates.append(script_dir / "config" / "archive_update_config.json")
        candidates.append(script_dir / "archive_update_config.json")
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(Path(meipass) / "config" / "archive_update_config.json")
            candidates.append(Path(meipass) / "archive_update_config.json")
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / "config" / "archive_update_config.json")
            candidates.append(exe_dir / "archive_update_config.json")
            # macOS .app => .../Contents/MacOS ; config may live in Contents/Resources
            candidates.append(exe_dir.parent / "Resources" / "config" / "archive_update_config.json")
            candidates.append(exe_dir.parent / "Resources" / "archive_update_config.json")

        for cfg_path in candidates:
            if not cfg_path.exists():
                continue
            try:
                return json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                continue
        return None

    def load_categories_config(self):
        candidates = []
        candidates.append(Path(__file__).resolve().parent / "categories.json")
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(Path(meipass) / "categories.json")
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / "categories.json")
            candidates.append(exe_dir.parent / "Resources" / "categories.json")

        for cfg_path in candidates:
            if not cfg_path.exists():
                continue
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
        return {}

    def get_category_values_from_config(self, db_field: str):
        cfg = self.categories_cfg if isinstance(self.categories_cfg, dict) else {}
        keys = [db_field]
        if db_field == "role":
            keys.append("roles")
        if db_field == "size":
            keys.append("sizes")
        for k in keys:
            vals = cfg.get(k, [])
            if isinstance(vals, list) and vals:
                out = [str(v).strip() for v in vals if str(v).strip()]
                if out:
                    return out
        return []

    def bootstrap_archive_if_needed(self):
        if self.splash:
            self.splash.showMessage(
                "Initializing archive...",
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                Qt.GlobalColor.white,
            )
            QApplication.processEvents()

        self.archive_root.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            return True, "Archive already initialized."

        if not self.update_cfg:
            return False, (
                "No update configuration found. The packaged app needs "
                "archive_update_config.json with a manifest_url."
            )

        manifest_url = str(self.update_cfg.get("manifest_url", "")).strip()
        if not manifest_url:
            return False, "manifest_url missing in archive_update_config.json."

        timeout = int(self.update_cfg.get("request_timeout_seconds", 6))
        result = check_updates(self.archive_root, manifest_url, timeout_seconds=timeout)
        if not result.get("ok"):
            if result.get("offline"):
                return False, "Could not reach update server. Connect to internet and retry."
            return False, f"Manifest check failed: {result.get('error', 'unknown error')}"

        pending = self.filter_pending_downloads(result["pending"])
        if pending["download_count"] == 0 and pending["delete_count"] == 0:
            return False, (
                "Manifest reports no downloadable content, but local database is missing."
            )

        # First launch defaults to a full archive sync (subject to file filters in config).
        bootstrap_full = bool(self.update_cfg.get("bootstrap_full_archive", True))
        if not bootstrap_full:
            db_items = [
                row for row in pending.get("to_download", [])
                if str(row.get("path", "")).replace("\\", "/").lower() == "miniatures.db"
            ]
            if not db_items:
                return False, (
                    "miniatures.db is not available in manifest files for first-run bootstrap."
                )
            pending = {
                "to_download": db_items,
                "to_delete": [],
                "download_count": len(db_items),
                "delete_count": 0,
            }

        download_timeout = int(self.update_cfg.get("download_timeout_seconds", 20))
        sync_result = self.run_sync_with_progress(
            manifest=result["manifest"],
            pending=pending,
            remove_deleted=False,
            timeout_seconds=download_timeout,
            title="Initializing archive",
            label_prefix="Downloading",
            allow_mismatch_paths={"miniatures.db"},
            use_dialog=False,
            splash_message_prefix="Initializing archive",
        )

        if not self.db_path.exists():
            err_preview = "\n".join(sync_result.get("errors", [])[:4])
            return False, (
                "Initial archive download did not produce miniatures.db.\n"
                f"Errors:\n{err_preview}"
            )
        return True, "Archive initialized successfully."

    def startup_auto_update_with_splash(self):
        if not self.splash:
            return
        if not self.update_cfg:
            return
        if not bool(self.update_cfg.get("check_on_startup", True)):
            return

        manifest_url = str(self.update_cfg.get("manifest_url", "")).strip()
        if not manifest_url:
            return

        self.splash.showMessage(
            "Checking for updates...",
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
            Qt.GlobalColor.white,
        )
        QApplication.processEvents()

        timeout = int(self.update_cfg.get("request_timeout_seconds", 6))
        result = check_updates(self.archive_root, manifest_url, timeout_seconds=timeout)
        if not result.get("ok"):
            return

        pending = self.filter_pending_downloads(result["pending"])
        remove_deleted = bool(self.update_cfg.get("remove_deleted", False))
        has_downloads = pending["download_count"] > 0
        has_deletions = remove_deleted and pending["delete_count"] > 0
        if not has_downloads and not has_deletions:
            return

        download_timeout = int(self.update_cfg.get("download_timeout_seconds", 20))
        sync_result = self.run_sync_with_progress(
            manifest=result["manifest"],
            pending=pending,
            remove_deleted=remove_deleted,
            timeout_seconds=download_timeout,
            title="Updating archive",
            label_prefix="Downloading",
            allow_mismatch_paths={"miniatures.db"},
            allow_cancel=True,
            use_dialog=True,
            splash_message_prefix="Updating archive",
        )

        if sync_result.get("cancelled"):
            return

        db_reloaded = self.reload_db_safely()
        if db_reloaded:
            self.prune_missing_files()
            self.existing_columns = self.get_existing_columns()

    def filter_pending_downloads(self, pending: dict) -> dict:
        download_fullres = bool(self.update_cfg.get("download_fullres_images", False)) if self.update_cfg else False

        kept = []
        for row in pending.get("to_download", []):
            rel = str(row.get("path", "")).replace("\\", "/")
            rel_l = rel.lower()
            name_l = rel_l.rsplit("/", 1)[-1]

            if rel_l == "miniatures.db":
                kept.append(row)
                continue
            if rel_l.endswith(".mp4"):
                kept.append(row)
                continue
            if (
                name_l.endswith("_thumb.jpg")
                or name_l.endswith("_thumb.jpeg")
                or name_l.endswith("_thumb.png")
                or name_l.endswith("_thumb.webp")
            ):
                kept.append(row)
                continue
            if download_fullres and (
                rel_l.endswith(".jpg") or rel_l.endswith(".jpeg") or rel_l.endswith(".png") or rel_l.endswith(".webp")
            ):
                kept.append(row)
                continue

        return {
            "to_download": kept,
            "to_delete": pending.get("to_delete", []),
            "download_count": len(kept),
            "delete_count": len(pending.get("to_delete", [])),
        }

    def count_pending_miniatures(self, rows: list[dict]) -> int:
        keys = set()
        for row in rows:
            rel = str(row.get("path", "")).replace("\\", "/")
            rel_l = rel.lower()
            if rel_l == "miniatures.db":
                continue

            parts = rel.rsplit("/", 1)
            parent = parts[0] if len(parts) == 2 else ""
            name = parts[-1]
            stem = name.rsplit(".", 1)[0]
            if stem.endswith("_thumb"):
                stem = stem[:-6]
            key = f"{parent}/{stem}" if parent else stem
            keys.add(key.lower())
        return len(keys)

    def check_for_content_updates(self):
        self.app_update_btn.setVisible(False)
        self.app_update_btn.setEnabled(False)
        self.app_update_url = ""

        if not self.update_cfg:
            self.update_status_label.setText("Offline mode (no update source configured)")
            self.download_updates_btn.setEnabled(False)
            return

        manifest_url = self.update_cfg.get("manifest_url", "").strip()
        if not manifest_url:
            self.update_status_label.setText("Offline mode (manifest_url missing)")
            self.download_updates_btn.setEnabled(False)
            return

        timeout = int(self.update_cfg.get("request_timeout_seconds", 6))
        self.update_status_label.setText("Checking for archive updates...")
        result = check_updates(self.archive_root, manifest_url, timeout_seconds=timeout)
        self.last_update_check = result

        if not result.get("ok"):
            if result.get("offline"):
                self.update_status_label.setText("Offline (unable to reach update server)")
            else:
                self.update_status_label.setText("Update check failed")
            self.download_updates_btn.setEnabled(False)
            return

        pending = self.filter_pending_downloads(result["pending"])
        result["pending_filtered"] = pending
        app_info = result.get("manifest", {}).get("app", {})
        if isinstance(app_info, dict):
            remote_ver = str(app_info.get("latest_version", "")).strip()
            download_url = str(app_info.get("download_url", "")).strip()
            if not download_url:
                download_url = str(self.update_cfg.get("app_release_url", "")).strip()

            if remote_ver and is_remote_version_newer(APP_VERSION, remote_ver):
                self.app_update_url = download_url
                self.app_update_btn.setVisible(True)
                self.app_update_btn.setEnabled(bool(download_url))
                self.app_update_btn.setText(f"Download app update ({remote_ver})")

        remove_deleted_cfg = bool(self.update_cfg.get("remove_deleted", False)) if self.update_cfg else False
        has_downloads = pending["download_count"] > 0
        has_deletions = remove_deleted_cfg and pending["delete_count"] > 0

        if not has_downloads and not has_deletions:
            self.update_status_label.setText("Up to date")
            self.download_updates_btn.setEnabled(False)
            return

        mini_count = self.count_pending_miniatures(pending["to_download"])
        if mini_count > 0:
            msg = f"Update available: {mini_count} miniatures"
        else:
            msg = "Update available: metadata refresh"
        if has_deletions:
            msg += f", {pending['delete_count']} removals"
        self.update_status_label.setText(msg)
        self.download_updates_btn.setEnabled(True)

    def download_latest_archive(self):
        # Always refresh manifest right before download so we don't use stale state.
        self.check_for_content_updates()
        if not self.last_update_check or not self.last_update_check.get("ok"):
            QMessageBox.warning(self, "Update", "Could not fetch update manifest.")
            return

        pending = self.last_update_check.get("pending_filtered", self.last_update_check["pending"])
        remove_deleted = bool(self.update_cfg.get("remove_deleted", False)) if self.update_cfg else False

        has_downloads = pending["download_count"] > 0
        has_deletions = remove_deleted and pending["delete_count"] > 0
        if not has_downloads and not has_deletions:
            self.update_status_label.setText("Up to date")
            self.download_updates_btn.setEnabled(False)
            return

        timeout = int(self.update_cfg.get("download_timeout_seconds", 20)) if self.update_cfg else 20

        self.download_updates_btn.setEnabled(False)
        self.update_status_label.setText("Downloading archive updates...")
        sync_result = self.run_sync_with_progress(
            manifest=self.last_update_check["manifest"],
            pending=pending,
            remove_deleted=remove_deleted,
            timeout_seconds=timeout,
            title="Downloading latest archive",
            label_prefix="Downloading",
            allow_mismatch_paths={"miniatures.db"},
        )

        if not sync_result["ok"]:
            preview = "\n".join(sync_result["errors"][:5])
            QMessageBox.warning(self, "Update errors", f"Some files failed:\n{preview}")

        # Re-check and refresh visible data.
        db_reloaded = self.reload_db_safely()
        if db_reloaded:
            self.prune_missing_files()
            self.existing_columns = self.get_existing_columns()
            self.run_search()
        self.check_for_content_updates()

        msg = f"Downloaded: {sync_result['downloaded']}\nRemoved: {sync_result['removed']}"
        warns = sync_result.get("warnings", [])
        if warns:
            msg += "\n\nWarnings:\n" + "\n".join(warns[:3])
        if not db_reloaded:
            msg += "\n\nDatabase reload skipped (downloaded DB was invalid)."
        QMessageBox.information(self, "Archive updated", msg)

    def open_app_update_page(self):
        url = self.app_update_url.strip()
        if not url:
            QMessageBox.information(self, "App update", "No app update URL available.")
            return
        webbrowser.open(url)

    def run_sync_with_progress(
        self,
        manifest,
        pending,
        remove_deleted,
        timeout_seconds,
        title,
        label_prefix,
        allow_mismatch_paths=None,
        allow_cancel=False,
        use_dialog=True,
        splash_message_prefix="",
    ):
        rows = pending.get("to_download", [])
        total = max(1, len(rows))
        dlg = None
        if use_dialog:
            dlg = QProgressDialog(f"{label_prefix}...", "Skip" if allow_cancel else "", 0, total, self)
            dlg.setWindowTitle(title)
            dlg.setMinimumDuration(0)
            dlg.setAutoClose(False)
            dlg.setAutoReset(False)
            if not allow_cancel:
                dlg.setCancelButton(None)
            dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
            dlg.setValue(0)
            dlg.show()
            QApplication.processEvents()

        def on_progress(info: dict):
            idx = int(info.get("index", 0))
            path = str(info.get("path", ""))
            shown = path if len(path) <= 70 else ("..." + path[-67:])
            if dlg is not None:
                dlg.setLabelText(f"{label_prefix} ({idx}/{total})\n{shown}")
                dlg.setValue(min(idx, total))
            if self.splash and splash_message_prefix:
                self.splash.showMessage(
                    f"{splash_message_prefix}... ({idx}/{total})",
                    Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                    Qt.GlobalColor.white,
                )
            QApplication.processEvents()

        def should_cancel():
            return bool(dlg and allow_cancel and dlg.wasCanceled())

        try:
            return sync_updates(
                self.archive_root,
                manifest=manifest,
                pending=pending,
                remove_deleted=remove_deleted,
                timeout_seconds=timeout_seconds,
                progress_callback=on_progress,
                allow_mismatch_paths=allow_mismatch_paths,
                should_cancel=should_cancel,
            )
        finally:
            if dlg is not None:
                dlg.setValue(total)
                dlg.close()

    def reload_db_safely(self) -> bool:
        old_conn = self.conn
        try:
            new_conn = sqlite3.connect(self.db_path)
            cur = new_conn.cursor()
            row = cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='miniatures'"
            ).fetchone()
            if not row:
                raise RuntimeError("miniatures table missing")
            self.conn = new_conn
            old_conn.close()
            return True
        except Exception:
            try:
                new_conn.close()  # type: ignore[name-defined]
            except Exception:
                pass
            self.conn = old_conn
            return False



    



def main():
    if len(sys.argv) > 1:
        archive_root = Path(sys.argv[1]).expanduser().resolve()
    else:
        archive_root = get_default_archive_root()

    app = QApplication(sys.argv)
    app.setStyleSheet("""
    QListWidget::item:selected {
        color: palette(highlighted-text);
        background: palette(highlight);
    }
    QListWidget::item:selected:!active {
        color: palette(highlighted-text);
        background: palette(highlight);
    }
    """)

    def find_splash_image() -> Path | None:
        name_candidates = [
            "Splash Screen.png",
            "splash.png",
            "splash_screen.png",
            "Splash.png",
        ]
        path_candidates = []
        script_dir = Path(__file__).resolve().parent
        for n in name_candidates:
            path_candidates.append(script_dir / "assets" / "splash" / n)
            path_candidates.append(script_dir / n)
            path_candidates.append(script_dir.parent / n)

        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            # inside .app resources
            for n in name_candidates:
                path_candidates.append(exe_dir.parent / "Resources" / "assets" / "splash" / n)
                path_candidates.append(exe_dir.parent / "Resources" / n)
            # alongside .app in dist/
            try:
                dist_dir = exe_dir.parent.parent.parent
                for n in name_candidates:
                    path_candidates.append(dist_dir / n)
            except Exception:
                pass

        for p in path_candidates:
            if p.exists():
                return p
        return None

    splash = None
    start_ts = time.monotonic()
    target_screen = QGuiApplication.screenAt(QCursor.pos()) or app.primaryScreen()
    splash_path = find_splash_image()
    if splash_path is not None:
        pix = QPixmap(str(splash_path))
        if not pix.isNull():
            pix = pix.scaledToWidth(900, Qt.TransformationMode.SmoothTransformation)
            splash = LockedSplashScreen(pix)
            splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            if target_screen is not None:
                g = target_screen.availableGeometry()
                x = g.x() + (g.width() - pix.width()) // 2
                y = g.y() + (g.height() - pix.height()) // 2
                splash.move(x, y)
            splash.show()
            splash.showMessage(
                "Starting Ragnar's Miniature Archive...",
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                Qt.GlobalColor.white,
            )
            app.processEvents()

    win = MiniViewer(archive_root, splash=splash)
    if target_screen is not None:
        win.setGeometry(target_screen.availableGeometry())
    if splash is not None:
        # keep splash on-screen for at least 3 seconds
        while time.monotonic() - start_ts < 3.0:
            app.processEvents()
            time.sleep(0.02)
    win.showMaximized()
    if splash is not None:
        splash.finish(win)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
