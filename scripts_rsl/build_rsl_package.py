"""РГБ: собрать найденные карточки в пакет каталога и прогнать общим гейтом.

Источник прогнан впервые 20.10.2026. Маршрут — внешний поиск: `search.rsl.ru` закрывает
роботам каталог (`Disallow: /`), но явно разрешает карточки (`Allow: /ru/record`), а
Яндекс их индексирует. Обойти разрешённое напрямую нельзя: sitemap даёт ~10,4 млн URL без
заголовков.

Гейт переиспользуется из `scripts_gaso/build_gaso_package.py` — правила отбора общие для
всех источников, расхождение между ними было бы дефектом (так же сделано по ГАЯО и ГАКО).

У РГБ своя особенность против архивов: это БИБЛИОТЕКА, и в выдачу попадают современные
издания — советские топокарты 1:500 000, «Археологическая карта России» по областям,
учебные атласы. Они картографические, но не исторические губернские карты, поэтому к
общему гейту добавлена отсечка по веку: в каталог идёт изданное до 1930 г., остальное —
в needs_human с причиной (решение по дате — за приёмщиком, не за сборщиком).

Запуск:
    python -B scripts_rsl/build_rsl_package.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts_gaso"))
from build_gaso_package import OUT_FIELDS, apply_gate, norm_sign  # noqa: E402

SRC = ROOT / "output" / "rsl_yandex_20261020" / "rsl_cards.jsonl"
OUT = ROOT / "output" / "rsl_package_20261020"

GUB = {
    "Калужская": r"Калуж|Боровск|Козельск|Медын|Мосальск|Тарус|Жиздр|Мещовск|Перемышл|Лихвин",
    "Смоленская": r"Смоленск|Вязем|Вязьм|Гжатск|Дорогобуж|Духовщин|Рославл|Сычев|Юхнов|Ельнин|Поречск",
    "Ярославская": r"Ярослав|Ростовск|Углич|Мышкин|Пошехон|Молог|Рыбинск|Любим|Данилов|Романово",
    "Пермская": r"Пермск|\bПерм[ьи]\b|Соликамск|Чердын|Кунгур|Оханск|Осинск|Верхотур|Ирбит"
                r"|Шадринск|Красноуфимск|Камышлов|Екатеринбург",
}
# ⚠️ Ловушки, пойманные приёмщиком 20.10 уже ПОСЛЕ внесения — защита обязательна:
#  * «Карта Ростовского пригородного района Северо-Кавказского края» → «Ростовск» дало
#    Ярославскую (тот же капкан, что «Ростов на Дону» в ГАЯО ф. 560);
#  * «План города Стерлитамака Уфимской губернии … ж. д. Оренбург — Уфа — Пермь» →
#    «Пермь» в названии МАРШРУТА дало Пермскую.
# Правило: если названа чужая территория, запись не принимается автоматически.
ALIEN = re.compile(
    r"Ростов\w*[-\s]*на[-\s]*Дону|Северо-Кавказск|Стерлитамак|Уфимск|Оренбургск|Донск"
    r"|Таврическ|Херсонск|Киевск|Полтавск|Черниговск|Волынск|Подольск(?:ой|ая)\s+губ"
    r"|Тобольск|Томск|Енисейск|Иркутск|Якутск|Забайкальск|Приморск|Амурск|Туркестанск"
    r"|Закаспийск|Эриванск|Тифлисск|Бакинск|Кутаисск|Варшавск|Ковенск|Виленск|Гродненск"
    r"|Лифляндск|Эстляндск|Курляндск|Финлянд", re.I)
CARTO = re.compile(r"\[Карты\]|\bкарт[аыуеой]\b|\bкарты\b|\bплан\b|\bпланы\b|атлас|чертеж"
                   r"|чертёж|съемк|съёмк|топограф|межев|картограмм", re.I)
YEAR = re.compile(r"\b(1[5-9]\d{2}|19[0-2]\d|19[3-9]\d|20[0-2]\d)\b")
# Современные издания, которые по предмету карты, но не исторические губернские
MODERN = re.compile(r"\bСССР\b|Археологическая карта России|Российская Федерация"
                    r"|\bобласт[ьи]\b.*\b(19[5-9]\d|20\d\d)\b|атлас автомобильных дорог", re.I)


def years(text: str) -> tuple[str | None, str | None]:
    yy = YEAR.findall(text or "")
    if not yy:
        return None, None
    return yy[0], (yy[-1] if yy[-1] != yy[0] else None)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)

    rows, skipped = [], 0
    for ln in SRC.open(encoding="utf-8"):
        c = json.loads(ln)
        title = (c.get("zagolovok") or "").strip()
        text = f"{title} {c.get('snippet', '')}"
        if not title or not CARTO.search(text):
            skipped += 1
            continue
        gub = [g for g, p in GUB.items() if re.search(p, text, re.I)]
        if not gub:
            skipped += 1
            continue
        d1, d2 = years(text)
        note = ["РГБ, карточка электронного каталога"]
        if c.get("snippet"):
            note.append(c["snippet"][:200])
        rows.append({
            "fund": "", "opis": "", "n_delo": c.get("record_id", ""),
            "zagolovok": title,
            "data_nachato": d1, "data_okoncheno": d2,
            "listov": None, "obyekt": None,
            "kartograficheskiy_priznak": norm_sign(None, title),
            "primechanie": "; ".join(note),
            "sposob": "РГБ: карточка каталога (найдена внешним поиском)",
            "page": None,
            "flags": f"rsl;record{c.get('record_id', '')}",
            "territoriya": "; ".join(gub),
            "url": c.get("url", ""),
            "sovremennoe_izdanie": "да" if MODERN.search(text) else "",
            "chuzhaya_territoriya": (m.group(0) if (m := ALIEN.search(text)) else ""),
        })

    for r in rows:
        r["gate"], r["gate_reason"] = apply_gate(r)
        # отдельная отсечка: современное издание в каталог исторических карт не идёт
        if r["sovremennoe_izdanie"] == "да" and r["gate"] == "принято":
            r["gate"] = "needs_human"
            r["gate_reason"] = "современное издание (СССР/РФ) — решение о внесении за приёмщиком"
        # ⚠️ НЕ в отсев: под это правило попадают общероссийские атласы, которые чужую
        # территорию называют наряду с нашими («Атлас российской, состоящей из 19
        # специальных карт», «Ф.945 Карты и планы губерний, уездов и местностей»).
        # Выбрасывать их нельзя — решение за человеком.
        if r["chuzhaya_territoriya"] and r["gate"] == "принято":
            r["gate"] = "needs_human"
            r["gate_reason"] = (f"названа чужая территория «{r['chuzhaya_territoriya']}»: "
                                "либо ложное совпадение, либо общероссийский атлас с нашими "
                                "губерниями в составе — нужен просмотр карточки")

    fields = [*OUT_FIELDS, "territoriya", "url", "sovremennoe_izdanie", "chuzhaya_territoriya"]

    def dump(name: str, data: list[dict]) -> None:
        if not data:
            return
        with (OUT / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)
        with (OUT / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps({k: r.get(k) for k in fields}, ensure_ascii=False) + "\n")

    acc = [r for r in rows if r["gate"] == "принято"]
    nh = [r for r in rows if r["gate"] == "needs_human"]
    drop = [r for r in rows if r["gate"] == "отсев"]
    dump("rsl_all_records", rows)
    dump("rsl_accepted", acc)
    dump("rsl_needs_human", nh)
    dump("rsl_scope_drops", drop)

    print(f"карточек в наборе: {sum(1 for _ in SRC.open(encoding='utf-8'))}, "
          f"не картографические или не наши: {skipped}")
    print(f"в пакете: {len(rows)}")
    print(f"  принято:     {len(acc)}")
    print(f"  needs_human: {len(nh)}")
    print(f"  отсев:       {len(drop)}")
    print("\nпо губерниям (принято):")
    for g, n in Counter(x for r in acc for x in r["territoriya"].split("; ")).most_common():
        print(f"  {n:>4}  {g}")
    print("\nпризнак у принятых:")
    for s, n in Counter(r["kartograficheskiy_priznak"] for r in acc).most_common(8):
        print(f"  {n:>4}  {s}")
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
