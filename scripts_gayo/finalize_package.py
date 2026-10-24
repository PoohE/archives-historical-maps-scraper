"""Финальная сборка пакета ГАЯО под решения пользователя от 18.10.2026.

Три решения, которые меняют состав пакета против машинного гейта:

1. Текстовые межевые книги (46,6 тыс.) ВНОСИМ, но отдельным классом, чтобы
   картографическая часть каталога оставалась чистой и фильтровалась одним щелчком.
   ⚠️ Новый select-вариант в Notion заводит только сессия claude-64, поэтому здесь
   проставляется ВРЕМЕННАЯ пометка класса в поле `klass_vremenno` — приёмщик заводит
   класс и переносит значение (объяснено в ПЕРЕДАЧА_на_внесение.md).

2. Ф. 560 (общероссийская коллекция) вносим ЦЕЛИКОМ — 911 дел. Территория не повод
   отсеивать, она становится полем `territoriya`.

3. needs_human (4537) разобраны: территория следует из фондовой принадлежности,
   а не из слов заголовка (см. classify_needs_human.py). Все они переходят в принятые
   с проставленной территорией и основанием решения.

Запуск:
    python -B scripts_gayo/finalize_package.py output/gayo_package_20261018
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_needs_human import ALIEN, OURS  # noqa: E402

KLASS_HINT = {
    "межевой акт (текст)": "Межевой акт (текст)",
    "графический": "Картографический документ",
    "делопроизводство": "Делопроизводство",
    "не определён": "Требует уточнения",
}


def territory_of(fund: str, verdict: str | None, title: str = "") -> tuple[str, str]:
    if fund == "560":
        if verdict == "наша" or OURS.search(title):
            return "Ярославская губерния", "в заголовке названа территория проекта"
        if verdict == "чужая" or ALIEN.search(title):
            return "вне охвата проекта", "коллекция ф.560: территория вне 4 губерний проекта"
        return "не определена", "коллекция ф.560: территорию уточнить при разборе"
    return "Ярославская губерния", "фондовая принадлежность (ярославское учреждение)"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("package")
    args = ap.parse_args()
    pkg = Path(args.package)

    verdicts: dict[str, str] = {}
    rp = pkg / "needs_human_resolved.csv"
    if rp.exists():
        for r in csv.DictReader(rp.open(encoding="utf-8-sig")):
            verdicts[r["flags"]] = r["verdict"]

    rows = []
    for name in ("gayo_accepted.jsonl", "gayo_needs_human.jsonl"):
        src = pkg / name
        if not src.exists():
            continue
        for ln in src.open(encoding="utf-8"):
            r = json.loads(ln)
            fund = str(r.get("fund") or "")
            terr, why = territory_of(fund, verdicts.get(r.get("flags", "")),
                                     r.get("zagolovok", ""))
            r["territoriya"] = terr
            r["territoriya_osnovanie"] = why
            r["klass_vremenno"] = KLASS_HINT.get(r.get("klass", ""), "Требует уточнения")
            r["iz_needs_human"] = "да" if name.endswith("needs_human.jsonl") else ""
            rows.append(r)

    fields = list(rows[0].keys())
    with (pkg / "gayo_to_catalog.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with (pkg / "gayo_to_catalog.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"в каталог: {len(rows)} записей")
    print("  классы (временная пометка):")
    for k, v in Counter(r["klass_vremenno"] for r in rows).most_common():
        print(f"    {v:>6}  {k}")
    print("  территория:")
    for k, v in Counter(r["territoriya"] for r in rows).most_common():
        print(f"    {v:>6}  {k}")
    print("  из них подняты из needs_human:",
          sum(1 for r in rows if r["iz_needs_human"] == "да"))
    print(f"\n→ {pkg / 'gayo_to_catalog.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
