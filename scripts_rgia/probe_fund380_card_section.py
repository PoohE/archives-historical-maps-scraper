"""Шаг 1 каскада: заполнено ли поле «Раздел описи» в карточках дел фонда 380.

Контекст: территорию 1140 отобранных записей из описей 38-41 не взять ни из заголовка
дела (губерния там не повторяется), ни из дерева описи (проверено: плоский список дел,
узлов-разделов нет). Последняя надежда — поле карточки `INVSECTIONNEW` «Раздел описи»:
если в нём стоит «Калужская губерния», территория восстанавливается обходом карточек.

Эта проба берёт небольшую выборку дел и смотрит, заполнено ли поле. От результата зависит,
имеет ли смысл обход 1140 карточек (около часа при темпе 3 с) или остаётся только
Vision-разбор скана описи.

Запуск из корня проекта:
    python -B scripts_rgia/probe_fund380_card_section.py
    python -B scripts_rgia/probe_fund380_card_section.py --sample 12
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
SRC = ROOT / "output" / "rgia_fund380_triage_20261009" / "step3_detailed.csv"
BASE = "https://fgurgia.ru"
AGENT = "Mozilla/5.0 (compatible; IGIS-research/1.0)"
PAUSE = 3.0  # темп сборщика фонда; не ускорять — был soft-ban

WANT = {"INVSECTIONNEW": "Раздел описи", "ANNOTATION": "Аннотация", "NAME": "Заголовок"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=10)
    args = ap.parse_args()

    with SRC.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    # равномерная выборка по всему файлу, а не первые N подряд
    step = max(1, len(rows) // args.sample)
    sample = rows[::step][:args.sample]
    print(f"подробных записей: {len(rows)}; проба: {len(sample)}, пауза {PAUSE} с\n")

    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    filled = Counter()

    for r in sample:
        url = r.get("url", "")
        oid = url.rstrip("/").split("/")[-1]
        if not oid.isdigit():
            continue
        try:
            req = urllib.request.Request(f"{BASE}/object/{oid}", headers={"User-Agent": AGENT})
            with op.open(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", "replace")
            m = re.search(r'data-search-index="(\d+)"', html)
            if not m:
                print(f"  {oid}: search-index не найден")
                time.sleep(PAUSE)
                continue
            time.sleep(PAUSE)
            u = (f"{BASE}/ajax/obj/{oid}/{m.group(1)}?"
                 + urllib.parse.urlencode({"children": "false"}))
            req2 = urllib.request.Request(u, headers={
                "User-Agent": AGENT, "X-Requested-With": "XMLHttpRequest"})
            with op.open(req2, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as e:
            print(f"  {oid}: {type(e).__name__}: {e}")
            time.sleep(PAUSE)
            continue

        att = {a.get("systemName"): (a.get("text") or "").strip()
               for a in data.get("attributes", [])}
        section = att.get("INVSECTIONNEW", "")
        annot = att.get("ANNOTATION", "")
        filled["раздел заполнен" if section else "раздел пуст"] += 1
        if annot:
            filled["есть аннотация"] += 1
        print(f"  {oid}  раздел: {section[:46] or '—':<46} "
              f"аннотация: {annot[:28] or '—'}")
        time.sleep(PAUSE)

    print(f"\nитог: {dict(filled)}")
    if filled.get("раздел заполнен"):
        print("\nВЫВОД: поле «Раздел описи» заполняется — обход карточек даст территорию.")
    else:
        print("\nВЫВОД: поле «Раздел описи» пустое во всей пробе. Обход 1140 карточек "
              "территории НЕ даст — остаётся Vision-разбор скана описи (как по ГАСО).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
