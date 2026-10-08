"""Разведка идентификаторов описей на портале ГАСО.

Зачем: на портале нет страницы фонда и нет списка описей — только прямые адреса
`opisView.jsf?id=N`, где N сквозной по всему архиву. Чтобы забрать сканы описей
нужных фондов, надо сначала построить карту id → (фонд, опись, есть ли скан).

Этот скрипт только ЗОНДИРУЕТ диапазон (несколько точек), чтобы оценить границы
и формат. Полный обход — отдельным сборщиком после согласования.

Запуск из корня проекта:
    python -B scripts_gaso/probe_opis_ids.py
    python -B scripts_gaso/probe_opis_ids.py --ids 1,50,155,300,600,1200,2000
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://portal.gaso-smolensk.ru/page/portal/opisView.jsf?id="
AGENT = "Mozilla/5.0 (compatible; IGIS-research/1.0)"
PAUSE = 1.5  # вежливая пауза; robots.txt на портале отсутствует (404)

FUND = re.compile(r"Ф(?:онд)?\.?\s*(\d{1,5})", re.I)
OPIS_NUM = re.compile(r"№\s*описи:\s*(\S{1,12})")
CHRON = re.compile(r"Хронология:\s*([\d\s\-,]{4,24})")
TITLE = re.compile(r"Заголовок описи:\s*([^№\n]{5,80})")
SCAN = re.compile(r"Скан-образы описи")
UNITS = re.compile(r"Единицы хранения")


def fetch(url: str, timeout: int = 30) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        return f"__ERR__{type(e).__name__}: {e}"[:200]


def plain(html: str) -> str:
    t = re.sub(r"<script[\s\S]*?</script>", " ", html)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="1,25,50,100,155,300,600,900,1200,1600,2000,2500")
    args = ap.parse_args()
    ids = [int(x) for x in args.ids.split(",") if x.strip().isdigit()]

    print(f"зондирую {len(ids)} идентификаторов, пауза {PAUSE} с\n")
    print(f"{'id':>5} | {'фонд':>6} | {'оп.':>5} | {'хронология':<18} | скан | заголовок")
    print("-" * 96)
    ok = 0
    for i in ids:
        html = fetch(BASE + str(i))
        if html is None or html.startswith("__ERR__"):
            print(f"{i:>5} | {'—':>6} | {'—':>5} | {'—':<18} |  —   | {html}")
            time.sleep(PAUSE)
            continue
        t = plain(html)
        if "Опись" not in t:
            print(f"{i:>5} | нет описи")
            time.sleep(PAUSE)
            continue
        ok += 1
        fund = FUND.search(t)
        num = OPIS_NUM.search(t)
        chron = CHRON.search(t)
        title = TITLE.search(t)
        has_scan = "есть" if SCAN.search(t) else "нет"
        print(f"{i:>5} | {(fund.group(1) if fund else '?'):>6} | "
              f"{(num.group(1) if num else '?'):>5} | "
              f"{(chron.group(1).strip() if chron else '?'):<18} | {has_scan:^4} | "
              f"{(title.group(1).strip()[:42] if title else '')}")
        time.sleep(PAUSE)

    print(f"\nответили: {ok} из {len(ids)}")
    print("Вывод по зонду определяет, нужен ли полный обход диапазона и каким шагом.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
