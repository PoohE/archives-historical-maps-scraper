"""
Отклоняет технические дубли по всему каталогу (любой архив), найденные полным QA-прогоном
catalog_qa_report.py: группы с совпадающим локатором (Архив+Фонд+Опись+Единица хранения) И
полностью совпадающим заголовком — это настоящий технический дубль (см. чек-лист п.3 и
dedupe_gaso_notion.py), в отличие от «одно дело — много строк описи» (совпадает только
локатор, заголовки разные — такие группы сюда не попадают).

Источник дублей — тот же CSV, что для catalog_qa_report.py (полный экспорт каталога).
Группу, где один из экземпляров уже помечен "Статус приёмки"="отклонено", считает уже
решённой и пропускает. Для остальных ("открытых") групп запрашивает created_time каждой
страницы напрямую через client.pages.retrieve (НЕ через SQL Query Data Source — в обход
квоты MCP), оставляет самую раннюю, остальные помечает "отклонено" с примечанием и ссылкой
на оставленную — как в dedupe_gaso_notion.py. Физически не удаляет.

Запуск:
  python scripts/dedupe_true_duplicates.py output/notion_catalog_20261024_full.csv --dry-run
  python scripts/dedupe_true_duplicates.py output/notion_catalog_20261024_full.csv --apply
"""
import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import env, fix_stdout, load_env, log  # noqa: E402

from notion_client import Client  # noqa: E402

ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
RETRIES = 6


def call_retry(func, **kwargs):
    for attempt in range(RETRIES):
        try:
            return func(**kwargs)
        except Exception:  # noqa: BLE001 -- транспортные сбои httpx/VPN, не отказ операции
            if attempt == RETRIES - 1:
                raise
            time.sleep(min(2**attempt, 30))
    raise RuntimeError("unreachable")


def find_dupe_groups(csv_path: Path):
    """Та же логика, что catalog_qa_report.py: локатор+заголовок совпадают целиком."""
    locator_dupes = defaultdict(list)  # (archive, fond, opis, edhr) -> [(page_id, title, status), ...]
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            fond = (row.get("Фонд") or "").strip()
            opis = (row.get("Опись") or "").strip()
            edhr = (row.get("Единица хранения") or "").strip()
            if not (fond and opis and edhr):
                continue
            archive = (row.get("Архив хранения") or "").strip() or "(без архива)"
            pid = row.get("page_id", "")
            title = (row.get("Название источника") or "").strip()
            status = (row.get("Статус приёмки") or "").strip()
            locator_dupes[(archive, fond, opis, edhr)].append((pid, title, status))

    true_dupes = {}
    for key, items in locator_dupes.items():
        if len(items) < 2:
            continue
        titles = {t for _, t, _ in items}
        if len(titles) != 1:
            continue  # "одно дело - много строк описи", не дубль
        true_dupes[key] = items
    return true_dupes


def split_resolved(groups: dict):
    """Группа уже решена, если в ней есть хотя бы один 'отклонено' (значит её уже разобрали)."""
    open_groups, resolved_groups = {}, {}
    for key, items in groups.items():
        if any(status == "отклонено" for _, _, status in items):
            resolved_groups[key] = items
        else:
            open_groups[key] = items
    return open_groups, resolved_groups


def load_ledger(path: Path) -> set:
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("status") == "ok":
                done.add(rec["page_id"])
    return done


def append_ledger(path: Path, entry: dict):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--apply", action="store_true", help="реально писать в Notion (иначе предпросмотр)")
    args = parser.parse_args()

    fix_stdout()
    groups = find_dupe_groups(args.csv_path)
    open_groups, resolved_groups = split_resolved(groups)
    total_open_records = sum(len(v) for v in open_groups.values())
    print(f"Групп-дублей всего: {len(groups)} | уже решено: {len(resolved_groups)} | "
          f"ОТКРЫТЫХ: {len(open_groups)} групп, {total_open_records} записей")

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("dedupe_true_duplicates")

    # created_time -- точечно через pages.retrieve, не через SQL (обход квоты MCP)
    plan = []  # (reject_id, keep_id, key)
    for key, items in open_groups.items():
        fetched = []
        for pid, title, _status in items:
            page = call_retry(client.pages.retrieve, page_id=pid)
            fetched.append((pid, page["created_time"], title))
            time.sleep(0.34)
        fetched.sort(key=lambda x: x[1])
        keep_id = fetched[0][0]
        for pid, created, _title in fetched[1:]:
            plan.append((pid, keep_id, key))

    archive_counts = defaultdict(int)
    for _pid, _keep, key in plan:
        archive_counts[key[0]] += 1
    print(f"К отклонению: {len(plan)} записей")
    for archive, n in sorted(archive_counts.items(), key=lambda x: -x[1]):
        print(f"  {archive}: {n}")

    if not args.apply:
        for pid, keep_id, key in plan[:60]:
            print(f"  {pid} -> дубль {keep_id}  ({key[0]} ф{key[1]} оп{key[2]} д{key[3]})")
        if len(plan) > 60:
            print(f"  ... и ещё {len(plan) - 60}")
        print("\nПредпросмотр. Для записи в Notion запусти с --apply.")
        return

    ledger_path = args.csv_path.with_name(args.csv_path.stem + "_dedupe_ledger.jsonl")
    done = load_ledger(ledger_path)
    ok, failed, skipped = 0, 0, 0
    for pid, keep_id, key in plan:
        if pid in done:
            skipped += 1
            continue
        note = (f"Технический дубль по локатору и заголовку (Фонд {key[1]}, Опись {key[2]}, "
                f"Дело {key[3]}) — отклонено при сверке каталога 2026-10-25. Оставлена "
                f"https://app.notion.com/{keep_id.replace('-', '')}")
        try:
            page = call_retry(client.pages.retrieve, page_id=pid)
            existing_note = "".join(r["plain_text"] for r in page["properties"]["Примечания"]["rich_text"])
            merged = (existing_note + "\n" + note).strip() if existing_note else note
            call_retry(
                client.pages.update, page_id=pid,
                properties={
                    "Статус приёмки": {"select": {"name": "отклонено"}},
                    "Примечания": {"rich_text": [{"text": {"content": merged[:2000]}}]},
                },
            )
            append_ledger(ledger_path, {"page_id": pid, "status": "ok", "keep": keep_id, "key": list(key)})
            ok += 1
        except Exception as exc:  # noqa: BLE001 -- логируем и продолжаем, резюмируемо через ledger
            append_ledger(ledger_path, {"page_id": pid, "status": "fail", "error": str(exc)[:300]})
            failed += 1
            logger.info(f"FAIL {pid}: {exc}")
        if (ok + failed) % 20 == 0:
            logger.info(f"{ok + failed}/{len(plan)} ok={ok} failed={failed}")
        time.sleep(0.34)

    print(f"\nГотово: ok={ok} failed={failed} пропущено={skipped} из {len(plan)}")


if __name__ == "__main__":
    main()
