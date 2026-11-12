"""Связать записи каталога по «Материалам для географии и статистики России» с карточкой серии.

Записи этого издания лежат в каталоге россыпью (ЦВМБ и Президентская библиотека),
поле «Серия / массив» у них пустое — то есть из карточки серии их не видно и типовые
параметры из неё не подтягиваются.

  python link_series20_records.py          # показать, что нашлось, НИЧЕГО не писать
  python link_series20_records.py --apply  # проставить связь
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

from series910_notion_link import SERIES_DS, query_all, title_of  # noqa: E402

CATALOG_DS = "decdf63c-6f64-4852-ada2-65e72c79d9bc"
SERIES_NAME = "Материалы для географии и статистики России"
NEEDLE = "Материалы для географии и статистики России"
FIELD = "Серия / массив"


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    load_env(ENV_PATH)
    c = Client(auth=env("NOTION_TOKEN"))

    card = next(x for x in query_all(c, SERIES_DS) if SERIES_NAME in title_of(x))
    print(f"карточка серии: {title_of(card)} ({card['id']})")

    pages: list[dict] = []
    cur = None
    while True:
        q = {
            "data_source_id": CATALOG_DS,
            "filter": {"property": "Название источника", "title": {"contains": NEEDLE}},
            "page_size": 100,
        }
        if cur:
            q["start_cursor"] = cur
        r = retry(lambda q=q: c.data_sources.query(**q))
        pages += r["results"]
        if not r.get("has_more"):
            break
        cur = r["next_cursor"]

    print(f"найдено записей каталога: {len(pages)}")
    todo = []
    for p in pages:
        rel = (p["properties"].get(FIELD) or {}).get("relation") or []
        linked = any(x["id"] == card["id"] for x in rel)
        arch = p["properties"].get("Архив [авто]")
        arch_v = ""
        if arch and arch.get("type") == "formula":
            arch_v = (arch["formula"] or {}).get("string") or ""
        elif arch and arch.get("type") == "select":
            arch_v = ((arch.get("select")) or {}).get("name") or ""
        name = title_of(p)
        print(f"  {'✔ уже связана' if linked else '→ связать   '} | {arch_v:<6} | {name[:95]}")
        if not linked:
            todo.append((p, rel))

    if not args.apply:
        print(f"\nбез --apply ничего не записано. К связыванию: {len(todo)}")
        return

    for p, rel in todo:
        retry(
            lambda p=p, rel=rel: c.pages.update(
                page_id=p["id"],
                properties={FIELD: {"relation": rel + [{"id": card["id"]}]}},
            )
        )
    print(f"\nсвязано записей: {len(todo)}")


if __name__ == "__main__":
    main()
