"""Сколько записей каталога связано с каждой серией — по локальной выгрузке baseline.jsonl.

API data_sources.query обрывается на 10 000 записей, поэтому считаем офлайн.

  python series_link_counts_offline.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

BASELINE = Path(
    r"D:\Dropbox\Project\Pooh\19 Каталогизация исторических источников России"
    r"\Представленность исторических картографических источников в федеральных "
    r"и региональных архивах и библиотеках\данные\текущий_baseline.jsonl"
)
SERIES_DS = "339a16aa-aa56-4bf5-8767-4eddb24cb16c"
FIELD = "Серия / массив"


def main() -> None:
    fix_stdout()
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
            name = next(
                ("".join(r["plain_text"] for r in v["title"])
                 for v in p["properties"].values() if v.get("type") == "title"),
                "(без названия)",
            )
            series[p["id"].replace("-", "")] = name
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]
    print(f"карточек серий: {len(series)}")

    cnt: Counter = Counter()
    total = no_series = 0
    with BASELINE.open(encoding="utf-8") as f:
        for line in f:
            total += 1
            rec = json.loads(line)
            rel = rec.get("fields", {}).get(FIELD) or []
            if not rel:
                no_series += 1
                continue
            for r in rel:
                rid = r["id"] if isinstance(r, dict) else r
                cnt[str(rid).replace("-", "")] += 1

    print(f"записей каталога в выгрузке: {total}")
    print(f"без серии: {no_series} ({no_series * 100 // max(total, 1)} %)\n")
    print("записей каталога по сериям:")
    for sid, n in cnt.most_common():
        print(f"  {n:>6}  {series.get(sid, '??? ' + sid)}")
    print("\nсерии без единой связанной записи:")
    for sid, name in series.items():
        if sid not in cnt:
            print(f"         {name}")


if __name__ == "__main__":
    main()
