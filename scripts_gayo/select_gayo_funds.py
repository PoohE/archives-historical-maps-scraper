"""Отбор профильных фондов ГАЯО по названиям из каталога фондов.

Тот же приём, что в ГАСО и ГАКО: идти от списка фондов, а не от поиска по словам —
поиск находит лишь то, где слово попало в заголовок дела, а профильный фонд виден по
своему названию целиком («коллекция картографических документов», «губернский межевой
архив», «посредник по размежеванию земель»). Словарь групп общий с ГАКО, чтобы отбор
по источникам не расходился.

Запуск:
    python -B scripts_gayo/select_gayo_funds.py output/gayo/funds_all.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts_gako"))
from select_gako_funds import GROUPS, NOISE  # noqa: E402

# Советские фонды у ГАЯО помечены литерой Р- в номере; хронология проекта — до 1918 г.,
# но фонд с дореволюционными документами мог получить советский номер, поэтому не режем,
# а раскладываем на две корзины и смотрим крайние даты.
SOVIET = re.compile(r"^[РR]", re.I)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--out", default="")
    ap.add_argument("--max-year", type=int, default=1918,
                    help="фонд интересен, если его документы начинаются не позже этого года")
    args = ap.parse_args()

    src = Path(args.jsonl)
    rows = [json.loads(ln) for ln in src.open(encoding="utf-8") if ln.strip()]
    out = Path(args.out) if args.out else src.parent

    hits = []
    for r in rows:
        title = r["title"]
        tags = [g for g, pat in GROUPS.items() if re.search(pat, title.lower())]
        if not tags:
            continue
        yy = [int(y) for y in re.findall(r"\b(1[5-9]\d{2}|20\d{2})\b", r.get("dates", ""))]
        start = min(yy) if yy else None
        hits.append({**r, "tags": ", ".join(tags),
                     "noise": "да" if NOISE.search(title) else "",
                     "start_year": start,
                     "soviet": "да" if SOVIET.match(r["fund_num"]) else ""})

    # в охвате: дореволюционное начало документов, либо даты неизвестны (решает человек)
    scope = [h for h in hits
             if (h["start_year"] is None or h["start_year"] <= args.max_year)
             and not h["noise"]]
    later = [h for h in hits if h not in scope]

    print(f"всего фондов в каталоге: {len(rows)}")
    print(f"совпало по словарю: {len(hits)}")
    print(f"  в охвате (до {args.max_year} или даты неизвестны, без шума): {len(scope)}")
    print(f"  вне охвата / шум: {len(later)}\n")

    print("по группам (в охвате):")
    for g, n in Counter(t for h in scope for t in h["tags"].split(", ")).most_common():
        print(f"  {g:<28} {n}")

    print("\n=== В ОХВАТЕ, по архивам ===")
    for arc in sorted({h["arc"] for h in scope}):
        part = [h for h in scope if h["arc"] == arc]
        print(f"\n-- archive{arc}: {len(part)} фондов")
        for h in sorted(part, key=lambda x: (len(x["fund_num"]), x["fund_num"]))[:40]:
            cam = " 📷" if h.get("digitized") else ""
            vyb = " (выбыл)" if h.get("vybyl") else ""
            print(f"  Ф.{h['fund_num']:<8} {h['dates']:<14} [{h['tags']}]{cam}{vyb}")
            print(f"      {h['title'][:140]}")
        if len(part) > 40:
            print(f"      … ещё {len(part) - 40}")

    sel = out / "funds_selected.jsonl"
    with sel.open("w", encoding="utf-8") as fh:
        for h in sorted(scope, key=lambda x: (x["arc"], x["fund_num"])):
            fh.write(json.dumps(h, ensure_ascii=False) + "\n")
    csv_path = out / "funds_selected.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, extrasaction="ignore",
                           fieldnames=["arc", "fund_num", "title", "dates", "tags",
                                       "digitized", "vybyl", "soviet", "fund_id"])
        w.writeheader()
        w.writerows(sorted(hits, key=lambda x: (x["arc"], x["fund_num"])))
    print(f"\nотобрано → {sel}\nвесь улов → {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
