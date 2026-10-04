# -*- coding: utf-8 -*-
"""Зонд: есть ли у пяти описей ф.380 образы/PDF для распознавания.

Повод: предложено поручить Codex распознавание описей ф.380 — «там же PDF». Прежде чем
писать бриф, надо установить фактами, что именно отдаёт сайт по каждому узлу описи:
ссылку на PDF, постраничные сканы (scanid/viewer), только дерево дел — или ничего.

Проверяются узлы, названные пользователем:
2841163, 2841185, 2841191, 2841199, 2841217.
Пауза ≥4 с между запросами: fgurgia soft-банит под нагрузкой. Только GET, ничего не пишет
в каталоги прогонов.
"""
import io
import re
import sys
import time

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

OPISI = ["2841163", "2841185", "2841191", "2841199", "2841217"]
BASE = "https://fgurgia.ru"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
PAUSE = 4

TAG = re.compile(r"<[^>]+>")


def plain(html: str) -> str:
    return re.sub(r"\s+", " ", TAG.sub(" ", html))


def main() -> None:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})
    for oid in OPISI:
        time.sleep(PAUSE)
        url = f"{BASE}/object/{oid}"
        r = s.get(url, timeout=40)
        print("=" * 78)
        print(f"{url} → HTTP {r.status_code}, {len(r.content)} байт")
        if r.status_code != 200:
            continue
        html = r.text
        txt = plain(html)

        # заголовок описи и число дел
        h = re.search(r"<title>(.*?)</title>", html, re.S)
        print("  title:", plain(h.group(1))[:110] if h else "—")
        cases = re.search(r"Дела\s*\(\s*(\d+)\s*\)", txt)
        print("  «Дела (N)»:", cases.group(1) if cases else "не указано")
        ann = re.search(r"Аннотация[:\s]*(.{0,200})", txt)
        if ann:
            print("  аннотация:", ann.group(1).strip()[:150])

        # признаки материалов для распознавания
        pdfs = sorted(set(re.findall(r'href="([^"]*\.pdf[^"]*)"', html, re.I)))
        scans = sorted(set(re.findall(r"scanid[=/](\d+)", html, re.I)))
        viewer = sorted(set(re.findall(r'href="([^"]*(?:viewer|showpage|image)[^"]*)"', html, re.I)))
        imgs = sorted(set(re.findall(r'data-largeim="([^"]+)"', html)))
        print(f"  PDF-ссылок: {len(pdfs)} {pdfs[:2]}")
        print(f"  scanid: {len(scans)} {scans[:3]}")
        print(f"  viewer/image-ссылок: {len(viewer)} {viewer[:2]}")
        print(f"  data-largeim: {len(imgs)} {imgs[:2]}")
        idx = re.search(r'data-search-index="(\d+)"', html)
        comp = re.search(r'data-component-id="([^"]+)"', html)
        print(f"  дерево: search-index={idx.group(1) if idx else '—'}, "
              f"component-id={comp.group(1) if comp else '—'}")
        # есть ли слова про отсутствие описи в электронном виде
        for mark in ("не оцифров", "в читальном зале", "электронные образы",
                     "образы отсутств", "оцифрован"):
            if mark in txt.lower():
                m = re.search(r".{60}" + mark + r".{80}", txt, re.I)
                print(f"  ⚑ «{mark}»:", (m.group(0) if m else "")[:150])


if __name__ == "__main__":
    main()
