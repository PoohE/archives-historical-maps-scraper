"""
Массовое промоутирование РГВИА "кандидат" -> "принято" в каталоге Notion.

Контекст: 650-набор УИАД/РГВИА уже внесён в Notion (620 живых записей со ссылками
online.archives.ru), прошёл полный pre-import QA (ЧЕКПОЙНТ_РГВИА_импорт.md) и спот-проверку
(2х15 случайных записей, чисто). 1 истинный дубль (ф.417 оп.1 д.103) найден и отклонён
отдельно 16.10.2026. Остаётся перевести оставшиеся "кандидат" в "принято" — массовая
механическая операция. Сделана через notion_client (как import_rgvia_notion.py), а НЕ через
чат-инструмент Notion MCP: тот режет SQL на 100 строк/вызов и периодически упирается в лимит
"Query Data Source" (упирались дважды за сессию). Резюмируемо через ledger.

Запуск:
  python scripts_rosarchive/promote_rgvia_candidates_notion.py --dry-run   # только показать список
  python scripts_rosarchive/promote_rgvia_candidates_notion.py             # реальная запись
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import env, fix_stdout, load_env, log  # noqa: E402

from notion_client import Client  # noqa: E402

ROOT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
SCHEMA_PATH = ROOT / "scripts" / "modules" / "notion_schema.json"
ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
LEDGER_PATH = ROOT / "output" / "uiad_rgvia_maps_20261004" / "_notion_promote_ledger.jsonl"

FILTER = {"and": [
    {"property": "Статус приёмки", "select": {"equals": "кандидат"}},
    {"property": "Ссылка на онлайн-архив", "url": {"contains": "online.archives.ru"}},
]}

RETRIES = 6


def call_retry(fn, *a, **kw):
    """Повтор на разрыв соединения (WinError 10054 и т.п.) -- см. notion_catalog_export.py."""
    for attempt in range(RETRIES):
        try:
            return fn(*a, **kw)
        except Exception:  # noqa: BLE001 -- транспортные ошибки httpx разных классов
            if attempt == RETRIES - 1:
                raise
            time.sleep(min(2**attempt, 30))
    raise RuntimeError("unreachable")


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
        resp = call_retry(client.data_sources.query, data_source_id=catalog_id,
                           page_size=100, start_cursor=cursor, filter=FILTER)
        pages.extend(resp["results"])
        cursor = resp.get("next_cursor")
        if not resp.get("has_more") or not cursor:
            break
        time.sleep(0.34)
    return pages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="только показать найденные записи, не писать")
    args = parser.parse_args()

    fix_stdout()
    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("promote_rgvia")
    catalog_id = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["data_source_id"]

    pages = fetch_candidates(client, catalog_id)
    print(f"Найдено кандидатов РГВИА (online.archives.ru): {len(pages)}")

    if args.dry_run:
        for p in pages[:10]:
            title_prop = next((v for v in p["properties"].values() if v["type"] == "title"), None)
            title = "".join(r["plain_text"] for r in title_prop["title"]) if title_prop else ""
            print(" -", p["id"], title[:90])
        if len(pages) > 10:
            print(f" ... и ещё {len(pages) - 10}")
        return

    done = load_ledger()
    ok, failed, skipped = 0, 0, 0
    for i, page in enumerate(pages, 1):
        page_id = page["id"]
        if page_id in done:
            skipped += 1
            continue
        try:
            call_retry(client.pages.update, page_id=page_id,
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
