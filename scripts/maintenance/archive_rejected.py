"""
Архивирование записей «Статус приёмки» = отклонено (REST archived=true → корзина Notion, обратимо).

Обучающая ценность отклонённых сохраняется в журнале правил (docs/current/ПРАВИЛА_фильтра_ПрБ.md)
и регресс-тестах фильтра, поэтому копии в каталоге избыточны (решение пользователя 2026-09-26,
обновляет прежнее «отклонённые не удалять»).

Запуск:
  python scripts/maintenance/archive_rejected.py --dry-run
  python scripts/maintenance/archive_rejected.py
  python scripts/maintenance/archive_rejected.py --source prlib.ru   # только один источник
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
    ap.add_argument("--source", default="", help="фильтр по подстроке URL (напр. prlib.ru)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not TOKEN:
        print("Нет NOTION_TOKEN")
        sys.exit(1)

    res = api("POST", f"https://api.notion.com/v1/databases/{DB_ID}/query",
              {"filter": {"property": "Статус приёмки", "select": {"equals": "отклонено"}},
               "page_size": 100})
    rows = res.get("results", [])
    archived = errors = 0
    for p in rows:
        pr = p["properties"]
        url = pr.get("Ссылка на онлайн-архив", {}).get("url") or ""
        if a.source and a.source not in url:
            continue
        title = "".join(x.get("plain_text", "") for x in
                        pr.get("Название источника", {}).get("title", []))[:65]
        print(f"{'DRY ' if a.dry_run else ''}archive: {title}")
        archived += 1
        if a.dry_run:
            continue
        try:
            api("PATCH", f"https://api.notion.com/v1/pages/{p['id']}", {"archived": True})
            time.sleep(0.34)
        except RuntimeError as e:
            archived -= 1
            errors += 1
            print(f"  Ошибка: {e}")

    print(f"\n{'DRY-RUN ' if a.dry_run else ''}архивировано (в корзину Notion, обратимо): {archived} | ошибок: {errors}")


if __name__ == "__main__":
    main()
