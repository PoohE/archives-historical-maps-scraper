# -*- coding: utf-8 -*-
"""Разведка путеводителя РГВИА в базе guides.rusarchives.ru (Федеральное архивное агентство).

Повод: база электронных описей РГВИА картографические фонды не содержит
(РЕШЕНИЕ_РГВИА_база_не_содержит_ВУА_2026-10-04.md). Печатный путеводитель архива
(4 тома, 2006-2009) выложен в базе путеводителей и может дать состав и объём
фондов 414, 416, 418-421, 846 без очной работы.

Установлено: http редиректит на https, а https НЕ отдаёт промежуточный сертификат
(та же болезнь, что у портала ГАСО) — проверка цепочки падает `unable to get local issuer
certificate`. Страницы публичные, читаем с `verify=False`.
Структура: /terms/15/<node>/<slug> — узлы дерева путеводителя РГВИА (guide id = 15).
Раздел 4 «Коллекции» — узел 8361, именно там картографические коллекции.
"""
import io
import json
import re
import sys
import time
from pathlib import Path

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://guides.rusarchives.ru"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
OUT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output\rgvia_guide_20261004")
PAUSE = 2
ROOT = "/terms/15/8361/razdel-4-kollekcii"


def get(s, url):
    return s.get(url, timeout=60, verify=False)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})

    r = get(s, BASE + "/robots.txt")
    print(f"robots.txt → HTTP {r.status_code}, {len(r.content)} б")
    if r.status_code == 200:
        print(r.text[:600])

    r = get(s, BASE + ROOT)
    print(f"\nраздел 4 → HTTP {r.status_code}, {len(r.content)} б")
    (OUT / "razdel4.html").write_text(r.text, encoding="utf-8")
    soup = BeautifulSoup(r.text, "lxml")

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/terms/15/" in href or "/funds/15/" in href or "/fonds/" in href:
            txt = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
            links.append((txt, href))
    seen, uniq = set(), []
    for t, h in links:
        if h not in seen:
            seen.add(h)
            uniq.append((t, h))
    print(f"\nссылок на узлы путеводителя: {len(uniq)}")
    for t, h in uniq:
        print(f"   {t[:70]:72} {h}")
    (OUT / "razdel4_links.json").write_text(
        json.dumps(uniq, ensure_ascii=False, indent=1), encoding="utf-8")

    # поиск по номеру фонда — есть ли у базы поисковая форма
    for f in soup.find_all("form"):
        print("\nформа:", (f.get("method") or "get").upper(), f.get("action"),
              [i.get("name") for i in f.find_all(["input", "select"]) if i.get("name")])
    time.sleep(PAUSE)
    print(f"\nвыход: {OUT}")


if __name__ == "__main__":
    main()
