"""Чтение справочников каталога перед заливкой: «Архивы» и «Тип источника».

Два вопроса, на которые нельзя отвечать по памяти:
  1. ГАСО — коллизия двух архивов (Смоленск и Свердловск, память
     `reference_gaso-two-archives-collision`). Под каким именем в справочнике
     «Архивы» живёт СВЕРДЛОВСКИЙ, и живёт ли вообще;
  2. какие значения есть у «Тип источника» — чтобы раскладывать классы
     карта / статистика по существующим типам, а не заводить свои.

Только чтение, ничего не пишет.

  python probe_refs.py
"""

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import env, fix_stdout, load_env  # noqa: E402

ENV = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
ARCHIVES_DB = "a9e98744-faf8-493f-93e5-cb14c0374fd8"
CATALOG_DB = "5ead971c-b9bd-4bc2-90d8-73d0841b1f93"


def api(method: str, url: str, data: dict | None = None) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {env('NOTION_TOKEN')}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


def plain(prop: dict) -> str:
    for key in ("title", "rich_text"):
        if key in prop:
            return "".join(x.get("plain_text", "") for x in prop[key]).strip()
    if prop.get("type") == "select" and prop.get("select"):
        return str(prop["select"].get("name") or "")
    return ""


def main() -> None:
    fix_stdout()
    load_env(ENV)

    print("=== СПРАВОЧНИК «Архивы» ===")
    cursor = None
    rows = []
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        res = api("POST", f"https://api.notion.com/v1/databases/{ARCHIVES_DB}/query", body)
        for p in res.get("results", []):
            pr = p["properties"]
            rows.append((plain(pr.get("Аббревиатура", {})),
                         plain(pr.get("Название", {})), p["id"]))
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    print(f"записей: {len(rows)}")
    for abbr, name, pid in sorted(rows):
        mark = "  <<< " if any(
            s in (abbr + name).lower()
            for s in ("гасо", "свердл", "екатеринб", "урал")) else ""
        print(f"  {abbr:14s} | {name[:68]}{mark}")

    print("\n=== СХЕМА каталога: типы интересующих свойств ===")
    db = api("GET", f"https://api.notion.com/v1/databases/{CATALOG_DB}")
    for name in ("Тип источника", "Административный уровень", "Архив хранения",
                 "Охватываемая территория", "Серия / массив", "Масштаб: источник значения",
                 "Год: источник значения", "Территория: источник значения",
                 "Административный уровень: источник значения", "Статус приёмки",
                 "Статус доступа", "Цифровая копия (есть/нет)", "Язык", "DC Type"):
        p = db.get("properties", {}).get(name)
        if not p:
            print(f"  {name:46s} — СВОЙСТВА НЕТ")
            continue
        t = p.get("type")
        extra = ""
        if t == "select":
            extra = " | ".join(o["name"] for o in p["select"]["options"])[:150]
        elif t == "status":
            extra = " | ".join(o["name"] for o in p["status"]["options"])[:150]
        elif t == "relation":
            extra = "→ " + str(p["relation"].get("database_id"))
        print(f"  {name:46s} {t:10s} {extra}")


if __name__ == "__main__":
    main()
