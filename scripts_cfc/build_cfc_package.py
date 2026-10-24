"""ЦФК: собрать найденные единицы хранения в пакет каталога.

Источник — Центральный фондовый каталог Росархива, поиск по всему Архивному фонду РФ до
уровня дел. Прогон 20.10: 48 запросов → 128 карточек, 98 уникальных заголовков.

Что в них:
 * ГАРФ — 39 дел, почти все ф. Р-6890 оп. 2 (коллекция карт губерний при комиссии по
   районированию), с масштабом и носителем прямо в заголовке. Этого у нас не было.
 * ГАЯО — 84 карточки из фондов 455, 560, 82, 80, 76: это ПРОВЕРКА нашего же сбора,
   повторно в каталог не идут (помечаются `uzhe_sobrano`).
 * Неожиданные держатели: ЦГА Удмуртской Республики (личный фонд Р-1707), архивные
   отделы Ильинского и Осинского районов — муниципальные архивы, которых не было ни в
   одном нашем списке.

⚠️ Ловушка в самих данных: «Карта Боровского уезда ВОРОНЕЖСКОЙ губернии» и «Карта
Жиздринского уезда БРЯНСКОЙ губернии». Боровский и Жиздринский — калужские уезды по
названию, но после перекройки границ 1920-х отнесены к другим губерниям. Такие записи
уходят в needs_human, а не в каталог.

Запуск:
    python -B scripts_cfc/build_cfc_package.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "output" / "cfc_sweep_20261020" / "cfc_units.jsonl"
OUT = ROOT / "output" / "cfc_package_20261020"

GUB = {
    "Калужская": r"Калужск",
    "Смоленская": r"Смоленск",
    "Ярославская": r"Ярославск",
    "Пермская": r"Пермск|Екатеринбургск",
}
UEZD_GUB = {
    "Калужская": r"Боровск|Козельск|Медынск|Мосальск|Тарусск|Жиздринск|Мещовск|Перемышльск|Лихвинск",
    "Смоленская": r"Вяземск|Гжатск|Дорогобужск|Рославльск|Юхновск|Духовщинск|Ельнинск|Поречск|Сычевск",
    "Ярославская": r"Ростовск|Углич|Мышкинск|Пошехонск|Рыбинск|Мологск|Любимск|Даниловск|Романовск",
    "Пермская": r"Соликамск|Чердынск|Кунгурск|Верхотурск|Шадринск|Оханск|Осинск|Ирбитск|Красноуфимск|Камышловск",
}
# Чужая губерния, названная ЯВНО: уезд наш по имени, но отнесён к другой губернии
ALIEN_GUB = re.compile(r"\b(Воронежск|Брянск|Тверск|Владимирск|Костромск|Новгородск|Вологодск"
                       r"|Московск|Тульск|Орловск|Курск|Вятск|Уфимск|Оренбургск|Тобольск)\w*\s+губерни", re.I)
SCALE = re.compile(r"Масштаб:\s*([^.;]{2,40})", re.I)
YEAR = re.compile(r"\b(1[5-9]\d{2}|19[0-3]\d)\b")
# ⚠️ Поиск ЦФК ищет слова по всей карточке, поэтому в выдачу попадает делопроизводство,
# где губерния лишь упомянута: «Документы (протоколы, отчёты, доклады) об организационной,
# финансовой, экономической…» из новосибирского ф. Д-51. Картографический признак в
# ЗАГОЛОВКЕ обязателен.
CARTO = re.compile(r"\bкарт[аыуеой]\b|\bкарты\b|\bплан[ыаеу]?\b|\bпланов\b|атлас|чертеж"
                   r"|чертёж|съемк|съёмк|топограф|межев|картограмм|гипсометрическ", re.I)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)

    seen: set[tuple] = set()
    rows: list[dict] = []
    for ln in SRC.open(encoding="utf-8"):
        c = json.loads(ln)
        title = (c.get("zagolovok") or "").strip()
        key = (c.get("arhiv", "")[:40], c.get("fond"), c.get("opis"), c.get("n_delo"), title[:60])
        if not title or key in seen:
            continue
        seen.add(key)

        gub = [g for g, p in GUB.items() if re.search(p, title, re.I)]
        if not gub:
            gub = [g for g, p in UEZD_GUB.items() if re.search(p, title, re.I)]
        alien = ALIEN_GUB.search(title)
        arch = c.get("arhiv", "")
        already = bool(re.search(r"рославск", arch, re.I))

        sc = SCALE.search(title)
        yy = YEAR.search(title)
        rec = {
            "arhiv": arch[:120],
            "fond": (c.get("fond") or "").strip("-"),
            "opis": (c.get("opis") or "").strip("-"),
            "n_delo": (c.get("n_delo") or "").strip("-"),
            "zagolovok": title[:400],
            "data_nachato": yy.group(1) if yy else "",
            "masshtab": sc.group(1).strip() if sc else "",
            "territoriya": "; ".join(gub),
            "sposob": "ЦФК (Центральный фондовый каталог Росархива)",
            "zapros": c.get("zapros", ""),
            "uzhe_sobrano": "да (ГАЯО, собран нами)" if already else "",
            "chuzhaya_guberniya": alien.group(0) if alien else "",
        }
        if already:
            rec["status"] = "не вносить — уже собрано нашим прогоном ГАЯО"
        elif not CARTO.search(title):
            rec["status"] = "отсев — нет картографического признака в заголовке"
        elif alien:
            rec["status"] = "needs_human — уезд наш по имени, но назван в составе чужой губернии"
        elif not gub:
            rec["status"] = "needs_human — территория не опознана"
        else:
            rec["status"] = "НА ВНЕСЕНИЕ"
        rows.append(rec)

    acc = [r for r in rows if r["status"] == "НА ВНЕСЕНИЕ"]
    nh = [r for r in rows if r["status"].startswith("needs_human")]
    skip = [r for r in rows if r["status"].startswith("не вносить")]
    drop = [r for r in rows if r["status"].startswith("отсев")]

    def dump(name: str, data: list[dict]) -> None:
        if not data:
            return
        with (OUT / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0]))
            w.writeheader()
            w.writerows(data)
        with (OUT / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump("cfc_accepted", acc)
    dump("cfc_needs_human", nh)
    dump("cfc_already_collected", skip)
    dump("cfc_scope_drops", drop)

    print(f"уникальных дел: {len(rows)}")
    print(f"  НА ВНЕСЕНИЕ:          {len(acc)}")
    print(f"  needs_human:          {len(nh)}")
    print(f"  отсев (не карты):     {len(drop)}")
    print(f"  уже собрано (ГАЯО):   {len(skip)}")
    print("\nна внесение по архивам:")
    for a, n in Counter(r["arhiv"][:58] for r in acc).most_common():
        print(f"  {n:>4}  {a}")
    print("\nпо губерниям:")
    for g, n in Counter(x for r in acc for x in r["territoriya"].split("; ") if x).most_common():
        print(f"  {n:>4}  {g}")
    print(f"\nс масштабом в заголовке: {sum(1 for r in acc if r['masshtab'])}")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
