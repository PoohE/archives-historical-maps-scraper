"""Проба: сколько записей реально отдаёт data_sources.query по каталогу и где обрывается.

  python catalog_count_probe.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

CATALOG_DS = "decdf63c-6f64-4852-ada2-65e72c79d9bc"


def main() -> None:
    fix_stdout()
    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN"))

    total, cursor, pages = 0, None, 0
    last_resp = None
    while True:
        body: dict = {"page_size": 100, "filter_properties": ["title"]}
        if cursor:
            body["start_cursor"] = cursor
        resp = retry(lambda: client.data_sources.query(data_source_id=CATALOG_DS, **body))
        last_resp = resp
        n = len(resp["results"])
        total += n
        pages += 1
        if pages % 25 == 0:
            print(f"  {total} записей, страниц {pages}, has_more={resp.get('has_more')}")
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]

    print(f"\nИТОГО: {total} записей за {pages} страниц")
    print(f"последний ответ: has_more={last_resp.get('has_more')}, "
          f"next_cursor={last_resp.get('next_cursor')}")


if __name__ == "__main__":
    main()
