# -*- coding: utf-8 -*-
"""РГАДА ф.1355 оп.1 «Экономические примечания к планам дач Генерального межевания».

Распознанный архивом PDF с текстовым слоем: http://rgada.info/opisi/1355-opis_1.pdf
155 страниц, таблица 10 колонок — ГУБЕРНИЯ и УЕЗД отдельными полями (точнее, чем в ф.1356,
где территория вытаскивалась из заголовка).

Колонки: № ед. хр. | Литера | Губерния | Уезд | Название ед. хр. | Нач. дата | Кон. дата |
         Датировка | Кол-во лл. | Прим.

Содержание фонда — текстовые приложения к планам Генерального межевания (описания дач,
рек и речек, перечневые табели, каталоги к генеральным планам). Берём их как спутники
картографии: привязка к даче/уезду прямая, уровень §1.2 выполнен.
"""
import csv
import io
import json
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

import pdfplumber

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
PDF = BASE / "output" / "rgada_opisi_pdf_20261002" / "1355-opis_1.pdf"
OUT = BASE / "output" / "rgada_CONSOLIDATED"
URL = "http://rgada.info/opisi/1355-opis_1.pdf"
UA = {"User-Agent": "Mozilla/5.0"}

OPIS_NAME = ("Экономические примечания к планам дач Генерального межевания, 1765-1843 гг. "
             "(коллекция). Опись 1. Экономические примечания к планам Генерального межевания")

GUBERNIAS = {
    "Калужск": "Калужская губерния",
    "Пермск": "Пермская губерния",
    "Смоленск": "Смоленская губерния",
    "Ярославск": "Ярославская губерния",
}

# §1.2: отсекать только то, что ЦЕЛИКОМ про город. «описание города N» внутри уездного
# экономического примечания на дачи — часть уездной единицы, не городской план.
CITY_ONLY = re.compile(r"^(статистическое\s+)?описание\s+город\w*|^план\s+город\w*", re.I)
UEZD_MARK = re.compile(r"дач|уезд|губерн|рек|речек|табел|межев", re.I)

COLS = ["fund", "opis", "opis_name", "unit", "litera", "gubernia_raw", "uezd", "territory",
        "title", "year_from", "year_to", "year_source", "dating", "sheets", "note", "source",
        "level", "extraction", "opis_pdf"]


def fill_dates(rows: list[dict]) -> None:
    """В описи даты проставлены только у ПЕРВОЙ строки группы (объединённая ячейка):
    у №454 «1776-1780» есть, у №455-457 той же губернии — пусто. Протягиваем вниз,
    пока не сменилась губерния, и помечаем `year_source=inherited` — чтобы на приёмке
    было видно, где дата своя, а где унаследована от группы."""
    last_g = last_f = last_t = ""
    for r in rows:
        own = bool(re.fullmatch(r"\d{4}", r["year_from"] or ""))
        if own:
            last_g, last_f, last_t = r["gubernia_raw"], r["year_from"], r["year_to"]
            r["year_source"] = "own"
        elif last_f and r["gubernia_raw"] == last_g:
            r["year_from"], r["year_to"] = last_f, last_t
            r["year_source"] = "inherited"
        else:
            r["year_source"] = "none"


def fetch() -> Path:
    PDF.parent.mkdir(parents=True, exist_ok=True)
    if PDF.exists() and PDF.stat().st_size > 2000:
        return PDF
    b = urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=120).read()
    PDF.write_bytes(b)
    return PDF


def clean(v: str | None) -> str:
    return re.sub(r"\s+", " ", (v or "").replace("\n", " ")).strip()


def parse() -> list[dict]:
    out: list[dict] = []
    with pdfplumber.open(fetch()) as pdf:
        for page in pdf.pages:
            tb = page.extract_table()
            if not tb:
                continue
            for r in tb:
                if not r or len(r) < 9:
                    continue
                c = [clean(x) for x in r]
                if not re.fullmatch(r"\d+", c[0] or ""):      # шапка, итоговые строки «97 дач»
                    continue
                out.append({
                    "fund": "1355", "opis": "1", "opis_name": OPIS_NAME,
                    "unit": c[0], "litera": c[1],
                    "gubernia_raw": c[2], "uezd": c[3], "title": c[4],
                    "year_from": c[5], "year_to": c[6], "dating": c[7],
                    "sheets": c[8], "note": c[9] if len(c) > 9 else "",
                    "source": "rgada", "level": "unit",
                    "extraction": "pdf_text_layer_2026-10-02", "opis_pdf": URL,
                })
    return out


def territory(rec: dict) -> str | None:
    for key, full in GUBERNIAS.items():
        if re.search(key, rec["gubernia_raw"], re.I):
            return full
    return None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    allrows = parse()
    fill_dates(allrows)
    ours, city, other = [], [], []
    for r in allrows:
        t = territory(r)
        if not t:
            other.append(r)
            continue
        r["territory"] = t
        if CITY_ONLY.match(r["title"]) and not UEZD_MARK.search(r["title"]):
            city.append(r)
        else:
            ours.append(r)

    def dump(name: str, data: list[dict]) -> None:
        with (OUT / name).open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)

    dump("rgada_f1355_units_our_gubernias.csv", ours)
    dump("rgada_f1355_units_city_dropped.csv", city)
    (OUT / "rgada_f1355_units_all.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in allrows), encoding="utf-8")

    print(f"ВСЕГО разобрано дел: {len(allrows)}   (в каталоге архива заявлено 2131)")
    print(f"  наши губернии:      {len(ours)}")
    print(f"  отсев город (§1.2): {len(city)}")
    print(f"  прочие территории:  {len(other)}")
    print("  по губерниям:", dict(Counter(r["territory"] for r in ours)))
    print("  по уездам (топ):", Counter(f"{r['territory'][:8]}/{r['uezd']}" for r in ours).most_common(8))
    yrs = [r["year_from"] for r in ours if re.fullmatch(r"\d{4}", r["year_from"] or "")]
    if yrs:
        print(f"  годы: {min(yrs)}–{max(yrs)}, заполнено {len(yrs)} из {len(ours)}")
    print("  источник даты:", dict(Counter(r.get("year_source") for r in ours)))
    print(f"\nВыход: {OUT}")


if __name__ == "__main__":
    main()
