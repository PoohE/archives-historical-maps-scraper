"""Пачка 19 сессии анализа: держатель (музей) у записей Госкаталог.РФ (24.11.2026).

Карточка предмета: GET /muzfo-rest/rest/exhibits/<id> → museumId; музей: GET /muzfo-rest/rest/museums/<id>
(название, сокращение, fullUin «1-<код региона>-…», координаты). Те же адреса вызывает сам портал
goskatalog.ru/portal; robots.txt у сайта нет (404). Пауза 1 с, журнал возобновляемый.

  python scripts/goskatalog_museums_2026_11_24.py fetch   # предметы + музеи → output/goskatalog_museums_2026-11-24/
"""
import csv
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")
from common import fix_stdout  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "output" / "notion_catalog_20261123_231257.csv"
WORK = ROOT / "output" / "goskatalog_museums_2026-11-24"
UA = {"User-Agent": "Mozilla/5.0 (research; IGRAS RNF 26-17-00347)", "Accept": "application/json"}
API = "https://goskatalog.ru/muzfo-rest/rest/"


def get(path):
    for k in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(API + path, headers=UA), timeout=60) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if k == 2:
                return {"_error": str(e)[:200]}
            time.sleep(5)


def fetch():
    csv.field_size_limit(10**9)
    WORK.mkdir(parents=True, exist_ok=True)
    ex_p, mu_p = WORK / "exhibits.jsonl", WORK / "museums.jsonl"
    done = {json.loads(x)["gk_id"] for x in ex_p.open(encoding="utf-8")} if ex_p.exists() else set()
    rows = []
    for r in csv.DictReader(open(SNAP, encoding="utf-8-sig")):
        if r["Архив [авто]"].startswith("Госкаталог"):
            m = re.search(r"collections\?id=(\d+)", r["Примечания"] + " " + r["Описание"])
            rows.append((r["page_id"], m.group(1) if m else None))
    print("записей Госкаталога:", len(rows), "без id:", sum(1 for _, g in rows if not g))
    with ex_p.open("a", encoding="utf-8", newline="\n") as f:
        for pid, g in rows:
            if not g or g in done:
                continue
            d = get(f"exhibits/{g}")
            f.write(json.dumps({"page_id": pid, "gk_id": g, "museumId": d.get("museumId"), "err": d.get("_error")},
                               ensure_ascii=False) + "\n")
            f.flush()
            done.add(g)
            time.sleep(1)
    mids = {json.loads(x)["museumId"] for x in ex_p.open(encoding="utf-8")} - {None}
    have = {json.loads(x)["id"] for x in mu_p.open(encoding="utf-8")} if mu_p.exists() else set()
    with mu_p.open("a", encoding="utf-8", newline="\n") as f:
        for i in sorted(mids - have):
            d = get(f"museums/{i}")
            keep = {k: d.get(k) for k in ("id", "name", "abbreviation", "fullUin", "latitude", "longitude", "parentId", "_error")}
            keep["id"] = i
            f.write(json.dumps(keep, ensure_ascii=False) + "\n")
            f.flush()
            time.sleep(1)
    print("предметов:", len(done), "музеев:", len(mids))


if __name__ == "__main__":
    fix_stdout()
    {"fetch": fetch}[sys.argv[1]]()
