#!/usr/bin/env python3
"""
Create a padded icon so the app icon appears at a standard visual size.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image


SOURCE_ICON = Path("00_Apps/app_icon.png")
OUTPUT_ICON = Path("00_Apps/app_icon_packaged.png")
CANVAS_SIZE = 1024
CONTENT_SCALE = 0.82


def main() -> int:
    if not SOURCE_ICON.exists():
        raise FileNotFoundError(f"Icon not found: {SOURCE_ICON}")

    src = Image.open(SOURCE_ICON).convert("RGBA")
    max_side = max(src.size)
    fit_size = int(CANVAS_SIZE * CONTENT_SCALE)
    scale = fit_size / max_side
    resized = src.resize(
        (int(src.width * scale), int(src.height * scale)),
        Image.Resampling.LANCZOS,
    )

    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    x = (CANVAS_SIZE - resized.width) // 2
    y = (CANVAS_SIZE - resized.height) // 2
    canvas.paste(resized, (x, y), resized)
    canvas.save(OUTPUT_ICON)
    print(f"Wrote {OUTPUT_ICON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
