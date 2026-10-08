"""Разбор записей описей 38-41 фонда 380 РГИА: уточнение территории.

Зачем: описи 10, 21, 28 — губернские (Калужская, Пермская, Смоленская), там территория
определяется из заголовка дела надёжно (936 + 724 + 2052 = 3712 записей, у всех территория
проставлена). Описи 38-41 — сводные каталоги «Планового архива Министерства земледелия»
по всей империи: из 2633 записей территория определилась только у 17.

Остальные 2616 попали в набор как `territory_not_resolved` → keep + needs_human (заложенное
поведение гейта: «где объём не угрожает, помечать, а не выбрасывать»). Разобрать их машинно
нужно потому, что 2616 записей на ручной просмотр — это неподъёмная очередь, а бо́льшая часть
из них очевидно про чужие губернии (Виленская, Волынская, Черниговская, Харьковская…).

Что делает скрипт (НЕ меняя исходный records.csv):
  1. берёт записи описей 38-41 без территории;
  2. ищет в заголовке наши губернии и наши уезды (строгие пары «название + губерния/уезд»);
  3. ищет чужие губернии; если есть чужая и нет нашей — помечает `foreign_only`;
  4. остальное оставляет человеку.

Запуск из корня проекта:
    python -B scripts_rgia/retag_fund380_opisi_38_41.py
    python -B scripts_rgia/retag_fund380_opisi_38_41.py --src C:/arch/output/rgia_fund380_20261003_v3_1
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
DEFAULT_SRC = Path("C:/arch/output/rgia_fund380_20261003_v3_1")
OPISI = {"fund380_opis_38", "fund380_opis_39", "fund380_opis_40", "fund380_opis_41"}

GUB = r"губерн\w*|наместничеств\w*"
OURS = {
    "Калужская": re.compile(rf"Калужск\w*\s+(?:{GUB})", re.I),
    "Пермская": re.compile(rf"Пермск\w*\s+(?:{GUB})", re.I),
    "Смоленская": re.compile(rf"Смоленск\w*\s+(?:{GUB})", re.I),
    "Ярославская": re.compile(rf"Ярославск\w*\s+(?:{GUB})", re.I),
}
# Уезды наших губерний — территория может быть названа уездом без губернии
UEZD = {
    "Калужская": r"Боровск|Жиздринск|Козельск|Лихвинск|Малоярославецк|Медынск|Мещовск|"
                 r"Мосальск|Перемышльск|Тарусск|Калужск",
    "Пермская": r"Верхотурск|Екатеринбургск|Ирбитск|Камышловск|Красноуфимск|Кунгурск|"
                r"Осинск|Оханск|Соликамск|Чердынск|Шадринск|Пермск",
    "Смоленская": r"Бельск|Вяземск|Гжатск|Дорогобужск|Духовщинск|Ельнинск|Краснинск|"
                  r"Поречск|Рославльск|Сычевск|Юхновск|Смоленск",
    "Ярославская": r"Даниловск|Любимск|Мологск|Мышкинск|Пошехонск|Романово-Борисоглебск|"
                   r"Ростовск|Рыбинск|Угличск|Ярославск",
}
UEZD_RX = {k: re.compile(rf"(?:{v})\w*\s+уезд\w*", re.I) for k, v in UEZD.items()}
# Ловушки: «Ростовский» бывает и про Ростов-на-Дону / Дмитрия Ростовского
FALSE = re.compile(r"Ростовск\w*\s+крепост|Дмитри\w*\s+Ростовск|Ростов[а-я]*[- ]на[- ]Дону", re.I)
ANY_GUB = re.compile(rf"([А-ЯЁ][а-яё\-]+ск(?:ая|ой|ого|ом|ую))\s+(?:{GUB})", re.I)


def classify(title: str) -> dict:
    t = title or ""
    ours, evid = [], []
    for name, rx in OURS.items():
        m = rx.search(t)
        if m:
            ours.append(name)
            evid.append(f"{name}:губерния «{m.group(0)}»")
    for name, rx in UEZD_RX.items():
        m = rx.search(t)
        if m and not FALSE.search(t):
            if name not in ours:
                ours.append(name)
            evid.append(f"{name}:уезд «{m.group(0)}»")
    foreign = sorted({m.group(1) for m in ANY_GUB.finditer(t)}
                     - {"Калужская", "Калужской", "Пермская", "Пермской",
                        "Смоленская", "Смоленской", "Ярославская", "Ярославской"})
    if ours:
        return {"decision": "ours", "territory": "; ".join(ours),
                "evidence": "; ".join(evid), "foreign": foreign}
    if foreign:
        return {"decision": "foreign_only", "territory": "",
                "evidence": "чужие губернии: " + ", ".join(foreign[:6]), "foreign": foreign}
    # Дальше — записи без названной территории. Их три разных вида, и смешивать нельзя.
    if re.match(r"\s*(?:хронологическ\w*|систематическ\w*|алфавитн\w*)?\s*каталог\b", t, re.I):
        return {"decision": "catalog", "territory": "",
                "evidence": "опись описей: каталог карт и планов, а не сам картографический документ",
                "foreign": []}
    if re.search(r"\b(?:Росси\w*|Европейск\w*\s+Росси\w*|импери\w*|Сибир\w*|"
                 r"Привислинск\w*|Закавказ\w*|Кавказ\w*|Царств\w*\s+Польск\w*|"
                 r"[а-яё]+ск\w*\s+(?:округ\w*|край|края)|Балтийск\w*)\b", t, re.I):
        return {"decision": "supra_regional", "territory": "",
                "evidence": "уровень выше губернии (страна, округ, край) — §1.2",
                "foreign": []}
    if re.search(r"\b(?:карт\w*|план\w*|чертеж\w*)\s+(?:губерни\w*|уезд\w*|дач\w*|лесничеств\w*)",
                 t, re.I):
        return {"decision": "unnamed_region", "territory": "",
                "evidence": "губерния/уезд не названы в заголовке — нужна карточка или опись",
                "foreign": []}
    return {"decision": "unresolved", "territory": "", "evidence": "территория не названа",
            "foreign": []}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    args = ap.parse_args()
    src = Path(args.src)
    rec = src / "records.csv"
    if not rec.exists():
        print(f"нет файла: {rec}")
        return 2

    with rec.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    target = [r for r in rows if r.get("keyword") in OPISI]
    print(f"записей в records.csv: {len(rows)}; в описях 38-41: {len(target)}")

    out = []
    counts = {"ours": 0, "foreign_only": 0, "catalog": 0, "supra_regional": 0,
              "unnamed_region": 0, "unresolved": 0, "already": 0}
    for r in target:
        if (r.get("territory") or "").strip():
            counts["already"] += 1
            continue
        v = classify(r.get("title") or "")
        counts[v["decision"]] += 1
        out.append({
            "opis": r.get("keyword", "").replace("fund380_opis_", ""),
            "fund_code": r.get("fund_code", ""),
            "title": (r.get("title") or "")[:220],
            "url": r.get("url", ""),
            "year_from": r.get("year_from", ""),
            **v,
        })

    print("\nрезультат разбора:")
    for k, v in counts.items():
        print(f"  {k:<14} {v}")

    outdir = ROOT / "output" / f"rgia_fund380_opisi38_41_retag_{time.strftime('%Y%m%d')}"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "retag.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n", encoding="utf-8")
    ours = [r for r in out if r["decision"] == "ours"]
    with (outdir / "ours.csv").open("w", encoding="utf-8-sig", newline="") as f:
        if ours:
            w = csv.DictWriter(f, fieldnames=list(ours[0]))
            w.writeheader()
            w.writerows(ours)

    print(f"\nНАШИ ({len(ours)}), примеры:")
    for r in ours[:12]:
        print(f"  оп.{r['opis']} [{r['territory'][:22]:<22}] {r['title'][:78]}")
    print(f"\nвыход: {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
