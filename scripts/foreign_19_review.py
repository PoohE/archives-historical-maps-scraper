"""19 записей каталога с чужой территорией: выписать поимённо и отклонить.

Задача пользователя 10.11.2026: пройти по одному. Сплошной аудит показал, что
«чужих» в каталоге 19 из 112 202 — почти все из прогона ГАПК, где классификация
по подстрокам заголовка ошибается (память `project_gapk-manual-review-needed`).

По правилу проекта чужая территория не удаляется, а получает статус «отклонено»
с причиной (`rule_territory_multiprovince`, память `feedback_otsev-ne-musor-...`).

  python foreign_19_review.py            # выписать и показать, ничего не менять
  python foreign_19_review.py --apply    # проставить «отклонено» с причиной
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

from territory_gate import classify  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
BASELINE = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"
OUT = ROOT / "defects" / "foreign_19.jsonl"
STATUS = "Статус приёмки"
NOTE = "Примечания"


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    rows = []
    for line in BASELINE.open(encoding="utf-8"):
        if not line.strip():
            continue
        rec = json.loads(line)
        f = rec.get("fields") or {}
        blob = " ".join(
            str(f.get(k) or "")
            for k in ("Название источника", "Описание", "Примечания")
        )
        if not blob.strip():
            continue
        verdict, why = classify(blob)
        if verdict != "чужая":
            continue
        rows.append({
            "page_id": rec.get("page_id") or rec.get("id") or "",
            "arch": f.get("Архив [авто]") or "?",
            "fond": str(f.get("Фонд") or ""),
            "opis": str(f.get("Опись") or ""),
            "delo": str(f.get("Единица хранения") or ""),
            "title": (f.get("Название источника") or ""),
            "status": str(f.get(STATUS) or "— не задан —"),
            "note": str(f.get(NOTE) or ""),
            "why": why,
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + chr(10))

    print(f"записей с чужой территорией: {len(rows)}\n")
    for i, r in enumerate(rows, 1):
        print(f"{i:2d}. {r['arch']} ф.{r['fond']} оп.{r['opis']} д.{r['delo']} "
              f"[{r['status']}]")
        print(f"    {r['title'][:150]}")
        print(f"    основание гейта: {r['why']}")
    print(f"\n→ {OUT}")

    if not args.apply:
        print("\nбез --apply ничего не изменено")
        return

    load_env(ENV_PATH)
    c = Client(auth=env("NOTION_TOKEN"))
    n = 0
    for r in rows:
        if not r["page_id"]:
            continue
        mark = ("Отклонено 10.11.2026: территория вне проекта — "
                f"{r['why']}. Проверено поимённо при сплошном аудите каталога.")
        note = (r["note"] + chr(10) + mark).strip() if r["note"] else mark
        retry(lambda pid=r["page_id"], note=note: c.pages.update(
            page_id=pid,
            properties={
                STATUS: {"select": {"name": "отклонено"}},
                NOTE: {"rich_text": [{"type": "text",
                                      "text": {"content": note[:1900]}}]},
            },
        ))
        n += 1
        print(f"  отклонено: {r['arch']} ф.{r['fond']} д.{r['delo']}", flush=True)
    print(f"\nИТОГО отклонено: {n}")


if __name__ == "__main__":
    main()
