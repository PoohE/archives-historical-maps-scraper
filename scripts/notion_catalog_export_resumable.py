"""Полная выгрузка каталога ИГИС порциями по дням, с возобновлением (23.11.2026).

Зачем отдельный запуск поверх `notion_catalog_export.py`. 23.11.2026 обычная выгрузка
оборвалась трижды, причём два раза В ОДНОМ И ТОМ ЖЕ МЕСТЕ — на 44 058-й записи, перед
18.10.2026: в этот день в каталог залито ~65 тыс. записей ГАЯО, окно упирается в потолок
10 000, скрипт держит в памяти до 10 000 полных объектов Notion на уровень бисекции, и
сторож памяти Claude Code убивает фоновый процесс. Обычная выгрузка при этом всегда
начинает с начала — три прогона дали три одинаковых огрызка.

Что здесь иначе:
  * каталог режется на ДНИ по created_time; каждый день пишется в свой файл
    `parts/<день>.jsonl` (сначала .tmp, переименование — только по завершении дня).
    Убитый прогон продолжается с первого незаконченного дня;
  * порог бисекции снижен с 10 000 до 2 000 записей на окно — в памяти одновременно
    не больше ~2 000 объектов. Корректность та же: окно дробится РАНЬШЕ потолка Notion,
    а не на нём;
  * поля добираются из ЖИВОЙ схемы базы. Статический `notion_schema.json` не знает
    признаков происхождения значения («Масштаб: источник значения», «Год: источник
    значения», «Территория: источник значения», «Административный уровень: источник
    значения») — а без них в выгрузке эвристику не отличить от факта;
  * стабильная копия в папку статьи пишется ТОЛЬКО после полной сборки, а не из огрызка.

  python scripts/notion_catalog_export_resumable.py            # продолжить/начать
  python scripts/notion_catalog_export_resumable.py --fresh    # забыть порции, начать заново
  python scripts/notion_catalog_export_resumable.py --merge-only
"""
from __future__ import annotations

import argparse
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

m.CAP = 2_000                       # бисектим раньше: память, а не потолок Notion
WORK = m.OUT_DIR / "notion_export_parts"
PARTS = WORK / "parts"
STABLE = Path(
    r"D:\Dropbox\Project\Pooh\19 Каталогизация исторических источников России"
    r"\Представленность исторических картографических источников в федеральных"
    r" и региональных архивах и библиотеках\данные")
SIMPLE = {"title", "rich_text", "number", "select", "multi_select", "url", "date",
          "checkbox", "status", "email", "phone_number", "formula", "auto_increment_id",
          "created_time", "last_edited_time", "unique_id"}


def day_windows(start: datetime, end: datetime):
    d = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while d < end:
        yield d, d + timedelta(days=1)
        d += timedelta(days=1)


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true", help="удалить готовые порции")
    ap.add_argument("--merge-only", action="store_true", help="только собрать из порций")
    args = ap.parse_args()
    logger = log("export_resumable")

    if args.fresh and WORK.exists():
        shutil.rmtree(WORK)
    PARTS.mkdir(parents=True, exist_ok=True)

    load_env(m.ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    schema = json.loads(m.SCHEMA_PATH.read_text(encoding="utf-8"))
    props = dict(schema["schema"])
    catalog_id = schema["data_source_id"]

    # поля, которых нет в статическом снимке схемы, берём из живой базы
    live = client.data_sources.retrieve(data_source_id=catalog_id).get("properties", {})
    added, skipped = [], []
    for name, spec in live.items():
        if name in props:
            continue
        if spec.get("type") in SIMPLE:
            props[name] = {"type": spec["type"]}
            added.append(name)
        else:
            skipped.append(f"{name} ({spec.get('type')})")
    logger.info(f"полей в статической схеме: {len(schema['schema'])} | добрано из живой: "
                f"{len(added)} | пропущено (связи и прочее): {len(skipped)}")
    for n in added:
        logger.info(f"  + {n}")
    fields = list(props.keys())
    relation_fields = {k: v for k, v in props.items() if v["type"] == "relation"}

    rel_path = WORK / "relations.json"
    if rel_path.exists():
        relation_lookup = json.loads(rel_path.read_text(encoding="utf-8"))
    else:
        relation_lookup = {}
        for field, spec in relation_fields.items():
            if field in m.SELF_RELATION_FIELDS:
                continue
            relation_lookup[field] = m.fetch_title_map(
                client, m.ds_id(spec["data_source"]), logger, field)
        rel_path.write_text(json.dumps(relation_lookup, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    id2title = {f: {v: k for k, v in mp.items()} for f, mp in relation_lookup.items()}

    if not args.merge_only:
        bounds = WORK / "bounds.json"
        if bounds.exists():
            b = json.loads(bounds.read_text(encoding="utf-8"))
            earliest, latest = m.parse_ts(b["earliest"]), m.parse_ts(b["latest"])
        else:
            earliest = m.get_bound(client, catalog_id, "ascending")
            latest = m.get_bound(client, catalog_id, "descending") + timedelta(days=1)
            bounds.write_text(json.dumps({"earliest": m.fmt_ts(earliest),
                                          "latest": m.fmt_ts(latest)}), encoding="utf-8")
        logger.info(f"диапазон created_time: {earliest} .. {latest}")
        days = list(day_windows(earliest.astimezone(timezone.utc), latest.astimezone(timezone.utc)))
        todo = [(a, b) for a, b in days if not (PARTS / f"{a:%Y-%m-%d}.jsonl").exists()]
        logger.info(f"дней всего: {len(days)} | готово: {len(days) - len(todo)} | осталось: {len(todo)}")
        for a, b in todo:
            part = PARTS / f"{a:%Y-%m-%d}.jsonl"
            tmp = part.with_suffix(".tmp")
            n = 0
            with tmp.open("w", encoding="utf-8", newline="\n") as f:
                for page in m.fetch_window(client, catalog_id, a, b, logger):
                    raw = {}
                    for field in fields:
                        prop = page["properties"].get(field)
                        is_rel = props[field]["type"] == "relation"
                        raw[field] = (m.plain_value(prop) if prop is not None
                                      else ([] if is_rel else ""))
                    f.write(json.dumps({"page_id": page["id"], "fields": raw},
                                       ensure_ascii=False) + "\n")
                    n += 1
            tmp.replace(part)
            if n:
                logger.info(f"день {a:%Y-%m-%d}: {n}")

    # сборка
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = m.OUT_DIR / f"notion_catalog_{stamp}.csv"
    out_base = m.OUT_DIR / f"notion_catalog_{stamp}_baseline.jsonl"
    out_rel = m.OUT_DIR / f"notion_catalog_{stamp}_relations.json"
    shutil.copyfile(rel_path, out_rel)
    seen: set[str] = set()
    total = dupes = 0
    status: Counter = Counter()
    with out_csv.open("w", encoding="utf-8-sig", newline="") as fc, \
         out_base.open("w", encoding="utf-8", newline="\n") as fb:
        w = csv.DictWriter(fc, fieldnames=["page_id", "url", *fields])
        w.writeheader()
        for part in sorted(PARTS.glob("*.jsonl")):
            for ln in part.open(encoding="utf-8"):
                if not ln.strip():
                    continue
                r = json.loads(ln)
                pid = r["page_id"]
                if pid in seen:
                    dupes += 1
                    continue
                seen.add(pid)
                raw = r["fields"]
                row = {"page_id": pid, "url": f"https://app.notion.com/{pid.replace('-', '')}"}
                for field in fields:
                    val = raw.get(field, "")
                    if props[field]["type"] == "relation":
                        mp = id2title.get(field, {})
                        row[field] = "; ".join(mp.get(x, x) for x in (val or []))
                    else:
                        row[field] = val
                w.writerow(row)
                fb.write(ln if ln.endswith("\n") else ln + "\n")
                status[str(raw.get("Статус приёмки") or "(пусто)")] += 1
                total += 1
    logger.info(f"собрано {total} записей (дублей по границам дней: {dupes})")
    for k, v in status.most_common():
        logger.info(f"  статус приёмки «{k}»: {v}")

    unfinished = list(PARTS.glob("*.tmp"))
    if unfinished and not args.merge_only:
        logger.info(f"есть незаконченные порции ({len(unfinished)}) — стабильную копию не трогаю")
        return
    STABLE.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out_csv, STABLE / "текущий.csv")
    shutil.copyfile(out_base, STABLE / "текущий_baseline.jsonl")
    shutil.copyfile(out_rel, STABLE / "текущий_relations.json")
    logger.info(f"стабильная копия обновлена: {STABLE}")
    print(json.dumps({"rows": total, "columns": len(fields) + 2, "csv": str(out_csv),
                      "status": dict(status), "added_fields": added}, ensure_ascii=False))


if __name__ == "__main__":
    main()
