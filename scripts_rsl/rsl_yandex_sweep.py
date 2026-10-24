"""РГБ: поиск картографических карточек через выдачу Яндекса.

Почему так, а не обходом каталога. `search.rsl.ru/robots.txt`:
    User-agent: *
    Disallow: /            ← поиск и каталог закрыты
    Allow: /ru/record      ← карточки записей РАЗРЕШЕНЫ
    Allow: /sitemaps
`dlib.rsl.ru` закрыт целиком (`Disallow: /`).

Обойти разрешённое невозможно: sitemap — это 208 файлов по ~50 тыс. URL, около 10,4 млн
карточек БЕЗ заголовков; чтобы найти среди них наши, пришлось бы открыть каждую.
Поэтому ищем карточки внешним поиском (Яндекс индексирует каталог РГБ), а читаем только
то, что robots разрешает. Ничего не обходим: пользуемся тем, что РГБ сама отдала
поисковикам через sitemap.

Запуск:
    python -B scripts_rsl/rsl_yandex_sweep.py            # все запросы
    python -B scripts_rsl/rsl_yandex_sweep.py --limit 5  # проба
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
OUT = ROOT / "output" / "rsl_yandex_20261020"
SKILL = Path.home() / ".claude" / "skills" / "yandex-search-api"

GUBERNII = ["Калужской", "Смоленской", "Ярославской", "Пермской"]
# Слова предмета: у РГБ карточки озаглавлены «Карта …», «План …», «Атлас …»
KINDS = ["карта", "план", "атлас", "чертеж", "план города"]
# Уезды дают карточки, где губерния в заголовке не названа
UEZDY = {
    "Калужской": ["Боровского уезда", "Козельского уезда", "Медынского уезда",
                  "Мосальского уезда", "Тарусского уезда"],
    "Смоленской": ["Вяземского уезда", "Гжатского уезда", "Дорогобужского уезда",
                   "Рославльского уезда", "Юхновского уезда"],
    "Ярославской": ["Ростовского уезда", "Угличского уезда", "Мышкинского уезда",
                    "Пошехонского уезда", "Рыбинского уезда"],
    "Пермской": ["Соликамского уезда", "Чердынского уезда", "Кунгурского уезда",
                 "Верхотурского уезда", "Шадринского уезда"],
}

RECORD = re.compile(r"search\.rsl\.ru/ru/record/(\d+)")


def queries() -> list[str]:
    out = []
    for g in GUBERNII:
        for k in KINDS:
            out.append(f"site:search.rsl.ru {k} {g} губернии")
        for u in UEZDY[g]:
            out.append(f"site:search.rsl.ru карта {u}")
    return out


# ⚠️ Вызывать .sh голым «bash» на Windows нельзя: имя резолвится в WSL-овский bash,
# который не видит C:\-пути, и скрипт молча не отрабатывает (у нас это дало 0 находок
# при 20 реальных результатах). Берём явный путь к Git Bash.
BASH = next((p for p in (r"C:\Program Files\Git\bin\bash.exe",
                         r"C:\Program Files\Git\usr\bin\bash.exe")
             if Path(p).exists()), "bash")


def run_query(q: str, results: int = 50) -> list[dict]:
    cmd = [BASH, "scripts/web_search_sync.sh", "--query", q,
           "--region-id", "225", "--results", str(results)]
    try:
        r = subprocess.run(cmd, cwd=SKILL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
    except Exception as e:  # noqa: BLE001
        print(f"    запрос не выполнен: {type(e).__name__}: {e}")
        return []
    m = re.search(r"JSON:\s*(\S+\.json)", r.stdout or "")
    if not m:
        err = (r.stderr or r.stdout or "").strip().splitlines()
        print(f"    нет файла результата: {err[-1][:90] if err else 'пустой вывод'}")
        return []
    p = Path(m.group(1))
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="взять только N первых запросов")
    ap.add_argument("--delay", type=float, default=1.5)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    qs = queries()
    if args.limit:
        qs = qs[: args.limit]
    print(f"запросов: {len(qs)}")

    found: dict[str, dict] = {}
    for i, q in enumerate(qs, 1):
        rows = run_query(q)
        new = 0
        for r in rows:
            url = r.get("url", "")
            m = RECORD.search(url)
            if not m:
                continue
            rid = m.group(1)
            if rid in found:
                continue
            found[rid] = {
                "record_id": rid,
                "zagolovok": re.sub(r"\s*-\s*Search RSL\s*$", "", r.get("title", "")).strip(),
                "url": f"https://search.rsl.ru/ru/record/{rid}",
                "snippet": (r.get("snippet") or "").strip(),
                "zapros": q,
                "istochnik": "РГБ (поиск через Яндекс)",
            }
            new += 1
        print(f"  {i:>3}/{len(qs)} {q[:58]:<58} +{new} (всего {len(found)})", flush=True)
        time.sleep(args.delay)

    rows = sorted(found.values(), key=lambda r: r["zagolovok"])
    with (OUT / "rsl_cards.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["record_id"])
        w.writeheader()
        w.writerows(rows)
    with (OUT / "rsl_cards.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nуникальных карточек: {len(rows)}")
    print(f"→ {OUT / 'rsl_cards.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
