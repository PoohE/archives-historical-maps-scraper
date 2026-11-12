"""
Дозаполнение «Язык» и «Описание» по всему каталогу (QA 25-26.10.2026): 3177 записей без
Языка, 3262 без Описания (при наличии «Название источника»), сосредоточены в мелких
библиотечных/музейных источниках (Госкаталог.РФ, ПБ, ГПИБ, РГБ, Картфонд РГО, ГАКО и др.) --
туда не попадает отдельное поле описания при импорте, только заголовок карточки.

Правило (проверено на всех 3177 случаях -- 48 с латиницей в заголовке перепроверены вручную,
все ложные срабатывания: римские цифры веков, item-номера, имена граверов):
  - "Язык" пуст -> "Русский" (весь корпус русский; иностранных по содержанию не найдено).
  - "Описание" пуст, "Название источника" не пусто -> "Описание" = "Название источника"
    (тот же паттерн, что уже сложился у хорошо заполненных архивов типа РГИА, где при
    отсутствии отдельной карточки Описание дословно повторяет заголовок).

Пишет ТОЛЬКО пустые поля (не перетирает заполненные).

Запуск:
  python scripts/maintenance/backfill_lang_description.py output/notion_catalog_20261024_full.csv --dry-run
  python scripts/maintenance/backfill_lang_description.py output/notion_catalog_20261024_full.csv --apply
"""
import argparse
import csv
import json
import sys
import time
from collections import Counter
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


def build_plan(csv_path: Path):
    plan = []  # (page_id, {"Язык": bool, "Описание": bool}, title, archive)
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            title = (row.get("Название источника") or "").strip()
            need_lang = not (row.get("Язык") or "").strip()
            need_desc = not (row.get("Описание") or "").strip() and bool(title)
            if need_lang or need_desc:
                plan.append((row.get("page_id", ""), need_lang, need_desc, title,
                             (row.get("Архив хранения") or "").strip() or "(без архива)"))
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    fix_stdout()
    plan = build_plan(args.csv_path)
    by_archive = Counter(arc for _p, _l, _d, _t, arc in plan)
    lang_n = sum(1 for _p, lg, _d, _t, _a in plan if lg)
    desc_n = sum(1 for _p, _l, ds, _t, _a in plan if ds)
    print(f"Записей к правке: {len(plan)} (Язык: {lang_n}, Описание: {desc_n})")
    for arc, n in by_archive.most_common(15):
        print(f"  {arc}: {n}")

    if not args.apply:
        print("\nПредпросмотр. Для записи в Notion запусти с --apply.")
        return

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("backfill_lang_description")
    ledger_path = args.csv_path.with_name(args.csv_path.stem + "_lang_desc_ledger.jsonl")
    done = set()
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("status") == "ok":
                    done.add(rec["page_id"])

    ok, failed, skipped = 0, 0, 0
    for pid, need_lang, need_desc, title, _arc in plan:
        if pid in done:
            skipped += 1
            continue
        props = {}
        if need_lang:
            props["Язык"] = {"select": {"name": "Русский"}}
        if need_desc:
            props["Описание"] = {"rich_text": [{"text": {"content": title[:2000]}}]}
        try:
            call_retry(client.pages.update, page_id=pid, properties=props)
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
