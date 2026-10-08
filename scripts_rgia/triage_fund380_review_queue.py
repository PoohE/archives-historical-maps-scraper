"""Каскадный разбор очереди проверки фонда 380 (2295 записей без территории).

Решение пользователя 09.10: идти от дешёвого к дорогому, каждый шаг уменьшает остаток.
  Шаг 3 (этот скрипт) — отбор по МАСШТАБУ: подробные карты и планы оставляем в работе,
                        обзорные откладываем. Территорию не определяет, только сужает круг.
  Шаг 2 (потом)       — добор контекста описи: к какой губернии относится блок дел.
  Шаг 1 (в конце)     — карточки дел на fgurgia.ru для того, что осталось.

Почему масштаб решает: цель проекта — подробные карты, а не атласы и обзорные листы
(приоритет 1 против приоритета 3 в сводке по губерниям). Запись «Карта Европейской России,
масштаб 100 вёрст» не нужна, даже если территорию удастся установить.

Пересчёт старых мер (правило проекта):
    1 верста в дюйме  = 1:42 000
    1 сажень в дюйме  = 1:84
    (100 саженей = 1:8 400 — план дачи; 2 версты = 1:84 000 — уровень Менде)

Запуск из корня проекта:
    python -B scripts_rgia/triage_fund380_review_queue.py
    python -B scripts_rgia/triage_fund380_review_queue.py --threshold 100000
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "output" / "rgia_fund380_handoff_package_20261008"
OUT = ROOT / "output" / f"rgia_fund380_triage_{time.strftime('%Y%m%d')}"

VERSTA = 42000      # 1 верста в дюйме
SAZHEN = 84         # 1 сажень в дюйме

NUM = r"(\d+(?:[.,]\d+)?)"
PATTERNS = [
    (re.compile(r"1\s*/\s*(\d[\d\s]{3,9})"), "direct"),          # 1/84000
    (re.compile(rf"{NUM}\s*саж[еня]*\w*", re.I), "sazhen"),          # 100 саженей
    (re.compile(rf"{NUM}\s*верст\w*", re.I), "versta"),              # 10 вёрст
    (re.compile(rf"{NUM}\s*вер\.", re.I), "versta"),
]


# Инженерные чертежи: объект сооружения, а не территория (§1.2 object_conflict)
ENGINEERING = re.compile(
    r"\b(?:мост\w*|плотин\w*|шлюз\w*|лотк\w*|лоток|труб\w*|скважин\w*|колодц\w*|"
    r"водопровод\w*|трубопровод\w*|канализац\w*|здани\w*|建|корпус\w*|казарм\w*|"
    r"церкв\w*|часовн\w*|сара\w*|амбар\w*|мельниц\w*|завод\w*\s+корпус|"
    r"фасад\w*|разрез\w*|профил\w*|сооружен\w*|насос\w*|водокачк\w*|"
    r"железо-?бетон\w*|водоподъемн\w*|водосбор\w*)\b", re.I)
# Решение пользователя 09.10: «мосты и скважины конечно выбрасывать» — инженерные
# сооружения не нужны независимо от того, назван ли рядом топоним. Чертёж моста в даче X
# геометрии землепользования не даёт. Поэтому смотрим на ПРЕДМЕТ записи (начало заголовка),
# а не на присутствие слова где угодно: «План дачи с мельницей» — план дачи (берём),
# «Чертёж моста в даче» — чертёж моста (выбрасываем).
SUBJECT_ENGINEERING = re.compile(
    r"^\s*(?:чертеж\w*|чертёж\w*|проект\w*|эскиз\w*|генеральн\w*\s+план\s+здани\w*)\b"
    r"|^\s*план\w*\s+(?:и\s+)?(?:продольн\w*\s+)?(?:профил\w*|разрез\w*|фасад\w*|"
    r"мост\w*|плотин\w*|шлюз\w*|здани\w*|корпус\w*|сооружен\w*|водопровод\w*|"
    r"трубопровод\w*|скважин\w*|колодц\w*|канал\w*\s+для)", re.I)


def parse_scale(title: str) -> tuple[int | None, str]:
    """Вернуть знаменатель масштаба и способ, которым он получен."""
    t = title or ""
    tail = ""
    m = re.search(r"[Мм]асштаб\w*\s*([^.;]{1,60})", t)
    tail = m.group(1) if m else t
    for rx, kind in PATTERNS:
        mm = rx.search(tail)
        if not mm:
            continue
        raw = mm.group(1).replace(" ", "").replace(",", ".")
        try:
            val = float(raw)
        except ValueError:
            continue
        if kind == "direct":
            return int(val), "указан прямо"
        if kind == "sazhen":
            return int(val * SAZHEN), f"{mm.group(1)} саж. × 84"
        return int(val * VERSTA), f"{mm.group(1)} вёрст × 42000"
    return None, "масштаб не указан"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=int, default=100000,
                    help="знаменатель: подробнее этого — в работу (по умолчанию 1:100 000)")
    args = ap.parse_args()

    src = PKG / "review_queue.csv"
    with src.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"очередь проверки: {len(rows)} записей")

    detailed, overview, unknown, engineering = [], [], [], []
    for r in rows:
        title = r.get("title") or ""
        denom, how = parse_scale(title)
        if not denom:  # None или вырожденный ноль («масштаб 0 вёрст»)
            denom = None
        rec = dict(r, scale_denominator=denom if denom else "", scale_basis=how)
        # Крупный масштаб сам по себе не значит «подробная карта территории»:
        # 1:84 чаще всего чертёж моста или буровой скважины, а не план дачи.
        # §1.2: план здания/сооружения — не картографический объект нашего охвата.
        if SUBJECT_ENGINEERING.search(title) or (
                ENGINEERING.search(title) and not re.search(
                    r"^\s*(?:план\w*|карт\w*|геометрическ\w*|топографическ\w*|межев\w*)\s+"
                    r"(?:дач|генеральн|специальн|земел|участк|пустош|селени|деревн|"
                    r"волост|уезд|губерн|лесничеств|имени|надельн|разверстан)", title, re.I)):
            engineering.append(dict(rec, drop_reason="предмет записи — сооружение, не территория"))
        elif denom is None:
            unknown.append(rec)
        elif denom <= args.threshold:
            detailed.append(rec)
        else:
            overview.append(rec)

    detailed.sort(key=lambda r: int(r["scale_denominator"]))
    print(f"\nподробнее 1:{args.threshold:,}".replace(",", " ") + f" — {len(detailed)}")
    print(f"обзорные (крупнее знаменатель) — {len(overview)}")
    print(f"масштаб не указан — {len(unknown)}")
    print(f"инженерные чертежи (отсев) — {len(engineering)}")

    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in (("step3_detailed.csv", detailed),
                       ("step3_overview.csv", overview),
                       ("step3_no_scale.csv", unknown),
                       ("step3_engineering.csv", engineering)):
        if not data:
            continue
        cols: list[str] = []
        for r in data:
            for k in r:
                if k not in cols:
                    cols.append(k)
        with (OUT / name).open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)

    from collections import Counter
    buckets = Counter()
    for r in detailed:
        d = int(r["scale_denominator"])
        if d <= 10000:
            buckets["1:≤10 000 — план дачи, селения"] += 1
        elif d <= 25000:
            buckets["1:10 001–25 000"] += 1
        elif d <= 50000:
            buckets["1:25 001–50 000 — уровень версты"] += 1
        else:
            buckets["1:50 001–100 000 — уровень Менде"] += 1
    print("\nраспределение подробных:")
    for k, v in sorted(buckets.items()):
        print(f"  {v:>5}  {k}")

    print("\nсамые подробные, примеры:")
    for r in detailed[:10]:
        print(f"  1:{int(r['scale_denominator']):<7} оп.{r.get('keyword','')[-2:]}  "
              f"{(r.get('title') or '')[:76]}")

    rep = {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "step": "3 — отбор по масштабу (территория НЕ определяется)",
        "threshold": args.threshold,
        "input": len(rows),
        "detailed": len(detailed),
        "overview": len(overview),
        "no_scale": len(unknown),
        "engineering_dropped": len(engineering),
        "conservation_delta": len(rows) - (len(detailed) + len(overview)
                                           + len(unknown) + len(engineering)),
        "next": "шаг 2 — добор контекста описи для step3_detailed.csv",
    }
    (OUT / "TRIAGE_REPORT.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nвыход: {OUT}")
    return 0 if rep["conservation_delta"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
