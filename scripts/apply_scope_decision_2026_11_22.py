"""Применение решений владельца 22.11.2026 к пакету серийного улова (набор 4.1).

Решения:
  * периодика 1918 года и позже (советская и постсоветская) — ОТСЕВ. Граница по году
    выпуска, а не по шаблону «год/номер»: слепой шаблон режет «Пермские губернские
    ведомости 1856–1916» (160 записей) и «Пермские епархиальные ведомости» (50) —
    первостепенные источники по землевладению и межеванию;
  * дореволюционные тексты — ВНОСИМ виды 1, 4, 6, 7, 8, 9 (ведомости; сборники и своды
    статсведений; обзоры и отчёты губернии и земства; памятные книжки и адрес-календари;
    межевание и землеустройство; списки и указатели населённых мест);
  * виды 2, 3, 5 (журналы земских собраний; труды научных обществ; описания края и
    путеводители) — НЕ вносим;
  * «прочее» среди дореволюционных — НА РАЗБОР человеком, отдельным файлом;
  * класс «карта» и «статистика» идут в каталог целиком, кроме попавшей в них периодики
    1918+ («Агрометеорологический бюллетень» и подобное).

Отсев — не мусор: каждая снятая запись уходит в журнал с причиной, иначе решение
невоспроизводимо (правило reference_sets / otsev-ne-musor).

  python scripts/apply_scope_decision_2026_11_22.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "output" / "upload_2026-11-22-series" / "review_run"
SRC_CSV = REVIEW / "notion_import.csv"
SRC_REV = REVIEW / "export_review.json"
DEC = ROOT / "output" / "upload_2026-11-22-series" / "decisions"

ISSUE = re.compile(r"\b(1[89]\d\d|20[0-2]\d)\s*/\s*\d+\b")
SCOPE_YEAR = 1918

# виды дореволюционных текстов; порядок = нумерация, которой владелец принимал решение
VIDY = [
    (1, "губернские / епархиальные ведомости", r"губернские ведомости|епархиальн", True),
    (2, "журналы и сборники земских собраний", r"земск\w* собран|журнал\w* .*земск|земств", False),
    (3, "труды научных обществ, музеев", r"[Тт]руд\w*|общество|музе|комисси", False),
    (4, "сборник / свод статистических сведений", r"[Сс]борник|[Сс]вод\b|статистич", True),
    (5, "описание края, путеводитель", r"[Оо]писание|путеводител|[Оо]черк", False),
    (6, "обзор / отчёт губернии, земства", r"[Оо]бзор|[Оо]тч[её]т", True),
    (7, "памятная книжка / адрес-календарь", r"[Пп]амятн\w* книж|адрес-календар|[Кк]алендар", True),
    (8, "межевание, землеустройство, лесное", r"межев|землеустр|лесоустр|дач\w*\b", True),
    (9, "список / указатель населённых мест", r"[Сс]писок|[Уу]казател", True),
]
# порядок проверки видов — тот же, которым строилась разбивка, иначе числа не совпадут
ORDER = [1, 7, 6, 2, 4, 9, 3, 5, 8]


def klass(row: dict) -> str:
    m = re.search(r"класс «([^»]*)»", row["Примечания"])
    return m.group(1) if m else ""


def year(row: dict) -> int | None:
    y = row["Год создания (нижняя)"]
    return int(y) if y.isdigit() else None


def issue_year(row: dict) -> int | None:
    m = ISSUE.search(row["Название источника"])
    return int(m.group(1)) if m else None


def vid_of(row: dict) -> tuple[int, str, bool] | None:
    title = row["Название источника"]
    by_num = {v[0]: v for v in VIDY}
    for num in ORDER:
        _, name, pat, take = by_num[num]
        if re.search(pat, title):
            return num, name, take
    return None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    rows = list(csv.DictReader(SRC_CSV.open(encoding="utf-8-sig")))
    cols = list(rows[0].keys())
    rev = {r["url"]: r for r in json.loads(SRC_REV.read_text(encoding="utf-8"))["records"]}
    DEC.mkdir(parents=True, exist_ok=True)

    keep: list[dict] = []
    drops: list[dict] = []
    human: list[dict] = []

    for r in rows:
        k, y, iy = klass(r), year(r), issue_year(r)

        # 1. периодика 1918+ — отсев в любом классе
        if iy and iy >= SCOPE_YEAR:
            drops.append({**r, "_причина": f"периодика {iy} — советская/постсоветская, "
                                           f"вне скоупа XVIII — нач. XX в."})
            continue
        if y and y >= SCOPE_YEAR and k == "текст":
            drops.append({**r, "_причина": f"текст {y} года — 1918 и позже, вне скоупа"})
            continue

        # 2. карты и статистика — целиком
        if k in ("карта", "статистика"):
            keep.append(r)
            continue

        # 3. тексты: решение по видам
        if k == "текст":
            if y is None:
                human.append({**r, "_причина": "текст без года — решения владельца нет"})
                continue
            v = vid_of(r)
            if v is None:
                human.append({**r, "_причина": "дореволюционный текст, вид не опознан "
                                               "(«прочее») — на разбор"})
                continue
            num, name, take = v
            if take:
                keep.append(r)
            else:
                drops.append({**r, "_причина": f"вид {num} «{name}» — владелец решил не вносить"})
            continue

        keep.append(r)

    # записываем
    with (REVIEW / "notion_import.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(keep)
    keep_urls = {r["Ссылка на онлайн-архив"] for r in keep}
    SRC_REV.write_text(json.dumps(
        {"records": [v for u, v in rev.items() if u in keep_urls]},
        ensure_ascii=False, indent=1), encoding="utf-8")

    for name, lst in (("scope_drops.csv", drops), ("na_razbor.csv", human)):
        if lst:
            with (DEC / name).open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols + ["_причина"])
                w.writeheader()
                w.writerows(lst)

    print(f"было: {len(rows)}")
    print(f"  К ЗАЛИВКЕ:   {len(keep)}")
    print(f"  отсев:       {len(drops)}  -> decisions/scope_drops.csv")
    print(f"  на разбор:   {len(human)}  -> decisions/na_razbor.csv")
    print(f"  сумма сходится: {len(keep) + len(drops) + len(human) == len(rows)}")

    import collections
    print("\nотсев по причинам:")
    for why, n in collections.Counter(d["_причина"][:60] for d in drops).most_common():
        print(f"  {n:4d}  {why}")
    print("\nна разбор по причинам:")
    for why, n in collections.Counter(h["_причина"][:60] for h in human).most_common():
        print(f"  {n:4d}  {why}")
    print("\nв заливке по классам:",
          dict(collections.Counter(klass(r) for r in keep).most_common()))
    # контроль правила адреса заказа: ссылка обязательна у каждой записи
    no_link = [r for r in keep if not r["Ссылка на онлайн-архив"].strip()]
    print(f"записей без ссылки на карточку: {len(no_link)} "
          f"(правило адреса заказа — должно быть 0)")


if __name__ == "__main__":
    main()
