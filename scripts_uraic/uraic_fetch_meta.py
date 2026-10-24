"""Белинка (Свердловская ОУНБ, DSpace): добор метаданных карточек по handle.

⚠️ ЗАЧЕМ. Прогон 21.10 снял из выдачи только заголовок и ссылку. Для гейта этого мало,
и по двум причинам сразу:

 1. НЕТ ГОДА — а для библиотек действует граница 1989 года включительно;
 2. НЕТ ТИПА, а он здесь решает. Белинка — репозиторий краеведческих ПУБЛИКАЦИЙ:
    добрая половина записей это доклады Чупинских чтений вида «"Географический и
    статистический словарь Пермской губернии" Н. К. Чупина как источник по истории
    сельского расселения». По заголовку это выглядит пространственным описанием, а
    на деле `DC.type = Article` — статья О СЛОВАРЕ, а не сам словарь. Без типа такие
    записи пошли бы в каталог вместо источников.

Карточка DSpace отдаёт метаданные в <meta name="DC.*"> и <meta name="DCTERMS.*">:
creator, issued (год), type, subject (рубрики), isPartOf (издание-контейнер),
плюс ссылки на файлы через /bitstream/<handle>/<n>/<файл>.

Запуск:
    python -B scripts_uraic/uraic_fetch_meta.py --limit 20
    python -B scripts_uraic/uraic_fetch_meta.py
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "uraic_20261021"
SRC = OUT / "uraic_items.jsonl"
DST = OUT / "uraic_meta.jsonl"
HOST = "http://elib.uraic.ru"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
DELAY = 0.3
POTOKOV = 4

# ⚠️ keep-alive обязателен: установка соединения с этим хостом стоит 23 с,
# а запрос по уже открытой сессии — 1 с (см. шапку модуля)
_mestnye = threading.local()

META = re.compile(r'<meta\s+name="([A-Za-z.]+)"\s+content="([^"]*)"', re.I)
BITSTREAM = re.compile(r'href="(/bitstream/[^"]+)"')


def sessiya() -> requests.Session:
    """Своя сессия на поток: соединение открывается один раз и переиспользуется."""
    s = getattr(_mestnye, "s", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = UA
        _mestnye.s = s
    return s


def get(url: str, tries: int = 3) -> str | None:
    for n in range(tries):
        try:
            r = sessiya().get(url, timeout=60)
            if r.status_code in (403, 404):
                return None
            if r.ok:
                r.encoding = r.encoding or "utf-8"
                return r.text
        except Exception:  # noqa: BLE001
            _mestnye.s = None  # соединение испорчено — открыть заново
        time.sleep(2 + 3 * n)
    return None


def parse(doc: str) -> dict:
    fields: dict[str, list[str]] = {}
    for name, val in META.findall(doc):
        fields.setdefault(name, []).append(html.unescape(val))
    files = []
    for h in BITSTREAM.findall(doc):
        if h not in files:
            files.append(HOST + h)
    one = lambda k: (fields.get(k) or [""])[0]  # noqa: E731
    return {
        "avtor": "; ".join(fields.get("DC.creator", []))[:300],
        "god": one("DCTERMS.issued")[:10],
        "tip": one("DC.type"),
        "rubriki": "; ".join(fields.get("DC.subject", []))[:500],
        "iz_izdaniya": one("DCTERMS.isPartOf")[:300],
        "yazyk": one("DC.language"),
        "shifr": next((x for x in fields.get("DC.identifier", []) if not x.startswith("http")), ""),
        "opisanie": one("DCTERMS.abstract")[:500],
        "url_fajla": files[0] if files else "",
        "fajlov": len(files),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = [json.loads(ln) for ln in SRC.open(encoding="utf-8")]
    done: set[str] = set()
    if DST.exists():
        for ln in DST.open(encoding="utf-8", errors="replace"):
            try:
                done.add(json.loads(ln)["handle"])
            except Exception:  # noqa: BLE001, S112
                continue
    todo = [r for r in rows if r["handle"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"карточек всего {len(rows)}, уже с метаданными {len(done)}, в работе {len(todo)}",
          flush=True)

    zamok = threading.Lock()
    schet = {"i": 0}
    fh = DST.open("a", encoding="utf-8")

    def rabota(r: dict) -> None:
        doc = get(r["url"])
        time.sleep(DELAY)
        rec = {**r, **(parse(doc) if doc else {})}
        with zamok:
            schet["i"] += 1
            i = schet["i"]
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 100 == 0 or i == len(todo):
                print(f"  {i:>5}/{len(todo)}  {rec.get('god','?'):>4}  "
                      f"{rec.get('tip','?'):<10} {r['zagolovok'][:54]}", flush=True)

    with ThreadPoolExecutor(max_workers=POTOKOV) as pool:
        list(pool.map(rabota, todo))
    fh.close()

    out = []
    for ln in DST.open(encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:  # noqa: BLE001, S112
            continue
    if out:
        cols = sorted({k for r in out for k in r})
        with (OUT / "uraic_meta.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(out)
    print(f"\nс метаданными: {len(out)} | с годом: {sum(1 for r in out if r.get('god'))}"
          f" | с файлом: {sum(1 for r in out if r.get('url_fajla'))}")
    print(f"→ {OUT / 'uraic_meta.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
