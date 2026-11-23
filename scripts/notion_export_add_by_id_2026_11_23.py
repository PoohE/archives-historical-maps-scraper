"""Добор в слепок каталога страниц, которых не вернула выборка по времени (23.11.2026).

Выборка из базы с фильтром по created_time теряет свежие записи (отставание индекса —
память feedback_upload-acceptance-by-page-id-journal). Поэтому слепок сверяется с журналами
всех заливок: страница, которая есть в журнале, жива при опросе по номеру, но в слепке
отсутствует, дочитывается напрямую через GET /v1/pages/<id> и дописывается.

  python scripts/notion_export_add_by_id_2026_11_23.py output/notion_catalog_<метка>.csv
"""
import csv
import glob
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import notion_catalog_export as m  # noqa: E402

from common import env, fix_stdout, load_env, log  # noqa: E402
from notion_client import Client  # noqa: E402
from notion_export_finish_tail_2026_11_23 import STABLE  # noqa: E402


def main() -> None:
    fix_stdout()
    out_csv = Path(sys.argv[1])
    out_base = out_csv.with_name(out_csv.stem + "_baseline.jsonl")
    out_rel = out_csv.with_name(out_csv.stem + "_relations.json")
    logger = log("export_by_id")
    load_env(m.ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    schema = json.loads(m.SCHEMA_PATH.read_text(encoding="utf-8"))
    # Колонки — из заголовка САМОГО слепка, типы — из живой схемы: слепок обёртки
    # (notion_catalog_export_resumable.py) шире статической схемы на поля-признаки
    # «…: источник значения»; дописывать по статической — сдвинуть колонки.
    with out_csv.open(encoding="utf-8-sig", newline="") as fh:
        fields = next(csv.reader(fh))[2:]
    live = client.data_sources.retrieve(data_source_id=schema["data_source_id"])["properties"]
    props = {k: {"type": live.get(k, schema["schema"].get(k, {})).get("type", "rich_text")}
             for k in fields}
    rel = json.loads(out_rel.read_text(encoding="utf-8"))
    id2title = {f: {v: k for k, v in mp.items()} for f, mp in rel.items()}

    seen = {json.loads(ln)["page_id"] for ln in out_base.open(encoding="utf-8") if ln.strip()}
    known: set[str] = set()
    for pat in ("*/created_pages.jsonl", "*/*/created_pages.jsonl"):
        for p in glob.glob(str(m.OUT_DIR / pat)):
            for ln in Path(p).open(encoding="utf-8"):
                if ln.strip():
                    try:
                        pid = json.loads(ln).get("page_id")
                    except json.JSONDecodeError:
                        continue
                    if pid:
                        known.add(pid)
    missing = sorted(known - seen)
    logger.info(f"в слепке: {len(seen)} | номеров в журналах заливок: {len(known)} | "
                f"нет в слепке: {len(missing)}")
    added = trashed = gone = 0
    with out_csv.open("a", encoding="utf-8-sig", newline="") as f, \
         out_base.open("a", encoding="utf-8", newline="\n") as fb:
        w = csv.DictWriter(f, fieldnames=["page_id", "url", *fields])
        for pid in missing:
            try:
                page = client.pages.retrieve(page_id=pid)
            except Exception:  # noqa: BLE001 — 404 у снятых страниц
                gone += 1
                continue
            if page.get("in_trash") or page.get("archived"):
                trashed += 1
                continue
            row = {"page_id": pid, "url": f"https://app.notion.com/{pid.replace('-', '')}"}
            raw = {}
            for field in fields:
                prop = page["properties"].get(field)
                is_rel = props[field]["type"] == "relation"
                val = m.plain_value(prop) if prop is not None else ([] if is_rel else "")
                raw[field] = val
                row[field] = ("; ".join(id2title.get(field, {}).get(x, x) for x in val)
                              if is_rel else val)
            w.writerow(row)
            fb.write(json.dumps({"page_id": pid, "fields": raw}, ensure_ascii=False) + "\n")
            added += 1
    logger.info(f"дописано: {added} | в корзине: {trashed} | не найдено: {gone}")
    status: Counter = Counter()
    total = 0
    for ln in out_base.open(encoding="utf-8"):
        if ln.strip():
            total += 1
            status[str(json.loads(ln)["fields"].get("Статус приёмки") or "(пусто)")] += 1
    shutil.copyfile(out_csv, STABLE / "текущий.csv")
    shutil.copyfile(out_base, STABLE / "текущий_baseline.jsonl")
    shutil.copyfile(out_rel, STABLE / "текущий_relations.json")
    print(json.dumps({"rows": total, "added": added, "trashed": trashed,
                      "status": dict(status)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
