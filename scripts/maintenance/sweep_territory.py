"""Backfill «Современные регионы» и «Охватываемая территория» для УЖЕ залитых записей каталога.

Логика — общий модуль `modules/territory_resolve.py` (тот же, что встроен в мост
`notion_upload_candidates.py`, чтобы новые заливки заполнялись автоматически). Этот sweep нужен
только для РАЗОВОГО дозаполнения записей, залитых до внедрения правила. Заполняет ТОЛЬКО пустые
поля (не перетирает заполненные).

Запуск: python scripts/maintenance/sweep_territory.py [--apply]   (без флага — dry-run)
"""
import sys
import time
import urllib.request
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "modules"))
import territory_resolve as tr  # noqa: E402

ENV = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
TOK = ""
for _ln in ENV.read_text(encoding="utf-8").splitlines():
    if _ln.strip().startswith("NOTION_TOKEN"):
        TOK = _ln.split("=", 1)[1].strip().strip('"').strip("'")
H = {"Authorization": f"Bearer {TOK}", "Notion-Version": "2022-06-28",
     "Content-Type": "application/json"}

DB = "5ead971c-b9bd-4bc2-90d8-73d0841b1f93"
TERR_DB = "3920ba89-eabe-81a2-86a2-d50d1bfee1c0"
REG_DB = "6c6a3cfb-8d87-491e-8ce6-da7194bc857b"


def api(method, url, data=None):
    for att in range(4):
        try:
            rq = urllib.request.Request(
                url, data=json.dumps(data).encode() if data else None,
                headers=H, method=method)
            with urllib.request.urlopen(rq, timeout=40) as x:
                return json.load(x)
        except Exception:
            if att == 3:
                raise
            time.sleep(2)


def all_records():
    out, cur = [], None
    while True:
        body = {"page_size": 100}
        if cur:
            body["start_cursor"] = cur
        r = api("POST", f"https://api.notion.com/v1/databases/{DB}/query", body)
        out += r["results"]
        if not r["has_more"]:
            break
        cur = r["next_cursor"]
    return out


def main():
    apply = "--apply" in sys.argv
    print("РЕЖИМ:", "ПРИМЕНЕНИЕ" if apply else "DRY-RUN (--apply чтобы записать)")
    terr_stem_index, terr_gub, reg_index = tr.load_indexes(api, TERR_DB, REG_DB)
    print(f"справочники: территорий {len(terr_stem_index)}, регионов {len(reg_index)}")

    recs = all_records()
    print(f"записей каталога: {len(recs)}")

    reg_fill = terr_fill = 0
    for pg in recs:
        pr = pg["properties"]
        title = "".join(x["plain_text"] for x in pr["Название источника"]["title"])
        url = (pr.get("Ссылка на онлайн-архив", {}) or {}).get("url") or ""
        terr_ids, reg_ids = tr.resolve(title, url, terr_stem_index, terr_gub, reg_index)

        patch = {}
        if reg_ids and not pr.get("Современные регионы", {}).get("relation"):
            patch["Современные регионы"] = {"relation": [{"id": i} for i in reg_ids]}
        if terr_ids and not pr.get("Охватываемая территория", {}).get("relation"):
            patch["Охватываемая территория"] = {"relation": [{"id": i} for i in terr_ids]}

        if patch:
            if "Современные регионы" in patch:
                reg_fill += 1
            if "Охватываемая территория" in patch:
                terr_fill += 1
            if apply:
                api("PATCH", f"https://api.notion.com/v1/pages/{pg['id']}",
                    {"properties": patch})

    print(f"\nЗаполнено «Современные регионы»: {reg_fill}")
    print(f"Заполнено «Охватываемая территория»: {terr_fill}")


if __name__ == "__main__":
    main()
