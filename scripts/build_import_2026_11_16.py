# -*- coding: utf-8 -*-
"""Адаптер двух готовых пакетов → notion_import.csv v1.6 для моста (16.11.2026).

Пакеты:
  1. **Белинка** — 30 выпусков, восстановленных 13.11.2026: пермские памятные книжки и
     адрес-календари 1862–1915 и два уездных выпуска «Списка населённых мест Пермской
     губернии». 24.10 они были пропущены целиком как «серия уже представлена», без сверки
     по году; проверка у источника показала, что этих лет в каталоге нет.
  2. **РГИА, статистические фонды** — решение «берём» смыслового гейта `gate_rgia_stat.py`
     по улову фондового прогона (ф. 1290, 573, 733, 23, 37 и др.).

Тип источника ставится ПРАВИЛАМИ по заголовку, а не моделью: расшифровка 25 кодов снята
из справочника Notion (`type_codes_named.json`). Где правило не срабатывает — запись
получает статус «кандидат» и причину сомнительности, а не выдуманный тип.

Год: только раздельно в «Год создания (нижняя)»/«(верхняя)»; «Год источника» при диапазоне
остаётся пустым (правило preflight, выведенное из 1 847 дефектных записей ГАПК).

  python build_import_2026_11_16.py
"""

import collections
import csv
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")
from common import fix_stdout  # noqa: E402

OUT = ROOT / "output" / "upload_2026-11-16"
TYPE_CODES = ROOT / "output" / "upload_2026-11-11" / "type_codes.json"
SAMPLE_CSV = ROOT / "output" / "upload_2026-11-11" / "rgo_review_run" / "notion_import.csv"
BELINKA = ROOT / "output" / "night_2026-11-12" / "belinka_recovered_30.jsonl"
RGIA = ROOT / "output" / "rgia_stat_funds" / "gate_берём.jsonl"

TODAY = "2026-11-16"

# --- правила типа по заголовку (коды из справочника «Типы источника»)
TYPE_RULES = [
    (re.compile(r"список\w* насел[ёе]нных мест", re.I), "C7"),
    (re.compile(r"памятная книжка|адрес-календарь|календарь .* губернии", re.I), "C5"),
    (re.compile(r"перепис\w+ населения|всероссийская перепись|всесоюзная перепись", re.I), "C3"),
    (re.compile(r"сельскохозяйственн\w+ перепис", re.I), "C8"),
    (re.compile(r"военно-статистическ", re.I), "C4"),
    (re.compile(r"подворн\w+ перепис|земск\w+ оценк", re.I), "C6"),
    (re.compile(r"географическ\w+ и статистическ\w+ словар", re.I), "B7"),
    # ⚠️ 16.11.2026: правило «любой план → A3 межевые планы» ошибочно. Фонд 37 дал
    # 101 дело «Планы <N> завода <владельца> (Калужская губерния)» — это планы
    # ПРЕДПРИЯТИЙ, а не межевание. Разводим явно, спорное отдаём приёмщику.
    (re.compile(r"план\w*.{0,40}завод", re.I), "A5"),
    (re.compile(r"план\w*\s+(города|поселени)", re.I), "A6"),
    (re.compile(r"план\w*\s+(дач|имени|земел|межев)", re.I), "A3"),
    (re.compile(r"\bплан\w*\b", re.I), None),
    (re.compile(r"карт\w+\s+(губерни|уезд)", re.I), "A1"),
    (re.compile(r"\bатлас\b", re.I), "A2"),
    (re.compile(r"\bкарт\w+\b", re.I), "A5"),
    (re.compile(r"статистическ\w+ сведени|статистическ\w+ таблиц|ведомост", re.I), "C2"),
    (re.compile(r"сведени\w+ о (числ|количеств|состоян)", re.I), "C2"),
    (re.compile(r"административно-территориальн|об образовании волост", re.I), "B9"),
    (re.compile(r"отчёт|отчет|обзор", re.I), "B10"),
]

HOLDER = {"belinka": "Свердловская ОУНБ им. В.Г. Белинского", "rgia": "РГИА"}


def type_code(title: str) -> tuple[str | None, str]:
    for rx, code in TYPE_RULES:
        if rx.search(title):
            if code is None:
                return None, f"план без уточнения вида — решает приёмщик: {rx.pattern[:30]}"
            return code, f"правило: {rx.pattern[:46]}"
    return None, "правило типа не сработало"


def main() -> None:
    fix_stdout()
    columns = next(csv.reader(io.open(SAMPLE_CSV, encoding="utf-8-sig")))
    codes = json.loads(TYPE_CODES.read_text(encoding="utf-8"))
    print(f"колонок в формате моста: {len(columns)}")

    packs: dict[str, list[dict]] = {"belinka": [], "rgia": []}
    rels: dict[str, list[dict]] = {"belinka": [], "rgia": []}
    stat: collections.Counter = collections.Counter()
    unknown: list[dict] = []

    # --- 1. Белинка
    for line in BELINKA.open(encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        title = (r.get("zagolovok") or "").strip()
        code, why = type_code(title)
        row = dict.fromkeys(columns, "")
        row["Название источника"] = title[:1900]
        row["Ссылка на онлайн-архив"] = r.get("url", "")
        year = str(r.get("god") or "").strip()
        if re.fullmatch(r"\d{4}", year):
            row["Год создания (нижняя)"] = year
            row["Год создания (верхняя)"] = year
            row["Год сведений"] = year
            row["Год: источник значения"] = "из карточки библиотеки"
        row["Библиотечный шифр"] = r.get("shifr", "")
        row["Место хранения"] = HOLDER["belinka"]
        row["Прямая ссылка на файл изображения"] = r.get("url_fajla", "")
        row["Примечания"] = (
            "Восстановлено 13.11.2026: 24.10 выпуск был пропущен как «серия уже "
            "представлена» без сверки по году; проверка у источника — этого года в каталоге "
            "нет. " + str(r.get("повод") or ""))[:1900]
        row["Территория: источник значения"] = "из заголовка/рубрик карточки"
        row["Статус доступа"] = "Открытый доступ"
        if not code:
            row["Причина сомнительности"] = why if "Причина сомнительности" in columns else ""
            unknown.append({"pack": "belinka", "title": title[:140], "why": why})
            stat["белинка: тип не определён"] += 1
        else:
            stat[f"белинка: {code}"] += 1
        packs["belinka"].append(row)
        rel = [{"property": "Архив хранения", "source_label": "СОУНБ (Свердловск)"}]
        if code:
            rel.append({"property": "Тип источника",
                        "target_url": "https://www.notion.so/" + codes[code].replace("-", "")})
        rels["belinka"].append({"url": r.get("url", ""), "relations": rel,
                                "territory_hints": [str(r.get("territoriya") or "")]})

    # --- 2. РГИА
    for line in RGIA.open(encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        full = (r.get("title") or "").strip()
        content = (r.get("содержание") or full).strip()
        code, why = type_code(content)
        m = re.search(r"Ф\.\s*(\d+)\s*Оп\.\s*([\dА-Яа-я]+)\s*Д\.\s*(.+)$", r.get("fund_code") or "")
        row = dict.fromkeys(columns, "")
        row["Название источника"] = content[:1900] or full[:1900]
        row["Ссылка на онлайн-архив"] = r.get("url", "")
        if m:
            row["Фонд"] = m.group(1)
            row["Опись"] = m.group(2)
            row["Единица хранения"] = m.group(3).strip()
        yf, yt = str(r.get("year_from") or ""), str(r.get("year_to") or "")
        if re.fullmatch(r"\d{4}", yf):
            row["Год создания (нижняя)"] = yf
        if re.fullmatch(r"\d{4}", yt):
            row["Год создания (верхняя)"] = yt
        if yf and yf == yt:
            row["Год сведений"] = yf
        row["Год: источник значения"] = "из заголовка дела"
        row["Место хранения"] = HOLDER["rgia"]
        row["Примечания"] = (
            f"Фондовый прогон РГИА 16.11.2026 по статистическим фондам (реестр отложенного "
            f"добора, строки А33–А39). Название фонда: {r.get('fund_name', '')}. "
            f"Поисковая формула: {r.get('запрос', '')}. Полный заголовок: {full}")[:1900]
        row["Территория: источник значения"] = "из заголовка"
        # ⚠️ «Статус доступа» — SELECT: запятые в значении Notion запрещает (ошибка
        # 16.11.2026, 76 отказов подряд). Допустимые варианты базы: «Открытый доступ»,
        # «Эмбарго», «Ограниченный доступ», «Только метаданные». Для архивного описания
        # без скана верно последнее.
        row["Статус доступа"] = "Только метаданные"
        if not code:
            unknown.append({"pack": "rgia", "title": content[:140], "why": why})
            stat["ргиа: тип не определён"] += 1
        else:
            stat[f"ргиа: {code}"] += 1
        if not (row["Фонд"] and row["Опись"] and row["Единица хранения"]):
            unknown.append({"pack": "rgia", "title": content[:140],
                            "why": "шифр дела не распарсился — вносить нельзя",
                            "fund_code": r.get("fund_code", "")})
            stat["ргиа: отложено, нет шифра"] += 1
            continue
        if not row["Год создания (нижняя)"]:
            unknown.append({"pack": "rgia", "title": content[:140],
                            "why": "нет года в описании дела — вносить нельзя",
                            "fund_code": r.get("fund_code", "")})
            stat["ргиа: отложено, нет года"] += 1
            continue
        packs["rgia"].append(row)
        rel = [{"property": "Архив хранения", "source_label": "РГИА"}]
        if code:
            rel.append({"property": "Тип источника",
                        "target_url": "https://www.notion.so/" + codes[code].replace("-", "")})
        rels["rgia"].append({"url": r.get("url", ""), "relations": rel,
                             "territory_hints": []})

    OUT.mkdir(parents=True, exist_ok=True)
    for pack, rows in packs.items():
        d = OUT / f"{pack}_review_run"
        d.mkdir(parents=True, exist_ok=True)
        with (d / "notion_import.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=columns)
            w.writeheader()
            w.writerows(rows)
        (d / "export_review.json").write_text(
            json.dumps({"records": rels[pack]}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{pack:8s} → {len(rows):5d} записей  {d}")

    (OUT / "type_unknown.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in unknown), encoding="utf-8")
    print(f"\nтип не определён: {len(unknown)} → type_unknown.jsonl")
    print("\n--- сводка типов")
    for k, v in sorted(stat.items()):
        print(f"  {v:5d}  {k}")


if __name__ == "__main__":
    main()
