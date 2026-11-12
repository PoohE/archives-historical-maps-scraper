"""
Ночной анализ 26-27.10.2026 (без подтверждения пользователя, результат -- ТОЛЬКО в рабочий
файл, НИЧЕГО не пишет в Notion): две проверки по поручению пользователя.

A) Дача/Уезд: сверка «Тип источника» (код A1-C8) с «Административный уровень» -- коды
   несут естественный масштаб/территориальный охват (A3/B6/B8 = дача, A2 = уезд, A6 = нас.
   пункт, A1 = губерния), явное несовпадение -- сигнал ошибки разметки.
   «Тип источника» для РГИА/ГАСО в CSV-снэпшоте ещё пуст (экспорт был ДО сегодняшней
   классификации) -- код для этих архивов берётся из ledger-файлов сегодняшних прогонов.

B) Семантический предметный гейт: поиск записей, чей ПРЕДМЕТ (не территория) может не
   подпадать под критерий §1.1 ПРАВИЛА_ОТБОРА_источников.md (берём: карта/план/статистика
   с привязкой/полевая документация; не берём: чистое делопроизводство без привязки к
   объекту, переписка, личные документы). Ключевые слова взяты из уже подтверждённых
   сегодня прецедентов (диплом, письмо, архитектурная документация) + расширены на смежные
   категории (портрет, биография, анкета, воспоминания, грамота, приказ/указ без объекта).

Запуск:
  python scripts/maintenance/overnight_analysis.py output/notion_catalog_20261024_full.csv
"""
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import dated_path, fix_stdout  # noqa: E402

# --- A) Дача/Уезд -----------------------------------------------------------------

EXPECTED_LEVEL = {
    "A1": "Губерния", "A2": "Уезд", "A3": "Дача", "A6": "Нас. пункт",
    "B6": "Дача", "B8": "Дача", "B11": "Нас. пункт",
}
# Коды с естественно переменным охватом -- не проверяем строго (A4/A5/B1/B2/B3/B4/B5/B7/B9/B10/C1-C8)

LEVEL_ORDER = {"Губерния": 0, "Уезд": 1, "Волость": 2, "Нас. пункт": 2, "Дача": 3}
EXPECTED_TIER = {code: LEVEL_ORDER[lvl] for code, lvl in EXPECTED_LEVEL.items()}
IMPLAUSIBLE_GAP = 2  # разница тиров >= 2 -- физически неправдоподобно (напр. план дачи 1:8400
# не может покрывать всю губернию); разница в 1 тир -- пограничный случай, возможно норма
# (напр. "одно дело -- много строк описи" на уровне волости для кода A3/B8, см. чек-лист п.3)


def load_ledger_codes(path: Path) -> dict:
    codes = {}
    if not path.exists():
        return codes
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("status") == "ok" and rec.get("code"):
            codes[rec["page_id"]] = rec["code"]
    return codes


def run_check_a(csv_path: Path, rgia_codes: dict, gaso_codes: dict, out):
    cross = Counter()
    implausible = defaultdict(list)  # (code, expected, level) -> [(pid, title, archive), ...]
    borderline = Counter()  # (code, expected, level) -> count only (слишком много для списка)
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("Статус приёмки") or "").strip() == "отклонено":
                continue
            pid = row.get("page_id", "")
            code = row.get("Тип источника", "").strip()
            if not code:
                code = rgia_codes.get(pid) or gaso_codes.get(pid) or ""
            if not code or code not in EXPECTED_LEVEL:
                continue
            level = (row.get("Административный уровень") or "").strip() or "(пусто)"
            cross[(code, level)] += 1
            if level == "(пусто)" or level == EXPECTED_LEVEL[code]:
                continue
            expected = EXPECTED_LEVEL[code]
            gap = abs(LEVEL_ORDER.get(level, EXPECTED_TIER[code]) - EXPECTED_TIER[code])
            if gap >= IMPLAUSIBLE_GAP:
                title = row.get("Название источника", "")
                archive = (row.get("Архив хранения") or "").strip() or "(без архива)"
                implausible[(code, expected, level)].append((pid, title, archive))
            else:
                borderline[(code, expected, level)] += 1

    out.write("## A) Дача/Уезд: сверка «Тип источника» ↔ «Административный уровень»\n\n")
    out.write("Проверены коды с однозначным естественным уровнем: "
              "A1→Губерния, A2→Уезд, A3→Дача, A6→Нас.пункт, B6→Дача, B8→Дача, B11→Нас.пункт.\n"
              "Коды с переменным охватом (A4/A5/B1-B5/B7/B9/B10/C1-C8) не проверялись -- "
              "у них нет единственно верного уровня.\n\n"
              "Несовпадение разбито на два уровня серьёзности: **явно неправдоподобные** "
              "(разница ≥2 тиров шкалы Губерния–Уезд–Волость/Нас.пункт–Дача, напр. план дачи "
              "1:8400 физически не может покрывать всю губернию) -- список ниже, разбирать первым; "
              "**пограничные** (разница в 1 тир, может быть нормой -- см. чек-лист п.3 «одно "
              "дело, много строк описи») -- только счётчик, в список не выведены.\n\n")
    out.write("### Кросс-таблица (код, уровень, количество)\n\n")
    out.write("| Код | Уровень | Кол-во | Ожидался |\n|---|---|---:|---|\n")
    for (code, level), n in sorted(cross.items(), key=lambda x: (x[0][0], -x[1])):
        mark = "✅" if level == EXPECTED_LEVEL[code] else "⚠️"
        out.write(f"| {code} | {level} | {n} | {EXPECTED_LEVEL[code]} {mark} |\n")

    out.write("\n### Пограничные несовпадения (разница в 1 тир, вероятно норма) -- только счёт\n\n")
    out.write("| Код | Ожидался | Стоит | Кол-во |\n|---|---|---|---:|\n")
    for (code, expected, level), n in sorted(borderline.items(), key=lambda x: -x[1]):
        out.write(f"| {code} | {expected} | {level} | {n} |\n")

    out.write("\n### ⚠️ Явно неправдоподобные комбинации -- разбирать первым\n\n")
    total_implausible = sum(len(v) for v in implausible.values())
    out.write(f"Всего записей: **{total_implausible}**\n\n")
    for (code, expected, level), items in sorted(implausible.items(), key=lambda x: -len(x[1])):
        out.write(f"\n#### {code} (ожидался «{expected}», стоит «{level}») -- {len(items)} записей\n\n")
        archives = sorted({a for _, _, a in items})
        out.write(f"Архивы: {', '.join(a[:40] for a in archives)[:300]}\n\n")
        for pid, title, _a in items[:8]:
            out.write(f"- `{pid}` {title[:120]}\n")
        if len(items) > 8:
            out.write(f"- ... и ещё {len(items) - 8}\n")
    return implausible


# --- B) Семантический предметный гейт ----------------------------------------------

PREDMET_PATTERNS = {
    "диплом/грамота/награда": re.compile(
        r"диплом|грамота(?!\s+(?:жалован|владен))|похвальн\w+\s+лист|почётн\w+\s+грамот"
        r"|орден\w*\s+(?:красн|труд)", re.I),
    "портрет/фотография лица": re.compile(
        r"^портрет|фотограф\w*\s+(?:портрет|группов\w+)|^фото\.\s*портрет", re.I),
    "биография/воспоминания": re.compile(
        r"автобиографи|биографическ\w+\s+справк|воспоминани|мемуар|личн\w+\s+дело", re.I),
    "анкета/личный документ": re.compile(
        r"^анкета|послужн\w+\s+список|трудов\w+\s+книжк|паспорт\w*\s+(?:гражданин|личн)", re.I),
    "делопроизводство без объекта": re.compile(
        r"^приказ\b|^указ\b(?!\s+о\s+(?:размежеван|землеустрой|отводе|наделении))"
        r"|протокол\w*\s+(?:партийн|профсоюзн|комсомольск)|повестк\w+\s+дня\s*$"
        r"|^циркуляр(?!\w*\s+(?:о\s+)?(?:межеван|съёмк|землеустрой))", re.I),
    "переписка без указания объекта": re.compile(
        r"^переписка(?!.{0,60}(?:план|карт|дач|межеван|земл|участк|уезд|волост))", re.I),
    "диссертация/научная статья (не первоисточник)": re.compile(
        r"^диссертация|^автореферат|^статья\.\s", re.I),
}


def run_check_b(csv_path: Path, out):
    hits = defaultdict(list)
    total = 0
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("Статус приёмки") or "").strip() == "отклонено":
                continue
            title = (row.get("Название источника") or "").strip()
            if not title:
                continue
            total += 1
            for label, pat in PREDMET_PATTERNS.items():
                if pat.search(title):
                    hits[label].append((row.get("page_id", ""), title,
                                         (row.get("Архив хранения") or "").strip() or "(без архива)"))
                    break  # одно совпадение на запись достаточно

    out.write("\n\n## B) Семантический предметный гейт (независимо от территории)\n\n")
    out.write(f"Проверено записей: {total}. Совпадений по предметным паттернам: "
              f"{sum(len(v) for v in hits.values())}.\n\n")
    out.write("⚠️ Это НАБОР КАНДИДАТОВ на исключение, не окончательное решение -- многие "
              "совпадения могут быть ложными (например, «переписка» с указанием объекта "
              "дальше в заголовке, не пойманным простым правилом). Разбирать кластер за "
              "кластером так же, как территориальный гейт.\n\n")
    for label, items in sorted(hits.items(), key=lambda x: -len(x[1])):
        out.write(f"\n### {label} -- {len(items)} записей\n\n")
        archives = sorted({a for _, _, a in items})
        out.write(f"Архивы: {', '.join(a[:40] for a in archives)[:300]}\n\n")
        for pid, title, _a in items[:8]:
            out.write(f"- `{pid}` {title[:140]}\n")
        if len(items) > 8:
            out.write(f"- ... и ещё {len(items) - 8}\n")
    return hits


def main():
    fix_stdout()
    csv_path = Path(sys.argv[1])
    rgia_codes = load_ledger_codes(csv_path.with_name(csv_path.stem + "_rgia_tip_ledger.jsonl"))
    gaso_codes = load_ledger_codes(csv_path.with_name(csv_path.stem + "_gaso_tip_ledger.jsonl"))
    print(f"РГИА кодов из ledger: {len(rgia_codes)}, ГАСО: {len(gaso_codes)}")

    out_path = dated_path("OVERNIGHT_ПРОВЕРКА", "md", out=csv_path.parent.parent)
    with out_path.open("w", encoding="utf-8") as out:
        out.write(f"# Ночная проверка {out_path.stem}\n\n")
        out.write("Автономный прогон без подтверждения (по поручению пользователя 26.10.2026, "
                  "23:5x) -- НИЧЕГО не записано в Notion, только анализ для утреннего разбора.\n\n")
        mismatches = run_check_a(csv_path, rgia_codes, gaso_codes, out)
        hits = run_check_b(csv_path, out)

    dump_path = out_path.with_suffix(".full.json")
    with dump_path.open("w", encoding="utf-8") as jf:
        json.dump({
            "mismatches": {f"{c}|{e}|{lvl}": v for (c, e, lvl), v in mismatches.items()},
            "hits": {k: v for k, v in hits.items()},
        }, jf, ensure_ascii=False, indent=1)

    print(f"\nОтчёт -> {out_path}")
    print(f"Полные списки -> {dump_path}")
    print(f"A) несовпадений Дача/Уезд: {sum(len(v) for v in mismatches.values())}")
    print(f"B) предметных кандидатов: {sum(len(v) for v in hits.values())}")


if __name__ == "__main__":
    main()
