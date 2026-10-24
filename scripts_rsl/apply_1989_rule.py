"""РГБ: применить правило пользователя от 20.10.2026 — для библиотек верхняя граница 1989 г.

Решение: издания по 1989 год включительно принимаются в каталог, позднее — нет.
(Для архивов такого ограничения нет, правило только для библиотечных источников.)

⚠️ Ограничение данных: у большинства отложенных записей год в ЗАГОЛОВКЕ не указан — он
лежит в теле карточки РГБ, которое мы не читаем (robots разрешает карточки, но ходить за
каждой — это отдельный прогон). Поэтому:
  * год есть и ≤ 1989 → в каталог;
  * год есть и > 1989 → отсев с причиной;
  * года нет → остаётся на просмотр человеку, автоматически не решаем.

Выход: rsl_addon_1989.csv — то, что добавляется к уже внесённому пакету.

Запуск:
    python -B scripts_rsl/apply_1989_rule.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "output" / "rsl_package_20261020"
YEAR = re.compile(r"\b(1[5-9]\d{2}|20[0-2]\d)\b")
LIMIT = 1989


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    rows = [json.loads(ln) for ln in (PKG / "rsl_needs_human.jsonl").open(encoding="utf-8")]

    add, drop, unknown = [], [], []
    for r in rows:
        text = f"{r.get('zagolovok', '')} {r.get('primechanie') or ''}"
        yy = [int(y) for y in YEAR.findall(text)]
        # чужая территория — отдельный разбор, правило по дате её не отменяет
        if r.get("chuzhaya_territoriya"):
            unknown.append({**r, "resheniye": "сначала решить вопрос территории"})
            continue
        if not yy:
            unknown.append({**r, "resheniye": "год не указан в заголовке — смотреть карточку РГБ"})
        elif max(yy) <= LIMIT:
            add.append({**r, "resheniye": f"принято: издание {max(yy)} ≤ {LIMIT}"})
        else:
            drop.append({**r, "resheniye": f"отсев: издание {max(yy)} > {LIMIT}"})

    def dump(name: str, data: list[dict]) -> None:
        if not data:
            return
        fields = list(data[0])
        with (PKG / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)
        with (PKG / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump("rsl_addon_1989", add)
    dump("rsl_drop_after_1989", drop)
    dump("rsl_still_unknown_year", unknown)

    print(f"отложенных было: {len(rows)}")
    print(f"  ДОБАВИТЬ в каталог (≤{LIMIT}): {len(add)}")
    print(f"  отсев (>{LIMIT}):              {len(drop)}")
    print(f"  год неизвестен — к просмотру:  {len(unknown)}")
    if add:
        print("\nдобавляются:")
        for r in add:
            print(f"  · {r['resheniye'][:28]:<30} {r['zagolovok'][:62]}")
    if drop:
        print("\nотсев:")
        for r in drop[:8]:
            print(f"  · {r['resheniye'][:28]:<30} {r['zagolovok'][:62]}")
    print(f"\n→ {PKG / 'rsl_addon_1989.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
