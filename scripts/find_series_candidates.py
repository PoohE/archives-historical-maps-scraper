"""Поиск в выгрузке каталога записей-кандидатов для серий 6, 7, 8, 10 (и смежных).

Ищем по содержанию (название, описание, масштаб, примечания), а не по полю связи.

  python find_series_candidates.py [--dump]
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import fix_stdout  # noqa: E402

BASELINE = Path(
    r"D:\Dropbox\Project\Pooh\19 Каталогизация исторических источников России"
    r"\Представленность исторических картографических источников в федеральных "
    r"и региональных архивах и библиотеках\данные\текущий_baseline.jsonl"
)
OUT = Path(
    r"C:\Users\admin\AppData\Local\Temp\claude"
    r"\D--IG-Dropbox-Andy-PoohV-Project-Claude"
    r"\7fbfb943-dfbd-4420-95d7-a7e98d81798e\scratchpad\series_candidates.md"
)

TEXT_FIELDS = (
    "Название источника",
    "Описание",
    "Оригинальный масштаб",
    "Примечания",
    "Связанное издание: название",
    "Автор / составитель",
)

PATTERNS = {
    "серия 6 — военно-пограничная 4 версты": [
        r"военно[- ]?пограничн",
        r"пограничн\w* карт\w*.{0,40}4 верст",
        r"4 верст\w*.{0,40}пограничн",
    ],
    "серия 7 — семитопографические 4–5 вёрст": [
        r"семи ?топограф",
        r"полутопограф",
        r"5[- ]?вёрстн|5[- ]?верстн|пятивёрстн|пятиверстн",
        r"4[- ]?вёрстн|4[- ]?верстн|четырёхвёрстн|четырехверстн",
    ],
    "серия 8 — Шуберт, десятивёрстка 1:420 000": [
        r"шуберт",
        r"специальн\w* карт\w* западн\w* част",
        r"10[- ]?вёрстн|10[- ]?верстн|десятивёрстн|десятиверстн",
    ],
    "серия 10 — трёхвёрстка Тучкова 1:126 000": [
        r"трёхвёрстн|трехверстн|3[- ]?вёрстн|3[- ]?верстн",
        r"тучков",
        r"военно[- ]?топографическ\w* карт\w* (западной|европейской) росси",
    ],
    "серия 11 — Менде": [r"менде"],
    "серия 13 — Стрельбицкий": [r"стрельбицк"],
    "знаки / легенды / инструкции": [
        r"условн\w* знак",
        r"изъяснен\w* знак",
        r"межев\w* инструкц",
        r"наставлен\w* землемер",
    ],
}
COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in PATTERNS.items()}

SCALE_HINT = {
    168000: "4 версты",
    210000: "5 вёрст",
    420000: "10 вёрст",
    126000: "3 версты",
    84000: "2 версты",
    42000: "1 верста",
}


def blob(fields: dict) -> str:
    return " \u2502 ".join(str(fields.get(f) or "") for f in TEXT_FIELDS)


def main() -> None:
    fix_stdout()
    dump = "--dump" in sys.argv

    hits: dict[str, list[dict]] = {k: [] for k in PATTERNS}
    scales: Counter = Counter()
    total = 0

    with BASELINE.open(encoding="utf-8") as f:
        for line in f:
            total += 1
            rec = json.loads(line)
            fl = rec.get("fields", {})
            text = blob(fl)
            if not text.strip():
                continue
            for key, pats in COMPILED.items():
                if any(p.search(text) for p in pats):
                    hits[key].append(
                        {
                            "page_id": rec.get("page_id"),
                            "название": str(fl.get("Название источника") or "")[:160],
                            "год": fl.get("Год источника") or fl.get("Год создания (нижняя)"),
                            "масштаб": fl.get("Масштаб (знаменатель)")
                            or fl.get("Оригинальный масштаб"),
                            "архив": fl.get("Архив [авто]") or fl.get("Место хранения"),
                            "фонд": fl.get("Фонд"),
                            "опись": fl.get("Опись"),
                            "ед.хр.": fl.get("Единица хранения"),
                            "серия": fl.get("Серия / массив"),
                        }
                    )
            sc = fl.get("Масштаб (знаменатель)")
            if isinstance(sc, (int, float)) and int(sc) in SCALE_HINT:
                scales[int(sc)] += 1

    print(f"просмотрено записей: {total}\n")
    print("НАЙДЕНО ПО КЛЮЧЕВЫМ СЛОВАМ:")
    for key, rows in hits.items():
        linked = sum(1 for r in rows if r["серия"])
        print(f"  {len(rows):>5}  {key}   (из них уже привязано к серии: {linked})")

    print("\nЗАПИСИ С ХАРАКТЕРНЫМИ МАСШТАБАМИ (поле «Масштаб (знаменатель)»):")
    for sc, n in sorted(scales.items()):
        print(f"  1:{sc:<7} {SCALE_HINT[sc]:<10} {n} записей")

    if dump:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("w", encoding="utf-8") as w:
            w.write("# Кандидаты в серии 6–8, 10 по выгрузке каталога\n\n")
            w.write(f"Просмотрено записей: {total}\n\n")
            for key, rows in hits.items():
                w.write(f"\n## {key} — {len(rows)} записей\n\n")
                for r in rows[:400]:
                    w.write(
                        f"- **{r['название']}** | год {r['год']} | масштаб {r['масштаб']} | "
                        f"{r['архив']} ф. {r['фонд']} оп. {r['опись']} д. {r['ед.хр.']} | "
                        f"серия: {'ЕСТЬ' if r['серия'] else '—'} | `{r['page_id']}`\n"
                    )
                if len(rows) > 400:
                    w.write(f"\n…ещё {len(rows) - 400} записей\n")
        print(f"\nподробности: {OUT}")


if __name__ == "__main__":
    main()
