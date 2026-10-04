# -*- coding: utf-8 -*-
"""Разведка РГВИА: база электронных описей бд.ргвиа.рф — как устроен поиск.

Что уже есть в проекте (правило п.13 регламента — не писать заново):
  — `scripts/modules/scrapers/rgvia_saved.py` — офлайн-разбор СОХРАНЁННОЙ человеком
    таблицы выдачи в CSV (66 скалярных полей), без сети;
  — пакет `output/rgvia_handoff_20260914_v1` (14.09.2026) — разобрана выдача запроса
    «карт»: 10 дел. Сетевой обход тогда не делался.

Установлено сейчас: домен `xn--90ag.xn--80adcv1b.xn--p1ai` = **бд.ргвиа.рф**, «Электронные
описи»; работает только по **http** (у https ломается TLS), `robots.txt` отдаёт **404** —
собственных запретов у сайта нет.

Задача зонда: понять форму поиска (поля, метод, параметры), есть ли счётчик результатов
и постраничность, и даёт ли поиск по нашим губерниям хоть что-то. Несколько GET с паузами.
"""
import io
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://xn--90ag.xn--80adcv1b.xn--p1ai"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
PAUSE = 3


def main() -> None:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})

    r = s.get(BASE + "/", timeout=40)
    print(f"главная → HTTP {r.status_code}, {len(r.content)} байт")
    soup = BeautifulSoup(r.text, "lxml")

    print("\n--- формы на главной:")
    for f in soup.find_all("form"):
        action, method = f.get("action", ""), (f.get("method") or "get").upper()
        fields = [(i.get("name"), i.get("type") or i.name, (i.get("placeholder") or "")[:30])
                  for i in f.find_all(["input", "select", "textarea"]) if i.get("name")]
        print(f"  {method} {action} — полей {len(fields)}")
        for n, t, p in fields[:12]:
            print(f"      {n} ({t}) {p}")

    print("\n--- разделы меню:")
    links = []
    for a in soup.find_all("a", href=True):
        txt = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if txt and len(txt) < 45:
            links.append((txt, a["href"]))
    seen = set()
    for txt, href in links:
        if txt not in seen:
            seen.add(txt)
            print(f"   {txt[:40]:42} {href[:60]}")
        if len(seen) > 18:
            break

    # пробный поиск
    for q in ("карта Смоленской губернии", "Калужской губернии"):
        time.sleep(PAUSE)
        rr = s.get(BASE + "/search", params={"q": q}, timeout=60)
        txt = re.sub(r"\s+", " ", BeautifulSoup(rr.text, "lxml").get_text(" ", strip=True))
        found = re.search(r"(?:найдено|результат\w*|всего)\D{0,10}(\d+)", txt, re.I)
        rows = len(BeautifulSoup(rr.text, "lxml").find_all("tr"))
        print(f"\nпоиск «{q}» → HTTP {rr.status_code}, {len(rr.content)} байт, "
              f"строк таблицы {rows}, счётчик: {found.group(1) if found else '—'}")
        print("   фрагмент:", txt[:220])


if __name__ == "__main__":
    main()
