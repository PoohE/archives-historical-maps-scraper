"""Есть ли в карточке дела описи 21 ф. 380 привязка к строке бумажной описи.

Задача. В базе РГИА 724 дела описи 21 опознаются только шифром «Ф. 380 Оп. 21 Д. N»,
заголовки у всех пустые. Распознанные строки бумажной описи опознаются номером
хронологического каталога (9646, 10031, 46673…) и номером внутри рубрики. Прямой связи
«№ дела ↔ строка описи» ни в одном из наборов нет.

Проба смотрит ВСЕ атрибуты карточки нескольких дел: нет ли там номера каталога, листа
описи, названия дачи, рубрики — чего угодно, по чему два набора можно сомкнуть.

Запуск:
    python -B scripts_rgia/probe_op21_case_attributes.py
    python -B scripts_rgia/probe_op21_case_attributes.py --sample 8
"""
from __future__ import annotations

import argparse
import csv
import http.cookiejar
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "output" / "rgia_fund380_handoff_package_20261008" / "records_clean.csv"
BASE = "https://fgurgia.ru"
AGENT = "Mozilla/5.0 (compatible; IGIS-research/1.0)"
PAUSE = 3.0  # темп сборщика фонда; не ускорять — был soft-ban

# что считаем «зацепкой» за бумажную опись
RX_KATALOG = re.compile(r"\b(?:9\d{3}|1\d{4}|3\d{4}|4\d{4}|5\d{4})\b")
RX_LIST = re.compile(r"\bл\.\s*\d+|лист\s+\d+", re.I)


def fetch_card(op, oid: str) -> dict | None:
    req = urllib.request.Request(f"{BASE}/object/{oid}", headers={"User-Agent": AGENT})
    with op.open(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", "replace")
    m = re.search(r'data-search-index="(\d+)"', html)
    if not m:
        return None
    time.sleep(PAUSE)
    u = (f"{BASE}/ajax/obj/{oid}/{m.group(1)}?"
         + urllib.parse.urlencode({"children": "false"}))
    req2 = urllib.request.Request(u, headers={
        "User-Agent": AGENT, "X-Requested-With": "XMLHttpRequest"})
    with op.open(req2, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=6)
    args = ap.parse_args()

    with SRC.open(encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if "Оп. 21" in r.get("fund_code", "")]
    step = max(1, len(rows) // args.sample)
    sample = rows[::step][:args.sample]
    print(f"дел описи 21 в пакете: {len(rows)}; проба: {len(sample)}, пауза {PAUSE} с\n")

    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    seen_fields: Counter = Counter()
    hooks = Counter()

    for r in sample:
        oid = r.get("url", "").rstrip("/").split("/")[-1]
        if not oid.isdigit():
            continue
        print(f"=== {r['fund_code']}  ({BASE}/object/{oid})")
        try:
            data = fetch_card(op, oid)
        except Exception as exc:  # noqa: BLE001
            print(f"  ОШИБКА: {type(exc).__name__}: {exc}")
            time.sleep(PAUSE)
            continue
        if not data:
            print("  search-index не найден")
            time.sleep(PAUSE)
            continue

        attrs = data.get("attributes", [])
        if not attrs:
            print("  атрибутов нет")
        for a in attrs:
            name = a.get("systemName") or "?"
            text = (a.get("text") or "").strip()
            seen_fields[name] += 1
            if text:
                print(f"  {name:<22} = {text[:110]}")
                if RX_KATALOG.search(text):
                    hooks["есть 4-5-значное число (возможный № каталога)"] += 1
                if RX_LIST.search(text):
                    hooks["есть ссылка на лист"] += 1
        time.sleep(PAUSE)
        print()

    print(f"поля, встреченные в карточках: {dict(seen_fields)}")
    print(f"зацепки за бумажную опись: {dict(hooks) or 'НЕТ'}")
    if not hooks:
        print("\nВЫВОД: в карточке дела нет ни № хронологического каталога, ни ссылки "
              "на лист описи. Связать 724 дела со строками бумажной описи по данным "
              "сайта НЕЛЬЗЯ — наборы придётся вести как два независимых слоя.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
