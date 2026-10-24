"""Контактный лист описей: по одной серединной странице с каждой, плиткой в один файл.

Зачем: отличить машинопись от рукописи по всем описям разом, за один просмотр, а не за
N отдельных картинок. Тип письма виден и в миниатюре, а цена просмотра — одна картинка.

Запуск:
    python -B scripts_gaso/make_contact_sheet.py "C:\\arch\\output\\gaso_opisi_20261013"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

TILE_W, TILE_H = 460, 620
COLS = 5
LABEL_H = 26


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out", default="")
    ap.add_argument("--min-pages", type=int, default=0,
                    help="брать только описи длиннее N страниц (0 — все)")
    args = ap.parse_args()

    folder = Path(args.folder)
    out = Path(args.out) if args.out else folder / "contact_sheet.jpg"

    tiles = []
    for pdf in sorted(folder.glob("*.pdf")):
        doc = fitz.open(pdf)
        if doc.page_count <= args.min_pages:
            doc.close()
            continue
        idx = doc.page_count // 2
        pix = doc.load_page(idx).get_pixmap(dpi=100)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        img.thumbnail((TILE_W, TILE_H - LABEL_H))
        tiles.append((f"{pdf.stem}  с.{idx + 1}/{doc.page_count}", img))
        doc.close()

    if not tiles:
        print("нечего собирать")
        return 1

    rows = (len(tiles) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * TILE_W, rows * TILE_H), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (label, img) in enumerate(tiles):
        x, y = (i % COLS) * TILE_W, (i // COLS) * TILE_H
        draw.text((x + 6, y + 6), label, fill="black")
        sheet.paste(img, (x + 6, y + LABEL_H))
        draw.rectangle([x, y, x + TILE_W - 2, y + TILE_H - 2], outline="gray")

    sheet.save(out, format="JPEG", quality=62, optimize=True)
    print(f"{out}: {len(tiles)} плиток, {sheet.width}×{sheet.height}, "
          f"{out.stat().st_size // 1024} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
