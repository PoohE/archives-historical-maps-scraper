"""Геопортал РГО: добор карточек — названия и метаданные.

Зачем отдельный проход: в списках разделов у карточек вместо подписи КАРТИНКА, поэтому
обход каталога даёт только номера записей (1936 из 2112). Название и метаданные лежат
внутри карточки `/record/<N>`:

    Название · Издатель · Год издания · Тип материала
    Территориальный охват ← перечень регионов, по нему и отбираем
    Источник · Коллекция

⚠️ `robots.txt` геопортала просит `Crawl-delay: 10` — соблюдаем, поэтому проход по 2112
карточкам идёт около шести часов. Состояние пишется после каждой карточки, повторный
запуск продолжает с места обрыва.

Запуск:
    python -B scripts_rgo/rgo_fetch_records.py
    python -B scripts_rgo/rgo_fetch_records.py --limit 20   # проба
"""
from __future__ import annotations

import argparse
import csv
import html as H
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts_review"))
from cdp_fetch import Browser  # noqa: E402

OUT = ROOT / "output" / "rgo_geoportal_20261021"
SRC = OUT / "rgo_items.jsonl"
DST = OUT / "rgo_records.jsonl"
HOST = "https://geoportal.rgo.ru"
CRAWL_DELAY = 10.0

FIELDS = ["Название", "Автор", "Издатель", "Год издания", "Тип материала",
          "Территориальный охват", "Масштаб", "Источник", "Коллекция",
          "Дата публикации", "Язык", "Примечание"]


def parse_card(doc: str) -> dict:
    """Пары «подпись → значение» со страницы карточки."""
    txt = re.sub(r"<script.*?</script>", "", doc or "", flags=re.S)
    txt = re.sub(r"<style.*?</style>", "", txt, flags=re.S)
    txt = re.sub(r"<[^>]+>", "\n", txt)
    lines = [x.strip() for x in H.unescape(txt).splitlines()
             if x.strip() and not x.strip().startswith("@")]
    out: dict[str, str] = {}
    for i, line in enumerate(lines):
        if line in FIELDS and i + 1 < len(lines):
            val = lines[i + 1].strip()
            if val not in FIELDS and len(val) < 400:
                out.setdefault(line, val)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=CRAWL_DELAY)
    args = ap.parse_args()

    items = [json.loads(ln) for ln in SRC.open(encoding="utf-8")]
    done: set[str] = set()
    if DST.exists():
        for ln in DST.open(encoding="utf-8"):
            try:
                done.add(json.loads(ln)["url"])
            except Exception:  # noqa: BLE001, S112
                continue
    todo = [r for r in items if r["url"] not in done and "/record/" in r["url"]]
    if args.limit:
        todo = todo[: args.limit]
    print(f"карточек всего {len(items)}, уже взято {len(done)}, в работе {len(todo)}")

    br = Browser(HOST + "/")
    with DST.open("a", encoding="utf-8") as fh:
        for i, it in enumerate(todo, 1):
            doc = br.render(it["url"], wait=6)
            card = parse_card(doc)
            rec = {
                "record_id": it["url"].rstrip("/").rsplit("/", 1)[-1],
                "url": it["url"],
                "razdel": it.get("razdel", ""),
                "podrazdel": it.get("podrazdel", ""),
                "zagolovok": card.get("Название", ""),
                "avtor": card.get("Автор", ""),
                "izdatel": card.get("Издатель", ""),
                "god": card.get("Год издания", ""),
                "tip": card.get("Тип материала", ""),
                "territoriya_rgo": card.get("Территориальный охват", ""),
                "masshtab": card.get("Масштаб", ""),
                "istochnik": card.get("Источник", "Картографический фонд РГО"),
                "kollekciya": card.get("Коллекция", ""),
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 10 == 0 or i <= 3:
                print(f"  {i:>5}/{len(todo)} {rec['record_id']:>7} | "
                      f"{(rec['zagolovok'] or '—')[:54]}", flush=True)
            time.sleep(args.delay)
    br.close()

    rows = [json.loads(ln) for ln in DST.open(encoding="utf-8")]
    if rows:
        with (OUT / "rgo_records.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    named = sum(1 for r in rows if r.get("zagolovok"))
    print(f"\nкарточек прочитано: {len(rows)} | с названием: {named}")
    print(f"→ {OUT / 'rgo_records.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
