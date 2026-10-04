# -*- coding: utf-8 -*-
"""Разведка РГАЭ: есть ли онлайн-каталог, что разрешает robots, какой маршрут поиска.

Последний источник плана, по которому ничего не известно. Задача разведки — НЕ собирать
данные, а установить: отвечает ли сайт, что запрещено robots, есть ли электронный каталог
(собственный или через общероссийские порталы), и по какому маршруту вообще искать
картографические материалы по нашим четырём губерниям.

Только GET, паузы между запросами, ничего не пишется в каталоги прогонов.
"""
import io
import re
import sys
import time

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
PAUSE = 3

# кандидаты: собственный сайт архива и общероссийские точки доступа к его описям
TARGETS = [
    ("сайт архива", "http://rgae.ru/"),
    ("сайт архива (https)", "https://rgae.ru/"),
    ("robots", "https://rgae.ru/robots.txt"),
    ("ЦФК — единый каталог архивов РФ", "https://cfc.rusarchives.ru/"),
    ("Путеводители по фондам (rusarchives)", "https://guides.rusarchives.ru/"),
    ("portal.rusarchives — поиск", "https://portal.rusarchives.ru/"),
]


def probe(name: str, url: str, s: requests.Session) -> None:
    try:
        r = s.get(url, timeout=40, allow_redirects=True)
    except requests.RequestException as e:
        print(f"[{name}] {url} → ОШИБКА: {type(e).__name__}: {str(e)[:90]}")
        return
    body = r.text if "text" in r.headers.get("Content-Type", "") else ""
    title = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    title = re.sub(r"\s+", " ", title.group(1)).strip()[:80] if title else ""
    print(f"[{name}] → HTTP {r.status_code}, {len(r.content)} байт"
          f"{', конечный URL ' + r.url if r.url != url else ''}")
    if title:
        print(f"    title: {title}")
    if url.endswith("robots.txt") and r.status_code == 200:
        rules = [ln.strip() for ln in body.splitlines()
                 if ln.strip().lower().startswith(("disallow", "allow", "user-agent", "crawl-delay"))]
        print(f"    директив: {len(rules)}")
        for ln in rules[:18]:
            print("      ", ln)
    elif body:
        # ищем признаки электронного каталога
        marks = {
            "поиск по описям": r"поиск\s+по\s+(?:опис|фонд)",
            "электронный каталог": r"электронн\w+\s+каталог",
            "АИС/БД": r"\bАИС\b|база\s+данных",
            "ссылка на cfc": r"cfc\.rusarchives",
            "ссылка на portal": r"portal\.rusarchives",
            "личный кабинет / читальный зал": r"читальн\w+\s+зал",
        }
        found = [k for k, p in marks.items() if re.search(p, body, re.I)]
        print(f"    признаки каталога: {', '.join(found) if found else 'не найдены'}")
        links = sorted(set(re.findall(r'href="(https?://[^"]*(?:catalog|opis|fond|search)[^"]*)"',
                                      body, re.I)))[:5]
        for ln in links:
            print("      ссылка:", ln[:110])


def main() -> None:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})
    for name, url in TARGETS:
        probe(name, url, s)
        time.sleep(PAUSE)
        print()


if __name__ == "__main__":
    main()
