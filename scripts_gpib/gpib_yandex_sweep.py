"""ГПИБ: поиск описаний губерний через выдачу Яндекса.

⚠️ Почему источник ПЕРЕОТКРЫТ. 18.10 ГПИБ был закрыт с выводом «предмета по нашим
губерниям нет»: обход дерева дал 153 узла, 26 картографических, по 4 губерниям — ноль.
Вывод верен буквально, но узок: проверялась только КАРТОГРАФИЧЕСКАЯ витрина. 21.10
пользователь указал на «Статистическое описание Калужской губернии» —
`elib.shpl.ru/ru/nodes/79542`, оно там есть. Значит искать надо не «карту», а слой
описаний и статистики, который в проекте идёт наравне с картами (как «Списки населённых
мест», «Топографическое описание Ярославского наместничества», «Материалы для географии
и статистики» Генштаба — всё это уже в каталоге).

Маршрут: robots ГПИБ запрещает ровно `/ru/nodes/search`, карточки `/ru/nodes/<id>`
открыты. Поиск ведём внешним поисковиком (Яндекс индексирует ГПИБ), читаем разрешённое.

Запуск:
    python -B scripts_gpib/gpib_yandex_sweep.py --limit 4
    python -B scripts_gpib/gpib_yandex_sweep.py
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "gpib_yandex_20261021"
SKILL = Path.home() / ".claude" / "skills" / "yandex-search-api"
# ⚠️ голый «bash» на Windows уходит в WSL и молча не отрабатывает (0 находок при 20
# реальных) — только явный путь к Git Bash
BASH = next((p for p in (r"C:\Program Files\Git\bin\bash.exe",
                         r"C:\Program Files\Git\usr\bin\bash.exe")
             if Path(p).exists()), "bash")

GUBERNII = ["Калужской", "Смоленской", "Ярославской", "Пермской"]
# Жанры, в которых у ГПИБ лежит пространственное описание территории
KINDS = [
    "статистическое описание {g} губернии",
    "список населенных мест {g} губернии",
    "памятная книжка {g} губернии",
    "материалы для географии и статистики {g} губернии",
    "военно-статистическое обозрение {g} губернии",
    "топографическое описание {g} губернии",
    "карта {g} губернии",
    "атлас {g} губернии",
    "приложение к трудам {g} губернского статистического комитета",
]
NODE = re.compile(r"elib\.shpl\.ru/(?:ru/)?nodes/(\d+)")


def queries() -> list[str]:
    return [f"site:elib.shpl.ru {k.format(g=g)}" for g in GUBERNII for k in KINDS]


def run_query(q: str, results: int = 50) -> list[dict]:
    cmd = [BASH, "scripts/web_search_sync.sh", "--query", q,
           "--region-id", "225", "--results", str(results)]
    try:
        r = subprocess.run(cmd, cwd=SKILL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
    except Exception as e:  # noqa: BLE001
        print(f"    запрос не выполнен: {type(e).__name__}")
        return []
    m = re.search(r"JSON:\s*(\S+\.json)", r.stdout or "")
    if not m or not Path(m.group(1)).exists():
        return []
    try:
        return json.loads(Path(m.group(1)).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=1.5)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    qs = queries()
    if args.limit:
        qs = qs[: args.limit]
    print(f"запросов: {len(qs)}")

    found: dict[str, dict] = {}
    for i, q in enumerate(qs, 1):
        new = 0
        for r in run_query(q):
            m = NODE.search(r.get("url", ""))
            if not m or m.group(1) in found:
                continue
            found[m.group(1)] = {
                "node_id": m.group(1),
                "zagolovok": re.sub(r"^ГПИБ\s*\|\s*", "", r.get("title", "")).strip(),
                "url": f"http://elib.shpl.ru/ru/nodes/{m.group(1)}",
                "snippet": (r.get("snippet") or "").strip()[:300],
                "zapros": q.replace("site:elib.shpl.ru ", ""),
                "istochnik": "ГПИБ (поиск через Яндекс)",
            }
            new += 1
        print(f"  {i:>3}/{len(qs)} {q.replace('site:elib.shpl.ru ','')[:52]:<54} "
              f"+{new} (всего {len(found)})", flush=True)
        time.sleep(args.delay)

    rows = sorted(found.values(), key=lambda r: r["zagolovok"])
    if rows:
        with (OUT / "gpib_cards.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        with (OUT / "gpib_cards.jsonl").open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nуникальных карточек: {len(rows)}")
    print(f"→ {OUT / 'gpib_cards.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
