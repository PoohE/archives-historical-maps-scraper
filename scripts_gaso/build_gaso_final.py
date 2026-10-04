# -*- coding: utf-8 -*-
"""Сборка итогового набора по описи ГАСО ф. 259 оп. 1 и его проверка.

Вход : output/gaso_f259_opis1_vision_20261004/records.jsonl (распознано Claude Vision)
Выход: там же — records.csv, REPORT.json

Проверки, которые документ позволяет сделать сам:
  — сквозная нумерация 1..266 без пропусков и дублей;
  — наличие литерных дел (160а, 210а, 126а), заявленных заверительными надписями;
  — итог по заверительной надписи 16.12.1998: «числится 269 дел с № 1 по № 266,
    в том числе литерные 160а, 210а, 126а».
"""
import csv
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

OUT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output\gaso_f259_opis1_vision_20261004")
JSONL = OUT / "records.jsonl"

COLS = ["source", "archive", "fund", "opis", "n", "delo", "uezd", "svyazka",
        "title", "year_from", "year_to", "year_approx", "sheets", "sheets_num",
        "note", "page", "needs_human", "needs_human_reason"]

# разделы, которые по правилам отбора не являются картографическим профилем
NON_MAP = {"Чертежи и планы зданий"}
CITY_SUBJECT = re.compile(r"план(?:ы)?\s+город|план\s+г\.|усадеб.*г\.\s*Смоленск|владени[йя].*части\s+г\.", re.I)


def main() -> None:
    rows = [json.loads(ln) for ln in JSONL.read_text(encoding="utf-8").splitlines() if ln.strip()]

    out = []
    for r in rows:
        n = str(r.get("n", ""))
        sheets = str(r.get("sheets", ""))
        m = re.match(r"(\d+)", sheets)
        reasons = []
        if r.get("uezd") in NON_MAP:
            reasons.append("non_cartographic_section")
        if CITY_SUBJECT.search(r.get("title", "")):
            reasons.append("city_subject_check_1_2")
        if not r.get("year_from"):
            reasons.append("no_year")
        if "приблизительная" in str(r.get("note", "")):
            reasons.append("year_approximate")
        out.append({
            "source": "gaso", "archive": "ГАСО", "fund": "259", "opis": "1",
            "n": n, "delo": r.get("delo", ""), "uezd": r.get("uezd", ""),
            "svyazka": r.get("svyazka", ""), "title": r.get("title", ""),
            "year_from": r.get("year_from", ""), "year_to": r.get("year_to", ""),
            "year_approx": "true" if "приблизительная" in str(r.get("note", "")) else "false",
            "sheets": sheets, "sheets_num": m.group(1) if m else "",
            "note": r.get("note", ""), "page": r.get("page", ""),
            "needs_human": "true" if reasons else "false",
            "needs_human_reason": "; ".join(reasons),
        })

    with (OUT / "records.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    nums = [r["n"] for r in out]
    plain = {int(x) for x in nums if x.isdigit()}
    lit = sorted(x for x in nums if not x.isdigit())
    missing = [i for i in range(1, 267) if i not in plain]
    dups = [x for x, c in Counter(nums).items() if c > 1]
    declared_lit = ["160а", "210а", "126а"]
    lit_missing = [x for x in declared_lit if x not in lit]
    sheets_total = sum(int(r["sheets_num"]) for r in out if r["sheets_num"])

    rep = {
        "source": "gaso", "archive": "ГАСО", "fund": "259", "opis": "1",
        "opis_title": "Коллекция планов, чертежей земель и лесов Смоленской губернии",
        "chronology": "1750–1915",
        "recognized_by": "Claude Vision (Opus 5), сетки 2×2 при 165 dpi",
        "source_pdf": "input_gaso/document.pdf (87 страниц, текстового слоя нет)",
        "records": len(out),
        "numbers_plain": len(plain), "numbers_literal": lit,
        "missing_numbers": missing,
        "duplicate_numbers": dups,
        "declared_by_archive": "269 дел с № 1 по № 266, в том числе литерные 160а, 210а, 126а (надпись 16.12.1998)",
        "literal_missing_from_scan": lit_missing,
        "sheets_total": sheets_total,
        "by_uezd": dict(Counter(r["uezd"] for r in out)),
        "needs_human": sum(1 for r in out if r["needs_human"] == "true"),
        "needs_human_reasons": dict(Counter(
            x for r in out for x in r["needs_human_reason"].split("; ") if x)),
        "year_approx": sum(1 for r in out if r["year_approx"] == "true"),
        "no_year": sum(1 for r in out if not r["year_from"]),
        "ready_for_import": False,
    }
    (OUT / "REPORT.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    for k, v in rep.items():
        print(f"{k}: {v}")
    print(f"\nвыход: {OUT}")


if __name__ == "__main__":
    main()
