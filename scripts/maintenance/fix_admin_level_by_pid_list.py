"""
Правит «Административный уровень» по списку page_id -- Губерния-фолбэк у ПБ (QA 26.10.2026):
101 запись с заголовком «План гор. X»/«План части города X» имела уровень «Губерния»,
хотя заголовок явно называет конкретный населённый пункт.

Запуск:
  python scripts/maintenance/fix_admin_level_by_pid_list.py <pids.txt> "<новый уровень>" --dry-run
  python scripts/maintenance/fix_admin_level_by_pid_list.py <pids.txt> "<новый уровень>" --apply
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
    parser.add_argument("level", type=str)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    fix_stdout()
    pids = [p.strip() for p in args.pids_path.read_text(encoding="utf-8").splitlines() if p.strip()]
    print(f"К правке на {args.level!r}: {len(pids)}")

    if not args.apply:
        print("\nПредпросмотр. Для записи в Notion запусти с --apply.")
        return

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("fix_admin_level")
    ledger_path = args.pids_path.with_name(args.pids_path.stem + "_admin_level_ledger.jsonl")
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
    for pid in pids:
        if pid in done:
            skipped += 1
            continue
        try:
            call_retry(client.pages.update, page_id=pid,
                       properties={"Административный уровень": {"select": {"name": args.level}}})
            with ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page_id": pid, "status": "ok"}, ensure_ascii=False) + "\n")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            # "archived" -- запись уже отклонена/архивирована ранее (территориальный/
            # семантический гейт); правка уровня для неё неприменима и никогда не станет
            # "ok" -- считаем целью достигнутой (запись уже вне каталога), не повторяем вечно.
            if "archived" in str(exc).lower():
                with ledger_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"page_id": pid, "status": "already_archived"}, ensure_ascii=False) + "\n")
                archived += 1
                continue
            with ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page_id": pid, "status": "fail", "error": str(exc)[:300]}, ensure_ascii=False) + "\n")
            failed += 1
            logger.info(f"FAIL {pid}: {exc}")
        time.sleep(0.34)

    print(f"\nГотово: ok={ok} уже_архивировано={archived} failed={failed} пропущено={skipped} из {len(pids)}")


if __name__ == "__main__":
    main()
