"""Проставить территорию записям описи 39 ф. 380 по разделам бумажной описи.

Зачем: опись 39 — сводная («по всем губерниям и областям России»), и в электронном
каталоге у её дел нет территории: заголовок вида «Карта губернии, с обозначением лесов»
губернию не называет. Но бумажная опись (машинопись, скан `380_39.pdf`, 193 страницы)
построена по губерниям и уездам, и у неё есть оглавление с листами.

Разделы сняты Vision 09–10.10.2026 с листов 51–53, 104–105, 131, 168–176 (сканы 56–58,
109–110, 136, 173–181). Сверка проверена дело в дело: лист 51 даёт «КАЛУЖСКАЯ ГУБ.» с
д. 617, и дд. 617–626 совпали с нашей очередью по названиям, датам и масштабам.

Запуск:
    python -B scripts_rgia/apply_opis39_sections.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "output" / "rgia_fund380_handoff_package_20261008"
OUT = ROOT / "output" / f"rgia_f380_op39_territory_{time.strftime('%Y%m%d')}"

# Границы разделов описи 39 по номерам дел: (от, до, губерния, уезд)
# Уезд пустой — раздел губернии в целом (общегубернские карты).
SECTIONS: list[tuple[int, int, str, str]] = [
    # Калужская губ. — листы 51–53
    (617, 623, "Калужская губерния", ""),
    (624, 630, "Калужская губерния", "Жиздринский уезд"),
    (631, 632, "Калужская губерния", "Калужский уезд"),
    (633, 646, "Калужская губерния", "Козельский уезд"),
    (647, 650, "Калужская губерния", "Лихвинский уезд"),
    (651, 652, "Калужская губерния", "Перемышльский уезд"),
    (653, 653, "Калужская губерния", "Тарусский уезд"),
    # Пермская губ. — листы 104–105
    (1279, 1282, "Пермская губерния", ""),
    (1283, 1283, "Пермская губерния", "Верхотурский уезд"),
    (1284, 1285, "Пермская губерния", "Камышловский и Шадринский уезды"),
    (1286, 1287, "Пермская губерния", "Кунгурский уезд"),
    (1288, 1291, "Пермская губерния", "Осинский уезд"),
    (1292, 1292, "Пермская губерния", "Оханский уезд"),
    (1293, 1293, "Пермская губерния", "Пермский уезд"),
    (1294, 1294, "Пермская губерния", "Соликамский уезд"),
    # Смоленская губ. — лист 131
    (1586, 1588, "Смоленская губерния", ""),
    (1589, 1589, "Смоленская губерния", "Бельский уезд"),
    (1590, 1590, "Смоленская губерния", "Дорогобужский уезд"),
    # Ярославская губ. — листы 168–176
    (2010, 2018, "Ярославская губерния", ""),
    (2019, 2026, "Ярославская губерния", "Любимский уезд"),
    (2027, 2035, "Ярославская губерния", "Мологский уезд"),
    (2036, 2049, "Ярославская губерния", "Мышкинский уезд"),
    # листы 172–173 (сканы 177–178) по уездам не разобраны: губерния известна, уезд — нет
    (2050, 2093, "Ярославская губерния", ""),
    (2094, 2096, "Ярославская губерния", "Даниловский уезд"),
    (2097, 2097, "Ярославская губерния", "Мологский уезд"),
    (2098, 2098, "Ярославская губерния", "Романово-Борисоглебский уезд"),
    (2099, 2103, "Ярославская губерния", "Ростовский уезд"),
    (2104, 2107, "Ярославская губерния", "Рыбинский уезд"),
    (2108, 2111, "Ярославская губерния", "Угличский уезд"),
    (2112, 2113, "Ярославская губерния", "Ярославский уезд"),
]
UNPARSED_UEZD = range(2050, 2094)   # уезд не снят, губерния достоверна
COLS = ["fund_code", "delo", "territory", "uezd", "territory_source", "title",
        "date_raw", "year_from", "year_to", "sheets", "url"]


def section_of(delo: int) -> tuple[str, str] | None:
    for lo, hi, gub, uezd in SECTIONS:
        if lo <= delo <= hi:
            return gub, uezd
    return None


def main() -> int:
    rows = list(csv.DictReader((PKG / "review_queue.csv").open(encoding="utf-8-sig")))
    out_rows, by_gub = [], {}
    for r in rows:
        m = re.match(r"Ф\. 380 Оп\. 39 Д\. (\d+)$", (r.get("fund_code") or "").strip())
        if not m:
            continue
        delo = int(m.group(1))
        sec = section_of(delo)
        if sec is None:
            continue
        gub, uezd = sec
        src = ("раздел бумажной описи 39 (губерния и уезд)" if uezd
               else "раздел бумажной описи 39 (губерния); уезд не определён")
        if delo in UNPARSED_UEZD:
            src = ("раздел бумажной описи 39 (губерния); уезд не снят — "
                   "листы 172–173 не разобраны")
        out_rows.append({
            "fund_code": r["fund_code"], "delo": delo, "territory": gub, "uezd": uezd,
            "territory_source": src, "title": r.get("title", ""),
            "date_raw": r.get("date_raw", ""), "year_from": r.get("year_from", ""),
            "year_to": r.get("year_to", ""), "sheets": r.get("sheets", ""),
            "url": r.get("url", ""),
        })
        by_gub[gub] = by_gub.get(gub, 0) + 1

    out_rows.sort(key=lambda r: r["delo"])
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "op39_with_territory.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)

    with_uezd = sum(1 for r in out_rows if r["uezd"])
    (OUT / "REPORT.json").write_text(json.dumps({
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "source_queue": str(PKG / "review_queue.csv"),
        "queue_op39": sum(1 for r in rows if " Оп. 39 Д. " in (r.get("fund_code") or "")),
        "matched": len(out_rows),
        "by_guberniya": by_gub,
        "with_uezd": with_uezd,
        "sections_from": "скан 380_39.pdf, листы 51-53, 104-105, 131, 168-176",
        "note": "Дела 2050-2093 — губерния Ярославская достоверна (раздел описи), уезд не "
                "снят: листы 172-173 (сканы 177-178) не разобраны.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"записей описи 39 в очереди: "
          f"{sum(1 for r in rows if ' Оп. 39 Д. ' in (r.get('fund_code') or ''))}")
    print(f"получили территорию: {len(out_rows)} (из них с уездом {with_uezd})")
    for g, n in sorted(by_gub.items(), key=lambda x: -x[1]):
        print(f"  {g:<22} {n}")
    print(f"\nвыход: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
