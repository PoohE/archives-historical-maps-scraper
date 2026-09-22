"""Архивировать (в корзину Notion) страницы «Каталога» по фильтру Автор внесения + Дата внесения.

Notion REST API (integration token NOTION_TOKEN из Каталогизация/.env). Служебный откат
ошибочных агентских заливок: MCP не умеет удалять страницы, поэтому архивируем через REST
(PATCH archived=true → в корзину, обратимо из Notion UI 30 дней).

Запуск:
  python scripts/maintenance/notion_archive_pages.py --author Агент --date 2026-09-22 --dry-run
  python scripts/maintenance/notion_archive_pages.py --author Агент --date 2026-09-22
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DB_ID = "5ead971c-b9bd-4bc2-90d8-73d0841b1f93"
ENV = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")


def load_token() -> str:
    t = os.environ.get("NOTION_TOKEN", "")
    if t:
        return t
    if ENV.exists():
        for ln in ENV.read_text(encoding="utf-8").splitlines():
            if ln.strip().startswith("NOTION_TOKEN"):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


TOKEN = load_token()
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Notion-Version": "2022-06-28",
           "Content-Type": "application/json"}


def api(method: str, url: str, data: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                 headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()}") from e


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--author", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not TOKEN:
        print("Нет NOTION_TOKEN (env или Каталогизация/.env)")
        sys.exit(1)

    flt = {"and": [{"property": "Автор внесения", "select": {"equals": a.author}},
                   {"property": "Дата внесения", "date": {"equals": a.date}}]}
    ids: list[str] = []
    cursor = None
    while True:
        body = {"filter": flt, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        res = api("POST", f"https://api.notion.com/v1/databases/{DB_ID}/query", body)
        ids.extend(p["id"] for p in res.get("results", []))
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")

    print(f"Под фильтром (Автор={a.author}, Дата={a.date}): {len(ids)} страниц")
    if a.dry_run:
        print("dry-run — ничего не архивировано")
        return
    n = 0
    for pid in ids:
        api("PATCH", f"https://api.notion.com/v1/pages/{pid}", {"archived": True})
        n += 1
        time.sleep(0.34)
    print(f"Архивировано (в корзину): {n}")


if __name__ == "__main__":
    main()
