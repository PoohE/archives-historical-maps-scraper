# -*- coding: utf-8 -*-
"""Путеводитель РГВИА: описания 16 картографических коллекций раздела 4 → MD-справка.

Зачем: онлайн-описей этих фондов нет (РЕШЕНИЕ_РГВИА_...), поэтому путеводитель —
единственный способ узнать заранее объём, хронологию и состав; это материал для
решения об очной работе или тематическом запросе в архив.

Транспорт: https без промежуточного сертификата → verify=False; robots: Crawl-delay 10.
"""
import io
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
PAUSE = 10

# (узел, slug, подпись) — slug ОБЯЗАТЕЛЕН: /terms/15/<node> без него отдаёт 404
NODES = [
    ("8376", "generalnye-karty-rossii", "Генеральные карты России"),
    ("8377", "voenno-istoricheskie-karty-plany-i-albomy", "Военно-исторические карты, планы и альбомы"),
    ("8378", "voenno-istoricheskie-karty-plany-i-shemy", "Военно-исторические карты, планы и схемы"),
    ("8379", "dokumenty-o-granicah-rossii-pogranichnyh-i-zemlemernyh-rabotah",
     "Документы о границах России, пограничных и землемерных работах"),
    ("8380", "dokumenty-o-pogranichnyh-ukrepleniyah-krepostyah-i-ukreplennyh-poziciyah-rossii",
     "Документы о пограничных укреплениях, крепостях и укреплённых позициях России"),
    ("8381", "plany-i-opisaniya-gorodov-krepostey-seleniy-i-drugih-naselennyh-punktov-rossii",
     "Планы и описания городов, крепостей, селений и других населённых пунктов России"),
    ("8382", "karty-i-opisaniya-mestorozhdeniy-poleznyh-iskopaemyh-mineralnyh-istochnikov-i",
     "Карты и описания месторождений полезных ископаемых, минеральных источников и промышленных предприятий"),
    ("8383", "karty-i-opisaniya-putey-soobshcheniya-rossii", "Карты и описания путей сообщения России"),
    ("8384", "karty-i-opisaniya-vodnyh-soobshcheniy-rossii", "Карты и описания водных сообщений России"),
    ("8385", "gidrograficheskie-karty-i-plany-rossii", "Гидрографические карты и планы России"),
    ("8386", "topograficheskie-i-semitopograficheskie-raboty", "Топографические и семитопографические работы"),
    ("8387", "karty-i-atlasy-zemnogo-shara", "Карты и атласы земного шара"),
    ("8388", "karty-chastey-sveta", "Карты частей света"),
    ("8389", "astronomicheskie-karty", "Астрономические карты"),
    ("8363", "voenno-uchenyy-arhiv", "Военно-учёный архив (ф. 846)"),
    ("8365", "dokumenty-po-istorii-rossii-i-ee-vooruzhennyh-sil",
     "Документы по истории России и её вооружённых сил"),
]
FUND = re.compile(r"Ф(?:онд)?\.?\s*№?\s*(\d{2,4})")
VOLUME = re.compile(r"(\d[\d\s]{0,9})\s*(ед\.?\s*хр\.?|единиц хранения|д\.|дел)", re.I)
YEARS = re.compile(r"\b(1[5-9]\d\d|20\d\d)\s*[-–—]\s*(1[5-9]\d\d|20\d\d)")
OUR = re.compile(r"Смоленск|Калуж|Калуг|Перм|Ярослав", re.I)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})
    blocks = []
    for node, slug, label in NODES:
        f = OUT / f"node_{node}.html"
        if f.exists():
            html = f.read_text(encoding="utf-8")
        else:
            r = s.get(f"{BASE}/terms/15/{node}/{slug}", timeout=90, verify=False)
            html = r.text
            f.write_text(html, encoding="utf-8")
            print(f"{node} → HTTP {r.status_code}, {len(r.content)} б")
            time.sleep(PAUSE)
        soup = BeautifulSoup(html, "lxml")
        main_el = soup.find("div", class_=re.compile("content|region-content")) or soup
        txt = re.sub(r"[ \t]+", " ", main_el.get_text("\n", strip=True))
        # отрезаем общее меню путеводителя
        txt = re.split(r"Разделы путеводителя|Раздел 1\. Фонды высших", txt)[0]
        funds = sorted(set(FUND.findall(txt)), key=int)
        vol = VOLUME.search(txt)
        yr = YEARS.search(txt)
        ours = sorted(set(OUR.findall(txt)))
        body = "\n".join(ln for ln in txt.splitlines() if len(ln) > 2)
        blocks.append((node, label, funds, vol.group(0) if vol else "", yr.group(0) if yr else "",
                       ours, body))
        print(f"[{node}] {label[:50]:52} фонды {funds} объём «{vol.group(0) if vol else '—'}» "
              f"годы {yr.group(0) if yr else '—'} наши губернии {ours}")

    md = ["# РГВИА: картографические коллекции по путеводителю (том 1, раздел 4)", "",
          "Источник: guides.rusarchives.ru, путеводитель РГВИА (guide 15), раздел 4 «Коллекции», ",
          "подраздел «Картографические документы». Дата выемки: 2026-10-04.", "",
          "Зачем: в базе электронных описей РГВИА этих фондов нет вовсе (см. ",
          "`РЕШЕНИЕ_РГВИА_база_не_содержит_ВУА_2026-10-04.md`) — путеводитель остаётся ",
          "единственным способом узнать состав и объём до очной работы.", "",
          "| Узел | Коллекция | Фонд(ы) | Объём | Хронология | Наши губернии в тексте |",
          "|---|---|---|---|---|---|"]
    for node, label, funds, vol, yr, ours, _ in blocks:
        md.append(f"| {node} | {label} | {', '.join(funds) or '—'} | {vol or '—'} | "
                  f"{yr or '—'} | {', '.join(ours) or '—'} |")
    md.append("")
    for node, label, funds, vol, yr, ours, body in blocks:
        md += [f"## {label} (узел {node}; фонды: {', '.join(funds) or '—'})", "", body, ""]
    (OUT / "РГВИА_путеводитель_картография.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\nвыход: {OUT / 'РГВИА_путеводитель_картография.md'}")


if __name__ == "__main__":
    main()
