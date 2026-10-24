"""
Задним числом исправляет «Административный уровень» уже созданным страницам ГАСО —
баг найден спот-чеком 17.10.2026: функция `admin_level` (import_gaso_notion.py) проверяла
только поле `obyekt`, а у части фондов (ф.890 — оценочная комиссия) именованная общность
(«Кобызевского сельского общества») лежит ТОЛЬКО в `zagolovok`; плюс отсутствовала ветка
«Губерния» для явно губернских дел без уезда/волости. Функция исправлена, этот скрипт
применяет новый результат к уже созданным страницам (резюмируемо через ledger импорта,
page_id известен напрямую — повторный поиск по Notion не нужен).

Запуск:
  python scripts/fix_gaso_admin_level.py --dry-run
  python scripts/fix_gaso_admin_level.py
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
FIX_LEDGER = ROOT / "output" / "gaso_package_20261013" / "_notion_admin_level_fix_ledger.jsonl"
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
        new_level = gaso.admin_level(rec["obyekt"], rec["zagolovok"])
        to_fix.append((entry["page_id"], rec, new_level))

    print(f"Страниц для проверки: {len(to_fix)}")
    if args.dry_run:
        import collections
        print(collections.Counter(level for _, _, level in to_fix))
        for page_id, rec, level in to_fix[:3]:
            print(f"\n-- {page_id} ф{rec['fund']} оп{rec['opis']} д{rec['n_delo']} -> {level} --")
        return

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("fix_gaso_admin_level")
    done = load_fix_ledger()

    ok, failed, skipped, unchanged = 0, 0, 0, 0
    for i, (page_id, rec, new_level) in enumerate(to_fix, 1):
        if page_id in done:
            skipped += 1
            continue
        try:
            page = gaso.call_retry(client.pages.retrieve, page_id=page_id)
            current = page["properties"]["Административный уровень"]["select"]
            current_name = current["name"] if current else None
            if current_name == new_level:
                append_fix_ledger({"page_id": page_id, "status": "ok", "unchanged": True})
                unchanged += 1
                continue
            gaso.call_retry(
                client.pages.update, page_id=page_id,
                properties={"Административный уровень": {"select": {"name": new_level}}},
            )
            append_fix_ledger({"page_id": page_id, "status": "ok", "from": current_name, "to": new_level})
            ok += 1
        except Exception as exc:  # noqa: BLE001 -- логируем и продолжаем, резюмируемо через ledger
            append_fix_ledger({"page_id": page_id, "status": "fail", "error": str(exc)[:300]})
            failed += 1
            logger.info(f"FAIL {page_id}: {exc}")
        if i % 50 == 0:
            logger.info(f"{i}/{len(to_fix)} changed={ok} unchanged={unchanged} failed={failed}")
        time.sleep(0.34)

    print(f"\nГотово: изменено={ok} без изменений={unchanged} failed={failed} "
          f"пропущено(уже в ledger)={skipped} из {len(to_fix)}")


if __name__ == "__main__":
    main()
