"""Вернуть дела описи 37 ф. 380 из отсева гейта в очередь на доработку.

Опись 37 (Ярославская губерния) целиком ушла в out_of_scope: аннотация описи в базе
РГИА названа «Черниговская-Ярославская», и гейт счёл её чужим регионом (правило 1.1,
out_of_region). Проверка всех 11 описей-диапазонов (check_opis_ranges.py) показала,
что это единственная ложная потеря.

Записи возвращаются НЕ в чистую часть, а в очередь: заголовков у них нет вообще
(в базе РГИА опись 37 без заголовков дел, как и опись 21), поэтому ни территорию,
ни содержание из них взять нельзя. И то и другое приходит из распознавания бумажной
описи (object 2841217).

Запуск:
    python -B scripts_rgia/restore_opis37_from_drops.py [--out <папка>]
"""
import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DROPS = BASE / "output" / "rgia_fund380_20261003_v3_1" / "scope_drops.jsonl"
RX_OPIS37 = re.compile(r"Оп\.\s*37\s+Д")
RX_DELO = re.compile(r"Д\.\s*(\d+)")

FIELDS = [
    "fund_code", "delo_no", "title", "territory_draft", "opis_annotation",
    "url", "opis_object_id", "needs_human", "needs_human_reason",
    "restore_reason", "source",
]

REASON = (
    "возвращено из отсева: опись 37 отсеяна гейтом целиком по аннотации "
    "«Черниговская-Ярославская» (правило 1.1, out_of_region); проверка описей-диапазонов "
    "показала, что это ложная потеря — Ярославская губерния входит в scope"
)

NH_REASON = (
    "в базе РГИА у описи 37 нет заголовков дел — ни территорию, ни содержание "
    "из записи взять нельзя; и то и другое определяется распознаванием бумажной описи "
    "(object 2841217)"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else (
        BASE / "output" / f"rgia_f380_op37_restored_{datetime.now():%Y%m%d}")
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    with DROPS.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                drop = json.loads(line)
            except json.JSONDecodeError:
                continue
            rec = drop.get("record") or {}
            code = rec.get("fund_code", "")
            if not RX_OPIS37.search(code):
                continue
            m = RX_DELO.search(code)
            rows.append({
                "fund_code": code,
                "delo_no": m.group(1) if m else "",
                "title": rec.get("title", ""),
                "territory_draft": "Ярославская (требует подтверждения)",
                "opis_annotation": drop.get("territory", ""),
                "url": rec.get("url", ""),
                "opis_object_id": rec.get("opis_object_id", ""),
                "needs_human": "true",
                "needs_human_reason": NH_REASON,
                "restore_reason": REASON,
                "source": rec.get("source", "rgia"),
            })

    rows.sort(key=lambda r: int(r["delo_no"]) if r["delo_no"].isdigit() else 0)

    csv_path = out_dir / "opis37_restored_queue.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    empty_titles = sum(1 for r in rows if not r["title"].strip())
    report = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source_drops": str(DROPS),
        "restored": len(rows),
        "empty_titles": empty_titles,
        "delo_range": [rows[0]["delo_no"], rows[-1]["delo_no"]] if rows else [],
        "opis_object_id": rows[0]["opis_object_id"] if rows else "",
        "destination": "очередь на доработку, НЕ чистая часть",
        "why": REASON,
        "blocker": NH_REASON,
    }
    (out_dir / "RESTORE_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"возвращено дел описи 37: {len(rows)}")
    print(f"из них без заголовка: {empty_titles}")
    if rows:
        print(f"диапазон: Д. {rows[0]['delo_no']} — Д. {rows[-1]['delo_no']}")
    print(f"CSV:    {csv_path}")
    print(f"Отчёт:  {out_dir / 'RESTORE_REPORT.json'}")


if __name__ == "__main__":
    main()
