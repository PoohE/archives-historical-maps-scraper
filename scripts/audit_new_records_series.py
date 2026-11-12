"""Аудит привязки к сериям для записей каталога, созданных с заданной даты.

Baseline-выгрузка устарела (30.10), поэтому записи 02–07.11 считаем живым запросом
с фильтром по created_time — он укладывается в лимит 10 000.

  python audit_new_records_series.py [--since 2026-11-01]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

CATALOG_DS = "decdf63c-6f64-4852-ada2-65e72c79d9bc"
SERIES_DS = "339a16aa-aa56-4bf5-8767-4eddb24cb16c"
FIELD = "Серия / массив"


def title_of(page: dict) -> str:
    for v in page["properties"].values():
        if v.get("type") == "title":
            return "".join(r["plain_text"] for r in v["title"])
    return "(без названия)"


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-11-01")
    args = ap.parse_args()

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN"))

    series: dict[str, str] = {}
    cursor = None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp = retry(lambda: client.data_sources.query(data_source_id=SERIES_DS, **body))
        for p in resp["results"]:
            series[p["id"].replace("-", "")] = title_of(p)
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]

    rows = []
    cursor = None
    while True:
        body = {
            "page_size": 100,
            "filter": {"timestamp": "created_time",
                       "created_time": {"on_or_after": args.since}},
        }
        if cursor:
            body["start_cursor"] = cursor
        resp = retry(lambda: client.data_sources.query(data_source_id=CATALOG_DS, **body))
        for p in resp["results"]:
            rel = p["properties"].get(FIELD, {}).get("relation") or []
            names = [series.get(r["id"].replace("-", ""), "???") for r in rel]
            rows.append((p["created_time"][:10], title_of(p), names))
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]

    print(f"карточек серий в БД: {len(series)}")
    print(f"записей создано с {args.since}: {len(rows)}\n")
    nolink = 0
    for date, name, ser in sorted(rows):
        mark = "OK " if ser else "БЕЗ"
        if not ser:
            nolink += 1
        print(f"{mark} {date}  {name[:95]}")
        if ser:
            print(f"        серия: {'; '.join(ser)}")
    print(f"\nбез привязки к серии: {nolink} из {len(rows)}")

    print("\nкарточки серий, содержащие 'Кавказ', 'Трёхвёрст', 'Шуберт', 'Одновёрст':")
    for sid, nm in series.items():
        if any(k.lower() in nm.lower()
               for k in ("кавказ", "трёхвёрст", "трехвёрст", "шуберт", "одновёрст", "знак")):
            print(f"  {sid}  {nm}")


if __name__ == "__main__":
    main()
