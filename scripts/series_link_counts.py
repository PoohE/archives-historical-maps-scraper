"""Сколько записей каталога связано с каждой карточкой серии (поле «Серия / массив»).

  python series_link_counts.py
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

SERIES_DS = "339a16aa-aa56-4bf5-8767-4eddb24cb16c"
CATALOG_DS = "decdf63c-6f64-4852-ada2-65e72c79d9bc"
FIELD = "Серия / массив"


def title_of(page: dict) -> str:
    for v in page["properties"].values():
        if v.get("type") == "title":
            return "".join(r["plain_text"] for r in v["title"])
    return "(без названия)"


def query_all(client: Client, ds_id: str, props: list[str] | None = None) -> list[dict]:
    out, cursor = [], None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        if props:
            body["filter_properties"] = props
        resp = retry(lambda: client.data_sources.query(data_source_id=ds_id, **body))
        out.extend(resp["results"])
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]
    return out


def main() -> None:
    fix_stdout()
    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN"))

    series = {p["id"].replace("-", ""): title_of(p) for p in query_all(client, SERIES_DS)}
    print(f"карточек серий: {len(series)}")

    cat = query_all(client, CATALOG_DS)
    print(f"записей каталога: {len(cat)}")

    cnt: Counter = Counter()
    no_series = 0
    for p in cat:
        rel = p["properties"].get(FIELD, {}).get("relation", [])
        if not rel:
            no_series += 1
        for r in rel:
            cnt[r["id"].replace("-", "")] += 1

    print(f"\nбез серии: {no_series}\n")
    print("записей каталога по сериям (по убыванию):")
    for sid, n in cnt.most_common():
        print(f"  {n:>5}  {series.get(sid, '??? ' + sid)}")
    print("\nсерии БЕЗ единой связанной записи каталога:")
    for sid, name in series.items():
        if sid not in cnt:
            print(f"        {name}")


if __name__ == "__main__":
    main()
