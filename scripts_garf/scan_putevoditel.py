"""ГАРФ: поиск картографии в путеводителе (5 томов PDF с текстовым слоем).

Зачем путеводитель, а не сайт: `statearchive.ru/robots.txt` запрещает нас адресно
(`User-agent: anthropic-ai → Disallow: /`, рядом GPTBot, CCBot, openai). Обходить не
станем, а путеводитель у нас есть файлами.

⚠️ Что уже выяснилось и чего путеводитель НЕ покажет. По тому 1 я сделал вывод «карт по
нашим губерниям нет» — он оказался неверным: семантическая система ГА РФ (garf-nika.ru)
находит «Карта Калужской губернии 1913» и «Карта Пермской губернии 1913» в ф. 102
оп. 70 д. 10 ч. 27 прил. 4 и 8. Путеводитель описывает ФОНДЫ, а карты лежат
ПРИЛОЖЕНИЯМИ К ДЕЛАМ — уровнем ниже. Поэтому здесь ищем не полный список карт, а
указания на фонды и коллекции, где картография вообще заявлена.

Выход: garf_putevoditel_hits.csv — совпадения с контекстом, том и страница.

Запуск:
    python -B scripts_garf/scan_putevoditel.py
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(r"D:\Yandex.Disk\History&Geography\Архивы\ГАРФ")
OUT = ROOT / "output" / "garf_putevoditel_20261020"

# Картографический признак. «Карточка», «картотека», «картон», «картофель» — НЕ карты:
# в томе 1 именно они дали почти все ложные совпадения.
CARTO = re.compile(
    r"\bкарт[аыуеой]\b|\bкарты\b|\bкартам\b|\bкартах\b|\bплан[ыаеу]?\b|\bпланов\b"
    r"|\bчертеж\w*|\bчерт[её]ж\w*|\bатлас\w*|\bсъ[её]мк\w*|\bтопограф\w*"
    r"|\bмежев\w*|\bкартограф\w*|\bглобус\w*", re.I)
FALSE = re.compile(r"карточ|картотек|картон|картофел|плановы[йех]\s+отдел|по плану работ", re.I)
GUB = re.compile(r"Калужск\w*|Смоленск\w*|Ярославск\w*|Пермск\w*|\bПерм[ьи]\b"
                 r"|Соликамск\w*|Чердын\w*|Кунгур\w*|Верхотур\w*|Шадринск\w*"
                 r"|Вязем\w*|Гжатск\w*|Дорогобуж\w*|Рославл\w*|Юхновск\w*"
                 r"|Ростовск\w*|Углич\w*|Мышкин\w*|Пошехон\w*|Рыбинск\w*|Молог\w*"
                 r"|Боровск\w*|Козельск\w*|Медынск\w*|Мосальск\w*|Тарусск\w*", re.I)
FUND = re.compile(r"Ф(?:онд)?\.?\s*(\d+)", re.I)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []

    for pdf in sorted(SRC.glob("Putevoditel-Tom*.pdf")):
        doc = pymupdf.open(pdf)
        tom = re.search(r"Tom(\d+)", pdf.name).group(1)
        hits = 0
        fund_now = ""
        for i, page in enumerate(doc, 1):
            text = page.get_text()
            f = FUND.search(text)
            if f:
                fund_now = f.group(1)
            for m in CARTO.finditer(text):
                a, b = max(0, m.start() - 130), min(len(text), m.end() + 170)
                frag = re.sub(r"\s+", " ", text[a:b]).strip()
                if FALSE.search(frag):
                    continue
                rows.append({
                    "tom": tom, "stranica": i, "fond_na_stranice": fund_now,
                    "slovo": m.group(0),
                    "nashi_gubernii": "; ".join(sorted({g.group(0) for g in GUB.finditer(frag)})),
                    "kontekst": frag,
                })
                hits += 1
        print(f"том {tom}: страниц {doc.page_count}, совпадений {hits}")
        doc.close()

    with (OUT / "garf_putevoditel_hits.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["tom"])
        w.writeheader()
        w.writerows(rows)

    withgub = [r for r in rows if r["nashi_gubernii"]]
    print(f"\nвсего совпадений: {len(rows)}")
    print(f"из них рядом с нашими губерниями: {len(withgub)}")
    for r in withgub[:25]:
        print(f"  т.{r['tom']} с.{r['stranica']} [ф.{r['fond_na_stranice']}] "
              f"[{r['nashi_gubernii']}]")
        print(f"     …{r['kontekst'][:150]}…")
    print(f"\n→ {OUT / 'garf_putevoditel_hits.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
