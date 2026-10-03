# -*- coding: utf-8 -*-
"""НЭБ: разбор карточек каталога, сохранённых человеком вручную.

Зачем. Выдача (`search/?q=<губерния>&c[]=7`) не содержит ни масштаба, ни — у части
записей — года. Карточка содержит: блок «Детальная информация» (метка → значение),
библиографическое описание одной строкой, «Примечание содержания» с поштучным
перечнем листов и ИХ МАСШТАБАМИ, ББК с кодами территорий, рубрики «Тематика».

Вход : input_neb_cards/*.html («Веб-страница, полностью»); id документа берётся
       из поля «Код документа в НЭБ», иначе из имени файла.
Выход: output/neb_cards_20261003/ — cards.csv, cards.jsonl, REPORT.json.
"""
import csv
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
SRC = BASE / "input_neb_cards"
OUT = BASE / "output" / "neb_cards_20261003"

# метки блока «Детальная информация» — закрытый список: всё, что между меткой и
# следующей меткой, считается значением (поле «Объем» приходит двумя строками: «19», «л.»)
LABELS = [
    "Код документа в НЭБ", "Каталог", "Автор(ы)", "Заглавие", "Место издания",
    "Издательство", "Год издания", "Объем", "Ответственность", "ББК", "УДК",
    "Примечание содержания", "Примечание", "Серия", "Язык", "Вид документа",
    "Библиотека", "Тематика", "Место хранения оригинала документа на карте",
]
STOP = {"Еще", "Свернуть", "Скопировать", "Детальная информация", "Участник",
        "перейти в библиотеку", "Адрес:", "График работы:"}

# масштаб: числовой «1:840 000» и старорусский «х верст в дюйме» / «в сажени»
SCALE_NUM = re.compile(r"1\s*[:\uff1a]\s*(\d[\d \u00a0]{2,})")
SCALE_VERST = re.compile(r"(\d+(?:[.,]\d+)?)\s*вер[а-я]*\s*(?:в\s*)?(?:дюйм|д\.)", re.I)
SCALE_SAZH = re.compile(r"(\d+)\s*саж[а-я.]*\s*(?:в\s*)?(?:дюйм|д\.)", re.I)
YEAR = re.compile(r"\b(1[5-9]\d{2}|20[0-2]\d)\b")
# «186-]», «[18--]» — приблизительная датировка
YEAR_DECADE = re.compile(r"\b(1[5-9]\d)\s*[-\u2013\u2014.]")
YEAR_CENTURY = re.compile(r"\b(1[5-9])[-\u2013\u2014]{2}")

# словесная датировка: «2-я пол. XIX в.», «конец XIX-нач. XX в.», «XVIII в.»
ROMAN = {"XVI": 1500, "XVII": 1600, "XVIII": 1700, "XIX": 1800, "XX": 1900}
ROMAN_CENT = re.compile(r"\b(XVIII|XVII|XVI|XIX|XX)\s*(?:в\.|век)", re.I)


def roman_range(s: str) -> str:
    """«2-я пол. XIX в.» → 1850-1899; «конец XIX-нач. XX в.» → 1890-1919."""
    cents = [ROMAN[m.group(1).upper()] for m in ROMAN_CENT.finditer(s)
             if m.group(1).upper() in ROMAN]
    if not cents:
        return "-"
    lo, hi = min(cents), max(cents)
    low = s.lower()
    a, b = lo, hi + 99
    if len(cents) == 1:
        if "2-я пол" in low or "втор" in low or "конец" in low or "кон." in low:
            a = lo + 50
        if "1-я пол" in low or "перв" in low or "нач" in low:
            b = lo + 49
    else:
        if "конец" in low or "кон." in low:
            a = lo + 90
        if "нач" in low:
            b = hi + 19
    return f"{a}-{b}"


COLS = ["catalog_id", "file", "title", "biblio", "authors", "place", "publisher",
        "year_field", "year_from", "year_to", "year_source", "volume", "bbk", "udk",
        "contents_note", "subjects", "library", "scale_raw", "scale_count",
        "scale_min_denom", "sheets_in_note", "has_scale", "has_year"]


def norm(s: str) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", s).strip()


def parse_card(path: Path) -> dict:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "lxml")
    lines = [norm(x) for x in soup.get_text("\n", strip=True).split("\n")]
    lines = [x for x in lines if x]

    rec: dict = {"file": path.name, "biblio": ""}

    # библиографическое описание — первая осмысленная строка после метки
    for i, ln in enumerate(lines):
        if ln == "Библиографическое описание":
            for j in range(i + 1, min(i + 4, len(lines))):
                if lines[j] not in STOP:
                    rec["biblio"] = lines[j]
                    break
            break

    # блок метка → значение
    fields: dict = {}
    cur = None
    for ln in lines:
        if ln in LABELS:
            cur = ln
            fields.setdefault(cur, [])
            continue
        if cur is None or ln in STOP:
            continue
        if ln.startswith("Национальная электронная библиотека"):
            break
        fields[cur].append(ln)

    def g(label: str, limit: int = 4) -> str:
        return " ".join(fields.get(label, [])[:limit]).strip()

    rec["catalog_id"] = g("Код документа в НЭБ", 1)
    if not rec["catalog_id"]:
        m = re.search(r"(\d{6}_\d{6}_\d+)", path.name)
        rec["catalog_id"] = m.group(1) if m else ""
    rec["title"] = g("Заглавие", 2)
    rec["authors"] = g("Автор(ы)", 2)
    rec["place"] = g("Место издания", 2)
    rec["publisher"] = g("Издательство", 2)
    rec["year_field"] = g("Год издания", 1)
    rec["volume"] = g("Объем", 3)
    rec["bbk"] = g("ББК", 2)
    rec["udk"] = g("УДК", 2)
    rec["library"] = g("Библиотека", 1)
    note = " ".join(fields.get("Примечание содержания", []))
    rec["contents_note"] = note
    rec["subjects"] = " | ".join(x for x in fields.get("Тематика", []) if x != ">")[:600]

    # ---- датировка
    src = ""
    y1 = y2 = ""
    for hay, tag in ((rec["year_field"], "year_field"), (rec["biblio"], "biblio")):
        if not hay:
            continue
        if YEAR.search(hay):
            ys = YEAR.findall(hay)
            y1, y2, src = ys[0], ys[-1], tag + "_exact"
        elif YEAR_CENTURY.search(hay):
            c = YEAR_CENTURY.search(hay).group(1)
            y1, y2, src = c + "00", c + "99", tag + "_century"
        elif YEAR_DECADE.search(hay):
            d = YEAR_DECADE.search(hay).group(1)
            y1, y2, src = d + "0", d + "9", tag + "_decade"
        elif ROMAN_CENT.search(hay):
            y1, y2, src = roman_range(hay), "", tag + "_roman"
            y1, y2 = y1.split("-")[0], y1.split("-")[1]
        if src:
            break
    rec["year_from"], rec["year_to"], rec["year_source"] = y1, y2, src or "none"

    # ---- масштаб: примечание содержания + биб. описание
    hay = note + " " + rec["biblio"]
    nums = [int(re.sub(r"[ \u00a0]", "", m)) for m in SCALE_NUM.findall(hay)]
    raw = [f"1:{n}" for n in nums]
    raw += [f"{v} вер./дюйм" for v in SCALE_VERST.findall(hay)]
    raw += [f"{v} саж./дюйм" for v in SCALE_SAZH.findall(hay)]
    # верста = 500 саженей = 42000 дюймов; сажень = 84 дюйма
    for v in SCALE_VERST.findall(hay):
        nums.append(int(round(float(v.replace(",", ".")) * 42000)))
    for v in SCALE_SAZH.findall(hay):
        nums.append(int(v) * 84)
    rec["scale_raw"] = "; ".join(dict.fromkeys(raw))[:400]
    rec["scale_count"] = len(set(nums))
    rec["scale_min_denom"] = min(nums) if nums else ""
    rec["sheets_in_note"] = len(re.findall(r"(?:^|;)\s*\d+\.\s", note))
    rec["has_scale"] = "true" if nums else "false"
    rec["has_year"] = "true" if y1 else "false"
    return rec


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(SRC.rglob("*.html"))
    rows = [parse_card(f) for f in files]

    with (OUT / "cards.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    (OUT / "cards.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

    rep = {
        "source": "neb_cards", "files": len(files),
        "with_catalog_id": sum(1 for r in rows if r["catalog_id"]),
        "with_year": sum(1 for r in rows if r["has_year"] == "true"),
        "year_source": dict(Counter(r["year_source"] for r in rows)),
        "with_scale": sum(1 for r in rows if r["has_scale"] == "true"),
        "with_contents_note": sum(1 for r in rows if r["contents_note"]),
        "multi_scale": sum(1 for r in rows if (r["scale_count"] or 0) > 1),
        "with_bbk": sum(1 for r in rows if r["bbk"]),
        "no_year_no_scale": sum(1 for r in rows
                                if r["has_year"] == "false" and r["has_scale"] == "false"),
    }
    (OUT / "REPORT.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    for k, v in rep.items():
        print(f"{k}: {v}")
    print(f"\nвыход: {OUT}")


if __name__ == "__main__":
    main()
