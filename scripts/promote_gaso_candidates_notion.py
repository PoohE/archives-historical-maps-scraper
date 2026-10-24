"""
Массовое промоутирование ГАСО "кандидат" -> "принято" в каталоге Notion.

Контекст: пакет 5321 запись залит 17.10.2026 (import_gaso_notion.py), прошёл спот-чек
(два раунда, включая целевую проверку ф.890 после фикса «сельское общество»/«Губерния»
в admin_level — см. fix_gaso_admin_level.py). Ссылки на описи добавлены (fix_gaso_missing_urls.py).

Запуск:
  python scripts/promote_gaso_candidates_notion.py --dry-run
  python scripts/promote_gaso_candidates_notion.py
"""
import argparse
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
LEDGER_PATH = ROOT / "output" / "gaso_package_20261013" / "_notion_promote_ledger.jsonl"

FILTER = {"and": [
    {"property": "Статус приёмки", "select": {"equals": "кандидат"}},
    {"property": "Место хранения", "rich_text": {"contains": "Смоленск"}},
]}


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


def fetch_candidates(client, catalog_id):
    pages, cursor = [], None
    while True:
        resp = gaso.call_retry(client.data_sources.query, data_source_id=catalog_id,
                                page_size=100, start_cursor=cursor, filter=FILTER)
        pages.extend(resp["results"])
        cursor = resp.get("next_cursor")
        if not resp.get("has_more") or not cursor:
            break
        time.sleep(0.34)
    return pages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    fix_stdout()
    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("promote_gaso")
    catalog_id = json.loads(gaso.SCHEMA_PATH.read_text(encoding="utf-8"))["data_source_id"]

    pages = fetch_candidates(client, catalog_id)
    print(f"Найдено кандидатов ГАСО: {len(pages)}")
    if args.dry_run:
        for p in pages[:5]:
            title_prop = next((v for v in p["properties"].values() if v["type"] == "title"), None)
            title = "".join(r["plain_text"] for r in title_prop["title"]) if title_prop else ""
            print(" -", p["id"], title[:90])
        return

    done = load_ledger()
    ok, failed, skipped = 0, 0, 0
    for i, page in enumerate(pages, 1):
        page_id = page["id"]
        if page_id in done:
            skipped += 1
            continue
        try:
            gaso.call_retry(client.pages.update, page_id=page_id,
                             properties={"Статус приёмки": {"select": {"name": "принято"}}})
            append_ledger({"page_id": page_id, "status": "ok"})
            ok += 1
        except Exception as exc:  # noqa: BLE001 -- логируем и продолжаем, резюмируемо через ledger
            append_ledger({"page_id": page_id, "status": "fail", "error": str(exc)[:300]})
            failed += 1
            logger.info(f"FAIL {page_id}: {exc}")
        if i % 50 == 0:
            logger.info(f"{i}/{len(pages)} ok={ok} failed={failed} skipped={skipped}")
        time.sleep(0.34)

    print(f"Готово: ok={ok} failed={failed} skipped={skipped} из {len(pages)}")


if __name__ == "__main__":
    main()
