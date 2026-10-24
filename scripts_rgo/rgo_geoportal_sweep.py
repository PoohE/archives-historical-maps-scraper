"""Геопортал РГО: обход каталога карт.

Разведка 21.10: `geoportal.rgo.ru/robots.txt` — одна группа `*`, `Crawl-delay: 10`,
ИИ-агентов в списке НЕТ, запретов для нас нет. Соблюдаем задержку 10 с, как просит сайт.

Структура: `/catalog` → раздел → подраздел → единица. Разделов 16, из них профильные:
старинные атласы и карты, собрание карт и планов из изданий РГО, россыпь карт и планов,
региональные/исторические/тематические атласы, топографические и тематические карты,
общегеографические атласы России.

Страницы рисуются на клиенте, поэтому снимаем отрисованный DOM (`render`), а не html.
У списков есть пагинация `?page=N`.

Запуск:
    python -B scripts_rgo/rgo_geoportal_sweep.py --limit 2
    python -B scripts_rgo/rgo_geoportal_sweep.py
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
HOST = "https://geoportal.rgo.ru"
CRAWL_DELAY = 10.0  # robots.txt геопортала просит именно столько

SECTIONS = [
    "starinnye-atlasy-i-karty",
    "sobranie-kart-i-planov-iz-izdaniy-rgo",
    "rossyp-kart-planov-i-drugih-primechatelnyh-materialov",
    "regionalnye-atlasy",
    "istoricheskie-atlasy",
    "tematicheskie-karty",
    "topograficheskie-karty",
    "obshchegeograficheskie-atlasy-rossii",
    "tematicheskie-atlasy",
    "lichnye-kollekcii",
]
SKIP_TEXT = re.compile(r"Геопортал|навигац|персональн|^Каталог|Русского географ|Главная"
                       r"|Обратная связь|Карта сайта|Вход|Регистрац", re.I)


def slug_title(href: str) -> str:
    """Подпись из адреса, когда в ссылке её нет (у карточек там картинка)."""
    last = href.rstrip("/").rsplit("/", 1)[-1]
    return last.replace("-", " ").strip().capitalize()


def links(doc: str) -> list[tuple[str, str]]:
    """Ссылки с подписями.

    ⚠️ У карточек и подразделов геопортала текст ссылки ПУСТОЙ — внутри картинка.
    Первая версия требовала текст длиннее 6 знаков и теряла все подразделы
    (раздел «Старинные атласы и карты» показывал 0 вместо 3). Поэтому: нет текста —
    берём подпись из slug адреса, а не выбрасываем ссылку.
    """
    out, seen = [], set()
    for m in re.finditer(r'href="(/[^"#?]+)"[^>]*>(.*?)</a>', doc or "", re.S):
        txt = re.sub(r"<[^>]+>", "", m.group(2))
        txt = re.sub(r"\s+", " ", H.unescape(txt)).strip()
        href = m.group(1)
        if href in seen or SKIP_TEXT.search(txt):
            continue
        if len(txt) < 6:
            txt = slug_title(href)
        if len(txt) < 4 or len(txt) > 180:
            continue
        seen.add(href)
        out.append((href, txt))
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="взять только N разделов")
    ap.add_argument("--max-pages", type=int, default=12, help="страниц пагинации на список")
    ap.add_argument("--delay", type=float, default=CRAWL_DELAY)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    secs = SECTIONS[: args.limit] if args.limit else SECTIONS
    br = Browser(HOST + "/")
    found: dict[str, dict] = {}
    spent = 0

    def grab(url: str, wait: float = 8) -> str:
        nonlocal spent
        spent += 1
        doc = br.render(url, wait=wait) or ""
        time.sleep(args.delay)
        return doc

    for sec in secs:
        doc = grab(f"{HOST}/catalog/{sec}")
        subs = [(h, t) for h, t in links(doc) if h.startswith(f"/catalog/{sec}/")]
        print(f"\n=== {sec}: подразделов {len(subs)}", flush=True)
        targets = subs or [(f"/catalog/{sec}", sec)]
        for href, stitle in targets:
            for page in range(args.max_pages):
                url = f"{HOST}{href}" + (f"?page={page}" if page else "")
                d = grab(url)
                items = [(h, t) for h, t in links(d)
                         if not h.startswith("/catalog") or h.count("/") > 3]
                new = 0
                for h, t in items:
                    key = h
                    if key in found:
                        continue
                    found[key] = {
                        "razdel": sec, "podrazdel": stitle,
                        "zagolovok": t, "url": HOST + h,
                        "istochnik": "Геопортал РГО",
                    }
                    new += 1
                print(f"   {stitle[:40]:<42} стр.{page}: +{new} (всего {len(found)})",
                      flush=True)
                if new == 0:
                    break

    br.close()
    rows = sorted(found.values(), key=lambda r: r["zagolovok"])
    if rows:
        with (OUT / "rgo_items.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        with (OUT / "rgo_items.jsonl").open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nзапросов: {spent} | единиц собрано: {len(rows)}")
    print(f"→ {OUT / 'rgo_items.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
