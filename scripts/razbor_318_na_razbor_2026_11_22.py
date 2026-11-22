"""Разбор 318 записей набора 4.1, оставленных «на разбор человеком» (22.11.2026).

Откуда группа. При сборке набора 4.1 решение владельца было: периодика и тексты 1918 года
и позже — отсев. 318 записей под это решение не подвести было нельзя:
  * 259 — класс «текст», поле года пустое (отсеивать по дате нечем);
  * 59 — дореволюционные, но вид источника классификатор не опознал («прочее»).

Что делает скрипт. Не спрашивает владельца там, где ответ можно ДОБРАТЬ, и спрашивает
там, где нужно решение:

  1. Год из названия. У библиотечных записей выходные данные стоят в самом
     библиографическом описании («- Воронеж : [ВГЛТА], 2004. - 93 с.»). 53 записи из 259
     так датируются сразу, и все 53 — 2000-е годы.
  2. Год из карточки. Остальные 206 датируются обходом карточек
     (harvest_cards.py --queue …/god_dobor/queue.jsonl): у ПГКБ есть подписанное поле
     «Дата публикации», у ПрБ и РГБ — выходные данные в блоке «Описание». Год берётся
     только из подписанного места, с locator'ом; голых чисел из текста не берём
     (память feedback_guess-in-numeric-field-poisons-analysis).
  3. Решение владельца о 1918 годе применяется к добранным годам — это ИСПОЛНЕНИЕ уже
     принятого решения, а не новое. Механизм отсева тот же, что у 270 вне-скоупных:
     «Статус приёмки» = «отклонено» с причиной, не удаление.
  4. Что решением не закрывается, уходит в журнал `k_resheniyu_vladeltsa.csv`:
     навигационные узлы каталога (не источники), современная историография и
     авторефераты диссертаций, богослужебные книги, записи без установленного года.

Выход — `decisions/razbor_318/`:
  itog.csv                  — все 318 с годом, его источником и предлагаемым решением;
  k_otkloneniyu_1918.csv    — к отсеву по уже принятому решению;
  k_resheniyu_vladeltsa.csv — то, на что решения нет;
  v_skoupe.csv              — остаются в каталоге как есть.

  python scripts/razbor_318_na_razbor_2026_11_22.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import fix_stdout  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
W = ROOT / "output" / "upload_2026-11-22-series"
LIST = W / "decisions" / "na_razbor.csv"
OUTDIR = W / "decisions" / "razbor_318"
HARVEST = Path(sys.argv[1]) if len(sys.argv) > 1 else None

URL = "Ссылка на онлайн-архив"
NAME = "Название источника"
GRAN = 1918            # граница хронологии проекта (решение владельца по набору 4.1)

YEAR_ANY = re.compile(r"\b(1[5-9]\d\d|20[0-2]\d)\b")

# Навигационный узел каталога библиотеки, а не источник: рубрика по годам издания,
# раздел «Периодические издания», карточка самого учреждения.
NAV = (
    re.compile(r"^Издания\s+\d{4}\s*[-–]\s*\d{4}\s+годов", re.I),
    re.compile(r"^(Периодические издания|Календари и ежегодники|Карты и атласы|"
               r"Книжные издания|Фотографии|Рукописи)\b", re.I),
    re.compile(r"(библиотека\s*[—-]\s*филиал|как центр научно-исследовательских)", re.I),
)
# Современная исследовательская литература и авторефераты: это не исторический источник,
# а работа О нашем предмете. Признак — слово «дис.»/«диссертация» или год издания 1918+
# при дореволюционном предмете.
DISSER = re.compile(r"(Автореф(?:ерат)?\.?\s*дис|диссертаци|на соиск(?:ание)?\.?\s*учен)", re.I)
# Богослужебные книги: вид источника к проекту не относится вовсе.
LITURG = re.compile(r"^(Синодик|Канонник|Минея|Триодь|Октоих|Псалтирь|Часослов|Требник)\b", re.I)


def norm(u: str) -> str:
    return (u or "").strip().rstrip("/")


def year_from_title(title: str) -> int | None:
    """Год выхода издания из библиографического описания в названии записи.

    Берём НАИБОЛЬШИЙ найденный год: в описании по ГОСТ рядом стоят годы предмета
    («1812-1912»), а нас интересует год издания, он в выходных данных последний.
    """
    ys = [int(y) for y in YEAR_ANY.findall(title or "")]
    return max(ys) if ys else None


def main() -> None:
    fix_stdout()
    rows = list(csv.DictReader(LIST.open(encoding="utf-8-sig")))
    harvested: dict[str, dict] = {}
    if HARVEST and HARVEST.exists():
        for ln in HARVEST.open(encoding="utf-8"):
            if not ln.strip():
                continue
            r = json.loads(ln)
            harvested[norm(r.get("url", ""))] = r
    print(f"записей на разбор: {len(rows)} | добрано карточек: {len(harvested)}")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    itog: list[dict] = []
    for r in rows:
        name = r[NAME] or ""
        h = harvested.get(norm(r[URL]), {})
        god, src = None, ""
        if h.get("god_izdaniya"):
            god, src = int(h["god_izdaniya"]), f"карточка: {h.get('god_locator', '')}"
        elif (y := year_from_title(name)):
            god, src = y, "выходные данные в названии записи"
        elif r.get("Год создания (верхняя)"):
            god, src = int(r["Год создания (верхняя)"]), "поле записи «Год создания (верхняя)»"

        verdict, why = "", ""
        if any(p.search(name) for p in NAV):
            verdict, why = "к решению", "навигационный узел каталога библиотеки, а не источник"
        elif LITURG.match(name.strip()):
            verdict, why = "к решению", "богослужебная книга — вид источника вне предмета проекта"
        elif DISSER.search(name):
            verdict, why = "к решению", "автореферат диссертации — исследовательская работа, не источник"
        elif god is None:
            verdict, why = "к решению", "год не установлен ни в названии, ни в карточке"
        elif god >= GRAN and (m := re.search(rf"(1[5-9]\d\d)\s*[-–—]\s*{god}\b", name)) \
                and int(m.group(1)) < GRAN:
            # Издание выходило несколько лет и граница 1918 прошла внутри него
            # («Одесса : Экономическая тип., 1906-1918»): часть томов дореволюционная,
            # механически такую запись отсеивать нельзя.
            verdict = "к решению"
            why = (f"издание выходило {m.group(1)}–{god}: граница 1918 прошла внутри, "
                   "часть выпусков дореволюционная")
        elif god >= GRAN:
            verdict, why = "отклонить 1918+", f"год издания {god} — решение владельца по набору 4.1"
        else:
            verdict, why = "в скоупе", f"год издания {god} — в хронологических границах проекта"

        itog.append({"решение": verdict, "причина": why, "год": god or "",
                     "источник года": src, "держатель": r.get("Место хранения", ""),
                     "группа": r["_причина"], "название": name[:300], "ссылка": r[URL],
                     "контекст года": (h.get("god_ctx") or "")[:120],
                     "библ. описание": (h.get("bibl_opisanie") or "")[:300],
                     "статус добора": h.get("status", "не добиралось")})

    cols = list(itog[0].keys())

    def dump(path: Path, data: list[dict]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(data)

    dump(OUTDIR / "itog.csv", itog)
    groups = {
        "k_otkloneniyu_1918.csv": [x for x in itog if x["решение"] == "отклонить 1918+"],
        "k_resheniyu_vladeltsa.csv": [x for x in itog if x["решение"] == "к решению"],
        "v_skoupe.csv": [x for x in itog if x["решение"] == "в скоупе"],
    }
    for fn, data in groups.items():
        dump(OUTDIR / fn, data)
        print(f"  {fn}: {len(data)}")

    print("\nпо решениям и поводам:")
    from collections import Counter
    short = Counter()
    for x in itog:
        w = x["причина"]
        w = re.sub(r"год издания \d{4}.*", "год издания в границах/вне границ", w)
        w = re.sub(r"издание выходило .*", "издание на границе 1918 года", w)
        short[f"{x['решение']}: {w}"] += 1
    for why, n in short.most_common():
        print(f"  {n:4d}  {why}")
    print("\nисточник года:")
    for src, n in Counter(x["источник года"] or "не установлен" for x in itog).most_common():
        print(f"  {n:4d}  {src}")
    print("\nгоды отклоняемых по десятилетиям:")
    for d, n in sorted(Counter((x["год"] // 10 * 10) for x in groups["k_otkloneniyu_1918.csv"]
                               if isinstance(x["год"], int)).items()):
        print(f"  {d}-е: {n}")
    print(f"\nжурналы: {OUTDIR}")


if __name__ == "__main__":
    main()
