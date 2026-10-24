"""Оценка скачанных описей ГАСО: страницы, текстовый слой, образец первой страницы.

Зачем: до всякого распознавания определить цену работы. Три исхода на опись —
  (а) есть текстовый слой → распознавать НЕ НУЖНО, парсим как текст, 0 токенов;
  (б) слоя нет, машинопись → focr локально, 0 токенов;
  (в) слоя нет, рукопись → Claude Vision через API (Batch, -50%).

Запуск:
    python -B scripts_gaso/assess_opisi_pdfs.py "C:\\arch\\output\\gaso_opisi_20261013"
    python -B scripts_gaso/assess_opisi_pdfs.py <папка> --samples <папка для PNG>

Образцы первых страниц нужны, чтобы глазами отличить машинопись от скорописи.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))
try:
    from common import fix_stdout
except ImportError:                                     # движок живёт и без общего модуля
    def fix_stdout() -> None:
        sys.stdout.reconfigure(encoding="utf-8")

PROBE_PAGES = 3          # сколько страниц проверять на текстовый слой
MIN_CHARS = 40           # столько символов на странице считаем слоем, а не мусором


def assess(pdf: Path, samples: Path | None) -> dict:
    import fitz                                          # PyMuPDF

    rec: dict = {"file": pdf.name, "mb": round(pdf.stat().st_size / 1e6, 1)}
    try:
        doc = fitz.open(pdf)
    except Exception as exc:                             # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
        return rec
    rec["pages"] = doc.page_count

    chars = 0
    for i in range(min(PROBE_PAGES, doc.page_count)):
        chars += len(doc.load_page(i).get_text("text").strip())
    rec["chars_probe"] = chars
    rec["text_layer"] = chars >= MIN_CHARS * min(PROBE_PAGES, doc.page_count)

    if samples and doc.page_count:
        samples.mkdir(parents=True, exist_ok=True)
        page = doc.load_page(0)
        png = samples / f"{pdf.stem}_p1.png"
        page.get_pixmap(dpi=110).save(png)
        rec["sample"] = png.name
    doc.close()
    return rec


def main() -> int:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="папка со скачанными PDF описей")
    ap.add_argument("--samples", default="", help="куда положить PNG первых страниц")
    args = ap.parse_args()

    folder = Path(args.folder)
    samples = Path(args.samples) if args.samples else folder / "samples_p1"
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"PDF в {folder} не найдено")
        return 1

    rows = [assess(p, samples) for p in pdfs]
    print(f"{'файл':<22} {'МБ':>6} {'стр.':>5} {'симв.':>7}  текстовый слой")
    for r in rows:
        if "error" in r:
            print(f"{r['file']:<22} {r['mb']:>6} {'—':>5} {'—':>7}  ОШИБКА {r['error']}")
            continue
        print(f"{r['file']:<22} {r['mb']:>6} {r['pages']:>5} {r['chars_probe']:>7}  "
              f"{'ЕСТЬ — распознавание не нужно' if r['text_layer'] else 'нет — нужен OCR/Vision'}")

    ok = [r for r in rows if "error" not in r]
    total = sum(r["pages"] for r in ok)
    with_layer = [r for r in ok if r["text_layer"]]
    need_ocr = [r for r in ok if not r["text_layer"]]
    print(f"\nописей {len(ok)}, страниц всего {total}")
    print(f"  с текстовым слоем: {len(with_layer)} описей, {sum(r['pages'] for r in with_layer)} стр. — 0 токенов")
    print(f"  нужен OCR/Vision:  {len(need_ocr)} описей, {sum(r['pages'] for r in need_ocr)} стр.")
    print(f"образцы первых страниц: {samples}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
