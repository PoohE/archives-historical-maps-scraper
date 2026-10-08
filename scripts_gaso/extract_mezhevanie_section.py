"""Извлечение раздела путеводителя ГАСО о межевании и землеустройстве.

Зачем: механический отбор по словам даёт шум (слово «план» ловит «планы работ»,
а номер фонда рядом с картографическим термином может принадлежать соседнему фонду —
так Ф. 13 «Смоленское отделение крестьянского поземельного банка» попал в список
как «Сычевская комиссия»). В самом путеводителе есть тематический раздел
«9.2. МЕЖЕВАНИЕ И ЗЕМЛЕУСТРОЙСТВО, ОЦЕНКА ОТЧУЖДАЕМЫХ ЗЕМЕЛЬ» — его состав
и есть авторитетный список.

Скрипт вырезает этот раздел (и, для полноты, соседние земельные разделы) и разбирает
записи вида «<Название фонда> Ф. NNN. N ед. хр. ГОДЫ гг. N оп.».

Запуск из корня проекта:
    python -B scripts_gaso/extract_mezhevanie_section.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "input_gaso" / "putevoditel_gaso.doc"
OUT = ROOT / "output" / f"gaso_putevoditel_{time.strftime('%Y%m%d')}"

# Запись фонда: название, затем «Ф. NNN. 1333 ед. хр. 1907-1917 гг. 2 оп.»
ENTRY = re.compile(
    r"(?P<name>[^.\n]{4,170}?)\s*Ф\.\s*(?P<fund>Р?-?\s?\d{1,5})\.\s*"
    r"(?P<units>\d[\d\s]{0,8})\s*ед\.?\s*хр\.?\s*"
    r"(?P<years>[\d\s,\-–]{4,70}?)\s*гг?\.\s*"
    r"(?P<opis>\d{1,2})\s*оп\.")

# Заголовки тематических разделов путеводителя (ВЕРХНИМ РЕГИСТРОМ)
SECTION = re.compile(r"\n?\s*(\d{1,2}\.\d{0,2}\.?\s+[А-ЯЁ][А-ЯЁ\s,\-]{10,90})")


def load_text() -> str:
    raw = SRC.read_bytes()
    t = raw.decode("utf-16-le", "ignore").replace("\x00", " ")
    return re.sub(r"[^\S\n]+", " ", t)


def main() -> int:
    if not SRC.exists():
        print(f"нет файла: {SRC}")
        return 2
    text = load_text()

    # все тематические разделы — чтобы знать границы
    heads = [(m.start(), re.sub(r"\s+", " ", m.group(1)).strip()) for m in SECTION.finditer(text)]
    print(f"тематических разделов в путеводителе: {len(heads)}")

    target = [h for h in heads if re.search(r"МЕЖЕВАНИ|ЗЕМЛЕУСТРОЙСТВ|ЗЕМЕЛЬ", h[1], re.I)]
    if not target:
        print("раздел о межевании не найден — проверить заголовки")
        for _, h in heads[:25]:
            print("   ", h[:80])
        return 1
    for _, h in target:
        print(f"  целевой раздел: {h[:90]}")

    rows, seen = [], set()
    for pos, head in target:
        nxt = min((p for p, _ in heads if p > pos), default=len(text))
        block = text[pos:nxt]
        for m in ENTRY.finditer(block):
            fund = re.sub(r"\s+", "", m.group("fund")).upper()
            if fund in seen:
                continue
            seen.add(fund)
            name = re.sub(r"\s+", " ", m.group("name")).strip(" *.,;:")
            # хвост предыдущей записи вида «1 оп.» в начале названия
            name = re.sub(r"^\d*\s*оп\.?\s*", "", name)
            rows.append({
                "fund": fund,
                "name": name,
                "units": int(re.sub(r"\D", "", m.group("units")) or 0),
                "years": re.sub(r"\s+", " ", m.group("years")).strip(" ,-"),
                "opisi": int(m.group("opis")),
                "section": head[:70],
            })

    rows.sort(key=lambda r: -r["units"])
    print(f"\nфондов в целевых разделах: {len(rows)}; "
          f"суммарно {sum(r['units'] for r in rows):,} ед. хр.".replace(",", " "))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "mezhevanie_fondy.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# ГАСО: фонды разделов о межевании и землеустройстве — {time.strftime('%Y-%m-%d')}", "",
             "Источник: путеводитель архива, тематические разделы (не механический поиск по словам).", "",
             f"Фондов: **{len(rows)}**, суммарно "
             f"**{sum(r['units'] for r in rows):,} ед. хр.**".replace(",", " "), "",
             "| Фонд | Название | Ед. хр. | Описей | Годы |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| Ф. {r['fund']} | {r['name']} | {r['units']} | {r['opisi']} | {r['years']} |")
    (OUT / "MEZHEVANIE_FONDY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\nтоп-12 по объёму:")
    for r in rows[:12]:
        print(f"  Ф.{r['fund']:<7} {r['units']:>6} ед.хр. {r['opisi']} оп.  {r['name'][:62]}")
    print(f"\nотчёт: {OUT / 'MEZHEVANIE_FONDY.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
