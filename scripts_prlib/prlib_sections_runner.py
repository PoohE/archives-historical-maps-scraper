"""ПрБ: добор двух коллекций Пермского края, оставшихся в `pending` после прогона v8.1.

Остаток по источнику: две страницы листинга не дочитаны — коллекции 682122 «Пермcкий
край: страницы истории» и 2066551 «Пермский край». Поиск портала закрыт robots
(`/search`, `/prlib_search`, `/?q=search/`), поэтому идём легальным маршрутом коллекций,
как в v8: `/collections/<id>` → `/section/<id>` → `/item/<id>`.

Карточки лежат прямо в разделах (проверено 18.10: раздел 2048404 отдал 22 карточки без
пагинации), разделы вложены друг в друга. Обходим дерево разделов, собираем карточки,
картографические помечаем признаком — предметный гейт применяется отдельно, как в v8.

Запуск:
    python -B scripts_prlib/prlib_sections_runner.py --max-requests 200
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "prlib_perm_sections"
HOST = "https://www.prlib.ru"

COLLECTIONS = {
    "682122": "Пермcкий край: страницы истории",
    "2066551": "Пермский край",
}

# Картографические рубрики портала, найденные 18.10 при доборе пермской коллекции.
# Они лежат в общем рубрикаторе, а не внутри региональных коллекций: прежний вывод
# «общий фонд библиотеки не покрыт и покрыт быть не может, потому что поиск закрыт
# robots» этим опровергнут — карты достижимы по рубрикам.
CARTO_SECTIONS = {
    "1157350": "Физические карты",
    "1157351": "Земельные и лесные ресурсы",
    "1157352": "Водные ресурсы",
    "1157354": "Исторические карты",
    "1157355": "Политико-административные карты",
    "1157356": "Пути сообщения",
    "1157357": "Экономические карты",
    "1157359": "Этнографические карты",
    "1157360": "Планы населенных пунктов",
    "2048442": "Картографические материалы",
    "686714": "Работы в области картографии",
    "686715": "Атласы",
}

SECTION = re.compile(r'href="/section/(\d+)"[^>]*>\s*([^<]{3,120})')
ITEM = re.compile(r'href="/item/(\d+)"[^>]*>\s*([^<]{4,250})')
CARTO = re.compile(r"\bкарт[аыуеой]\b|\bкарты\b|\bплан\b|\bпланы\b|\bплана\b|атлас"
                   r"|чертеж|чертёж|съемк|съёмк|топограф|межев|глазомерн|верстк", re.I)
# Территория: Пермская губерния и её уезды (коллекция краевая, но попадаются соседи).
PERM = re.compile(r"\bПермск\w*|\bПерм[ьи]\b|\bСоликамск\w*|\bЧердын\w*|\bКунгур\w*"
                  r"|\bОханск\w*|\bОсинск\w*|\bВерхотур\w*|\bИрбитск\w*|\bШадринск\w*"
                  r"|\bЕкатеринбург\w*|\bКрасноуфимск\w*|\bКамышлов\w*|\bПрикам\w*", re.I)


def fetch(url: str, tries: int = 3) -> str | None:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            time.sleep(2 * (i + 1))
        except Exception:  # noqa: BLE001
            time.sleep(2 * (i + 1))
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-requests", type=int, default=200)
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--carto-sections", action="store_true",
                    help="идти по картографическим рубрикам портала, а не по коллекциям")
    ap.add_argument("--out-name", default="items",
                    help="имя файла выхода без расширения")
    ap.add_argument("--max-depth", type=int, default=0,
                    help="0 — без ограничения; иначе вглубь не дальше N уровней от старта. "
                         "Нужно потому, что рекурсия по /section/ уходит в общий рубрикатор "
                         "портала: 400 пройденных разделов оставили очередь 78 504")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    seen_sections: set[str] = set()
    items: dict[str, dict] = {}
    spent = 0
    queue: list[tuple[str, str, str]] = []

    if args.carto_sections:
        for sid, stitle in CARTO_SECTIONS.items():
            queue.append((sid, stitle, "картографические рубрики портала", 0))
        print(f"стартовых рубрик: {len(queue)}")
    else:
        for cid, cname in COLLECTIONS.items():
            htm = fetch(f"{HOST}/collections/{cid}")
            spent += 1
            time.sleep(args.delay)
            if not htm:
                print(f"коллекция {cid}: не получена")
                continue
            found = SECTION.findall(htm)
            print(f"коллекция {cid} «{cname}»: разделов {len({s for s, _ in found})}")
            for sid, stitle in found:
                queue.append((sid, html.unescape(stitle).strip(), cname, 0))

    while queue and spent < args.max_requests:
        sid, stitle, cname, depth = queue.pop(0)
        if sid in seen_sections:
            continue
        seen_sections.add(sid)
        htm = fetch(f"{HOST}/section/{sid}")
        spent += 1
        time.sleep(args.delay)
        if not htm:
            continue
        for iid, raw in ITEM.findall(htm):
            title = html.unescape(re.sub(r"\s+", " ", raw)).strip()
            if iid in items:
                continue
            items[iid] = {
                "item_id": iid, "title": title, "url": f"{HOST}/item/{iid}",
                "section_id": sid, "section": stitle, "collection": cname,
                "carto": bool(CARTO.search(title)), "perm": bool(PERM.search(title)),
            }
        if args.max_depth and depth + 1 > args.max_depth:
            continue
        for nsid, ntitle in SECTION.findall(htm):
            if nsid not in seen_sections:
                queue.append((nsid, html.unescape(ntitle).strip(), cname, depth + 1))

    (OUT / f"{args.out_name}.jsonl").write_text(
        "\n".join(json.dumps(v, ensure_ascii=False) for v in items.values()),
        encoding="utf-8")

    carto = [v for v in items.values() if v["carto"]]
    print(f"\nзапросов: {spent} | разделов пройдено: {len(seen_sections)} | "
          f"очередь осталась: {len(queue)}")
    print(f"карточек всего: {len(items)} | с картографическим признаком: {len(carto)}")
    if carto:
        print("\nкартографические карточки:")
        for v in carto[:40]:
            mark = "✓" if v["perm"] else " "
            print(f"  {mark} {v['title'][:88]}")
            print(f"     {v['url']}  [{v['section'][:40]}]")
        print("\nпо разделам:", dict(Counter(v["section"][:30] for v in carto).most_common(8)))
    print(f"\n→ {OUT / (args.out_name + '.jsonl')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
