"""
Унифицирует опечатку статуса приёмки: "отклонён" -> "отклонено" (QA 27.10.2026, найдено
1627 записей). Оба значения существовали как отдельные опции select-поля "Статус приёмки" --
из-за этого скрипты, фильтрующие по точной строке "отклонено", не исключали эти 1627 уже
отклонённых записей из анализа (ложный шум во всех сегодняшних QA-прогонах).

Запуск:
  python scripts/maintenance/normalize_status_typo.py <pids.txt> --dry-run
  python scripts/maintenance/normalize_status_typo.py <pids.txt> --apply
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
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    fix_stdout()
    pids = [p.strip() for p in args.pids_path.read_text(encoding="utf-8").splitlines() if p.strip()]
    print(f"К нормализации: {len(pids)}")
    if not args.apply:
        print("Предпросмотр. Для записи в Notion запусти с --apply.")
        return

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("normalize_status_typo")
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
            call_retry(client.pages.update, page_id=pid,
                       properties={"Статус приёмки": {"select": {"name": "отклонено"}}})
            with ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page_id": pid, "status": "ok"}, ensure_ascii=False) + "\n")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            with ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page_id": pid, "status": "fail", "error": str(exc)[:300]}, ensure_ascii=False) + "\n")
            failed += 1
            logger.info(f"FAIL {pid}: {exc}")
        if (ok + failed) % 200 == 0:
            logger.info(f"{ok + failed}/{len(pids)} ok={ok} failed={failed}")
        time.sleep(0.34)

    print(f"\nГотово: ok={ok} failed={failed} пропущено={skipped} из {len(pids)}")


if __name__ == "__main__":
    main()
