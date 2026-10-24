"""
Отклоняет технические дубли страниц ГАСО, возникшие 16-17.10.2026 из-за гонки: процесс
import_gaso_notion.py многократно убивался по памяти (система стабильно работала на
грани свободной RAM) ровно между успешным `pages.create` и записью в ledger — на резюме
скрипт не видел строку как сделанную и создавал страницу повторно.

Находит группы живых страниц с идентичным (Фонд, Опись, Единица хранения, Название
источника) — это надёжный признак технического дубля (настоящие разные строки описи
ф.814 на одно дело имеют РАЗНЫЕ названия, см. п.4-бис ПЕРЕДАЧА_на_внесение.md; проверено
17.10.2026 вручную на двух пограничных случаях). Внутри группы оставляет самую раннюю
страницу (created_time), остальные помечает "Статус приёмки"="отклонено" с ссылкой на
оставленную — как делали с дублем РГВИА (ф.417 д.103), НЕ удаляет физически.

Запуск:
  python scripts/dedupe_gaso_notion.py --dry-run
  python scripts/dedupe_gaso_notion.py
"""
import argparse
import collections
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import env, fix_stdout, load_env, log  # noqa: E402

from notion_client import Client  # noqa: E402

import import_gaso_notion as gaso  # noqa: E402

ROOT = gaso.ROOT
ENV_PATH = gaso.ENV_PATH
LEDGER_PATH = ROOT / "output" / "gaso_package_20261013" / "_notion_dedupe_ledger.jsonl"


def get_text(props, field, kind="rich_text"):
    val = props.get(field, {})
    if kind == "rich_text":
        return "".join(r["plain_text"] for r in val.get("rich_text", []))
    return "".join(r["plain_text"] for r in val.get("title", []))


def fetch_all_gaso_pages(client, catalog_id):
    pages, cursor = [], None
    while True:
        resp = gaso.call_retry(
            client.data_sources.query, data_source_id=catalog_id, page_size=100,
            start_cursor=cursor,
            filter={"property": "Место хранения", "rich_text": {"contains": "Смоленск"}},
        )
        pages.extend(resp["results"])
        cursor = resp.get("next_cursor")
        if not resp.get("has_more") or not cursor:
            break
        time.sleep(0.34)
    return pages


def find_dupe_groups(pages):
    groups = collections.defaultdict(list)
    for p in pages:
        props = p["properties"]
        key = (get_text(props, "Фонд"), get_text(props, "Опись"),
               get_text(props, "Единица хранения"), get_text(props, "Название источника", "title"))
        groups[key].append(p)
    return {k: v for k, v in groups.items() if len(v) > 1}


def load_ledger() -> set:
    done = set()
    if LEDGER_PATH.exists():
        for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("status") == "ok":
                done.add(rec["page_id"])
    return done


def append_ledger(entry: dict):
    with LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    fix_stdout()
    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("dedupe_gaso")
    catalog_id = json.loads(gaso.SCHEMA_PATH.read_text(encoding="utf-8"))["data_source_id"]

    pages = fetch_all_gaso_pages(client, catalog_id)
    dupe_groups = find_dupe_groups(pages)
    print(f"Всего живых страниц: {len(pages)}, групп-дублей: {len(dupe_groups)}")

    to_reject = []
    for key, group in dupe_groups.items():
        group_sorted = sorted(group, key=lambda p: p["created_time"])
        keep, rejects = group_sorted[0], group_sorted[1:]
        for r in rejects:
            to_reject.append((r["id"], keep["id"], key))

    print(f"Страниц к отклонению: {len(to_reject)}")
    if args.dry_run:
        for pid, keep_id, key in to_reject:
            print(f"  {pid} -> дубль {keep_id} (ф{key[0]} оп{key[1]} д{key[2]})")
        return

    done = load_ledger()
    ok, failed, skipped = 0, 0, 0
    for pid, keep_id, key in to_reject:
        if pid in done:
            skipped += 1
            continue
        note = (f"Дубль — технический сбой импорта (процесс убит между созданием страницы и "
                f"записью в ledger, 16-17.10.2026). Оставлена https://app.notion.com/{keep_id.replace('-', '')}")
        try:
            page = gaso.call_retry(client.pages.retrieve, page_id=pid)
            existing_note = "".join(r["plain_text"] for r in page["properties"]["Примечания"]["rich_text"])
            merged = (existing_note + "\n" + note).strip() if existing_note else note
            gaso.call_retry(
                client.pages.update, page_id=pid,
                properties={
                    "Статус приёмки": {"select": {"name": "отклонено"}},
                    "Примечания": {"rich_text": [{"text": {"content": merged[:2000]}}]},
                },
            )
            append_ledger({"page_id": pid, "status": "ok", "keep": keep_id, "key": list(key)})
            ok += 1
        except Exception as exc:  # noqa: BLE001 -- логируем и продолжаем, резюмируемо через ledger
            append_ledger({"page_id": pid, "status": "fail", "error": str(exc)[:300]})
            failed += 1
            logger.info(f"FAIL {pid}: {exc}")
        time.sleep(0.34)

    print(f"Готово: ok={ok} failed={failed} skipped={skipped} из {len(to_reject)}")


if __name__ == "__main__":
    main()
