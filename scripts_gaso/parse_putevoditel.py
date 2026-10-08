"""Разбор путеводителя ГАСО: поиск картографических фондов.

Путеводитель скачан с сайта архива (`gaso-smolensk.ru/wp-content/uploads/2024/10/
putevoditel_v_tipogr0.doc`), формат — старый Word (OLE2), текст внутри в UTF-16LE.
Полноценный парсер OLE не нужен: нам нужны заголовки фондов и упоминания карт.

Зачем: на портале ГАСО списка дел нет (вкладка «Единицы хранения» пуста), есть только
сканы описей. Значит единственный способ понять, ЧТО в архиве есть по картографии —
прочитать путеводитель и выписать фонды, где упомянуты планы, карты, чертежи, межевание.

Запуск из корня проекта:
    python -B scripts_gaso/parse_putevoditel.py
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "input_gaso" / "putevoditel_gaso.doc"
OUT = ROOT / "output" / f"gaso_putevoditel_{time.strftime('%Y%m%d')}"

# Номер фонда в путеводителе: «Ф. 259», «ФОНД 259», иногда с буквой («Ф. Р-1234»)
FUND = re.compile(r"\bФ(?:ОНД|\.)\s*(Р?-?\s?\d{1,5})\b", re.I)
# Картографические признаки
CARTO = re.compile(r"карт(?:а|ы|ой|е|у|ам|ах)?\b|картограф\w*|план(?:ы|ов|а|е)?\b|"
                   r"чертеж\w*|чертёж\w*|межев\w*|землемер\w*|топограф\w*|атлас\w*|"
                   r"съемк\w*|съёмк\w*|геодез\w*", re.I)
# Явно нерелевантное употребление слова «план»
NOISE = re.compile(r"план\w*\s+(?:работ|мероприят|развити|застройк[иа]\s+на|"
                   r"социальн|производств|посевн|финансов|учебн|пятилетн)", re.I)


def clean(s: str) -> str:
    s = s.replace("\x00", " ").replace("\r", "\n")
    s = re.sub(r"[^\S\n]+", " ", s)
    return re.sub(r"\n{2,}", "\n", s).strip()


def main() -> int:
    if not SRC.exists():
        print(f"нет файла: {SRC}")
        return 2
    raw = SRC.read_bytes()
    text = clean(raw.decode("utf-16-le", "ignore"))
    print(f"текст путеводителя: {len(text):,} знаков".replace(",", " "))

    # Разбиваем по упоминаниям номеров фондов и смотрим окно вокруг каждого
    hits: dict[str, dict] = {}
    for m in FUND.finditer(text):
        num = re.sub(r"\s+", "", m.group(1)).upper()
        win = text[max(0, m.start() - 200): m.start() + 1200]
        carto = [x.group(0).lower() for x in CARTO.finditer(win)]
        if not carto:
            continue
        noise = len(NOISE.findall(win))
        rec = hits.setdefault(num, {"fund": num, "mentions": 0, "terms": set(),
                                    "noise": 0, "samples": []})
        rec["mentions"] += 1
        rec["terms"].update(carto)
        rec["noise"] += noise
        if len(rec["samples"]) < 2:
            # Формат путеводителя: «<Название фонда> Ф. 259. 269 ед. хр. 1750-1915 гг. 1 оп.»
            # Название стоит ПЕРЕД номером, после номера идут объёмы.
            head = text[max(0, m.start() - 300): m.start()]
            name = re.split(r"\n|(?<=[а-яё])\.\s(?=[А-ЯЁ])|оп\.\s*", head)[-1]
            vol = re.match(r"[.\s]*(\d[\d\s]*ед\.?\s*хр\.?[^.]{0,45}\.?\s*\d*\s*оп\.?)",
                           text[m.end(): m.end() + 130])
            rec["samples"].append(
                re.sub(r"\s+", " ", name).strip()[:160]
                + (" — " + re.sub(r"\s+", " ", vol.group(1)).strip() if vol else ""))

    rows = sorted(hits.values(), key=lambda r: -(r["mentions"]))
    strong = [r for r in rows if r["mentions"] >= 2 or len(r["terms"]) >= 3]
    print(f"фондов с картографическими упоминаниями: {len(rows)}; "
          f"из них с устойчивым признаком: {len(strong)}")

    OUT.mkdir(parents=True, exist_ok=True)
    lines = [f"# ГАСО: картографические фонды по путеводителю — {time.strftime('%Y-%m-%d')}", "",
             "Источник: `gaso-smolensk.ru/wp-content/uploads/2024/10/putevoditel_v_tipogr0.doc`",
             f"(скачан в `input_gaso/putevoditel_gaso.doc`, {len(raw) / 1024 / 1024:.1f} МБ, "
             f"текст {len(text):,} знаков).".replace(",", " "), "",
             "Отбор механический: номер фонда + картографические термины в окне ±1200 знаков.",
             "Это **кандидаты для проверки**, а не готовый список — проверять по самим описям.", "",
             f"## Фонды с устойчивым признаком ({len(strong)})", "",
             "| Фонд | Упом. | Термины | Фрагмент названия |", "|---|---|---|---|"]
    for r in strong[:60]:
        terms = ", ".join(sorted(r["terms"])[:6])
        sample = (r["samples"][0] if r["samples"] else "").replace("|", "/")
        lines.append(f"| Ф. {r['fund']} | {r['mentions']} | {terms} | {sample} |")
    (OUT / "KARTO_FONDY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nтоп-15 по числу упоминаний:")
    for r in strong[:15]:
        print(f"  Ф.{r['fund']:<8} упом.{r['mentions']:<3} "
              f"{(r['samples'][0] if r['samples'] else '')[:88]}")
    print(f"\nотчёт: {OUT / 'KARTO_FONDY.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
