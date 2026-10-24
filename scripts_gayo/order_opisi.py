"""Упорядочить описи перед обходом дел: ценное — первым.

Портал ограничивает темп, прогон длинный и может быть прерван. Поэтому идём не в порядке
номеров фондов, а по убыванию ожидаемой отдачи: сначала собственно картографические
собрания и чертежная, затем межевое, затем остальное. Если прогон оборвётся, в руках
окажется главное, а не случайный срез.

Запуск: python -B scripts_gayo/order_opisi.py output/gayo/opisi.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# по убыванию приоритета
PRIORITY = ["560", "82", "455", "1443", "76", "80", "452", "456", "457", "458",
            "459", "460", "462", "463", "1219", "1000", "642", "474", "475", "1176"]


def rank(fund: str) -> int:
    return PRIORITY.index(fund) if fund in PRIORITY else len(PRIORITY)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    src = Path(args.jsonl)
    rows = [json.loads(ln) for ln in src.open(encoding="utf-8") if ln.strip()]
    rows.sort(key=lambda r: (rank(str(r["fund_num"])), str(r["fund_num"]), r["inv_id"]))
    out = Path(args.out) if args.out else src.with_name("opisi_ordered.jsonl")
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"описей: {len(rows)} → {out}")
    print("первые десять:")
    for r in rows[:10]:
        label = (r.get("inv_cells") or ["", ""])[:2]
        print(f"  Ф.{r['fund_num']:<6} оп.{' '.join(label)[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
