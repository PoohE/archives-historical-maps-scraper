# -*- coding: utf-8 -*-
"""РГАДА ф.1354 «Планы дач Генерального и Специального межевания»: разбор списка описей.

Описи ф.1354 организованы ПО ГУБЕРНИЯМ И УЕЗДАМ — т.е. территориальный гейт §1.2
применяется прямо к названию описи, без спуска на дело-уровень.
Шаг 1 (этот скрипт): список описей → отбор по нашим 4 губерниям + отметка, у каких есть PDF.
Шаг 2 (parse_rgada_f1354_pdf.py): у отобранных с PDF — спуск на дело-уровень.
"""
import csv
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
OUT = BASE / "output" / "rgada_CONSOLIDATED"
UA = {"User-Agent": "Mozilla/5.0"}
URL = "http://rgada.info/poisk/index.php?fund_number=1354&Sk=1000"

GUBERNIAS = {
    "Калужск": "Калужская губерния",
    "Пермск": "Пермская губерния",
    "Смоленск": "Смоленская губерния",
    "Ярославск": "Ярославская губерния",
}


def fetch() -> str:
    cache = OUT / "_f1354_listing.html"
    if cache.exists() and cache.stat().st_size > 10000:
        return cache.read_text(encoding="utf-8")
    h = urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=90).read()
    txt = h.decode("utf-8", "replace")
    OUT.mkdir(parents=True, exist_ok=True)
    cache.write_text(txt, encoding="utf-8")
    return txt


def rows(html: str) -> list[dict]:
    """Строки таблицы описей: <tr> с ячейками (№ описи | хранилище | годы | кол-во | аннотация | ...)."""
    out: list[dict] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
        if len(tds) < 5:
            continue
        cells = []
        for td in tds:
            pdf = re.search(r'href="([^"]*\.pdf)"', td, re.I)
            t = re.sub(r"<[^>]+>", " ", td)
            t = t.replace("&nbsp;", " ").replace("&quot;", '"')
            t = re.sub(r"\s+", " ", t).strip()
            cells.append((t, pdf.group(1) if pdf else ""))
        text = [c[0] for c in cells]
        pdfs = [c[1] for c in cells if c[1]]
        if "1354" not in text[0]:
            continue
        # text: [фонд, название фонда, № описи, название описи, хранилище, годы, кол-во, аннотация, ...]
        if len(text) < 7:
            continue
        opis_no = text[2]
        name = text[3]
        if not opis_no or opis_no.lower().startswith("№"):
            continue
        out.append({
            "fund": "1354",
            "opis": opis_no,
            "opis_name": name,
            "storage": text[4],
            "years": text[5],
            "units_count": text[6],
            "annotation": text[7] if len(text) > 7 else "",
            "opis_pdf": ("http://rgada.info" + pdfs[0]) if pdfs else "",
            "source": "rgada",
            "level": "opis",
        })
    return out


def territory(rec: dict) -> str | None:
    blob = f"{rec['opis_name']} {rec['annotation']}"
    for key, full in GUBERNIAS.items():
        if re.search(key, blob, re.I):
            return full
    return None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    html = fetch()
    allrows = rows(html)
    print(f"описей ф.1354 разобрано: {len(allrows)}")

    ours = []
    for r in allrows:
        t = territory(r)
        if t:
            r["territory"] = t
            ours.append(r)

    cols = ["fund", "opis", "opis_name", "territory", "storage", "years", "units_count",
            "annotation", "opis_pdf", "source", "level"]
    with (OUT / "rgada_f1354_opisi_our_gubernias.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for d in ours:
            w.writerow(d)
    (OUT / "rgada_f1354_opisi_all.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in allrows), encoding="utf-8")

    import collections
    print(f"наши губернии: {len(ours)} описей")
    print("  ", dict(collections.Counter(r["territory"] for r in ours)))
    withpdf = [r for r in ours if r["opis_pdf"]]
    print(f"  из них с распознанным PDF: {len(withpdf)}")
    for r in withpdf:
        print(f"    оп.{r['opis']} — {r['territory']} — {r['units_count']} дел — {r['opis_pdf']}")
    tot = 0
    for r in ours:
        m = re.fullmatch(r"\d+", r["units_count"].strip())
        if m:
            tot += int(r["units_count"])
    print(f"  суммарно дел в наших описях: {tot}")
    print(f"\nВыход: {OUT}")


if __name__ == "__main__":
    main()
