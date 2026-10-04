# -*- coding: utf-8 -*-
"""РГВИА: сбор всего, что база электронных описей даёт по нашим четырём губерниям.

База: бд.ргвиа.рф (`xn--90ag.xn--80adcv1b.xn--p1ai`), только http; `robots.txt` → 404,
собственных запретов нет. Поиск — POST `/search` (Yii) с CSRF-токеном, поля
`Search[query]`, `Search[table]` (''/funds/lists/cases), `Search[from]`, `Search[to]`.

Объём базы: ~78 страниц перечня фондов (≈860 фондов), преимущественно периода Первой
мировой войны. **Фонд 846 (ВУА) — главное картографическое собрание РГВИА — в базе
отсутствует** (поиск по «846», «военно-учёный», «карты» на уровне фондов даёт 0).

Скрипт обходит набор запросов по губерниям и их уездным центрам, сводит результаты
в единый набор без дублей и помечает картографические заголовки.
"""
import csv
import io
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://xn--90ag.xn--80adcv1b.xn--p1ai"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
OUT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output\rgvia_gubernias_20261004")
PAUSE = 4

QUERIES = [
    ("Смоленск", "Смоленская"), ("Смоленской", "Смоленская"), ("Вязьма", "Смоленская"),
    ("Калуж", "Калужская"), ("Калуга", "Калужская"),
    ("Пермск", "Пермская"), ("Пермь", "Пермская"),
    ("Ярослав", "Ярославская"), ("Рыбинск", "Ярославская"),
]
# предмет: картографический заголовок
MAP_SUBJ = re.compile(r"\bкарт\w*|\bплан\w*|\bсъемк\w*|\bсъёмк\w*|\bчертеж\w*|\bатлас\w*|"
                      r"топографическ|глазомерн|рекогносцир", re.I)
COLS = ["source", "territory", "fund", "opis", "delo", "title", "date_from", "date_to",
        "sheets", "note", "query", "is_map", "needs_human", "needs_human_reason"]


def token(s: requests.Session) -> str:
    html = s.get(BASE + "/search", timeout=40).text
    el = BeautifulSoup(html, "lxml").find("input", attrs={"name": "YII_CSRF_TOKEN"})
    return el.get("value") if el else ""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})
    tok = token(s)
    if not tok:
        print("CSRF-токен не получен — стоп")
        return

    seen: dict[tuple, dict] = {}
    per_query: dict[str, int] = {}
    for q, terr in QUERIES:
        time.sleep(PAUSE)
        r = s.post(BASE + "/search", timeout=120, headers={"Referer": BASE + "/search"},
                   data={"YII_CSRF_TOKEN": tok, "Search[query]": q,
                         "Search[table]": "cases", "Search[from]": "", "Search[to]": ""})
        if r.status_code != 200:
            print(f"«{q}» → HTTP {r.status_code}, пропуск")
            continue
        (OUT / f"raw_{q.lower()}.html").write_text(r.text, encoding="utf-8")
        pages = [r.text]
        # выдача отдаёт 10 строк; полный список id уходит в /search/pager?tbl=b&ids=...&page=N
        m = re.search(r'href="(/search/pager\?tbl=[^"&]+&amp;ids=[^"&]+)(?:&amp;page=\d+)?"', r.text)
        if m:
            href = m.group(1).replace("&amp;", "&")
            total = len(re.findall(r"%2C", href)) + 1
            last = (total + 9) // 10
            print(f"   полный список: {total} дел → {last} страниц")
            for pg in range(2, last + 1):
                time.sleep(PAUSE)
                rp = s.get(BASE + href + f"&page={pg}", timeout=90,
                           headers={"Referer": BASE + "/search"})
                if rp.status_code == 200:
                    pages.append(rp.text)
        rows = []
        for html in pages:
            rows += BeautifulSoup(html, "lxml").find_all("tr")
        n = 0
        for tr in rows:
            c = [x.get_text(" ", strip=True) for x in tr.find_all("td")]
            if len(c) < 7 or not any(c):
                continue
            delo, opis, fund, title, d1, d2, sheets = c[0], c[1], c[2], c[3], c[4], c[5], c[6]
            note = c[7] if len(c) > 7 else ""
            key = (fund, opis, delo)
            is_map = bool(MAP_SUBJ.search(title))
            reasons = []
            if not is_map:
                reasons.append("subject_not_cartographic")
            if not re.search(r"губерни|уезд", title, re.I):
                reasons.append("territory_not_in_title")
            rec = {
                "source": "rgvia", "territory": terr, "fund": fund, "opis": opis,
                "delo": delo, "title": title, "date_from": d1, "date_to": d2,
                "sheets": sheets, "note": note, "query": q,
                "is_map": "true" if is_map else "false",
                "needs_human": "true" if reasons else "false",
                "needs_human_reason": "; ".join(reasons),
            }
            if key in seen:
                if terr not in seen[key]["territory"]:
                    seen[key]["territory"] += "; " + terr
            else:
                seen[key] = rec
            n += 1
        per_query[q] = n
        print(f"«{q}» → строк {n}")

    rows = sorted(seen.values(), key=lambda x: (x["territory"], x["fund"], x["delo"]))
    with (OUT / "records.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    (OUT / "records.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

    rep = {
        "source": "rgvia", "base": "бд.ргвиа.рф (электронные описи)",
        "transport": "http только; https ломает TLS; robots.txt → 404 (запретов нет)",
        "search": "POST /search, Yii CSRF, Search[query]/[table]/[from]/[to]",
        "fund_846_vua_present": False,
        "queries": per_query,
        "records": len(rows),
        "maps": sum(1 for r in rows if r["is_map"] == "true"),
        "by_territory": dict(Counter(r["territory"] for r in rows)),
        "needs_human": sum(1 for r in rows if r["needs_human"] == "true"),
        "ready_for_import": False,
    }
    (OUT / "REPORT.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in rep.items():
        print(f"{k}: {v}")
    print(f"\nвыход: {OUT}")


if __name__ == "__main__":
    main()
