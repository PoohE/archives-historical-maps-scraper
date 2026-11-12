"""
Дозаполнение «Тип источника» для РГИА (4813 из 4819 записей архива пусты -- QA 25.10.2026).
Почти все записи идут из фонда 380 «Плановый архив Министерства земледелия» (описи 10/21/28/37/
38/39/41, ~4793 записи) и фонда 1293 «строительное отделение» (городские планы, ~12 записей) --
обе серии имеют СТРОГО регулярную схему заголовка, правило построено по ручному разбору образцов
(см. распределение по подтипам в сессии 25.10): никакой классификации моделью не нужно.

Справочник кодов -- "Типы источников" (collection://92034cc0-c3a9-42d9-ac69-d228aeb2efea),
полная таблица с описаниями затребована отдельно, здесь зашиты только нужные код->page_id.

Правило (ф.380):
  - заголовок содержит "(общегубернская карта)" -> это обзорная/тематическая карта ВСЕЙ губернии
    (опись 37, Ярославская губ.): тематическая (лес/промысел/почва/повинность/завод/фабрика/
    этнография в тексте) -> A5; иначе (отчётная карта съёмки, губернская карта, administrative
    overlay волости/округа) -> A1.
  - заголовок начинается с "Уездная карта" (без общегуб. тега) -> A2 (карта уезда).
  - иначе (дело про конкретную дачу/оброчную статью/крестьянские земли/пустошь -- индивидуальный
    земельный объект, любой фонд.опись из 380) -> A3 (крупномасштабный план дачи, любой объект).

Правило (городская серия -- ф.1293 и записи с утерянным локатором, тот же паттерн заголовка):
  - "план(ы) гор./план ... гор." -> A6; "карта ... уезда" -> A2; "карта ... губернии" -> A1;
    "уменьшенный план земель уездного гор." -> A6 (план территории города).

Прочее (не ф.380, либо не распознано правилом) -- НЕ трогается, остаётся needs_human
(их немного, см. предпросмотр).

Запуск:
  python scripts/maintenance/classify_rgia_f380_tip.py output/notion_catalog_20261024_full.csv --dry-run
  python scripts/maintenance/classify_rgia_f380_tip.py output/notion_catalog_20261024_full.csv --apply
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

# "Типы источников" (collection://92034cc0-c3a9-42d9-ac69-d228aeb2efea) -- код -> page_id
TIP_PAGE_ID = {
    "A1": "3830ba89eabe816da278cf6ce9cdeec6",
    "A2": "3830ba89eabe816e90d4eced7e4ce20f",
    "A3": "3830ba89eabe81e88960d51ab3be3447",
    "A5": "3830ba89eabe8180a87dd5d89c0de70d",
    "A6": "3830ba89eabe8171ac4aee07e78f3a7e",
}

THEMATIC_MARKERS = ("лес", "промысл", "почв", "повинност", "завод", "фабрик", "этнографич")


def classify_f380(title: str) -> str | None:
    if "(общегубернская карта)" in title:
        low = title.lower()
        return "A5" if any(m in low for m in THEMATIC_MARKERS) else "A1"
    if title.strip().startswith("Уездная карта"):
        return "A2"
    return "A3"


def classify_city_series(title: str) -> str | None:
    """Серия городских планов/карт (ф.1293 и записи с утерянным локатором, тот же паттерн
    заголовка «Губерния. План(ы) гор. X» / «Карта X уезда/губернии») -- по тексту заголовка,
    независимо от значения поля «Фонд» (пустой фонд -- отдельная известная проблема, п.3
    очереди QA, здесь не чиним, только классифицируем тип)."""
    low = title.lower()
    if "план" in low and "гор." in low:
        return "A6"
    if "уменьшенный план земель уездного гор" in low:
        return "A6"
    if re.search(r"карта .*уезда", low):
        return "A2"
    if re.search(r"карта .*губерни", low):
        return "A1"
    return None


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
            if (row.get("Архив хранения") or "").strip() != "Российский государственный исторический архив (РГИА)":
                continue
            if (row.get("Тип источника") or "").strip():
                continue
            fond = (row.get("Фонд") or "").strip()
            title = row.get("Название источника") or ""
            code = classify_f380(title) if fond == "380" else classify_city_series(title)
            if code:
                plan.append((row.get("page_id", ""), code, title))
            else:
                unresolved.append((row.get("page_id", ""), fond, title))
    return plan, unresolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    fix_stdout()
    plan, unresolved = build_plan(args.csv_path)

    from collections import Counter
    by_code = Counter(code for _pid, code, _t in plan)
    print(f"К заполнению: {len(plan)}")
    for code, n in by_code.most_common():
        print(f"  {code}: {n}")
    print(f"\nНе распознано правилом (needs_human, не трогается): {len(unresolved)}")
    for pid, fond, title in unresolved[:20]:
        print(f"  ф.{fond}  {title[:90]!r}")

    if not args.apply:
        print("\nПредпросмотр. Для записи в Notion запусти с --apply.")
        return

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("classify_rgia_f380_tip")
    ledger_path = args.csv_path.with_name(args.csv_path.stem + "_rgia_tip_ledger.jsonl")
    done = set()
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("status") == "ok":
                    done.add(rec["page_id"])

    ok, failed, skipped = 0, 0, 0
    for pid, code, _title in plan:
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
