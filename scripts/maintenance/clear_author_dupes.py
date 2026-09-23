"""
Разовая чистка после перезалива v1.6 (реш. Д7): у записей ПрБ поле
«Автор / составитель» (11) очищается, если оно ДОСЛОВНО дублирует
«Связанное издание: автор / ответственность» (25) — это старая заливка
ответственности издания в поле автора карты. Только точные дубли; иное — не трогаем.

Запуск:
  python scripts/maintenance/clear_author_dupes.py --dry-run
  python scripts/maintenance/clear_author_dupes.py
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
A11 = "Автор / составитель"
A25 = "Связанное издание: автор / ответственность"


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


def rt(p: dict) -> str:
    return "".join(x.get("plain_text", "") for x in p.get("rich_text", []))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not TOKEN:
        print("Нет NOTION_TOKEN")
        sys.exit(1)

    pages, cursor = [], None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        res = api("POST", f"https://api.notion.com/v1/databases/{DB_ID}/query", body)
        pages += res.get("results", [])
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")

    cleared = kept = errors = 0
    for p in pages:
        pr = p["properties"]
        v11, v25 = rt(pr.get(A11, {})).strip(), rt(pr.get(A25, {})).strip()
        if not v11 or v11 != v25:
            continue
        title = "".join(x.get("plain_text", "") for x in
                        pr.get("Название источника", {}).get("title", []))[:55]
        print(f"{'DRY ' if a.dry_run else ''}clear 11 (дубль 25): {title}")
        cleared += 1
        if a.dry_run:
            continue
        try:
            api("PATCH", f"https://api.notion.com/v1/pages/{p['id']}",
                {"properties": {A11: {"rich_text": []}}})
            time.sleep(0.34)
        except RuntimeError as e:
            cleared -= 1
            errors += 1
            print(f"  Ошибка [{title}]: {e}")
    kept = sum(1 for p in pages if rt(p["properties"].get(A11, {})).strip())
    tag = "DRY-RUN " if a.dry_run else ""
    print(f"\n{tag}очищено: {cleared} | ошибок: {errors} | всего записей с полем 11: {kept}")


if __name__ == "__main__":
    main()
