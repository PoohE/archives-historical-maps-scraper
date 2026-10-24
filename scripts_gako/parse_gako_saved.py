"""Разбор страниц ГАКО, сохранённых ПОЛЬЗОВАТЕЛЕМ вручную (robots запрещает нам обход).

Страницы бывают двух видов, скрипт определяет сам:
  * `/gako/type/stocks` — список фондов (номер + название + сколько описей);
  * `/gako/search?...`  — выдача поиска (описи, внутри раскрытые дела).

Запуск:
    python -B scripts_gako/parse_gako_saved.py C:\\arch\\gako_in --out C:\\arch\\output\\gako_parsed_20261013
"""
from __future__ import annotations

import argparse
import csv
import html as H
import json
import re
import sys
from pathlib import Path

TAG = re.compile(r"<[^>]+>")
COUNT = re.compile(r"Результаты поиска:\s*([\d\-–]+)\s*из\s*(\d+)")
QUERY = re.compile(r"Найдено по запросу:\s*([^<]{0,200})")
# «Ф. Ф-62 Оп. 1 Д. 2051 Дело об отводе…» и «Ф. Ф-1 КАЛУЖСКИЙ ГОРОДОВОЙ СИРОТСКИЙ СУД»
FUND_TITLE = re.compile(r"Ф\.\s*([А-ЯЁ]?-?\d+[а-я]?)\s+([^<]{3,400})")
DELO = re.compile(r"Ф\.\s*([А-ЯЁ]?-?\d+[а-я]?)\s*Оп\.\s*([\w\-/]+)\s*Д\.\s*(\d+[а-я]?)\s*([^<]{0,400})")
OPIS = re.compile(r"Ф\.\s*([А-ЯЁ]?-?\d+[а-я]?)\s*Оп\.\s*([\w\-/]+)\s*(Опись[^<]{0,200})")
OPIS_COUNT = re.compile(r"Описи\s*\((\d+)\)")


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", H.unescape(TAG.sub(" ", s))).strip()


def page_kind(raw: str) -> str:
    if "type/stocks" in raw and "Найдено по запросу" not in raw:
        return "stocks"
    return "search"


def parse_stocks(raw: str) -> list[dict]:
    """Список фондов: берём заголовки панелей вида «Ф. Ф-1 НАЗВАНИЕ»."""
    rows, seen = [], set()
    for m in FUND_TITLE.finditer(raw):
        fund, title = m.group(1).strip(), clean(m.group(2))
        if not title or title.lower().startswith(("оп.", "д.")):
            continue
        if len(title) < 4:
            continue
        key = (fund, title[:60])
        if key in seen:
            continue
        seen.add(key)
        rows.append({"fund": fund, "title": title})
    return rows


def parse_search(raw: str) -> tuple[list[dict], list[dict]]:
    opisi, dela, seen_d = [], [], set()
    for m in OPIS.finditer(raw):
        opisi.append({"fund": m.group(1).strip(), "opis": m.group(2).strip(),
                      "title": clean(m.group(3))})
    for m in DELO.finditer(raw):
        fund, opis, n, tail = (m.group(1).strip(), m.group(2).strip(),
                               m.group(3).strip(), clean(m.group(4)))
        key = (fund, opis, n)
        if key in seen_d:
            continue
        seen_d.add(key)
        dela.append({"fund": fund, "opis": opis, "n_delo": n,
                     "zagolovok": tail or None})
    return opisi, dela


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    all_funds, all_opisi, all_dela = [], [], []

    print(f"{'файл':<50} {'вид':<8} {'найдено':>8}  запрос")
    for f in sorted(Path(args.src).glob("*.html")):
        raw = f.read_text(encoding="utf-8", errors="replace")
        kind = page_kind(raw)
        cm = COUNT.search(raw)
        total = cm.group(2) if cm else "?"
        qm = QUERY.search(raw)
        query = clean(qm.group(1)) if qm else ""
        print(f"{f.name[:48]:<50} {kind:<8} {total:>8}  {query[:60]}")

        if kind == "stocks":
            funds = parse_stocks(raw)
            for r in funds:
                r["source_file"] = f.name
            all_funds.extend(funds)
        else:
            opisi, dela = parse_search(raw)
            for r in opisi:
                r.update({"query": query, "source_file": f.name})
            for r in dela:
                r.update({"query": query, "source_file": f.name})
            all_opisi.extend(opisi)
            all_dela.extend(dela)

    # дедуп фондов по номеру
    uniq_funds, seen = [], set()
    for r in all_funds:
        if r["fund"] in seen:
            continue
        seen.add(r["fund"])
        uniq_funds.append(r)

    def dump(name: str, rows: list[dict], fields: list[str]) -> None:
        if not rows:
            return
        with (out / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump("gako_funds", uniq_funds, ["fund", "title", "source_file"])
    dump("gako_opisi", all_opisi, ["fund", "opis", "title", "query", "source_file"])
    dump("gako_dela", all_dela, ["fund", "opis", "n_delo", "zagolovok", "query", "source_file"])

    with_title = sum(1 for r in all_dela if r.get("zagolovok"))
    print(f"\nфондов уникальных: {len(uniq_funds)}")
    print(f"описей в выдаче:   {len(all_opisi)}")
    print(f"дел в выдаче:      {len(all_dela)}, из них с заголовком: {with_title}")
    print(f"выход: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
