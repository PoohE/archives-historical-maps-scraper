# -*- coding: utf-8 -*-
"""РГАДА ф.1356 оп.2 и оп.3: записи наших губерний, снятые Claude Vision с образов описи.

PDF у этих описей НЕТ (404) — только постраничные образы
`rgada.info/opisi/1356-opis_{N}/{NNNN}.jpg` (оп.2 — 15 листов, оп.3 — 10).
Машинопись 1977 г., читается Vision целиком; выборка сделана визуально,
провенанс — номер образа (`image`), сверено с заверительной надписью описи.

Результат оп.2 (401 ед. хр., заверена 11.10.1977):
  губернии описи — Витебская, Вологодская, Екатеринославская, Курская, Могилевская,
  Олонецкая, Петербургская, Псковская, Харьковская, ЯРОСЛАВСКАЯ.
  Калужской, Пермской, Смоленской в описи НЕТ.
Результат оп.3 (100 ед. хр., заверена 19.09.1977): из наших — только Ярославская.
"""
import csv
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
OUT = BASE / "output" / "rgada_CONSOLIDATED"

OP2_NAME = "Губернские, уездные и городские атласы, карты и планы Генерального межевания 1766-1883 гг. Опись 2. Уездные планы-атласы (наклеенные на картон)"
OP3_NAME = "Губернские, уездные и городские атласы, карты и планы Генерального межевания 1766-1883 гг. Опись 3. Уездные планы «нового образца»"

# оп.2, ЯРОСЛАВСКАЯ губ.: (уезд, всего частей, первый №, образ)
OP2_YAR = [
    ("Даниловский уезд", 2, 378, "0013"),
    ("Любимский уезд", 3, 380, "0013"),
    ("Моложский уезд", 4, 383, "0014"),
    ("Мышкинский уезд", 2, 387, "0014"),
    ("Пошехонский уезд", 4, 389, "0014"),
    ("Ростовский уезд", 2, 393, "0014"),
    ("Рыбинский уезд", 3, 395, "0014"),
    ("Угличский уезд", 3, 398, "0014"),
    ("Ярославский уезд", 1, 401, "0014"),
]

# оп.3, ЯРОСЛАВСКАЯ губ.: (№, уезд, заголовок как в описи, кол-во листов, образ)
OP3_YAR = [
    ("98", "Мологский уезд", "Мологский уезд (1 сб. лист, 3 табл., лл. 1-12)", "16", "0008"),
    ("99", "Романово-Борисоглебский уезд",
     "Романово-Борисоглебский уезд (1 сб. л., 6 табл., лл. 1-8)", "15", "0008"),
]

COLS = ["fund", "opis", "opis_name", "unit", "territory", "uezd", "title", "scale",
        "sheets", "note", "source", "level", "extraction", "image", "opis_url"]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for uezd, parts, first, img in OP2_YAR:
        for i in range(parts):
            unit = first + i
            part = f"Часть {i + 1}" if parts > 1 else "Часть 1"
            title = f"Генеральный уездный план-атлас. {uezd}. {part}" + (
                f" (из {parts} частей)" if parts > 1 else " (1-я часть)")
            rows.append({
                "fund": "1356", "opis": "2", "opis_name": OP2_NAME, "unit": str(unit),
                "territory": "Ярославская губерния", "uezd": uezd, "title": title,
                "scale": "м-2-в (2 версты в дюйме)", "sheets": "", "note": "наклеен на картон",
                "source": "rgada", "level": "unit", "extraction": "claude_vision_2026-10-02",
                "image": f"http://rgada.info/opisi/1356-opis_2/{img}.jpg",
                "opis_url": "http://rgada.info/poisk/index2.php?str=1356-opis_2",
            })

    for unit, uezd, title, sheets, img in OP3_YAR:
        rows.append({
            "fund": "1356", "opis": "3", "opis_name": OP3_NAME, "unit": unit,
            "territory": "Ярославская губерния", "uezd": uezd, "title": title,
            "scale": "", "sheets": sheets, "note": "уездный план «нового образца»",
            "source": "rgada", "level": "unit", "extraction": "claude_vision_2026-10-02",
            "image": f"http://rgada.info/opisi/1356-opis_3/{img}.jpg",
            "opis_url": "http://rgada.info/poisk/index2.php?str=1356-opis_3",
        })

    path = OUT / "rgada_f1356_op2_op3_our_gubernias.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)

    print(f"записей: {len(rows)}")
    print(f"  оп.2: {sum(1 for r in rows if r['opis'] == '2')} (Ярославская, 9 уездов, №378–401)")
    print(f"  оп.3: {sum(1 for r in rows if r['opis'] == '3')} (Ярославская, №98–99)")
    print(f"выход: {path}")


if __name__ == "__main__":
    main()
