"""Разбор focr-выдачи описей ГАСО (машинопись) в записи каталога.

Вход — `.md` от `focr ocr`: табличная часть выходит HTML-таблицами по столбцам описи
(№№пп, индекс дела, заголовок, крайние даты, кол-во листов, примечание), между ними —
строки-разделители по годам («1908 год») и служебные листы (титул, заверительная запись).

Контроль не «файл не пустой», а арифметика самого документа: в конце описи стоит
«В данную опись внесено N (прописью) дел с № 1 по № M» — сверяем с числом разобранных
записей и максимальным номером. Расхождение печатается как ⚠, строки не выбрасываются.

⚠️ Дефекты focr, которые чиним здесь (из отчёта Винки З-011):
  - в ячейках пропадают пробелы на месте переноса строки («нахуторские», «заседанийкомиссии»);
  - опечатки в топонимах («Пюречского», «Роспальского») — НЕ правим молча, помечаем флагом.

Запуск:
    python -B scripts_gaso/parse_focr_opisi.py "УПРАВЛЕНИЕ_ВИНКИ/ОТЧЁТЫ/З-011_вывод" \
        --out C:\\arch\\output\\gaso_focr_parsed_20261013
"""
from __future__ import annotations

import argparse
import csv
import html as H
import json
import re
import sys
from pathlib import Path

FIELDS = ["fund", "opis", "n_delo", "index_dela", "zagolovok", "god_razdel",
          "data_nachato", "data_okoncheno", "listov", "obyekt",
          "kartograficheskiy_priznak", "primechanie", "source_file", "flags"]

TABLE = re.compile(r"<table>(.*?)</table>", re.S)
ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
# ⚠️ ячейки бывают с colspan (заголовок на две колонки, строка года на всю ширину) —
# по этой причине первая версия парсера теряла записи целиком (334_1: 90 из 96).
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
DATEISH = re.compile(r"\d{4}\s*(?:г|год)|\d{1,2}\s+[а-яё]+\s+\d{4}")
NUMERIC = re.compile(r"^\d{1,4}$")
YEAR_ROW = re.compile(r"^\s*(\d{4})\s*(?:год|г\.?)\s*$")
# «В данную опись внесено 96 (девяносто шесть) дел с № 1 по № 96» — и короткий вариант
# для одного дела: «внесено 1 (одно) дело с № 1» (без «по № M»).
TOTAL = re.compile(
    r"внесено\s+(\d+)\s*\([^)]*\)\s*дел\w*\s*(?:ед\.?\s*хр\.?)?\s*"
    r"с\s*№\s*(\d+)(?:\s*по\s*№\s*(\d+))?", re.S | re.I)
N_DELO = re.compile(r"^\s*(\d+)\s*\.?\s*$")

# Картографические признаки — ищем в ЗАГОЛОВКЕ, порядок = приоритет.
# ⚠️ Слова «землеустройство», «землемер», «хуторские участки», «отруб» СОЗНАТЕЛЬНО не
# считаются признаком: иначе в выборку валом идут прошения крестьян о денежных ссудах
# на хуторское землеустройство (проверено на ф. 428 и ф. 237 — там таких дел большинство).
# Первая версия словаря давала 520 ложных «межеваний» на этом.
SIGNS = [
    ("выкопировка", r"выкопировк"),
    ("план", r"\bплан[аовы]?\b|планов"),
    ("чертёж", r"чертеж|чертёж"),
    ("карта", r"\bкарт[аые]\b"),
    ("межевая книга", r"межев\w*\s+книг"),
    ("экономические примечания", r"экономическ\w*\s+примечан"),
    ("ведомость дачам", r"ведомост\w*\s+дач"),
    ("владенная запись", r"владенн\w*\s+запис"),
    ("полевые записки", r"полев\w*\s+(?:журнал|запис|книж)"),
    # Типология актов межевания — из предисловия самого архива к описи ф. 814 ГАСО
    # (О.Л. Москалев, ГАСО): «полевые записки, межевые планы, межевые книги, выкопировки
    # из планов генерального или специального межевания, ГЕОФИЗИЧЕСКИЕ ОПИСАНИЯ ГРАНИЦ
    # наделов, полевой журнал и межевая его книга». «Геофизическое описание» — так в
    # документе (у нас в словаре было только «геодезическое»), «полюбовная сказка» —
    # акт полюбовного размежевания, встречается в ф. 576 сплошь.
    ("описание границ", r"геофизическ\w*\s+описан|описани\w*\s+границ"),
    ("полюбовная сказка", r"полюбовн\w*\s+(?:сказк|развод|соглашен|акт)"),
    ("список селений", r"список\w*\s+селени|списки\s+селени"),
    ("оценка земель", r"оценочн\w*\s+(?:таблиц|ведомост|опис)|оценк\w*\s+земел"),
    ("съёмка", r"съемк|съёмк|геодез|нивелир|топограф"),
    # землеустроительное действие над конкретной землёй — к таким делам прилагались планы.
    # «выдел» и «отвод» добавлены 13.10: без них гейт принимал «о разверстании земли
    # деревни X», но отсеивал «о выделе надельной земли деревни X» — одно и то же по сути.
    ("межевание", r"межеван|размежеван|разверстан|выдел\w*\s+(?:к одному месту|надельн|земл)"
                  r"|отвод\w*\s+земл|отрубн\w*\s+участк|на хутор(?:а\b|ские участк)"),
]

OBJ = re.compile(
    r"(деревн\w+|дер\.\s*[А-ЯЁ][\w-]+|сельц\w+|сел[аое]\s+[А-ЯЁ][\w-]+|с\.\s*[А-ЯЁ][\w-]+"
    r"|пустош\w+|дач\w+|хутор\w*|слобод\w+|посел\w+|им\.\s*[А-ЯЁ][\w-]+"
    r"|[А-ЯЁ][\w-]+ской\s+волост\w+|[А-ЯЁ][\w-]+ского\s+уезд\w+"
    r"|[А-ЯЁ][\w-]+\s+волост\w+|[А-ЯЁ][\w-]+\s+уезд\w+|г\.\s*[А-ЯЁ][\w-]+)")

SUSPECT = re.compile(r"[A-Za-z]{2,}|[ЪЬ]{2,}|[а-яё]{14,}")


def unglue(s: str) -> str:
    """Вернуть пробелы, съеденные focr на переносах строк."""
    s = H.unescape(s)
    s = re.sub(r"([а-яё])([А-ЯЁ])", r"\1 \2", s)        # словоСлово
    s = re.sub(r"([а-яёА-ЯЁ])(\d)", r"\1 \2", s)        # слово1912
    s = re.sub(r"(\d)([а-яёА-ЯЁ])", r"\1 \2", s)        # 1912года → 1912 года
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def split_dates(s: str) -> tuple[str | None, str | None]:
    parts = re.split(r"\s*[—–-]\s*", s)
    if len(parts) >= 2:
        return parts[0].strip() or None, parts[-1].strip() or None
    return (s.strip() or None), None


def sign_of(title: str) -> str:
    low = title.lower()
    hits = [name for name, pat in SIGNS if re.search(pat, low)]
    return ", ".join(hits) if hits else "нет"


def parse_file(path: Path) -> tuple[list[dict], dict]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    stem = path.stem
    fund, _, opis = stem.partition("_")
    rows: list[dict] = []
    year = None

    for tbl in TABLE.findall(raw):
        for tr in ROW.findall(tbl):
            cells = [unglue(c) for c in CELL.findall(tr)]
            if not cells:
                continue

            # строка-раздел по году: единственная непустая ячейка вида «1825 год»
            filled = [c for c in cells if c]
            if len(filled) == 1 and YEAR_ROW.match(filled[0]):
                year = YEAR_ROW.match(filled[0]).group(1)
                continue
            if not N_DELO.match(cells[0]):
                continue                                   # строка нумерации столбцов и т.п.

            # Поля определяем по СОДЕРЖИМОМУ, а не по номеру колонки: из-за colspan
            # столбцы съезжают, и привязка к индексу теряет записи.
            rest = cells[1:]
            title = max(rest, key=len) if rest else ""
            if len(title) < 8:
                continue
            others = [c for c in rest if c is not title and c]
            dates = next((c for c in others if DATEISH.search(c)), "")
            listov = next((c for c in others if NUMERIC.match(c)), "")
            idx = next((c for c in others if c not in (dates, listov)
                        and not re.match(r"^Кор", c)), "")
            prim = next((c for c in others if re.match(r"^Кор", c)), "")
            d1, d2 = split_dates(dates)
            flags = []
            if SUSPECT.search(title):
                flags.append("проверить_топонимы")
            objs = OBJ.findall(title)
            rows.append({
                "fund": fund, "opis": opis,
                "n_delo": N_DELO.match(cells[0]).group(1),
                "index_dela": idx or None,
                "zagolovok": title,
                "god_razdel": year,
                "data_nachato": d1, "data_okoncheno": d2,
                "listov": listov or None,
                "obyekt": "; ".join(dict.fromkeys(objs)) or None,
                "kartograficheskiy_priznak": sign_of(title),
                "primechanie": prim or None,
                "source_file": path.name,
                "flags": ",".join(flags) or None,
            })

    return rows, read_control(raw)


def read_control(text: str) -> dict:
    """Заверительная запись описи — независимое третье число для арифметической сверки."""
    m = TOTAL.search(unglue(text))
    if not m:
        return {}
    last = int(m.group(3)) if m.group(3) else int(m.group(2))
    return {"declared": int(m.group(1)), "from": int(m.group(2)), "to": last}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="папка с .md от focr")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict] = []
    print(f"{'опись':<10} {'разобрано':>9} {'заявлено':>9} {'макс №':>7}  контроль")
    for md in sorted(Path(args.src).glob("*.md")):
        rows, ctrl = parse_file(md)
        all_rows.extend(rows)
        nums = [int(r["n_delo"]) for r in rows] or [0]
        decl = ctrl.get("declared")
        if decl is None:
            verdict = "⚠ контрольная запись не найдена"
        elif decl == len(rows) and max(nums) == ctrl["to"]:
            verdict = "✓ сходится"
        else:
            verdict = f"⚠ расхождение (в описи № 1–{ctrl['to']})"
        print(f"{md.stem:<10} {len(rows):>9} {decl if decl is not None else '—':>9} "
              f"{max(nums):>7}  {verdict}")

    jsonl = out / "gaso_focr_records.jsonl"
    with jsonl.open("w", encoding="utf-8") as fh:
        for r in all_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    csv_f = out / "gaso_focr_records.csv"
    with csv_f.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(all_rows)

    carto = sum(1 for r in all_rows if r["kartograficheskiy_priznak"] != "нет")
    flagged = sum(1 for r in all_rows if r["flags"])
    print(f"\nвсего записей: {len(all_rows)}; с картографическим признаком: {carto} "
          f"({carto / len(all_rows) * 100:.0f}%); помечено на вычитку: {flagged}")
    print(f"JSONL: {jsonl}\nCSV:   {csv_f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
