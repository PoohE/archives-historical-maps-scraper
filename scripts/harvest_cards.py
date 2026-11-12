"""Добор карточек: полное название, масштаб, шифр хранения, выходные данные.

Вход  — output/work_2026-11-08/work.jsonl (3099 карточек после дедупа и отсева тех,
        что уже в каталоге).
Выход — harvested.jsonl, построчно, с возобновлением по ключу.

Маршруты и вежливость:
  РГБ  search.rsl.ru/ru/record/...  — robots разрешает /ru/record, пауза 1,2 с
  ПБ   www.prlib.ru/item/N          — robots разрешает /item/, Crawl-delay 2
  КП   kp.rusneb.ru                 — пробуем, пауза 1,5 с
  НЭБ  rusneb.ru                    — 403 на программные запросы, НЕ ходим
  РГО  elib.rgo.ru                  — сайт не отвечает, НЕ ходим (вернуться, когда поднимется)

Хост, трижды подряд не ответивший, отключается до конца прогона — иначе таймауты
съедают всё время (на первом заходе 25 строк за 9 минут из-за лежащего РГО).

  python harvest_cards.py            # прогон с возобновлением
  python harvest_cards.py --limit 20 # проба
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import fix_stdout  # noqa: E402

DIR = Path(__file__).resolve().parents[1] / "output" / "work_2026-11-08"
WORK = DIR / "work.jsonl"
OUT = DIR / "harvested.jsonl"

UA = {"User-Agent": "Mozilla/5.0 (research; IGRAS RNF 26-17-00347; contact down.pooh@gmail.com)"}
DELAY = {"search.rsl.ru": 1.2, "www.prlib.ru": 2.0, "kp.rusneb.ru": 1.5}
SKIP_HOLDERS = {"НЭБ", "РГО"}          # 403 и недоступен
DEAD_AFTER = 3

_last: dict[str, float] = {}
_fails: dict[str, int] = {}

SC = re.compile(r"1\s*[:：]\s*(\d[\d\s\u00a0]{2,12})")
SHELF = re.compile(r"((?:FB|KGR|OMF|IZO|MK|ZV|NTO)\s+[^\s][\w\s/\-.№]{2,34}?)"
                   r"\s+(?:Читать|Заказать|Marc21)")
TAILS = (" - Search RSL", " | Президентская библиотека имени Б.Н. Ельцина",
         " | Президентская библиотека", " имени Б.Н. Ельцина")


def route(row: dict) -> str | None:
    holder, url = row["key"].split(":", 1)[0], row["url"]
    if holder in SKIP_HOLDERS:
        return None
    if holder == "РГБ":
        m = re.search(r"000199_000009_(\d{9})", url) or re.search(r"record/0?1?(\d{9})", url)
        return f"https://search.rsl.ru/ru/record/01{m.group(1)}" if m else None
    if holder == "ПБ":
        return url.replace("https://prlib.ru/", "https://www.prlib.ru/")
    if holder == "КП":
        return url
    return None


def fetch(url: str) -> str | None:
    host = url.split("/")[2]
    if _fails.get(host, 0) >= DEAD_AFTER:
        return None
    gap = DELAY.get(host, 1.5)
    wait = gap - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
            body = r.read().decode("utf-8", "ignore")
        _fails[host] = 0
        return body
    except (urllib.error.URLError, TimeoutError, OSError):
        _fails[host] = _fails.get(host, 0) + 1
        if _fails[host] == DEAD_AFTER:
            print(f"  !! {host} молчит {DEAD_AFTER} раза — отключаю до конца прогона", flush=True)
        return None


def parse(html: str) -> dict:
    out: dict = {}
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if m:
        t = unescape(re.sub(r"\s+", " ", m.group(1))).strip()
        for tail in TAILS:
            if t.endswith(tail):
                t = t[: -len(tail)]
        t = re.sub(r"\s*имени Б\.Н\. Ельцина\s*$", "", t).strip(" .|—-")
        if t:
            out["zagolovok_polnyi"] = t
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    w = re.search(r"Масштаб[^.;]{0,160}", txt)
    s = SC.search(w.group(0)) if w else None
    if s:
        out["scale"] = int(re.sub(r"\D", "", s.group(1)))
        out["scale_ctx"] = w.group(0).strip()[:120]
    elif out.get("zagolovok_polnyi") and (s := SC.search(out["zagolovok_polnyi"])):
        out["scale"] = int(re.sub(r"\D", "", s.group(1)))
        out["scale_ctx"] = s.group(0)
    m = SHELF.search(txt)
    if m:
        out["shelf"] = m.group(1).strip()
    return out


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = [json.loads(ln) for ln in WORK.open(encoding="utf-8")]
    done: set[str] = set()
    if OUT.exists():
        for ln in OUT.open(encoding="utf-8"):
            try:
                done.add(json.loads(ln)["key"])
            except (json.JSONDecodeError, KeyError):
                continue
    todo = [r for r in rows if r["key"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"всего в работе: {len(rows)} | уже добрано: {len(done)} | к обходу: {len(todo)}",
          flush=True)

    got = skipped = 0
    with OUT.open("a", encoding="utf-8") as f:
        for i, r in enumerate(todo, 1):
            src = route(r)
            if not src:
                r["status"] = "хост недоступен (НЭБ 403 / РГО лежит)"
                skipped += 1
            else:
                html = fetch(src)
                if html:
                    r.update(parse(html))
                    r["istochnik_kartochki"] = src
                    r["status"] = "добрано" if r.get("zagolovok_polnyi") else "карточка пуста"
                    got += 1
                else:
                    r["status"] = "не ответил"
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            if i % 50 == 0:
                print(f"  {i}/{len(todo)} — добрано {got}, пропущено {skipped}", flush=True)

    print(f"\nдобрано карточек: {got}; пропущено по недоступности: {skipped}")
    print(f"файл: {OUT}")


if __name__ == "__main__":
    main()
