"""Карта поля «Охватываемая территория»: id справочника → название и охват.

Третий пункт приёмки 10.11.2026: заливать признак масштаба надо по ПОЛЮ территории,
а не по тексту заголовка. Первые два пункта показали, почему: гейт по заголовку
читает лишь то, что написано в названии дела, и 552 записи из 553 «без территории»
на самом деле имеют её в поле.

Скрипт собирает из выгрузки все встречающиеся id территорий с частотой и
разрешает их названия через Notion, чтобы стало видно, какие id — наши четыре
губернии (и их уезды, если справочник иерархический).

  python territory_field_map.py [путь_к_baseline.jsonl]
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
DEFAULT = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"
OUT = ROOT / "defects" / "territory_map.json"
FIELD = "Охватываемая территория"


def ids_of(val) -> list[str]:
    """Поле приходит либо списком id, либо строкой-представлением списка."""
    if isinstance(val, list):
        return [str(x) for x in val if x]
    s = str(val or "").strip()
    if not s or s == "[]":
        return []
    try:
        parsed = json.loads(s.replace("'", '"'))
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x]
    except json.JSONDecodeError:
        pass
    return [s]


def title_of(page: dict) -> str:
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title") or [])
    return ""


def main() -> None:
    fix_stdout()
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    freq: Counter = Counter()
    n = 0
    for line in src.open(encoding="utf-8"):
        if not line.strip():
            continue
        n += 1
        f = (json.loads(line).get("fields") or {})
        for tid in ids_of(f.get(FIELD)):
            freq[tid] += 1

    print(f"записей: {n} | различных территорий в поле: {len(freq)}")
    load_env(ENV_PATH)
    c = Client(auth=env("NOTION_TOKEN"))
    names: dict[str, str] = {}
    for tid, cnt in freq.most_common():
        try:
            pg = retry(lambda tid=tid: c.pages.retrieve(page_id=tid))
            names[tid] = title_of(pg) or "— без названия —"
        except Exception as e:  # noqa: BLE001 — любая ошибка чтения справочника
            names[tid] = f"— не прочитано: {type(e).__name__} —"
        print(f"  {cnt:7d}  {names[tid][:70]}  [{tid}]", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {tid: {"name": names[tid], "records": freq[tid]} for tid in freq},
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
