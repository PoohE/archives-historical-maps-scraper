"""Разбор описей ГАСО, у которых в PDF есть текстовый слой (распознавание не нужно).

Это современные выгрузки архива: таблица Word с теми же колонками, что у машинописных
(№№пп, индекс, заголовок, крайние даты, листов, примечание). Берём таблицы PyMuPDF
`page.find_tables()`, поля определяем по содержимому (как в `parse_focr_opisi.py` —
из-за объединённых ячеек привязка к номеру колонки ненадёжна).

Контроль тот же: «В данную опись внесено N дел с № 1 по № M» против разобранного.

Запуск:
    python -B scripts_gaso/parse_textlayer_opisi.py C:\\arch\\output\\gaso_opisi_20261013 \
        --out C:\\arch\\output\\gaso_textlayer_parsed_20261013 \
        --files 223_1,666_1,828_1,88_1,890_1,998_1,1063_1,1104_1,1105_1,1107_1,1173_1,1191_1,1257_1
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_focr_opisi import (  # noqa: E402
    DATEISH,
    FIELDS,
    N_DELO,
    NUMERIC,
    OBJ,
    YEAR_ROW,
    read_control,
    sign_of,
    split_dates,
    unglue,
)


def parse_pdf(pdf: Path) -> tuple[list[dict], dict]:
    import fitz

    stem = pdf.stem
    fund, _, opis = stem.partition("_")
    doc = fitz.open(pdf)
    rows: list[dict] = []
    year = None
    full_text: list[str] = []

    for pno in range(doc.page_count):
        page = doc.load_page(pno)
        full_text.append(page.get_text("text"))
        for tab in page.find_tables().tables:
            for raw_row in tab.extract():
                cells = [unglue(str(c)) if c else "" for c in raw_row]
                if not cells:
                    continue
                filled = [c for c in cells if c]
                if len(filled) == 1 and YEAR_ROW.match(filled[0]):
                    year = YEAR_ROW.match(filled[0]).group(1)
                    continue
                if not N_DELO.match(cells[0]):
                    continue
                rest = cells[1:]
                title = max(rest, key=len) if rest else ""
                if len(title) < 8:
                    continue
                others = [c for c in rest if c is not title and c]
                dates = next((c for c in others if DATEISH.search(c)), "")
                listov = next((c for c in others if NUMERIC.match(c)), "")
                idx = next((c for c in others if c not in (dates, listov)
                            and not re.match(r"^Кор", c)), "")
                prim = next((c for c in others if re.match(r"^Кор", c)), "")
                d1, d2 = split_dates(dates)
                rows.append({
                    "fund": fund, "opis": opis,
                    "n_delo": N_DELO.match(cells[0]).group(1),
                    "index_dela": idx or None,
                    "zagolovok": title,
                    "god_razdel": year,
                    "data_nachato": d1, "data_okoncheno": d2,
                    "listov": listov or None,
                    "obyekt": "; ".join(dict.fromkeys(OBJ.findall(title))) or None,
                    "kartograficheskiy_priznak": sign_of(title),
                    "primechanie": prim or None,
                    "source_file": pdf.name,
                    "flags": None,
                })
    doc.close()

    return rows, read_control("\n".join(full_text))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", required=True)
    ap.add_argument("--files", required=True)
    args = ap.parse_args()

    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict] = []
    print(f"{'опись':<10} {'разобрано':>9} {'заявлено':>9} {'макс №':>7}  контроль")
    for stem in [x for x in args.files.split(",") if x.strip()]:
        pdf = src / f"{stem}.pdf"
        if not pdf.exists():
            print(f"{stem:<10} НЕТ ФАЙЛА")
            continue
        rows, ctrl = parse_pdf(pdf)
        all_rows.extend(rows)
        nums = [int(r["n_delo"]) for r in rows] or [0]
        decl = ctrl.get("declared")
        if decl is None:
            verdict = "⚠ контрольная запись не найдена"
        elif decl == len(rows) and max(nums) == ctrl["to"]:
            verdict = "✓ сходится"
        else:
            verdict = f"⚠ расхождение (в описи № 1–{ctrl.get('to')})"
        print(f"{stem:<10} {len(rows):>9} {decl if decl is not None else '—':>9} "
              f"{max(nums):>7}  {verdict}")

    jsonl = out / "gaso_textlayer_records.jsonl"
    with jsonl.open("w", encoding="utf-8") as fh:
        for r in all_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    csv_f = out / "gaso_textlayer_records.csv"
    with csv_f.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(all_rows)

    carto = sum(1 for r in all_rows if r["kartograficheskiy_priznak"] != "нет")
    print(f"\nвсего записей: {len(all_rows)}; с картографическим признаком: {carto}"
          + (f" ({carto / len(all_rows) * 100:.0f}%)" if all_rows else ""))
    print(f"JSONL: {jsonl}\nCSV:   {csv_f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
