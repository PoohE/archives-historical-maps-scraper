"""Проставить примечания записям фонда 380, у которых не определена территория.

Решение пользователя 09.10: записать в примечания к самим записям, почему территория
не установлена и что для неё нужно. Иначе через месяц никто не вспомнит, был ли это
недоработанный обход или установленный предел источника.

Что установлено (каскад 09.10, три шага от дешёвого к дорогому):
  шаг 3 — отбор по масштабу: отделены подробные (1140) от обзорных (586);
          попутно выброшены 129 чертежей сооружений (мосты, плотины, скважины);
  шаг 2 — дерево описи: узлов-разделов с губерниями НЕТ, дела идут плоским списком
          (проверено на оп. 39: 22 узла = 20 дел + 2 служебных);
  шаг 1 — карточка дела: поле «Раздел описи» (INVSECTIONNEW) ПУСТОЕ у всей выборки,
          аннотация тоже пуста.
Вывод: территория существует только в бумажной описи, выложенной PDF-сканом.

Запуск из корня проекта:
    python -B scripts_rgia/annotate_fund380_queue.py
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "output" / "rgia_fund380_handoff_package_20261008"
TRIAGE = ROOT / "output" / "rgia_fund380_triage_20261009"

NOTE_BASE = (
    "Территория не установлена. Проверено 09.10.2026: (1) в заголовке дела губерния не "
    "названа — в описях 38-41 дела сгруппированы по губерниям, и губерния стоит в заголовке "
    "РАЗДЕЛА описи; (2) в дереве описи на fgurgia.ru узлов-разделов нет, дела идут плоским "
    "списком; (3) поле карточки «Раздел описи» (INVSECTIONNEW) пустое, аннотация пуста. "
    "Территорию можно взять только из PDF-скана бумажной описи (Vision-разбор, как по ГАСО). "
    "Обход сайта её НЕ даст — повторять не нужно."
)
NOTE_DETAILED = (
    " ПРИОРИТЕТ: масштаб {scale} — подробная карта, кандидат приоритета 1 для ИГИС."
)
NOTE_OVERVIEW = (
    " Масштаб {scale} — обзорный лист; для ИГИС низкий приоритет даже при установленной "
    "территории."
)
NOTE_NOSCALE = " Масштаб в заголовке не указан."
NOTE_ENGINEERING = (
    "Вне охвата: предмет записи — инженерное сооружение (мост, плотина, скважина, здание), "
    "а не территория. Решение пользователя 09.10: такие записи выбрасывать независимо от "
    "того, назван ли рядом топоним — геометрии землепользования они не дают (§1.2)."
)


def annotate(path: Path, note_fn) -> int:
    if not path.exists():
        print(f"  нет файла: {path.name}")
        return 0
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return 0
    for r in rows:
        r["Примечания"] = note_fn(r)
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  {path.name}: {len(rows)} записей")
    return len(rows)


def scale_text(r: dict) -> str:
    d = (r.get("scale_denominator") or "").strip()
    return f"1:{int(d):,}".replace(",", " ") if d.isdigit() else "не определён"


def main() -> int:
    print(f"примечания, {time.strftime('%Y-%m-%d')}\n")
    total = 0
    total += annotate(TRIAGE / "step3_detailed.csv",
                      lambda r: NOTE_BASE + NOTE_DETAILED.format(scale=scale_text(r)))
    total += annotate(TRIAGE / "step3_overview.csv",
                      lambda r: NOTE_BASE + NOTE_OVERVIEW.format(scale=scale_text(r)))
    total += annotate(TRIAGE / "step3_no_scale.csv", lambda r: NOTE_BASE + NOTE_NOSCALE)
    total += annotate(TRIAGE / "step3_engineering.csv", lambda r: NOTE_ENGINEERING)
    # та же база — в общей очереди пакета, чтобы примечание ехало вместе с набором
    total += annotate(PKG / "review_queue.csv", lambda r: NOTE_BASE)
    print(f"\nвсего размечено: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
