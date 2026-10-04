# -*- coding: utf-8 -*-
"""ГАСО: разбор описи ф. 259 оп. 1 (id=155) — коллекция планов и чертежей Смоленской губернии.

Продолжение работы, остановленной 14.09.2026 на `transport_error`. Причина той остановки
установлена сегодня: у `https://portal.gaso-smolensk.ru` не отдаётся промежуточный сертификат,
проверка TLS падает (`unable to get local issuer certificate`). По `http://` портал работает,
`robots.txt` поддомена отдаёт **404** — собственных запретов у него нет; у основного домена
`gaso-smolensk.ru` запрещён только `/wp-admin/`.

Фонд: **259 «Коллекция планов, чертежей земель и лесов Смоленской губернии», 1750–1915**,
одна опись. Это профильный картографический фонд по одной из наших четырёх губерний.

Задача зонда — установить состав описи: сколько дел, какие заголовки, есть ли даты и листы.
Один GET, ничего не пишет в каталоги прогонов, дела не открывает.
"""
import io
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

URL = "http://portal.gaso-smolensk.ru/page/portal/opisView.jsf?id=155"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
OUT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output\gaso_opis155_probe_20261004")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})
    r = s.get(URL, timeout=60)
    print(f"HTTP {r.status_code}, {len(r.content)} байт")
    (OUT / "opis155.html").write_bytes(r.content)
    if r.status_code != 200:
        return

    soup = BeautifulSoup(r.text, "lxml")
    txt = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    # шапка описи
    for mark in ("Фонд", "Опись", "Количество дел", "Крайние даты", "Заголовок"):
        m = re.search(mark + r"[:\s]{1,3}([^|]{0,90})", txt)
        if m:
            print(f"  {mark}: {m.group(1).strip()[:90]}")

    # таблицы JSF
    tables = soup.find_all("table")
    print(f"\nтаблиц на странице: {len(tables)}")
    best, best_rows = None, 0
    for t in tables:
        rows = t.find_all("tr")
        if len(rows) > best_rows:
            best, best_rows = t, len(rows)
    if best is None:
        print("таблиц нет — состав описи рисуется иначе")
        return
    rows = best.find_all("tr")
    print(f"самая большая таблица: {len(rows)} строк")
    head = [re.sub(r"\s+", " ", c.get_text(" ", strip=True))[:28]
            for c in rows[0].find_all(["th", "td"])]
    print("  шапка:", head)
    for tr in rows[1:9]:
        cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True))[:70]
                 for c in tr.find_all(["th", "td"])]
        if any(cells):
            print("   ", cells)

    # признаки постраничности
    pag = re.findall(r"(?:страниц|Page|из)\s*[:\s]*(\d+)", txt)[:5]
    print("\nвозможные счётчики страниц:", pag)
    nums = re.findall(r"(\d{2,5})\s*(?:дел|ед\. хр\.|единиц)", txt)[:5]
    print("возможные счётчики дел:", nums)
    print(f"\nсохранено: {OUT / 'opis155.html'}")


if __name__ == "__main__":
    main()
