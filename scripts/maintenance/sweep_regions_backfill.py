"""
Дозаполнение «Современные регионы» для записей каталога, где поле пусто, но территория
известна (из «Охватываемая территория» и/или заголовка) — найдено QA-прогоном 25.10.2026:
8115 записей без региона по всему каталогу (РГИА 4813, Госкаталог.РФ 2084, ПБ 414, ГПИБ 229,
РГБ 119, ГАКО/ГАРФ/СОУНБ/КОНБ/др. меньше). Логика — общий модуль `modules/territory_resolve.py`
(тот же, что встроен в мост `notion_upload_candidates.py` для НОВЫХ заливок): по тексту
«Охватываемая территория» (сырые названия губерний/уездов из CSV-экспорта, надёжнее парсинга
заголовка) + фолбэк по стему в названии.

⚠️ Старый `sweep_territory.py` указывал на database_id каталога из ДО миграции схемы
(`5ead971c-...`, не совпадает с текущим `data_source_id` в notion_schema.json) — не запускать
его повторно без проверки; этот скрипт берёт id из notion_schema.json и источник записей —
уже выгруженный CSV (не повторный обход всех 114 тыс. записей через API).

Пишет ТОЛЬКО пустое поле «Современные регионы» (не трогает заполненное, не трогает другие поля).

Запуск:
  python scripts/maintenance/sweep_regions_backfill.py output/notion_catalog_20261024_full.csv --dry-run
  python scripts/maintenance/sweep_regions_backfill.py output/notion_catalog_20261024_full.csv --apply
"""
import argparse
import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "modules"))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
import territory_resolve as tr  # noqa: E402
from common import env, fix_stdout, load_env, log  # noqa: E402

from notion_client import Client  # noqa: E402

ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
SCHEMA_PATH = HERE / "modules" / "notion_schema.json"
TERR_DB_ID = "3920ba89-eabe-81a2-86a2-d50d1bfee1c0"
REG_DB_ID = "6c6a3cfb-8d87-491e-8ce6-da7194bc857b"
RETRIES = 6


def call_retry(func, **kwargs):
    for attempt in range(RETRIES):
        try:
            return func(**kwargs)
        except Exception:  # noqa: BLE001 -- транспортные сбои httpx/VPN
            if attempt == RETRIES - 1:
                raise
            time.sleep(min(2**attempt, 30))
    raise RuntimeError("unreachable")


def make_legacy_api(token: str):
    """Справочники территорий/регионов -- старой REST-версией API (2022-06-28), как в
    notion_upload_candidates.py: именно под эту версию существует эндпойнт /databases/{id}/query
    (в текущей версии API он заменён на /data_sources, а TERR_DB_ID/REG_DB_ID -- database_id)."""
    headers = {"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28",
               "Content-Type": "application/json"}

    def api(method, url, data=None):
        for attempt in range(RETRIES):
            try:
                rq = urllib.request.Request(
                    url, data=json.dumps(data).encode() if data else None,
                    headers=headers, method=method)
                with urllib.request.urlopen(rq, timeout=40) as resp:
                    return json.load(resp)
            except Exception:  # noqa: BLE001
                if attempt == RETRIES - 1:
                    raise
                time.sleep(min(2**attempt, 30))
    return api


def load_candidates(csv_path: Path):
    """Строки с пустым «Современные регионы», но непустым заголовком -- кандидаты на дозаполнение."""
    rows = []
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("Современные регионы") or "").strip():
                continue
            title = (row.get("Название источника") or "").strip()
            if not title:
                continue
            rows.append({
                "page_id": row.get("page_id", ""),
                "title": title,
                "url": (row.get("Ссылка на онлайн-архив") or "").strip(),
                "territory_hint": (row.get("Охватываемая территория") or "").strip(),
                "archive": (row.get("Архив хранения") or "").strip(),
            })
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    fix_stdout()
    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("sweep_regions_backfill")

    token = env("NOTION_TOKEN", required=True)
    terr_stem_index, terr_gub, reg_index = tr.load_indexes(make_legacy_api(token), TERR_DB_ID, REG_DB_ID)
    print(f"справочники: территорий {len(terr_stem_index)}, регионов {len(reg_index)}")

    candidates = load_candidates(args.csv_path)
    print(f"Кандидатов (пустые «Современные регионы», заголовок есть): {len(candidates)}")

    plan = []  # (page_id, [region_ids], archive)
    unresolved_by_archive: dict[str, int] = {}
    for c in candidates:
        hints = [h.strip() for h in c["territory_hint"].split(";") if h.strip()]
        _terr_ids, reg_ids = tr.resolve(c["title"], c["url"], terr_stem_index, terr_gub, reg_index, hints=hints)
        if reg_ids:
            plan.append((c["page_id"], reg_ids, c["archive"]))
        else:
            unresolved_by_archive[c["archive"]] = unresolved_by_archive.get(c["archive"], 0) + 1

    by_archive: dict[str, int] = {}
    for _pid, _rids, arc in plan:
        by_archive[arc] = by_archive.get(arc, 0) + 1
    print(f"\nБудет заполнено: {len(plan)}")
    for arc, n in sorted(by_archive.items(), key=lambda x: -x[1]):
        print(f"  {arc}: {n}")
    print(f"\nНе резолвится (нет совпадения с территорией/регионом): {sum(unresolved_by_archive.values())}")
    for arc, n in sorted(unresolved_by_archive.items(), key=lambda x: -x[1])[:15]:
        print(f"  {arc}: {n}")

    if not args.apply:
        print("\nПредпросмотр. Для записи в Notion запусти с --apply.")
        return

    ledger_path = args.csv_path.with_name(args.csv_path.stem + "_regions_backfill_ledger.jsonl")
    done = set()
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("status") == "ok":
                    done.add(rec["page_id"])

    ok, failed, skipped = 0, 0, 0
    for pid, reg_ids, _arc in plan:
        if pid in done:
            skipped += 1
            continue
        try:
            call_retry(client.pages.update, page_id=pid,
                       properties={"Современные регионы": {"relation": [{"id": i} for i in reg_ids]}})
            with ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page_id": pid, "status": "ok"}, ensure_ascii=False) + "\n")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            with ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"page_id": pid, "status": "fail", "error": str(exc)[:300]}, ensure_ascii=False) + "\n")
            failed += 1
            logger.info(f"FAIL {pid}: {exc}")
        if (ok + failed) % 100 == 0:
            logger.info(f"{ok + failed}/{len(plan)} ok={ok} failed={failed}")
        time.sleep(0.34)

    print(f"\nГотово: ok={ok} failed={failed} пропущено={skipped} из {len(plan)}")


if __name__ == "__main__":
    main()
