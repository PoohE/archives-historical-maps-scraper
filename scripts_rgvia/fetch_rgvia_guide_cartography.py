# -*- coding: utf-8 -*-
"""Путеводитель РГВИА (guides.rusarchives.ru, guide id 15): выемка картографических фондов.

Повод: в базе электронных описей РГВИА картографических фондов нет вовсе
(РЕШЕНИЕ_РГВИА_база_не_содержит_ВУА_2026-10-04.md). Печатный путеводитель даёт
объём, хронологию и состав фондов 414, 416, 418-421, 846 — то, что нужно, чтобы
решить, стоит ли очная работа.

Транспорт: http редиректит на https, https НЕ отдаёт промежуточный сертификат
(та же болезнь, что у портала ГАСО) → читаем с verify=False. robots.txt: Crawl-delay 10,
закрыты служебные пути Drupal; /terms/ и /funds/ разрешены.

Подразделы раздела 4 «Коллекции»:
  8362 — военно-исторические и картографические документы Военно-учёного архива
  8364 — документы по истории России, её вооружённых сил; картографические документы
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

BASE = "https://guides.rusarchives.ru"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
OUT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output\rgvia_guide_20261004")
PAUSE = 10  # robots: Crawl-delay 10
NODES = {
    "8362": "/terms/15/8362/voenno-istoricheskie-i-kartograficheskie-dokumenty-voenno-uchenogo-arhiva",
    "8364": "/terms/15/8364/dokumenty-po-istorii-rossii-ee-vooruzhennyh-sil-kartograficheskie-dokumenty",
}
WANTED = {"414", "416", "418", "419", "420", "421", "846", "827", "386", "435"}
FUND_RE = re.compile(r"Ф(?:онд)?\.?\s*(\d{2,4})")


def fetch(s, path):
    r = s.get(BASE + path, timeout=90, verify=False)
    return r


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})

    index = {}
    for node, path in NODES.items():
        r = fetch(s, path)
        print(f"узел {node} → HTTP {r.status_code}, {len(r.content)} б")
        (OUT / f"node_{node}.html").write_text(r.text, encoding="utf-8")
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.find_all("a", href=True):
            txt = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
            if "/terms/15/" in a["href"] and txt and txt not in ("Раздел 4. Коллекции",):
                index[a["href"]] = txt
        time.sleep(PAUSE)

    print(f"\nузлов-потомков найдено: {len(index)}")
    hits = {}
    for href, txt in index.items():
        m = FUND_RE.search(txt)
        fund = m.group(1) if m else ""
        mark = "  ← НУЖЕН" if fund in WANTED else ""
        print(f"   [{fund or '—':>4}] {txt[:80]}{mark}")
        if fund in WANTED:
            hits[fund] = {"title": txt, "href": href}

    (OUT / "razdel4_children.json").write_text(
        json.dumps({"children": index, "wanted_hits": hits}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"\nиз нужных фондов на уровне подразделов видно: {sorted(hits)}")
    print(f"выход: {OUT}")


if __name__ == "__main__":
    main()
