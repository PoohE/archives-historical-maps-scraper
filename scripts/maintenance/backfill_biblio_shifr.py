"""
Дозаполнение «Библиотечный шифр» для записей без локатора (QA 26.10.2026): 2859 записей
без фонд/опись/дело И без библиотечного шифра -- почти все из музейных/библиотечных
источников, где при импорте каталожный номер остался только в «Примечания» (или в URL),
не был вынесен в «Библиотечный шифр».

Правило по архиву (проверено на выборке, покрытие see --dry-run):
  Госкаталог.РФ   -- "предмет id (\\d+)" в Примечаниях   -> "Госкаталог.РФ, предмет № {}"
  ПБ              -- "item_id (\\d+)" в Примечаниях      -> "ПБ, item {}"
  СОУНБ           -- "№\\s*(\\d+)" в Примечаниях          -> "СОУНБ, № {}"
  Картфонд РГО    -- "запись (\\d+)" в Примечаниях        -> "Картфонд РГО, запись {}"
  ГПИБ            -- "node_id (\\d+)" в Примечаниях, иначе "/nodes/(\\d+)" в ссылке
                     -> "ГПИБ, node {}"

Пишет ТОЛЬКО пустой «Библиотечный шифр» (не перетирает заполненный, не трогает записи
с уже заполненным фонд/опись/дело). Записи без распознанного id (needs_human) не трогаются.

Запуск:
  python scripts/maintenance/backfill_biblio_shifr.py output/notion_catalog_20261024_full.csv --dry-run
  python scripts/maintenance/backfill_biblio_shifr.py output/notion_catalog_20261024_full.csv --apply
"""
import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import env, fix_stdout, load_env, log  # noqa: E402

from notion_client import Client  # noqa: E402

ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
RETRIES = 6

RULES = {
    "Госкаталог.РФ (Государственный каталог Музейного фонда РФ) (Госкаталог.РФ)":
        (re.compile(r"предмет id (\d+)"), "Госкаталог.РФ, предмет № {}"),
    "Президентская библиотека имени Б.Н. Ельцина (ПБ)":
        (re.compile(r"item_id (\d+)"), "ПБ, item {}"),
    "Смоленская областная универсальная научная библиотека им. А.Т. Твардовского (СОУНБ)":
        (re.compile(r"№\s*(\d+)"), "СОУНБ, № {}"),
    "Картографический фонд Русского географического общества (Картфонд РГО)":
        (re.compile(r"запись (\d+)"), "Картфонд РГО, запись {}"),
}
GPIB = "Государственная публичная историческая библиотека России (ГПИБ)"
GPIB_NOTE_PAT = re.compile(r"node_id (\d+)")
GPIB_URL_PAT = re.compile(r"/nodes/(\d+)")


def call_retry(func, **kwargs):
    for attempt in range(RETRIES):
        try:
            return func(**kwargs)
        except Exception:  # noqa: BLE001
            if attempt == RETRIES - 1:
                raise
            time.sleep(min(2**attempt, 30))
    raise RuntimeError("unreachable")


def build_plan(csv_path: Path):
    plan, unresolved = [], []
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("Фонд") or row.get("Опись") or row.get("Единица хранения") or row.get("Библиотечный шифр"):
                continue
            arc = (row.get("Архив хранения") or "").strip()
            notes = row.get("Примечания", "") or ""
            pid = row.get("page_id", "")
            value = None
            if arc in RULES:
                pat, template = RULES[arc]
                m = pat.search(notes)
                if m:
                    value = template.format(m.group(1))
            elif arc == GPIB:
                m = GPIB_NOTE_PAT.search(notes) or GPIB_URL_PAT.search(row.get("Ссылка на онлайн-архив", "") or "")
                if m:
                    value = f"ГПИБ, node {m.group(1)}"
            if value:
                plan.append((pid, value, arc))
            elif arc in RULES or arc == GPIB:
                unresolved.append((pid, arc))
    return plan, unresolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    fix_stdout()
    plan, unresolved = build_plan(args.csv_path)
    from collections import Counter
    by_arc = Counter(arc for _p, _v, arc in plan)
    print(f"К заполнению: {len(plan)}")
    for arc, n in by_arc.most_common():
        print(f"  {arc}: {n}")
    print(f"\nНе распознано (needs_human): {len(unresolved)}")
    for pid, arc in unresolved[:10]:
        print(f"  {pid}  {arc}")

    if not args.apply:
        print("\nПредпросмотр. Для записи в Notion запусти с --apply.")
        return

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("backfill_biblio_shifr")
    ledger_path = args.csv_path.with_name(args.csv_path.stem + "_biblio_ledger.jsonl")
    done = set()
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("status") == "ok":
                    done.add(rec["page_id"])

    ok, failed, skipped = 0, 0, 0
    for pid, value, _arc in plan:
        if pid in done:
            skipped += 1
            continue
        try:
            call_retry(client.pages.update, page_id=pid,
                       properties={"Библиотечный шифр": {"rich_text": [{"text": {"content": value}}]}})
            with ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page_id": pid, "status": "ok"}, ensure_ascii=False) + "\n")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            with ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page_id": pid, "status": "fail", "error": str(exc)[:300]}, ensure_ascii=False) + "\n")
            failed += 1
            logger.info(f"FAIL {pid}: {exc}")
        if (ok + failed) % 200 == 0:
            logger.info(f"{ok + failed}/{len(plan)} ok={ok} failed={failed}")
        time.sleep(0.34)

    print(f"\nГотово: ok={ok} failed={failed} пропущено={skipped} из {len(plan)}")


if __name__ == "__main__":
    main()
