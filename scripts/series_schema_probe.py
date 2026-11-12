"""Схема БД серий: parent database_id + типы свойств (для создания новой карточки серии)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

SERIES_DS = "339a16aa-aa56-4bf5-8767-4eddb24cb16c"


def main() -> None:
    fix_stdout()
    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN"))

    resp = retry(lambda: client.data_sources.query(data_source_id=SERIES_DS, page_size=1))
    page = resp["results"][0]
    print("parent:", page["parent"])
    ds = retry(lambda: client.data_sources.retrieve(data_source_id=SERIES_DS))
    print("database_parent:", ds.get("parent"))
    for name, spec in ds["properties"].items():
        t = spec["type"]
        extra = ""
        if t == "select":
            extra = " | " + ", ".join(o["name"] for o in spec["select"]["options"])[:200]
        elif t == "relation":
            extra = " -> " + str(spec["relation"].get("data_source_id")
                                 or spec["relation"].get("database_id"))
        print(f"  {name}: {t}{extra}")


if __name__ == "__main__":
    main()
