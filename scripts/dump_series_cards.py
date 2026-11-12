"""Выгрузить свойства карточек серий (по подстроке в названии) — чтобы видеть, что заполнено.

  python dump_series_cards.py Трёхвёрстная Шуберт Двухвёрстная
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

SERIES_DS = "339a16aa-aa56-4bf5-8767-4eddb24cb16c"


def plain(v: dict) -> str:
    t = v.get("type")
    if t == "title":
        return "".join(r["plain_text"] for r in v["title"])
    if t == "rich_text":
        return "".join(r["plain_text"] for r in v["rich_text"])
    if t == "select":
        return (v["select"] or {}).get("name", "")
    if t == "multi_select":
        return ", ".join(o["name"] for o in v["multi_select"])
    if t == "number":
        return "" if v["number"] is None else str(v["number"])
    if t == "date":
        return (v["date"] or {}).get("start", "") or ""
    if t == "url":
        return v["url"] or ""
    if t == "checkbox":
        return "да" if v["checkbox"] else "нет"
    if t in ("relation",):
        return f"{len(v['relation'])} связей"
    if t in ("rollup", "formula", "created_time", "last_edited_time",
             "created_by", "last_edited_by", "people", "files"):
        return "<служебное>"
    return f"<{t}>"


def main() -> None:
    fix_stdout()
    keys = [a.lower() for a in sys.argv[1:]] or ["трёхвёрстная"]
    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN"))

    pages = []
    cursor = None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp = retry(lambda: client.data_sources.query(data_source_id=SERIES_DS, **body))
        pages.extend(resp["results"])
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]

    for p in pages:
        name = next(
            ("".join(r["plain_text"] for r in v["title"])
             for v in p["properties"].values() if v.get("type") == "title"), "")
        if not any(k in name.lower() for k in keys):
            continue
        print(f"\n=== {name}\n    id {p['id']}")
        for prop, v in p["properties"].items():
            val = plain(v)
            if val and val != "<служебное>":
                print(f"  {prop}: {val[:300]}")
            elif not val:
                print(f"  {prop}: —  [ПУСТО]")


if __name__ == "__main__":
    main()
