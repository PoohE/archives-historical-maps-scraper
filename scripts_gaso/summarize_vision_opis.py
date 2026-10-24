"""Сводка по распознанной описи: записи, картографический признак, пропуски, расход.

Запуск:
    python -B scripts_gaso/summarize_vision_opis.py C:\\arch\\output\\gaso_vision_20261013\\576_1.jsonl
    ... --csv C:\\arch\\output\\gaso_vision_20261013\\576_1.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

PRICE_IN, PRICE_OUT = 2.0, 10.0

FIELDS = ["page", "fund", "opis", "n_poryadok", "n_delo", "zagolovok",
          "data_nachato", "data_okoncheno", "listov", "obyekt",
          "kartograficheskiy_priznak", "primechanie"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--csv", default="")
    args = ap.parse_args()

    src = Path(args.jsonl)
    pages = [json.loads(ln) for ln in src.open(encoding="utf-8") if ln.strip()]
    pages.sort(key=lambda r: r["page"])

    rows, tin, tout, empty, unparsed = [], 0, 0, [], []
    for p in pages:
        tin += p["usage"]["in"]
        tout += p["usage"]["out"]
        if p.get("raw"):
            unparsed.append(p["page"])
        if not p["rows"]:
            empty.append(p["page"])
        for r in p["rows"]:
            rows.append({"page": p["page"], "fund": p["fund"], "opis": p["opis"],
                         **{k: r.get(k) for k in FIELDS[3:]}})

    seen = {p["page"] for p in pages}
    gaps = [n for n in range(min(seen), max(seen) + 1) if n not in seen]

    signs = Counter((r.get("kartograficheskiy_priznak") or "нет").strip().lower() for r in rows)
    carto = sum(v for k, v in signs.items() if k != "нет")

    print(f"файл: {src.name}")
    print(f"страниц в файле: {len(pages)} (с {min(seen)} по {max(seen)})"
          + (f", ПРОПУЩЕНЫ: {gaps}" if gaps else ""))
    print(f"записей всего: {len(rows)}")
    print(f"с картографическим признаком: {carto} ({carto / len(rows) * 100:.0f}%)" if rows else "")
    print(f"страниц без записей: {len(empty)}" + (f" — {empty}" if empty else ""))
    print(f"страниц с неразобранным JSON: {len(unparsed)}" + (f" — {unparsed}" if unparsed else ""))
    print(f"токены: вход {tin:,}, выход {tout:,} → "
          f"${tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT:.2f}")

    print("\nпризнаки:")
    for k, v in signs.most_common():
        print(f"  {k:<26} {v}")

    with_obj = sum(1 for r in rows if (r.get("obyekt") or "").strip())
    print(f"\nзаписей с названным объектом: {with_obj} "
          f"({with_obj / len(rows) * 100:.0f}%)" if rows else "")

    if args.csv:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        print(f"\nCSV: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
