"""Есть ли у дефекта года другие формы, кроме помеченных «по крайним датам описи».

Вопрос пользователя 10.11.2026: «когда прогон закончится, мы закроем ошибку с годом
и масштабом для ВСЕХ источников в каталоге?»

Исправлены были 1 847 записей, у которых прогон САМ оставил в примечаниях оговорку
«Год приближённо — по крайним датам описи». Но если какой-то прогон проставил год
по описи БЕЗ оговорки, такие записи мы не нашли и не исправили. Скрипт ищет косвенные
признаки того же дефекта:

  A. у многих записей одной описи ОДИН И ТОТ ЖЕ нижний год — характерный след
     «год дела = начало диапазона описи»;
  B. год стоит, а в примечаниях есть слова приблизительности («ок.», «предположительно»);
  C. нижний год равен верхнему у всей описи сразу (единая дата на сотни дел).

Ничего не меняет: только считает и выписывает подозрительные описи.

  python year_defect_sweep.py [путь_к_baseline.jsonl]
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
DEFAULT = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"
OUT = ROOT / "defects" / "year_defect_sweep.json"

MARKED = re.compile(r"крайни\w*\s+дат\w*\s+описи|по\s+крайним\s+датам", re.I)
VAGUE = re.compile(r"приближ|предположительно|\bок\.\s*1[5-9]\d{2}|примерно", re.I)
#: сколько дел одной описи должны делить один год, чтобы счесть это следом дефекта
SUSPECT_MIN = 20


def main() -> None:
    fix_stdout()
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    by_opis: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    marked = 0
    vague_unmarked = 0
    total_with_year = 0
    n = 0
    for line in src.open(encoding="utf-8"):
        if not line.strip():
            continue
        n += 1
        f = (json.loads(line).get("fields") or {})
        prim = str(f.get("Примечания") or "")
        y = f.get("Год создания (нижняя)")
        if MARKED.search(prim):
            marked += 1
            continue  # эти уже исправлены
        if not isinstance(y, (int, float)):
            continue
        total_with_year += 1
        if VAGUE.search(prim):
            vague_unmarked += 1
        key = (
            str(f.get("Архив [авто]") or "?"),
            str(f.get("Фонд") or ""),
            str(f.get("Опись") or ""),
        )
        by_opis[key][int(y)] += 1

    print(f"записей: {n}")
    print(f"  уже помечены «по крайним датам описи» (исправлены): {marked}")
    print(f"  с годом и БЕЗ такой пометки: {total_with_year}")
    print(f"  из них с иными словами приблизительности в примечаниях: {vague_unmarked}")

    suspects = []
    for key, years in by_opis.items():
        if not years:
            continue
        year, cnt = years.most_common(1)[0]
        share = cnt / sum(years.values())
        if cnt >= SUSPECT_MIN and share >= 0.8 and len(years) <= 3:
            suspects.append({
                "arch": key[0], "fond": key[1], "opis": key[2],
                "year": year, "records": cnt,
                "share": round(share, 2), "distinct_years": len(years),
                "total": sum(years.values()),
            })
    suspects.sort(key=lambda x: -x["records"])
    print(f"\nОПИСИ, ГДЕ ≥{SUSPECT_MIN} ДЕЛ ДЕЛЯТ ОДИН ГОД (≥80 % описи, ≤3 разных года):")
    print(f"  таких описей: {len(suspects)}; записей в них: "
          f"{sum(s['records'] for s in suspects)}")
    for s in suspects[:20]:
        print(f"  {s['arch']:6s} ф.{s['fond']:>6s} оп.{s['opis']:<4s} "
              f"год {s['year']} у {s['records']} из {s['total']} дел "
              f"({int(s['share'] * 100)} %), разных годов {s['distinct_years']}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "помечены_и_исправлены": marked,
        "с_годом_без_пометки": total_with_year,
        "иные_слова_приблизительности": vague_unmarked,
        "подозрительные_описи": suspects,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
