"""Шаг 2 каскада: есть ли в дереве описей 38-41 узлы-разделы с губерниями.

Контекст: в описях 38-41 фонда 380 дела сгруппированы по губерниям, и в заголовке
дела губерния не повторяется («Карта лесов уезда», «Топографический межевой атлас
губернии»). Если в дереве описи есть узлы-разделы с названиями губерний, территорию
1140 отобранных записей можно восстановить без обхода карточек.

Сборщик фонда брал из дерева ТОЛЬКО узлы с шифром «Ф. 380 Оп. N Д. X» и падал на
остальных (`case_node_code_mismatch`). Здесь смотрим ВСЕ узлы страницы как есть.

Это разведка: несколько страниц, ничего не пишет в наборы.

Запуск из корня проекта:
    python -B scripts_rgia/probe_fund380_opis_tree.py
    python -B scripts_rgia/probe_fund380_opis_tree.py --opis 2841221 --pages 1,2,3
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://fgurgia.ru"
AGENT = "Mozilla/5.0 (compatible; IGIS-research/1.0)"
PAUSE = 3.0  # темп сборщика: 3 с между запросами, не ускорять (был soft-ban)

OPISI = {"2841219": "38", "2841221": "39", "2841223": "40", "2841225": "41"}
GUB = re.compile(r"([А-ЯЁ][а-яё\-]+ск(?:ая|ой|ого|ую))\s+губерн", re.I)


OPENER = None


def session_index(object_id: str) -> str | None:
    """Получить сессионный search-index объекта.

    У fgurgia.ru `/ajax/tree/{index}` работает не с произвольным числом, а с
    `data-search-index`, который выдаётся на странице `/object/{id}` в ТОЙ ЖЕ сессии
    (куки). Без него ajax отвечает HTTP 500 — так и было в первой пробе.
    Тот же приём использует сборщик фонда (`index_from_page`).
    """
    global OPENER
    jar = http.cookiejar.CookieJar()
    OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(f"{BASE}/object/{object_id}",
                                 headers={"User-Agent": AGENT})
    try:
        with OPENER.open(req, timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"  страница объекта: {type(e).__name__}: {e}")
        return None
    m = re.search(rf'data-object-id="{re.escape(object_id)}"[^>]*data-search-index="(\d+)"', html)
    if not m:
        m = re.search(rf'data-search-index="(\d+)"[^>]*data-object-id="{re.escape(object_id)}"', html)
    print(f"  страница объекта: {len(html)} байт, куки {len(jar)}, "
          f"search-index {'найден: ' + m.group(1) if m else 'НЕ найден'}")
    time.sleep(PAUSE)
    return m.group(1) if m else None


def fetch(url: str, params: dict) -> str | None:
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={
        "User-Agent": AGENT,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE}/object/380",
    })
    try:
        with (OPENER or urllib.request).open(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"    ошибка: {type(e).__name__}: {e}")
        return None


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--opis", default="2841221", help="object_id описи (по умолчанию оп. 39)")
    ap.add_argument("--pages", default="1,2,3")
    args = ap.parse_args()
    pages = [p.strip() for p in args.pages.split(",") if p.strip()]
    num = OPISI.get(args.opis, "?")

    print(f"опись {num} (object_id {args.opis}), страницы {pages}, пауза {PAUSE} с\n")
    index = session_index(args.opis)
    if not index:
        print("\nбез сессионного search-index ajax отдаёт HTTP 500 — выходим")
        return 1

    kinds: dict[str, int] = {}
    gubernii: list[tuple[str, str]] = []

    for page in pages:
        params = {"page": page, "nPage": page, "id": "0", "parentId": args.opis,
                  "objectType": args.opis + "-1050", "showPageList": "true",
                  "completeWorkId": "-1"}
        body = fetch(f"{BASE}/ajax/tree/{index}", params)
        time.sleep(PAUSE)
        if not body:
            continue
        try:
            nodes = json.loads(body)
        except json.JSONDecodeError:
            print(f"  стр.{page}: ответ не JSON ({len(body)} байт)")
            continue
        if not isinstance(nodes, list):
            print(f"  стр.{page}: не список, ключи {list(nodes)[:6]}")
            continue
        print(f"  стр.{page}: узлов {len(nodes)}")
        for n in nodes:
            text = strip_tags(str(n.get("text", "")))
            has_code = bool(re.search(r"Ф\.\s*380\s+Оп\.\s*\d+\s+Д\.", text))
            kind = "дело" if has_code else "НЕ дело"
            kinds[kind] = kinds.get(kind, 0) + 1
            if not has_code:
                print(f"      [{kind}] id={n.get('id')} type={n.get('type', '')} "
                      f"{text[:110]}")
            m = GUB.search(text)
            if m and not has_code:
                gubernii.append((str(n.get("id")), m.group(0)))

    print(f"\nитог: {kinds}")
    if gubernii:
        print(f"узлы с губернией в названии: {len(gubernii)}")
        for i, g in gubernii[:10]:
            print(f"   id={i}  {g}")
        print("\nВЫВОД: разделы по губерниям в дереве ЕСТЬ — территорию можно восстановить "
              "обходом разделов, без карточек.")
    else:
        print("\nВЫВОД: узлов-разделов с губерниями в дереве НЕ видно. "
              "Территорию придётся брать из карточек дел (шаг 1) либо из скана описи.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
