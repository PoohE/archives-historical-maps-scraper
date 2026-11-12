"""Разрезать собранный review_run на порции под раздельные прогоны моста.

Повод 11.11.2026: фоновый прогон записи 598 дел ГАСО-Урал был убит нехваткой памяти
на 223-й записи (свободно оставалось 0,93 ГБ из 15,73). Урок памяти проекта —
тяжёлые прогоны идут по одному и порциями, а не одним длинным фоном.

Мост дедуплицирует по «Ссылке на онлайн-архив», поэтому порции безопасно
перезапускать: уже внесённые записи он пропустит.

  python split_review_run.py <review_run> [--size 120]
"""

import argparse
import csv
import shutil
import sys
from pathlib import Path

sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")
from common import fix_stdout  # noqa: E402


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("review_run", type=Path)
    ap.add_argument("--size", type=int, default=120)
    args = ap.parse_args()

    src = args.review_run
    rows = list(csv.DictReader((src / "notion_import.csv").open(encoding="utf-8-sig")))
    cols = list(rows[0].keys())
    print(f"строк: {len(rows)} → порций по {args.size}")

    for i in range(0, len(rows), args.size):
        part = rows[i:i + args.size]
        d = src.parent / f"{src.name}_part{i // args.size + 1}"
        d.mkdir(parents=True, exist_ok=True)
        with (d / "notion_import.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(part)
        # связи и подсказки ключуются по URL — отдаём файл целиком, он невелик
        shutil.copy(src / "export_review.json", d / "export_review.json")
        print(f"  {d.name}: {len(part)}")


if __name__ == "__main__":
    main()
