# -*- coding: utf-8 -*-
"""РГАДА: губернские межевые фонды — опись-уровень «Полевых записок» по нашим 4 губерниям.

Решение пользователя 2026-10-02: вносить ПО ОДНОЙ СТРОКЕ, как в каталоге архива,
без разбора и просмотра содержимого описи. Дело-уровень не нужен: у этих описей
распознанных PDF нет (только 1965 постраничных образов), а сами «Полевые записки» —
первичная съёмочная документация землемеров, в карточку идёт опись целиком.

Берётся ТОЛЬКО опись 1 «Полевые записки» (все её части). Остальные описи этих фондов
(дела спорные, дела мелочные, журналы и протоколы межевых контор) под критерии не подходят.

Фонды: 1313 Калужская, 1327 Пермская, 1337 Смоленская, 1353 Ярославская.
"""
import csv
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

import pdfplumber  # noqa: F401  (единая среда с остальными скриптами rgada)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
OUT = BASE / "output" / "rgada_CONSOLIDATED"
UA = {"User-Agent": "Mozilla/5.0"}

FUNDS = {
    "1313": "Калужская губерния",
    "1327": "Пермская губерния",
    "1337": "Смоленская губерния",
    "1353": "Ярославская губерния",
}
TAKE = re.compile(r"^полевые\s+записки", re.I)

COLS = ["fund", "fund_name", "opis", "opis_name", "territory", "storage", "years",
        "units_count", "annotation", "opis_url", "opis_pdf", "source", "level", "note"]


def fetch(fund: str) -> str:
    cache = OUT / f"_f{fund}_listing.html"
    if cache.exists() and cache.stat().st_size > 5000:
        return cache.read_text(encoding="utf-8")
    url = f"http://rgada.info/poisk/index.php?fund_number={fund}&Sk=500"
    txt = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
    txt = txt.decode("utf-8", "replace")
    OUT.mkdir(parents=True, exist_ok=True)
    cache.write_text(txt, encoding="utf-8")
    return txt


def rows(html: str, fund: str) -> list[dict]:
    out: list[dict] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
        if len(tds) < 7:
            continue
        cell = []
        for td in tds:
            t = re.sub(r"<[^>]+>", " ", td).replace("&nbsp;", " ").replace("&quot;", '"')
            cell.append(re.sub(r"\s+", " ", t).strip())
        if cell[0] != fund:
            continue
        opis, oname = cell[2], cell[3]
        if not TAKE.match(oname):
            continue
        part = re.sub(r"[^0-9]", "", opis.split(".")[-1]) or "1"
        tag = f"{fund}-opis_1-{part}" if "." in opis else f"{fund}-opis_{opis}"
        out.append({
            "fund": fund,
            "fund_name": cell[1],
            "opis": opis,
            "opis_name": oname,
            "territory": FUNDS[fund],
            "storage": cell[4],
            "years": cell[5],
            "units_count": cell[6],
            "annotation": cell[7] if len(cell) > 7 else "",
            "opis_url": f"http://rgada.info/poisk/index2.php?str={tag}",
            "opis_pdf": "",
            "source": "rgada",
            "level": "opis",
            "note": "полевые записки Генерального и Специального межевания; "
                    "распознанной описи нет, доступны постраничные образы",
        })
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    allrows: list[dict] = []
    for fund in FUNDS:
        r = rows(fetch(fund), fund)
        allrows += r
        total = sum(int(x["units_count"]) for x in r if x["units_count"].isdigit())
        print(f"ф.{fund} {FUNDS[fund]}: описей-частей {len(r)}, дел за ними {total}")
        for x in r:
            print(f"    оп.{x['opis']:<8} {x['units_count']:>6} дел  {x['years']:<14} {x['annotation'][:24]}")

    path = OUT / "rgada_gubernskie_mezhevye_opisi.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(allrows)
    (OUT / "rgada_gubernskie_mezhevye_opisi.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in allrows), encoding="utf-8")

    grand = sum(int(x["units_count"]) for x in allrows if x["units_count"].isdigit())
    print(f"\nВСЕГО строк (опись-уровень): {len(allrows)}; дел за ними: {grand}")
    print(f"выход: {path}")


if __name__ == "__main__":
    main()
