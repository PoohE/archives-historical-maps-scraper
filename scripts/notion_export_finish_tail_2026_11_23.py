"""Дозавершение выгрузки каталога 23.11.2026: хвост за последние сутки + стабильная копия.

Полная выгрузка `notion_catalog_export.py` дочитала 118 081 запись и была убита сторожем
памяти перед самым концом: в слепке не хватило записей, созданных в последние часы
(20 из 267 сегодняшней партии), и копия в папку статьи не обновилась. Перечитывать
118 тыс. записей ради двух десятков незачем: здесь дочитывается только окно с начала
суток, новые записи дописываются в CSV и baseline, после чего обновляется стабильная копия.

  python scripts/notion_export_finish_tail_2026_11_23.py output/notion_catalog_<метка>.csv
"""
import csv
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import notion_catalog_export as m  # noqa: E402

from common import env, fix_stdout, load_env, log  # noqa: E402
from notion_client import Client  # noqa: E402

STABLE = Path(
    r"D:\Dropbox\Project\Pooh\19 Каталогизация исторических источников России"
    r"\Представленность исторических картографических источников в федеральных"
    r" и региональных архивах и библиотеках\данные")


def main() -> None:
    fix_stdout()
    csv.field_size_limit(10 ** 9)
    out_csv = Path(sys.argv[1])
    out_base = out_csv.with_name(out_csv.stem + "_baseline.jsonl")
    out_rel = out_csv.with_name(out_csv.stem + "_relations.json")
    logger = log("export_tail")
    load_env(m.ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    schema = json.loads(m.SCHEMA_PATH.read_text(encoding="utf-8"))
    props, catalog_id = schema["schema"], schema["data_source_id"]
    fields = list(props.keys())
    if out_rel.exists():
        rel = json.loads(out_rel.read_text(encoding="utf-8"))
    else:
        # справочники маленькие — если файл связей утрачен, дочитываем их заново
        rel = {}
        for field, spec in props.items():
            if spec["type"] == "relation" and field not in m.SELF_RELATION_FIELDS:
                rel[field] = m.fetch_title_map(client, m.ds_id(spec["data_source"]), logger, field)
        out_rel.write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8")
    id2title = {f: {v: k for k, v in mp.items()} for f, mp in rel.items()}

    seen = {json.loads(ln)["page_id"] for ln in out_base.open(encoding="utf-8") if ln.strip()}
    logger.info(f"в слепке до дозавершения: {len(seen)}")
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=2)
    added = 0
    with out_csv.open("a", encoding="utf-8-sig", newline="") as f, \
         out_base.open("a", encoding="utf-8", newline="\n") as fb:
        w = csv.DictWriter(f, fieldnames=["page_id", "url", *fields])
        for page in m.fetch_window(client, catalog_id, start, now + timedelta(days=1), logger):
            pid = page["id"]
            if pid in seen:
                continue
            seen.add(pid)
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
    logger.info(f"дописано записей: {added} | всего: {len(seen)}")

    status: Counter = Counter()
    for ln in out_base.open(encoding="utf-8"):
        if ln.strip():
            status[str(json.loads(ln)["fields"].get("Статус приёмки") or "(пусто)")] += 1
    for k, v in status.most_common():
        logger.info(f"  статус приёмки «{k}»: {v}")
    STABLE.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out_csv, STABLE / "текущий.csv")
    shutil.copyfile(out_base, STABLE / "текущий_baseline.jsonl")
    shutil.copyfile(out_rel, STABLE / "текущий_relations.json")
    logger.info(f"стабильная копия обновлена: {STABLE}")
    print(json.dumps({"rows": len(seen), "added": added, "status": dict(status)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
