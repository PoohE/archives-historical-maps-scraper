"""Чек-лист заполненности перед заливкой: собранный импорт против нормы каталога.

Запрос пользователя 11.11.2026: «при внесении проверяю по чек-листу, что заполнены все
основные поля». Скрипт считает долю заполненности каждого основного поля в собранных
CSV и сравнивает с тем, как это поле заполнено в каталоге (112 202 записи, baseline).

Поля «Охватываемая территория» и «Современные регионы» в CSV не лежат — их ставит мост
по заголовку и по подсказкам фондообразователя, поэтому для них считается ПРОГНОЗ:
сколько записей имеют хоть один источник значения (заголовок или подсказку).

  python check_import_fill.py
"""

import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")
from common import fix_stdout  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "output"
WORK = OUT / "upload_2026-11-11"
BASELINE = OUT / "notion_catalog_20261030_023643_baseline.jsonl"
PACKS = ["gaso", "rgo", "neb", "rgia380"]

#: поля, которые считаем основными (в каталоге заполнены ≥89 %)
MAIN = ["Название источника", "Описание", "Язык", "Административный уровень",
        "DC Type", "Статус доступа", "Фонд", "Опись", "Единица хранения",
        "Примечания", "Ссылка на онлайн-архив", "Год создания (нижняя)",
        "Год создания (верхняя)", "Листы / страницы"]
EXTRA = ["Оригинальный масштаб", "Масштаб (знаменатель)", "Размер листа (мм)",
         "Автор / составитель", "Библиотечный шифр", "Место хранения",
         "Путь / URL к файлу"]
PROV = ["Масштаб: источник значения", "Год: источник значения",
        "Территория: источник значения",
        "Административный уровень: источник значения"]


def main() -> None:
    fix_stdout()

    total = 0
    cat: Counter = Counter()
    for line in BASELINE.open(encoding="utf-8"):
        if not line.strip():
            continue
        f = json.loads(line).get("fields") or {}
        total += 1
        for k, v in f.items():
            if v not in (None, "", [], {}):
                cat[k] += 1

    packs: dict[str, list[dict]] = {}
    rels: dict[str, list[dict]] = {}
    for p in PACKS:
        d = WORK / f"{p}_review_run"
        if not (d / "notion_import.csv").exists():
            continue
        packs[p] = list(csv.DictReader(
            (d / "notion_import.csv").open(encoding="utf-8-sig")))
        rels[p] = json.loads((d / "export_review.json").read_text(
            encoding="utf-8"))["records"]
    n_all = sum(len(v) for v in packs.values())
    print(f"к внесению: {n_all} записей — "
          + ", ".join(f"{p} {len(v)}" for p, v in packs.items()))

    def pct(p: str, col: str) -> str:
        rows = packs[p]
        c = sum(1 for r in rows if (r.get(col) or "").strip())
        return f"{100 * c / len(rows):5.0f}" if rows else "    —"

    head = f"{'поле':38s} {'каталог':>8s}" + "".join(
        f"{p:>9s}" for p in packs)
    print("\n=== ОСНОВНЫЕ ПОЛЯ (% заполнено)\n" + head)
    for col in MAIN:
        base = f"{100 * cat.get(col, 0) / total:5.0f}" if total else "    —"
        print(f"{col[:38]:38s} {base:>8s}" + "".join(
            f"{pct(p, col):>9s}" for p in packs))

    print("\n=== ДОПОЛНИТЕЛЬНЫЕ\n" + head)
    for col in EXTRA:
        base = f"{100 * cat.get(col, 0) / total:5.0f}" if total else "    —"
        print(f"{col[:38]:38s} {base:>8s}" + "".join(
            f"{pct(p, col):>9s}" for p in packs))

    print("\n=== ПРИЗНАКИ ПРОИСХОЖДЕНИЯ ЗНАЧЕНИЯ")
    for col in PROV:
        print(f"\n  {col}")
        for p, rows in packs.items():
            c = Counter((r.get(col) or "—") for r in rows)
            print(f"    {p:8s} " + "  ".join(f"{k}: {v}" for k, v in c.most_common()))

    print("\n=== ТЕРРИТОРИЯ: прогноз простановки мостом")
    for p, rr in rels.items():
        with_hint = sum(1 for x in rr if x.get("territory_hints"))
        from_title = sum(1 for r in packs[p]
                         if (r.get("Территория: источник значения") or "") == "из заголовка")
        none = sum(1 for r in packs[p]
                   if (r.get("Территория: источник значения") or "") == "не установлена")
        print(f"    {p:8s} из заголовка {from_title:4d} | по фондообразователю "
              f"{with_hint:4d} | не установлена {none:4d}")

    print("\n=== ПУСТО В ОСНОВНОМ ПОЛЕ — где именно")
    for p, rows in packs.items():
        gaps = {col: sum(1 for r in rows if not (r.get(col) or "").strip())
                for col in MAIN}
        bad = {k: v for k, v in gaps.items() if v}
        if bad:
            print(f"    {p}: " + ", ".join(f"{k} — {v}" for k, v in
                                           sorted(bad.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
