"""
Применение правок из локально отредактированного CSV обратно в Notion-каталог.

Сравнивает ОТРЕДАКТИРОВАННЫЙ CSV (та же схема колонок, что выгрузил notion_catalog_export.py)
с JSON-снэпшотом _baseline.json того же прогона выгрузки — построчно по page_id, поле за полем.
Пишется только то, что реально изменилось относительно снэпшота (не относительно текущего
состояния Notion — если база менялась извне параллельно, re-export и сравни заново перед sync).
relation-поля резолвятся по title через _relations.json того же прогона; title, не найденный
в справочнике, НЕ пишется (всё поле целиком пропускается с пометкой в журнале) — создавать
новые записи в справочниках-целях скрипт не умеет, это ручная правка в Notion.

Read-only поля схемы (rollup/formula/auto_increment_id) и self-relation
"ID связанных источников" никогда не записываются, даже если отличаются в CSV.

По умолчанию — ТОЛЬКО предпросмотр изменений (без --apply ничего не пишется в Notion).
Журнал `<csv>_sync_ledger.jsonl` — резюмируемость: повторный запуск с --apply не дублирует
уже применённые (page_id, набор полей).

Запуск:
  python scripts/notion_catalog_sync.py output/notion_catalog_ДАТА.csv \
      output/notion_catalog_ДАТА_baseline.json output/notion_catalog_ДАТА_relations.json
      # только предпросмотр диффа, ничего не пишет

  ...--apply                 # реальная запись в Notion
  ...--apply --limit 20      # пробная запись первых 20 изменённых строк
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import env, fix_stdout, load_env, log  # noqa: E402

from notion_client import Client  # noqa: E402

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "modules" / "notion_schema.json"
ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")

READONLY_TYPES = {"rollup", "formula", "auto_increment_id"}
SKIP_FIELDS = {"ID связанных источников"}


def csv_display(ptype: str, raw, relation_id_to_title: dict | None) -> str:
    """Сырое значение из baseline.json -> та же строковая форма, что лежит в CSV (для диффа)."""
    if ptype == "relation":
        id2title = relation_id_to_title or {}
        return "; ".join(id2title.get(pid, pid) for pid in (raw or []))
    if ptype == "number":
        return "" if raw in (None, "") else str(raw)
    return str(raw or "")


def values_equal(ptype: str, old_display: str, new_csv: str) -> bool:
    old, new = old_display.strip(), (new_csv or "").strip()
    if ptype == "number":
        if old == "" and new == "":
            return True
        try:
            return old != "" and new != "" and float(old) == float(new)
        except ValueError:
            return old == new
    if ptype == "relation" or ptype == "multi_select":
        old_set = {x.strip() for x in old.split(";") if x.strip()}
        new_set = {x.strip() for x in new.split(";") if x.strip()}
        return old_set == new_set
    return old == new


def to_rest_value(ptype: str, csv_value: str, relation_title_to_id: dict | None):
    """Строка из CSV -> форма REST API Notion. Для relation возвращает (value, missing_titles)."""
    v = (csv_value or "").strip()
    if ptype == "title":
        return {"title": [{"text": {"content": v[:2000]}}]} if v else {"title": []}
    if ptype == "rich_text":
        return {"rich_text": [{"text": {"content": v[:2000]}}]} if v else {"rich_text": []}
    if ptype == "number":
        return {"number": float(v) if v else None}
    if ptype == "select":
        return {"select": {"name": v} if v else None}
    if ptype == "multi_select":
        names = [x.strip() for x in v.split(";") if x.strip()]
        return {"multi_select": [{"name": n} for n in names]}
    if ptype == "url":
        return {"url": v or None}
    if ptype == "date":
        return {"date": {"start": v} if v else None}
    if ptype == "relation":
        if not v:
            return {"relation": []}, []
        titles = [x.strip() for x in v.split(";") if x.strip()]
        ids, missing = [], []
        for t in titles:
            pid = (relation_title_to_id or {}).get(t)
            (ids if pid else missing).append(pid if pid else t)
        if missing:
            return None, missing
        return {"relation": [{"id": i} for i in ids]}, []
    raise ValueError(f"не умею писать тип свойства: {ptype}")


RETRIES = 6  # соединение под VPN периодически рвётся (WinError 10054) -- не ошибка записи


def update_page_retry(client, page_id: str, properties: dict):
    """client.pages.update с повтором на разрыв соединения, чтобы транспортный сбой не
    записался в журнал как настоящий отказ правки (см. query_retry в notion_catalog_export.py)."""
    for attempt in range(RETRIES):
        try:
            return client.pages.update(page_id=page_id, properties=properties)
        except Exception:  # noqa: BLE001 -- транспортные ошибки httpx разных классов
            if attempt == RETRIES - 1:
                raise
            time.sleep(min(2**attempt, 30))
    raise RuntimeError("unreachable")


def load_baseline(path: Path) -> dict:
    """Читает baseline и в новом построчном NDJSON (_baseline.jsonl), и в старом однофайловом
    JSON (_baseline.json, прогоны до 24.10.2026) — для совместимости со старыми выгрузками."""
    if path.suffix == ".jsonl":
        baseline = {}
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                baseline[rec["page_id"]] = rec["fields"]
        return baseline
    return json.loads(path.read_text(encoding="utf-8"))


def load_ledger(path: Path) -> set:
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("status") == "ok":
                done.add((rec["page_id"], tuple(sorted(rec["fields"]))))
    return done


def append_ledger(path: Path, entry: dict):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def compute_changes(rows, props, baseline, relation_lookup):
    relation_id_to_title = {field: {v: k for k, v in m.items()} for field, m in relation_lookup.items()}
    changes, unknown_pages = [], 0
    for row in rows:
        page_id = row.get("page_id")
        if not page_id or page_id not in baseline:
            unknown_pages += 1
            continue
        base = baseline[page_id]
        diff = {}
        for field, spec in props.items():
            ptype = spec["type"]
            if ptype in READONLY_TYPES or field in SKIP_FIELDS or field not in row:
                continue
            old_display = csv_display(ptype, base.get(field), relation_id_to_title.get(field))
            new_csv = row.get(field) or ""
            if not values_equal(ptype, old_display, new_csv):
                diff[field] = (old_display, new_csv)
        if diff:
            changes.append((page_id, diff))
    return changes, unknown_pages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edited_csv", type=Path)
    parser.add_argument("baseline_json", type=Path)
    parser.add_argument("relations_json", type=Path)
    parser.add_argument("--apply", action="store_true", help="реально писать в Notion (иначе только предпросмотр)")
    parser.add_argument("--limit", type=int, default=0, help="применить только первые N изменённых строк")
    args = parser.parse_args()

    fix_stdout()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    props = schema["schema"]
    baseline = load_baseline(args.baseline_json)
    relation_lookup = json.loads(args.relations_json.read_text(encoding="utf-8"))
    relation_title_to_id = relation_lookup

    with args.edited_csv.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    changes, unknown_pages = compute_changes(rows, props, baseline, relation_lookup)
    if args.limit:
        changes = changes[: args.limit]

    print(f"Изменённых строк: {len(changes)} (page_id из CSV не найден в снэпшоте: {unknown_pages})")
    for page_id, diff in changes[:20]:
        print(f"\n-- {page_id} --")
        for field, (old, new) in diff.items():
            print(f"  {field}: {old!r} -> {new!r}")
    if len(changes) > 20:
        print(f"\n... и ещё {len(changes) - 20} строк")

    if not args.apply:
        print("\nПредпросмотр. Для записи в Notion запусти с --apply.")
        return

    load_env(ENV_PATH)
    token = env("NOTION_TOKEN", required=True)
    client = Client(auth=token)
    logger = log("notion_catalog_sync")
    ledger_path = args.edited_csv.with_name(args.edited_csv.stem + "_sync_ledger.jsonl")
    done = load_ledger(ledger_path)

    ok, failed, skipped = 0, 0, 0
    for page_id, diff in changes:
        key = (page_id, tuple(sorted(diff.keys())))
        if key in done:
            skipped += 1
            continue
        payload, missing_report = {}, {}
        for field, (_old, new) in diff.items():
            ptype = props[field]["type"]
            if ptype == "relation":
                value, missing = to_rest_value(ptype, new, relation_title_to_id.get(field))
                if missing:
                    missing_report[field] = missing
                    continue
                payload[field] = value
            else:
                payload[field] = to_rest_value(ptype, new, None)
        if missing_report:
            append_ledger(ledger_path, {"page_id": page_id, "fields": list(diff.keys()),
                                         "status": "skip_unresolved_relation", "missing": missing_report})
            skipped += 1
            logger.info(f"{page_id}: нерезолвленные значения relation {missing_report} — пропущено")
            continue
        try:
            update_page_retry(client, page_id, payload)
            append_ledger(ledger_path, {"page_id": page_id, "fields": list(diff.keys()), "status": "ok"})
            ok += 1
        except Exception as exc:  # noqa: BLE001 -- логируем и продолжаем, резюмируемо через ledger
            append_ledger(ledger_path, {"page_id": page_id, "fields": list(diff.keys()),
                                         "status": "fail", "error": str(exc)[:300]})
            failed += 1
            logger.info(f"FAIL {page_id}: {exc}")
        if (ok + failed) % 25 == 0:
            logger.info(f"{ok + failed}/{len(changes)} ok={ok} failed={failed}")
        time.sleep(0.34)

    print(f"\nГотово: ok={ok} failed={failed} пропущено={skipped} из {len(changes)}")


if __name__ == "__main__":
    main()
