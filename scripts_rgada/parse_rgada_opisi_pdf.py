# -*- coding: utf-8 -*-
"""РГАДА: разбор PDF-описей (распознанных архивом) в дело-уровневые записи.

Маршрут: http://rgada.info/opisi/{фонд}-opis_{опись}.pdf — текстовый слой, таблица 9 колонок.
Это НЕ краул: PDF скачиваются точечно, разбираются офлайн. Работает независимо от смены
формата сайта (решение 2026-10-02: разработка скраперов РГАДА заморожена).

Выход — единый каталог РГАДА: output/rgada_CONSOLIDATED/
"""
import csv
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pdfplumber

BASE = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
PDF_DIR = BASE / "output" / "rgada_opisi_pdf_20261002"
OUT = BASE / "output" / "rgada_CONSOLIDATED"
UA = {"User-Agent": "Mozilla/5.0"}

# описи, у которых архив выложил распознанный PDF (проверено 2026-10-02)
OPISI = [
    ("1356", "1", "Губернские, уездные и городские атласы, карты и планы Генерального межевания"),
    ("192", "4", "Атласы России"),
    ("192", "5", "Атласы мира"),
]

GUBERNIAS = {
    "Калужск": "Калужская губерния",
    "Пермск": "Пермская губерния",
    "Смоленск": "Смоленская губерния",
    "Ярославск": "Ярославская губерния",
}

# §1.2 правил: город — не единица анализа
CITY = re.compile(r"\bплан\s+г\.|\bплан\s+города|карта\s+города|городск\w+\s+план", re.I)


def fetch(fund: str, op: str) -> Path | None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    p = PDF_DIR / f"{fund}-opis_{op}.pdf"
    if p.exists() and p.stat().st_size > 1000:
        return p
    url = f"http://rgada.info/opisi/{fund}-opis_{op}.pdf"
    try:
        b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
        if not b.startswith(b"%PDF"):
            return None
        p.write_bytes(b)
        return p
    except Exception as exc:
        print(f"  ! {fund}-{op}: {type(exc).__name__}")
        return None


def parse(path: Path, fund: str, op: str, opis_name: str) -> list[dict]:
    """Таблица описи → записи. Колонки: № | Литера | Нач | Кон | Датировка | Адм.ед | Заголовок | Лл | Прим."""
    rows: list[dict] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            tb = page.extract_table()
            if not tb:
                continue
            for r in tb:
                if not r or len(r) < 7:
                    continue
                cell = [(c or "").replace("\n", " ").strip() for c in r]
                num = cell[0]
                if not re.fullmatch(r"\d+", num or ""):   # шапка/мусор
                    continue
                rows.append({
                    "fund": fund,
                    "opis": op,
                    "opis_name": opis_name,
                    "unit": num,
                    "litera": cell[1],
                    "year_from": cell[2],
                    "year_to": cell[3],
                    "dating": cell[4],
                    "adm_unit": cell[5],
                    "title": cell[6],
                    "sheets": cell[7] if len(cell) > 7 else "",
                    "note": cell[8] if len(cell) > 8 else "",
                    "source": "rgada",
                    "level": "unit",
                    "opis_pdf": f"http://rgada.info/opisi/{fund}-opis_{op}.pdf",
                })
    return rows


def territory(rec: dict) -> str | None:
    blob = f"{rec['adm_unit']} {rec['title']}"
    for key, full in GUBERNIAS.items():
        if re.search(key, blob, re.I):
            return full
    return None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    allrows: list[dict] = []
    for fund, op, name in OPISI:
        p = fetch(fund, op)
        if not p:
            print(f"  ф.{fund} оп.{op}: PDF недоступен (ещё не распознан)")
            continue
        rows = parse(p, fund, op, name)
        allrows += rows
        print(f"  ф.{fund} оп.{op}: {len(rows)} дел из PDF ({p.stat().st_size // 1024} КБ)")

    # территориальная привязка + гейт §1.2
    ours, other, city = [], [], []
    for r in allrows:
        t = territory(r)
        if not t:
            other.append(r)
            continue
        r["territory"] = t
        (city if CITY.search(r["title"]) else ours).append(r)

    cols = ["fund", "opis", "opis_name", "unit", "litera", "year_from", "year_to", "dating",
            "adm_unit", "territory", "title", "sheets", "note", "source", "level", "opis_pdf"]

    def dump(name: str, data: list[dict]) -> None:
        with (OUT / name).open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for d in data:
                w.writerow(d)

    dump("rgada_units_our_gubernias.csv", ours)
    dump("rgada_units_city_dropped.csv", city)
    (OUT / "rgada_units_all.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in allrows), encoding="utf-8")

    print(f"\nВСЕГО дел разобрано: {len(allrows)}")
    print(f"  наши губернии:      {len(ours)}")
    print(f"  отсев город (§1.2): {len(city)}")
    print(f"  прочие территории:  {len(other)}")
    import collections
    print("  по губерниям:", dict(collections.Counter(r["territory"] for r in ours)))
    print(f"\nВыход: {OUT}")


if __name__ == "__main__":
    main()
