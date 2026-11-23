"""Выборочная проверка записей «кандидат» по слоям (23.11.2026, решение владельца).

Зачем. Статья article-34 считает представленность только после того, как определятся
статусы 23 064 кандидатов. Сплошь — дни работы; владелец утвердил выборку по слоям:
60 межевых книг ГАЯО ф. 455, по 30 записей на прочие слои (источник), слой без брака
(для источника — не более 1 ошибки) переводится в «принято» целиком, с браком — сплошь.

Скрипт только читает слепок и пишет выборку с автоматическими флагами; каталог не трогает.

  python scripts/kandidaty_vyborka_2026_11_23.py output/notion_catalog_<метка>.csv
"""
import csv
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

OUR = ("Калужск", "Пермск", "Смоленск", "Ярославск")
OUT = Path(__file__).resolve().parents[1] / "output" / "kandidaty_proverka_2026-11-23"
SEED = 20261123


def stratum(r: dict) -> str:
    a = r["Архив [авто]"] or "(без архива)"
    if a == "ГАЯО":
        return "ГАЯО ф. 455" if r["Фонд"] == "455" else "ГАЯО прочее (ноябрьский добор и др.)"
    return a


def year(r: dict) -> int | None:
    for k in ("Год создания (нижняя)", "Год источника", "Связанное издание: год издания"):
        m = re.search(r"\d{4}", r.get(k) or "")
        if m:
            return int(m.group())
    return None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8-sig", newline="")))
    live = [r for r in rows if r["Статус приёмки"] != "отклонено"]
    links = Counter(r["Ссылка на онлайн-архив"] for r in live if r["Ссылка на онлайн-архив"])
    cand = [r for r in rows if r["Статус приёмки"] == "кандидат"]
    by = defaultdict(list)
    for r in cand:
        by[stratum(r)].append(r)
    rnd = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    cols = ["слой", "page_id", "url", "Название источника", "Архив [авто]", "Фонд", "Опись",
            "Год", "Современные регионы", "Ссылка на онлайн-архив", "Код типа [авто]",
            "флаги", "вердикт", "почему"]
    out = []
    print(f"кандидатов: {len(cand)}")
    for s, lst in sorted(by.items(), key=lambda x: -len(x[1])):
        n = 60 if s == "ГАЯО ф. 455" else 30
        smp = lst if len(lst) <= n else rnd.sample(lst, n)
        print(f"  {s}: {len(lst)} → в выборке {len(smp)}")
        for r in smp:
            fl = []
            if not r["Ссылка на онлайн-архив"]:
                fl.append("нет ссылки")
            elif links[r["Ссылка на онлайн-архив"]] > 1:
                fl.append(f"ссылка у {links[r['Ссылка на онлайн-архив']]} живых записей")
            reg = r["Современные регионы"]
            if not reg:
                fl.append("регион пуст")
            elif not any(o in reg for o in OUR):
                fl.append("регион не наш")
            y = year(r)
            if y is None:
                fl.append("год не указан")
            elif y > 1917:
                fl.append(f"год {y} > 1917")
            if not (r["Название источника"] or "").strip():
                fl.append("нет названия")
            out.append({"слой": s, "page_id": r["page_id"], "url": r["url"],
                        "Название источника": r["Название источника"],
                        "Архив [авто]": r["Архив [авто]"], "Фонд": r["Фонд"], "Опись": r["Опись"],
                        "Год": y or "", "Современные регионы": reg,
                        "Ссылка на онлайн-архив": r["Ссылка на онлайн-архив"],
                        "Код типа [авто]": r["Код типа [авто]"], "флаги": "; ".join(fl),
                        "вердикт": "", "почему": ""})
    p = OUT / "vyborka.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    print(f"выборка: {len(out)} → {p}")
    print("флаги:", Counter(x for o in out for x in o["флаги"].split("; ") if x).most_common())


if __name__ == "__main__":
    main()
