"""
Отклоняет записи по списку page_id (территориальный гейт, сверка каталога 26.10.2026).
Общий инструмент для всех найденных групп -- не писать отдельный скрипт под каждую.

Помечает "Статус приёмки"="отклонено" с примечанием; физически не удаляет.

Запуск:
  python scripts/maintenance/reject_by_pid_list.py <pids.txt> "<текст примечания>" --dry-run
  python scripts/maintenance/reject_by_pid_list.py <pids.txt> "<текст примечания>" --apply
"""
import argparse
import json
import sys
import time
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
        except Exception:  # noqa: BLE001
            if attempt == RETRIES - 1:
                raise
            time.sleep(min(2**attempt, 30))
    raise RuntimeError("unreachable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pids_path", type=Path)
    parser.add_argument("note", type=str)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    fix_stdout()
    pids = [p.strip() for p in args.pids_path.read_text(encoding="utf-8").splitlines() if p.strip()]
    print(f"К отклонению: {len(pids)}")

    if not args.apply:
        for p in pids:
            print(f"  {p}")
        print("\nПредпросмотр. Для записи в Notion запусти с --apply.")
        return

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("reject_by_pid_list")
    ledger_path = args.pids_path.with_name(args.pids_path.stem + "_ledger.jsonl")
    done = set()
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("status") == "ok":
                    done.add(rec["page_id"])

    ok, failed, skipped = 0, 0, 0
    for pid in pids:
        if pid in done:
            skipped += 1
            continue
        try:
            page = call_retry(client.pages.retrieve, page_id=pid)
            existing_note = "".join(r["plain_text"] for r in page["properties"]["Примечания"]["rich_text"])
            merged = (existing_note + "\n" + args.note).strip() if existing_note else args.note
            call_retry(
                client.pages.update, page_id=pid,
                properties={
                    "Статус приёмки": {"select": {"name": "отклонено"}},
                    "Примечания": {"rich_text": [{"text": {"content": merged[:2000]}}]},
                },
            )
            with ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page_id": pid, "status": "ok"}, ensure_ascii=False) + "\n")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            with ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page_id": pid, "status": "fail", "error": str(exc)[:300]}, ensure_ascii=False) + "\n")
            failed += 1
            logger.info(f"FAIL {pid}: {exc}")
        time.sleep(0.34)

    print(f"\nГотово: ok={ok} failed={failed} пропущено={skipped} из {len(pids)}")


if __name__ == "__main__":
    main()
