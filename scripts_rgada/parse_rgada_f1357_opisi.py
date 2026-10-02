# -*- coding: utf-8 -*-
"""РГАДА ф.1357 (атлас России ген.-майора Менде, 1847-1868) — опись-уровень, 2 строки.

Решение пользователя 2026-10-02: образы описей НЕ распознаём. Голубинский (зам. директора
РГАДА) сказал, что часть описей архив распознаёт сам и выложит в нормальном виде ≈ через месяц.
Если ф.1357 попадёт в распознавание — заберём дело-уровень повторным прогоном тем же парсером,
что и ф.1356 оп.1 / ф.1355 (`parse_rgada_opisi_pdf.py` / `parse_rgada_f1355_pdf.py`).
До тех пор в каталоге стоят две строки уровня описи.

Съёмка Менде — крупномасштабная (1 верста в дюйме) топографическая съёмка межевого корпуса.
Из наших четырёх губерний в атлас Менде входит ЯРОСЛАВСКАЯ; остальные три — нет.
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
FUND = "1357"

COLS = ["fund", "fund_name", "opis", "opis_name", "territory", "storage", "years",
        "units_count", "annotation", "opis_url", "opis_pdf", "source", "level", "note"]

NOTE = ("образы описи не распознавались (решение 2026-10-02); при публикации архивом "
        "распознанной описи забрать дело-уровень повторным прогоном")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    url = f"http://rgada.info/poisk/index.php?fund_number={FUND}&Sk=100"
    html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90)
    html = html.read().decode("utf-8", "replace")

    rows: list[dict] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
        if len(tds) < 7:
            continue
        c = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", td)
                    .replace("&nbsp;", " ").replace("&quot;", '"')).strip() for td in tds]
        # номер описи приходит как «1 ОЦ» (особо ценное) — берём ведущее число
        num = re.match(r"\s*(\d+)", c[2] or "")
        if c[0] != FUND or not num or num.group(1) not in ("1", "2"):
            continue      # оп.3 «Черновые материалы и делопроизводство» не берём
        rows.append({
            "fund": FUND, "fund_name": c[1], "opis": c[2], "opis_name": c[3],
            "territory": "Ярославская губерния (в составе съёмки Менде)",
            "storage": c[4], "years": c[5], "units_count": c[6],
            "annotation": c[7] if len(c) > 7 else "",
            "opis_url": f"http://rgada.info/poisk/index2.php?str={FUND}-opis_{num.group(1)}",
            "opis_pdf": "", "source": "rgada", "level": "opis", "note": NOTE,
        })

    rows.sort(key=lambda x: x["opis"])
    path = OUT / "rgada_f1357_mende_opisi.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    (OUT / "rgada_f1357_mende_opisi.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

    print(f"строк: {len(rows)}")
    for r in rows:
        print(f"  оп.{r['opis']} «{r['opis_name']}» — {r['units_count']} дел, {r['years']}")
    print(f"выход: {path}")


if __name__ == "__main__":
    main()
