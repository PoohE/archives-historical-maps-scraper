"""Backfill «Охватываемая территория»/«Современные регионы» для записей ПрБ по entry["territory"].

Причина: прогон ПрБ снял чистую территорию в `entry["territory"]` (из рубрикатора/крошек коллекции:
«Калужская губерния», «Соликамск», «Чердынь»…), но раскладка её не использовала — резолвинг шёл
только по названию. Sweep берёт эти хинты и доставляет их в territory_resolve.resolve(hints=...),
заполняя ТОЛЬКО пустые поля существующих записей (по URL).

Запуск: python scripts/maintenance/sweep_prlib_territory.py [records_full.jsonl] [--apply]
По умолчанию — output/prlib_catalog_full_20260917_v1/records_full.jsonl, dry-run.
"""
import io
import json
import sys
import time
import urllib.request
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
DEFAULT = HERE.parent / "output" / "prlib_catalog_full_20260917_v1" / "records_full.jsonl"


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


def main():
    apply = "--apply" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = Path(args[0]) if args else DEFAULT
    print("РЕЖИМ:", "ПРИМЕНЕНИЕ" if apply else "DRY-RUN", "| источник:", src.name)

    terr_idx, terr_gub, reg_idx = tr.load_indexes(api, TERR_DB, REG_DB)

    # url -> {title, hints}
    per_url = {}
    for x in io.open(src, encoding="utf-8-sig"):
        if not x.strip():
            continue
        e = json.loads(x)
        rec = e.get("record", {})
        u = rec.get("url", "")
        terr = (e.get("territory") or "").strip()
        if not u:
            continue
        d = per_url.setdefault(u, {"title": rec.get("title", ""), "hints": set()})
        if terr:
            d["hints"].add(terr)
    print(f"уникальных URL ПрБ: {len(per_url)}")

    reg_fill = terr_fill = nohint = notfound = 0
    for u, info in per_url.items():
        hints = list(info["hints"])
        if not hints:
            nohint += 1
            continue
        tail = u.rstrip("/").split("/")[-1]
        r = api("POST", f"https://api.notion.com/v1/databases/{DB}/query",
                {"filter": {"property": "Ссылка на онлайн-архив",
                            "url": {"contains": tail}}, "page_size": 1})
        if not r["results"]:
            notfound += 1
            continue
        pg = r["results"][0]
        pr = pg["properties"]
        terr_ids, reg_ids = tr.resolve(info["title"], u, terr_idx, terr_gub, reg_idx, hints=hints)
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
                time.sleep(0.34)

    print(f"\nзаполнено «Охватываемая территория»: {terr_fill}")
    print(f"заполнено «Современные регионы»: {reg_fill}")
    print(f"без хинта территории: {nohint} | не найдено в Notion: {notfound}")


if __name__ == "__main__":
    main()
