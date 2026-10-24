"""
Задним числом добавляет «Ссылка на онлайн-архив» (+ примечание) уже созданным страницам
ГАСО — баг обнаружен пользователем 16.10.2026: первая версия import_gaso_notion.py заводила
записи вовсе без ссылки, хотя для 22 из 23 пар фонд+опись (кроме ф.814, его опись получена
архивом по прямому запросу) она есть в манифесте сбора (`OPIS_MANIFEST.page_url`).

Источник правок — ledger уже сделанного импорта (`_notion_import_ledger.jsonl`, статус "ok"):
для каждой записи знаем её `page_id` напрямую, повторный поиск по Notion не нужен.
Резюмируемо через отдельный `_notion_url_fix_ledger.jsonl`.

Запуск:
  python scripts/fix_gaso_missing_urls.py --dry-run
  python scripts/fix_gaso_missing_urls.py
"""
import argparse
import csv
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
SOURCE_CSV = gaso.SOURCE_CSV
IMPORT_LEDGER = gaso.LEDGER_PATH
FIX_LEDGER = ROOT / "output" / "gaso_package_20261013" / "_notion_url_fix_ledger.jsonl"
ENV_PATH = gaso.ENV_PATH


def load_source_by_key():
    with SOURCE_CSV.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return {(r["fund"], r["opis"], r["n_delo"], r.get("page", "")): r for r in rows}


def load_import_ledger_ok():
    out = []
    for line in IMPORT_LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("status") == "ok":
            out.append(rec)
    return out


def load_fix_ledger() -> set:
    done = set()
    if FIX_LEDGER.exists():
        for line in FIX_LEDGER.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("status") == "ok":
                done.add(rec["page_id"])
    return done


def append_fix_ledger(entry: dict):
    with FIX_LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    fix_stdout()
    by_key = load_source_by_key()
    ledger_entries = load_import_ledger_ok()

    to_fix = []
    for entry in ledger_entries:
        fund, opis, n_delo, page = entry["key"]
        rec = by_key.get((fund, opis, n_delo, page))
        if rec is None:
            continue
        opis_url = gaso.OPIS_URLS.get((fund, opis))
        if not opis_url and fund != "814":
            continue  # нечего добавлять
        to_fix.append((entry["page_id"], rec, opis_url))

    print(f"Страниц требует правки: {len(to_fix)} из {len(ledger_entries)} в ledger импорта")
    if args.dry_run:
        for page_id, rec, opis_url in to_fix[:3]:
            print(f"\n-- {page_id} ф{rec['fund']} оп{rec['opis']} д{rec['n_delo']} --")
            print("  url:", opis_url)
        return

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("fix_gaso_urls")
    done = load_fix_ledger()

    ok, failed, skipped = 0, 0, 0
    for i, (page_id, rec, opis_url) in enumerate(to_fix, 1):
        if page_id in done:
            skipped += 1
            continue
        props = {}
        if opis_url:
            props["Ссылка на онлайн-архив"] = {"url": opis_url}
        note = ("Ссылка — на опись фонда (карточки дел портал не публикует), не на дело"
                if opis_url else "Опись получена архивом по прямому запросу, страницы портала нет")
        try:
            page = gaso.call_retry(client.pages.retrieve, page_id=page_id)
            existing_note = "".join(
                r["plain_text"] for r in page["properties"]["Примечания"]["rich_text"]
            )
            if note not in existing_note:
                merged = (existing_note + "\n" + note).strip() if existing_note else note
                props["Примечания"] = {"rich_text": [{"text": {"content": merged[:2000]}}]}
            gaso.call_retry(client.pages.update, page_id=page_id, properties=props)
            append_fix_ledger({"page_id": page_id, "status": "ok"})
            ok += 1
        except Exception as exc:  # noqa: BLE001 -- логируем и продолжаем, резюмируемо через ledger
            append_fix_ledger({"page_id": page_id, "status": "fail", "error": str(exc)[:300]})
            failed += 1
            logger.info(f"FAIL {page_id}: {exc}")
        if i % 50 == 0:
            logger.info(f"{i}/{len(to_fix)} ok={ok} failed={failed} skipped={skipped}")
        time.sleep(0.34)

    print(f"Готово: ok={ok} failed={failed} skipped={skipped} из {len(to_fix)}")


if __name__ == "__main__":
    main()
