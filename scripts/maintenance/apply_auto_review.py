"""
Применяет решения из scripts/maintenance/auto_review_candidates.py (output/
auto_review_candidates_full.tsv): bucket=keep -> "Статус приёмки"="принято",
bucket=drop -> "отклонено" (с причиной в Примечания). bucket=review не трогается
(остаётся "кандидат" для человека).

Запуск:
  python scripts/maintenance/apply_auto_review.py output/auto_review_candidates_full.tsv --dry-run
  python scripts/maintenance/apply_auto_review.py output/auto_review_candidates_full.tsv --apply
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

ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
RETRIES = 6
SLEEP = 0.34


def call_retry(func, **kwargs):
    for attempt in range(RETRIES):
        try:
            return func(**kwargs)
        except Exception as exc:  # noqa: BLE001
            # "archived" -- постоянная ошибка (страница уже в корзине Notion), повтор
            # не поможет никогда; не жечь все RETRIES попыток с backoff на каждую.
            if "archived" in str(exc).lower() or attempt == RETRIES - 1:
                raise
            time.sleep(min(2**attempt, 30))
    raise RuntimeError("unreachable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tsv_path", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    fix_stdout()
    keep_pids, drop_rows = [], []
    with args.tsv_path.open(encoding="utf-8", newline="") as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            if row["bucket"] == "keep":
                keep_pids.append(row["page_id"])
            elif row["bucket"] == "drop":
                drop_rows.append((row["page_id"], row["reason"]))

    print(f"keep -> принято: {len(keep_pids)}")
    print(f"drop -> отклонено: {len(drop_rows)}")

    if not args.apply:
        print("Предпросмотр. Для записи в Notion запусти с --apply.")
        return

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("apply_auto_review")
    ledger_path = args.tsv_path.with_name(args.tsv_path.stem + "_apply_ledger.jsonl")
    done = set()
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("status") in ("ok", "already_archived"):
                    done.add(rec["page_id"])

    ok, failed, skipped, archived = 0, 0, 0, 0
    total = len(keep_pids) + len(drop_rows)

    for pid in keep_pids:
        if pid in done:
            skipped += 1
            continue
        try:
            call_retry(client.pages.update, page_id=pid,
                       properties={"Статус приёмки": {"select": {"name": "принято"}}})
            with ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page_id": pid, "status": "ok", "action": "keep"}, ensure_ascii=False) + "\n")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            if "archived" in str(exc).lower():
                with ledger_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"page_id": pid, "status": "already_archived"}, ensure_ascii=False) + "\n")
                archived += 1
                continue
            with ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page_id": pid, "status": "fail", "error": str(exc)[:300]}, ensure_ascii=False) + "\n")
            failed += 1
            logger.info(f"FAIL keep {pid}: {exc}")
        if (ok + failed) % 500 == 0:
            logger.info(f"{ok + failed}/{total} ok={ok} failed={failed}")
        time.sleep(SLEEP)

    note_tpl = "Отклонено автопроверкой кандидатов 27.10.2026 (run_review.decide, причина: {})."
    for pid, reason in drop_rows:
        if pid in done:
            skipped += 1
            continue
        try:
            page = call_retry(client.pages.retrieve, page_id=pid)
            existing_note = "".join(r["plain_text"] for r in page["properties"]["Примечания"]["rich_text"])
            note = note_tpl.format(reason)
            merged = (existing_note + "\n" + note).strip() if existing_note else note
            call_retry(
                client.pages.update, page_id=pid,
                properties={
                    "Статус приёмки": {"select": {"name": "отклонено"}},
                    "Примечания": {"rich_text": [{"text": {"content": merged[:2000]}}]},
                },
            )
            with ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page_id": pid, "status": "ok", "action": "drop"}, ensure_ascii=False) + "\n")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            if "archived" in str(exc).lower():
                with ledger_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"page_id": pid, "status": "already_archived"}, ensure_ascii=False) + "\n")
                archived += 1
                continue
            with ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page_id": pid, "status": "fail", "error": str(exc)[:300]}, ensure_ascii=False) + "\n")
            failed += 1
            logger.info(f"FAIL drop {pid}: {exc}")
        if (ok + failed) % 500 == 0:
            logger.info(f"{ok + failed}/{total} ok={ok} failed={failed}")
        time.sleep(SLEEP)

    print(f"\nГотово: ok={ok} уже_архивировано={archived} failed={failed} пропущено={skipped} из {total}")


if __name__ == "__main__":
    main()
