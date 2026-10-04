# -*- coding: utf-8 -*-
"""Разведка РГВИА, шаг 2: пробный поиск в базе электронных описей бд.ргвиа.рф.

Форма поиска — POST `/search` (Yii) с CSRF-токеном и полями:
  `Search[query]`  ключевые слова
  `Search[table]`  уровень поиска (на всех уровнях / фонды / описи / дела)
  `Search[from]`, `Search[to]`  даты

`robots.txt` сайта отдаёт 404 — собственных запретов нет; сайт работает только по http.

Задача: установить, сколько результатов даёт поиск по нашим губерниям, как выглядит
выдача (таблица, колонки) и есть ли постраничность. Делает несколько запросов с паузами,
сохраняет по одной странице выдачи на запрос для последующего офлайн-разбора.
"""
import io
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://xn--90ag.xn--80adcv1b.xn--p1ai"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
OUT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output\rgvia_probe_20261004")
PAUSE = 4

QUERIES = ["Смоленской губернии", "Калужской губернии",
           "Пермской губернии", "Ярославской губернии"]


def token(s: requests.Session) -> tuple[str, dict]:
    html = s.get(BASE + "/search", timeout=40).text
    soup = BeautifulSoup(html, "lxml")
    el = soup.find("input", attrs={"name": "YII_CSRF_TOKEN"})
    m = el.get("value") if el else None
    opts = dict(re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)</option>', html))
    return (m or ""), opts


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})

    tok, opts = token(s)
    print("CSRF-токен получен:", bool(tok))
    print("уровни поиска (Search[table]):", opts)

    for q in QUERIES:
        time.sleep(PAUSE)
        r = s.post(BASE + "/search", timeout=90, headers={"Referer": BASE + "/search"},
                   data={"YII_CSRF_TOKEN": tok, "Search[query]": q,
                         "Search[table]": "", "Search[from]": "", "Search[to]": ""})
        soup = BeautifulSoup(r.text, "lxml")
        txt = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        rows = soup.find_all("tr")
        cnt = re.search(r"(?:Найдено|Всего|результат\w*)\D{0,12}(\d[\d\s]*)", txt, re.I)
        pages = sorted(set(re.findall(r"_page=(\d+)", r.text)), key=lambda x: int(x))
        print(f"\n«{q}» → HTTP {r.status_code}, {len(r.content)} б, строк {len(rows)}, "
              f"счётчик {cnt.group(1).strip() if cnt else '—'}, страниц {pages[-1] if pages else '1'}")
        f = OUT / f"search_{q.split()[0].lower()}.html"
        f.write_text(r.text, encoding="utf-8")
        if rows:
            head = [c.get_text(" ", strip=True)[:22] for c in rows[0].find_all(["th", "td"])]
            print("   шапка:", head)
            for tr in rows[1:4]:
                cells = [c.get_text(" ", strip=True)[:60] for c in tr.find_all("td")]
                if any(cells):
                    print("   ", cells)
    print(f"\nвыход: {OUT}")


if __name__ == "__main__":
    main()
