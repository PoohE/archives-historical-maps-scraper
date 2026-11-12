"""Починка пакета series_package.jsonl перед заливкой в каталог.

Три дефекта пакета от 07.11.2026, из-за которых заливать его было нельзя:
  1. у 230 из 402 записей ЗАГОЛОВОК ОБРЕЗАН многоточием (сохранён сниппет выдачи,
     а не название с карточки);
  2. поле «губернии» подставлено ШАБЛОННО из запроса («Калужская; Смоленская; Ярославская;
     Пермская» стоит даже у Атласа Калужского наместничества);
  3. есть ДУБЛИ — одна карточка попала в разные серии (напр. rusneb 003340324).

Скрипт добирает полные заголовки с карточек и раскладывает строки на готовые к заливке
и требующие человека.

Маршруты заголовков:
  НЭБ  000199_000009_NNNNNNNNN → РГБ search.rsl.ru/ru/record/01NNNNNNNNN (rusneb отдаёт 403)
  РГБ  search.rsl.ru/ru/record/... — напрямую (robots.txt разрешает /ru/record)
  ПБ   prlib.ru/item/N — напрямую (robots.txt разрешает /item/, Crawl-delay 2)
  РГО  elib.rgo.ru/handle/... — напрямую
  РНБ  primo.nlr.ru — JS-витрина, не берётся; остаётся человеку

  python series_package_repair.py [--limit N]
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

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import fix_stdout  # noqa: E402

PKG = Path(
    r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output"
    r"\series_package_20261107\series_package.jsonl"
)
OUT = PKG.parent
UA = {"User-Agent": "Mozilla/5.0 (research; IGRAS RNF 26-17-00347; contact down.pooh@gmail.com)"}
GUB4 = "Калужская; Смоленская; Ярославская; Пермская"
GUBS = ("Калужск", "Смоленск", "Ярославск", "Пермск")

DELAY = {"www.prlib.ru": 2.0, "search.rsl.ru": 1.0, "elib.rgo.ru": 1.0}
_last: dict[str, float] = {}


_fails: dict[str, int] = {}
DEAD_AFTER = 3  # подряд неудач — считаем хост недоступным и больше не ждём его таймаутов


def fetch(url: str) -> str | None:
    host = url.split("/")[2]
    if _fails.get(host, 0) >= DEAD_AFTER:
        return None
    gap = DELAY.get(host, 1.0)
    wait = gap - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=12) as r:
            body = r.read().decode("utf-8", "ignore")
        _fails[host] = 0
        return body
    except (urllib.error.URLError, TimeoutError, OSError):
        _fails[host] = _fails.get(host, 0) + 1
        if _fails[host] == DEAD_AFTER:
            print(f"  !! {host} не отвечает {DEAD_AFTER} раза подряд — пропускаю этот хост",
                  flush=True)
        return None


def page_title(html: str) -> str | None:
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if not m:
        return None
    t = unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    for tail in (" | Президентская библиотека", " — Электронный каталог РГБ",
                 " | Российская государственная библиотека"):
        t = t.replace(tail, "")
    return t.strip(" .|—-") or None


def title_url(row: dict) -> str | None:
    url, holder = row["record_url"] or "", row["holder"]
    if holder == "НЭБ":
        m = re.search(r"000199_000009_(\d{9})", url)
        return f"https://search.rsl.ru/ru/record/01{m.group(1)}" if m else None
    if holder in ("РГБ", "Картфонд РГО", "ПБ"):
        return url.replace("https://prlib.ru/", "https://www.prlib.ru/")
    return None


def canon_id(row: dict) -> str:
    url = row["record_url"] or ""
    for pat in (r"000199_000009_(\d{9})", r"record/0?1?(\d{9})",
                r"item/(\d+)", r"handle/123456789/(\d+)"):
        m = re.search(pat, url)
        if m:
            return f"{row['holder']}:{m.group(1)}" if row["holder"] != "НЭБ" else f"РГБ:{m.group(1)}"
    return url


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = [json.loads(ln) for ln in PKG.open(encoding="utf-8")]
    work = [r for r in rows if r["gate"] == "needs_human"]
    if args.limit:
        work = work[: args.limit]
    print(f"строк в пакете: {len(rows)}; к обработке: {len(work)}")

    # дедуп: одна карточка — одна строка, серии сливаем в список
    merged: dict[str, dict] = {}
    for r in work:
        key = canon_id(r)
        if key in merged:
            s = merged[key]["seriya"]
            if r["seriya"] not in s:
                merged[key]["seriya"] = f"{s}; {r['seriya']}"
            merged[key]["_dup"] = merged[key].get("_dup", 1) + 1
        else:
            merged[key] = dict(r)
    print(f"после дедупа: {len(merged)} (склеено дублей: {len(work) - len(merged)})")

    # возобновляемость: пишем построчно, при перезапуске пропускаем сделанное
    part = OUT / "package_repair.partial.jsonl"
    seen: set[str] = set()
    if part.exists():
        for ln in part.open(encoding="utf-8"):
            try:
                seen.add(json.loads(ln)["_key"])
            except (json.JSONDecodeError, KeyError):
                continue
        print(f"возобновление: уже обработано {len(seen)}")

    fpart = part.open("a", encoding="utf-8")
    ready, human = [], []
    for i, (key, r) in enumerate(merged.items(), 1):
        if key in seen:
            continue
        src = title_url(r)
        full = None
        if src:
            html = fetch(src)
            if html:
                full = page_title(html)
        if full and len(full) > len(r["zagolovok"] or "") - 3:
            r["zagolovok_polnyi"] = full
            r["istochnik_zagolovka"] = src
        # шаблонные губернии снимаем, если в названии нет ни одной из них
        if r.get("gub_serii") == GUB4:
            t = (full or r["zagolovok"] or "")
            hit = [g for g in GUBS if g in t]
            r["gub_serii_iz_zapisi"] = "; ".join(hit)
            r["gub_serii_shablon"] = GUB4
            r["gub_serii"] = "; ".join(hit)
        r["_key"] = key
        fpart.write(json.dumps(r, ensure_ascii=False) + "\n")
        fpart.flush()
        if i % 25 == 0:
            print(f"  {i}/{len(merged)} обработано", flush=True)
    fpart.close()

    # финальная раскладка — из полного .partial, включая строки прошлых заходов
    for ln in part.open(encoding="utf-8"):
        r = json.loads(ln)
        (ready if r.get("zagolovok_polnyi") else human).append(r)

    for name, data in (("package_ready.jsonl", ready),
                       ("package_still_human.jsonl", human)):
        with (OUT / name).open("w", encoding="utf-8") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nполный заголовок добыт: {len(ready)}")
    print(f"остаётся человеку:      {len(human)}")
    print(f"файлы: {OUT / 'package_ready.jsonl'}, {OUT / 'package_still_human.jsonl'}")


if __name__ == "__main__":
    main()
