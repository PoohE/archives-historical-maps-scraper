"""Отбор профильных фондов ГАКО по названиям из каталога фондов.

Тот же приём, что сработал в ГАСО: идти от списка фондов, а не от поиска по словам.
Поиск находит только то, где слово попало в заголовок дела, а профильный фонд виден
по своему названию целиком — «межевая контора», «землеустроительная комиссия»,
«коллекция планов».

Запуск:
    python -B scripts_gako/select_gako_funds.py C:\\arch\\output\\gako_parsed_20261013\\gako_funds.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

GROUPS = {
    "межевание": r"межев|размежеван",
    "землеустройство": r"землеустро|землемер|поземельн\w*\s+устройств|уравнени\w*.*сбор",
    "съёмка/геодезия": r"съемк|съёмк|геодез|топограф|нивелир|чертежн",
    "планы/карты/чертежи": r"\bплан|чертеж|картограф|\bкарт[аы]\b|коллекц\w*.*(?:план|карт|чертеж)",
    "оценка/отчуждение": r"оценочн|оценк\w*\s+(?:земел|имуществ)|отчужден",
    "владенные записи": r"владенн",
    "лесное/казённые земли": r"лесничеств|лесн\w*\s+(?:дач|хозяйств)|удельн|государственн\w*\s+имуществ",
    "статистика": r"статистическ",
    "строительство/дороги": r"дорожн|шоссейн|путей сообщен|строительн\w*\s+отделен",
}

# заведомо не наше, даже если слово совпало
NOISE = re.compile(r"партийн|комсомол|профсоюз|совет депутат|исполнительн\w*\s+комитет|"
                   r"райком|горком|обком|колхоз|совхоз|школ|больниц|суд\b|прокуратур|"
                   r"милиц|военкомат|загс", re.I)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    src = Path(args.jsonl)
    rows = [json.loads(ln) for ln in src.open(encoding="utf-8") if ln.strip()]
    out = Path(args.out) if args.out else src.parent

    hits = []
    for r in rows:
        title = r["title"]
        low = title.lower()
        tags = [g for g, pat in GROUPS.items() if re.search(pat, low)]
        if not tags:
            continue
        noisy = bool(NOISE.search(title))
        hits.append({**r, "tags": ", ".join(tags), "noise": "да" if noisy else ""})

    dorev = [h for h in hits if not h["fund"].upper().startswith(("Р", "R"))]
    sov = [h for h in hits if h["fund"].upper().startswith(("Р", "R"))]

    print(f"всего фондов в каталоге: {len(rows)}")
    print(f"совпало по словарю: {len(hits)} "
          f"(дореволюционных {len(dorev)}, советских Р-* {len(sov)})\n")

    print("=== ДОРЕВОЛЮЦИОННЫЕ (наш охват) ===")
    for h in sorted(dorev, key=lambda x: x["fund"]):
        mark = "  ⚠ шум" if h["noise"] else ""
        print(f"Ф. {h['fund']:<8} [{h['tags']}]{mark}\n    {h['title'][:150]}")

    print("\n=== СОВЕТСКИЕ Р-* (вне хронологии, справочно) ===")
    for h in sorted(sov, key=lambda x: x["fund"])[:20]:
        print(f"Ф. {h['fund']:<8} [{h['tags']}] {h['title'][:110]}")
    if len(sov) > 20:
        print(f"  … ещё {len(sov) - 20}")

    f = out / "gako_funds_selected.csv"
    with f.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["fund", "title", "tags", "noise", "source_file"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(hits, key=lambda x: x["fund"]))
    print(f"\nCSV: {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
