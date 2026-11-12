"""
Отклоняет 25 записей-чертежей фабричных построек/агрегатов (разрезы, фасады, планы
этажей), найденных территориальным гейтом 26.10.2026 (scripts_review/false_carto.py).

Правило подтверждено пользователем 26.10: архитектурная документация ОТДЕЛЬНОГО ЗДАНИЯ
или агрегата -- не территориальный источник (тот же принцип, что уже применён 21.10 к
комплексу Гостиного двора в Калуге, см. false_carto.py строки 56-62). Чертёж цеха/печи/
турбины/этажа описывает внутреннее устройство постройки, а не местность.

Список page_id -- output/group1_building_drawings_pids.txt (один на строку).
Помечает "Статус приёмки"="отклонено" с примечанием; физически не удаляет.

Запуск:
  python scripts/maintenance/reject_building_drawings.py --dry-run
  python scripts/maintenance/reject_building_drawings.py --apply
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
NOTE = ("Отклонено территориальным гейтом 26.10.2026: чертёж внутреннего устройства "
        "постройки/агрегата (разрез, фасад, план этажа) -- не территориальный источник, "
        "тот же принцип, что применён 21.10 к комплексу Гостиного двора (Калуга).")


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
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    fix_stdout()
    pids_path = Path("output/group1_building_drawings_pids.txt")
    pids = [p.strip() for p in pids_path.read_text(encoding="utf-8").splitlines() if p.strip()]
    print(f"К отклонению: {len(pids)}")

    if not args.apply:
        for p in pids:
            print(f"  {p}")
        print("\nПредпросмотр. Для записи в Notion запусти с --apply.")
        return

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("reject_building_drawings")
    ledger_path = Path("output/group1_building_drawings_ledger.jsonl")
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
            merged = (existing_note + "\n" + NOTE).strip() if existing_note else NOTE
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
