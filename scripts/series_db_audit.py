"""Аудит базы «Серийные массивы»: какие серии заведены, сколько записей каталога связано с каждой.

  python series_db_audit.py
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

SERIES_DS = "339a16aa-aa56-4bf5-8767-4eddb24cb16c"  # data source «Серийные массивы»
CATALOG_DS = "decdf63c-5fb6-4d18-9c4a-5d9a4d3b06e3"  # data source каталога (из прежних скриптов)


def rt_text(prop: dict) -> str:
    for key in ("title", "rich_text"):
        if key in prop:
            return "".join(r["plain_text"] for r in prop[key])
    return ""


def main() -> None:
    fix_stdout()
    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN"))

    rows, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp = retry(
            lambda: client.data_sources.query(data_source_id=SERIES_DS, **body)
        )
        rows.extend(resp["results"])
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]

    print(f"карточек серий: {len(rows)}\n")
    for p in rows:
        props = p["properties"]
        name = ""
        for k, v in props.items():
            if v.get("type") == "title":
                name = rt_text(v)
                break
        filled = []
        for field in (
            "Типы отображаемых объектов",
            "Отображаемые объекты (детально)",
            "Условные знаки (легенды)",
            "Использование в анализе (литература)",
        ):
            v = props.get(field)
            if not v:
                filled.append(f"{field}: НЕТ ПОЛЯ")
            elif v["type"] == "relation":
                filled.append(f"{field}: {len(v['relation'])} связей")
            else:
                n = len(rt_text(v))
                filled.append(f"{field}: {n} зн." if n else f"{field}: ПУСТО")
        rel_counts = {
            k: len(v["relation"])
            for k, v in props.items()
            if v.get("type") == "relation" and v["relation"]
        }
        print(f"— {name}")
        print(f"   id {p['id']}")
        print("   " + "; ".join(filled))
        print(f"   связи: {rel_counts}")
        print()

    print("=" * 70)
    print("Счётчик по типам полей первой карточки:")
    if rows:
        print(Counter(v["type"] for v in rows[0]["properties"].values()))


if __name__ == "__main__":
    main()
