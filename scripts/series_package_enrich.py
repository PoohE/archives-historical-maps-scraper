"""Обогащение пакета перед заливкой: разбор карточки + наследование от серии.

Два источника значений, с жёстким приоритетом:

  1. КАРТОЧКА (точно про этот экземпляр) — разбор ISBD-описания: автор, выходные данные,
     место, издатель, год, листы, размер, масштаб, цветность, тип. Побеждает всегда.
  2. СЕРИЯ (про массив в целом) — только там, где у серии ОДНО документированное значение;
     заполняет лишь пустое и помечается «по серии, не сверено по листу».

Где у серии значения разные (наместничества 1:336 000/1:84 000/1:4 200; Вильбрехт
1:465 000/1:575 000/1:770 000; Менде 1 и 2 версты), наследование ЗАПРЕЩЕНО — иначе
в каталог попадёт выдуманное число.

  python series_package_enrich.py            # разбор + наследование → package_enriched.jsonl
  python series_package_enrich.py --no-net   # только наследование, без обхода карточек
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import fix_stdout  # noqa: E402
from series_package_repair import fetch, title_url  # noqa: E402

DIR = Path(
    r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output\series_package_20261107"
)
OUT = DIR / "package_enriched.jsonl"

# --- что наследуется от серии. Только однозначные, документированные в разборе величины.
SERIES_DEFAULTS: dict[str, dict] = {
    "серия 8 — Шуберт, десятивёрстка 1:420 000": {
        "Масштаб (знаменатель)": 420000,
        "Оригинальный масштаб": "1:420 000 (10 вёрст в дюйме)",
        "Картографическая проекция": "Бонна",
        "Нулевой меридиан": "Ферро",
        "Техника исполнения": "гравюра на меди",
        "Место создания": "Санкт-Петербург",
        "Автор / составитель": "Военно-топографическое депо; рук. Ф.Ф. Шуберт",
        "_src": "блок 8 разбора: проекция Бонна, ср. параллель 54°30′, ср. меридиан 51°30′ "
                "от Ферро, гравюра на меди, 59 основных листов + 3 клапана",
    },
    "серия 13 — Стрельбицкий 1:420 000": {
        "Масштаб (знаменатель)": 420000,
        "Оригинальный масштаб": "1:420 000 (10 вёрст в дюйме)",
        "Автор / составитель": "Военно-топографический отдел Главного штаба; "
                               "сост. И.А. Стрельбицкий",
        "_src": "карточка серии «Карта Стрельбицкого»: 1:420 000, ВТО Главного штаба",
    },
    "серия 10 — трёхвёрстка 1:126 000": {
        "Масштаб (знаменатель)": 126000,
        "Оригинальный масштаб": "1:126 000 (3 версты в дюйме)",
        "Картографическая проекция": "Бонна",
        "Нулевой меридиан": "Пулково",
        "Автор / составитель": "Военно-топографическое депо (Корпус военных топографов)",
        "_src": "блок 10 разбора: проекция Бонна от Пулковского меридиана; "
                "⚠️ составитель П.А. Тучков, НЕ Шуберт",
    },
    "серия 5а — Столистовая карта": {
        "Масштаб (знаменатель)": 840000,
        "Оригинальный масштаб": "20 вёрст в дюйме = 1:840 000",
        "Нулевой меридиан": "Ферро",
        "_src": "карточка серии: 1:840 000, долготы от Ферро (проверено по рамке листа A "
                "издания 1816). ПРОЕКЦИЯ НЕ НАСЛЕДУЕТСЯ — источники расходятся",
    },
}

# Серии, где наследование запрещено, и почему (для отчёта).
NO_INHERIT = {
    "серия 4 — карты и атласы наместничеств":
        "единого масштаба нет: 1:336 000 (наместничество), 1:84 000 (уезды), "
        "1:4 200 и 1:8 400 (города)",
    "серия 5 — Российский атлас Вильбрехта":
        "«масштабы разные»: Калужская ≈1:465 000, Ярославская ≈1:575 000, "
        "Смоленская ≈1:770 000 (измерено по сканам Rumsey)",
    "серия 11 — атласы и карты Менде":
        "карточка серии пуста (серия не разобрана); внутри серии 1 верста и 2 версты",
    "серия 2 — Атлас Российский Академии наук 1745":
        "масштабы листов не сверены",
    "условные знаки и инструкции":
        "не карты — масштаба и проекции не имеют",
}

SC = re.compile(r"1\s*[:：]\s*(\d[\d\s\u00a0]{2,12})")
AUTHOR = re.compile(r"^([А-ЯЁ][а-яё]+(?:ов|ев|ин|ский|цкий|ко|ич|ова|ева)?,\s*"
                    r"[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s*(\([^)]*\))?\s*\.\s*-")
IMPRINT = re.compile(r"\.\s*-\s*(\[?[А-ЯЁA-Z][^.:\-]{2,45}?\]?)\s*:\s*"
                     r"(\[?[^,;]{2,60}?\]?)\s*,?\s*(\[?(?:1[5-9]\d\d|\d{3}-)\]?)")
SHEETS = re.compile(r"(\d+\s*к\.\s*\(\d+\s*отд\.\s*л\.\)|(?:\[\d+\]|\d+)\s*(?:л\.|с\.)(?:\s*карт\.?)?)")
SIZE = re.compile(r"(\d{1,3}(?:[.,]\d)?\s*[хx×]\s*\d{1,3}(?:[.,]\d)?\s*см)")
YEAR = re.compile(r"\[?(1[5-9]\d\d|20\d\d)")


def parse_card(title: str) -> dict:
    """Разбор ISBD-описания карточки. Пустые ключи не возвращаются."""
    t = title.replace(" - Search RSL", "").strip()
    out: dict = {}
    m = AUTHOR.search(t)
    if m:
        out["Автор / составитель"] = (m.group(1) + " " + (m.group(2) or "")).strip()
    m = SC.search(t)
    if m:
        out["Масштаб (знаменатель)"] = int(re.sub(r"\D", "", m.group(1)))
        seg = t[m.start():m.start() + 60].split(". -")[0].strip(" .")
        out["Оригинальный масштаб"] = seg
    m = IMPRINT.search(t)
    if m:
        out["Место создания"] = m.group(1).strip(" []")
        out["Связанное издание: автор / ответственность"] = m.group(2).strip(" []")
        y = YEAR.search(m.group(3))
        if y:
            out["Год создания (нижняя)"] = int(y.group(1))
    elif (y := YEAR.search(t)):
        out["Год создания (нижняя)"] = int(y.group(1))
    m = SHEETS.search(t)
    if m:
        out["Листы / страницы"] = m.group(1).strip()
    m = SIZE.search(t)
    if m:
        out["Размер карты"] = m.group(1).strip() + " (по карточке)"
    if re.search(r"\bцв\.|цветн", t):
        out["Цветность скана"] = "цветной"
    if "[Карты]" in t or "[Карта]" in t:
        out["DC Type"] = "StillImage"
    return out


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-net", action="store_true")
    args = ap.parse_args()

    rows = [json.loads(ln) for ln in (DIR / "package_ready.jsonl").open(encoding="utf-8")]
    print(f"готовых строк: {len(rows)}")

    stat_card: dict[str, int] = {}
    stat_inh: dict[str, int] = {}
    n_inh_rows = 0

    for r in rows:
        fields = parse_card(r["zagolovok_polnyi"])
        # шифр хранения — только если карточка его отдала (второй проход по телу страницы)
        if not args.no_net and r["holder"] in ("РГБ", "НЭБ"):
            src = title_url(r)
            if src:
                html = fetch(src)
                if html:
                    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
                    # шифр стоит непосредственно перед кнопками «Читать / Заказать»
                    m = re.search(r"((?:FB|KGR|OMF|IZO|MK|ZV|NTO)\s+[^\s][\w\s/\-.№]{2,34}?)"
                                  r"\s+(?:Читать|Заказать|Marc21)", txt)
                    if m:
                        fields["Библиотечный шифр"] = m.group(1).strip()
        for k in fields:
            stat_card[k] = stat_card.get(k, 0) + 1

        inh = SERIES_DEFAULTS.get(r["seriya"], {})
        used = False
        for k, v in inh.items():
            if k.startswith("_"):
                continue
            if k not in fields:                      # карточка побеждает
                fields[k] = v
                fields.setdefault("_унаследовано", []).append(k)
                stat_inh[k] = stat_inh.get(k, 0) + 1
                used = True
        if used:
            n_inh_rows += 1
            fields["Примечания по оцифровке"] = (
                "Часть полей взята ОТ СЕРИИ, не сверена по листу: "
                + ", ".join(fields["_унаследовано"]) + ". Основание — " + inh["_src"]
            )
        r["notion_fields"] = fields

    with OUT.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    counts_clean = [len([k for k in r["notion_fields"] if not k.startswith("_")]) for r in rows]
    print(f"\nполей на запись: мин {min(counts_clean)}, медиана "
          f"{sorted(counts_clean)[len(counts_clean) // 2]}, макс {max(counts_clean)}")
    print(f"строк с наследованием от серии: {n_inh_rows}")
    print("\nиз КАРТОЧКИ разобрано:")
    for k, v in sorted(stat_card.items(), key=lambda x: -x[1]):
        print(f"  {k:<42} {v:>4}")
    print("\nот СЕРИИ унаследовано:")
    for k, v in sorted(stat_inh.items(), key=lambda x: -x[1]):
        print(f"  {k:<42} {v:>4}")
    print("\nнаследование запрещено:")
    for s, why in NO_INHERIT.items():
        n = sum(1 for r in rows if r["seriya"] == s)
        if n:
            print(f"  {n:>4}  {s} — {why}")
    print(f"\nфайл: {OUT}")


if __name__ == "__main__":
    main()
