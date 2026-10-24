"""Ждать, пока портал снимет пометку с сессии: один запрос раз в N минут.

Смысл — выяснить, ограничитель ли это по времени (тогда достаточно сбавить темп) или
пометка держится до прохождения капчи. Чаще одного запроса в четверть часа не стучим:
нас уже попросили сбавить, и смысл проверки — соблюсти правило, а не продавить его.

Запуск: python -u -B scripts_gayo/wait_unblock.py --every 15 --tries 8
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gayo_harvest as G  # noqa: E402

URL = "https://af.yar-archives.ru/archive5/funds"  # самый маленький архив — минимум нагрузки


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=int, default=15, help="минут между проверками")
    ap.add_argument("--tries", type=int, default=8)
    args = ap.parse_args()

    for i in range(1, args.tries + 1):
        html = G.fetch(URL, tries=1)
        ok = bool(html and G.fund_rows(html, 5))
        stamp = time.strftime("%H:%M")
        print(f"[{stamp}] проверка {i}/{args.tries}: {'СВОБОДНО' if ok else 'капча'}",
              flush=True)
        if ok:
            print("пометка снята — можно продолжать в щадящем темпе")
            return 0
        if i < args.tries:
            time.sleep(args.every * 60)
    print("пометка держится — сама по времени не спадает")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
