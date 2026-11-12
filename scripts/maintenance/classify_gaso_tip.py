"""
Дозаполнение «Тип источника» для ГАСО (5327 записей, QA 25.10.2026) -- правило по фонду,
подтверждённое ручным разбором заголовков каждого фонда (см. сессию 25.10):

  ф.814 (межевые книги Генерального межевания), ф.1027 (геодезические/полевые журналы
  землемеров), ф.576 (переписка с Межевой канцелярией), ф.666/998 (переписка/отчёты о
  работе топографов/межевщиков), ф.88 (переписка о размежевании + копии уставных грамот)
    -> B8 "Текстовое сопровождение межевания: границы, смежества, промеры"

  ф.890 (оценочные таблицы по оценке земель), ф.1071 (оценочные таблицы земельных угодий)
    -> B6 "Текстовые описания дач: владельцы, угодья, число душ, качество земель"

  ф.828 (журнал ревизии лесной дачи + ведомости культур -- тематический лесной отчёт)
    -> B10 "Текстовые тематические описания и отчёты (... лесные...)"

  ф.237/428/458/560/87/562/495/523/1073/334/89/1173/1191 (дела землеустроительных комиссий
  о разверстании надельных земель на хутора/отруба, столыпинская реформа 1906-1917)
    -> B11 "Делопроизводство землеустроительных комиссий" (НОВЫЙ код, заведён 25.10.2026
    в collection://92034cc0-c3a9-42d9-ac69-d228aeb2efea после проверки по архивным
    описям ГАТО/ГАПК и генеалогическим источникам -- тип подтверждён в историографии).

Остальные фонды (не из списка выше) -- НЕ трогаются, остаются needs_human.

Запуск:
  python scripts/maintenance/classify_gaso_tip.py output/notion_catalog_20261024_full.csv --dry-run
  python scripts/maintenance/classify_gaso_tip.py output/notion_catalog_20261024_full.csv --apply
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

TIP_PAGE_ID = {
    "B6": "3c30ba89eabe8161b533c149b6f12aa8",
    "B8": "3c30ba89eabe8156867dd8a6f3cec753",
    "B10": "3c30ba89eabe81019c97e344090c601a",
    "B11": "4040ba89eabe8145b8f0ce456aa99298",
}

FUND_TO_CODE = {
    "814": "B8", "1027": "B8", "576": "B8", "666": "B8", "998": "B8", "88": "B8",
    "890": "B6", "1071": "B6",
    "828": "B10",
    "237": "B11", "428": "B11", "458": "B11", "560": "B11", "87": "B11", "562": "B11",
    "495": "B11", "523": "B11", "1073": "B11", "334": "B11", "89": "B11", "1173": "B11",
    "1191": "B11",
}


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
            if (row.get("Архив хранения") or "").strip() != "Государственный архив Смоленской области (ГАСО)":
                continue
            if (row.get("Тип источника") or "").strip():
                continue
            fond = (row.get("Фонд") or "").strip()
            code = FUND_TO_CODE.get(fond)
            if code:
                plan.append((row.get("page_id", ""), code, fond))
            else:
                unresolved.append((row.get("page_id", ""), fond, row.get("Название источника", "")))
    return plan, unresolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    fix_stdout()
    plan, unresolved = build_plan(args.csv_path)

    by_code = Counter(code for _pid, code, _fond in plan)
    print(f"К заполнению: {len(plan)}")
    for code, n in by_code.most_common():
        print(f"  {code}: {n}")
    print(f"\nНе распознано (фонд не в списке, needs_human): {len(unresolved)}")
    for pid, fond, title in unresolved[:20]:
        print(f"  ф.{fond}  {title[:90]!r}")

    if not args.apply:
        print("\nПредпросмотр. Для записи в Notion запусти с --apply.")
        return

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("classify_gaso_tip")
    ledger_path = args.csv_path.with_name(args.csv_path.stem + "_gaso_tip_ledger.jsonl")
    done = set()
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("status") == "ok":
                    done.add(rec["page_id"])

    ok, failed, skipped = 0, 0, 0
    for pid, code, _fond in plan:
        if pid in done:
            skipped += 1
            continue
        try:
            call_retry(client.pages.update, page_id=pid,
                       properties={"Тип источника": {"relation": [{"id": TIP_PAGE_ID[code]}]}})
            with ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page_id": pid, "status": "ok", "code": code}, ensure_ascii=False) + "\n")
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
