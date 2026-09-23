"""
Миграция перед DROP поля «Библиографическое описание» (реш. Д4, слияние 20->21).

У записей, где «Библиографическое описание» заполнено и НЕ дублирует «Описание»,
дозаписывает его текст в конец «Описания» блоком «[Библиография карточки] ...».
Дубли (тексты равны) пропускает. REST-токен из Каталогизация/.env (канон п.5, не MCP).

Запуск:
  python scripts/maintenance/migrate_bib_to_description.py --dry-run
  python scripts/maintenance/migrate_bib_to_description.py
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
BIB = "Библиографическое описание"
DESC = "Описание"
MARK = "[Библиография карточки]"


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


def rt_text(prop: dict) -> str:
    return "".join(x.get("plain_text", "") for x in prop.get("rich_text", []))


def chunks(s: str, n: int = 2000) -> list[dict]:
    return [{"text": {"content": s[i:i + n]}} for i in range(0, len(s), n)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not TOKEN:
        print("Нет NOTION_TOKEN (env или Каталогизация/.env)")
        sys.exit(1)

    pages, cursor = [], None
    body: dict = {"filter": {"property": BIB, "rich_text": {"is_not_empty": True}},
                  "page_size": 100}
    while True:
        if cursor:
            body["start_cursor"] = cursor
        res = api("POST", f"https://api.notion.com/v1/databases/{DB_ID}/query", body)
        pages += res.get("results", [])
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")

    merged = skipped_dup = already = errors = 0
    for p in pages:
        props = p["properties"]
        bib = rt_text(props.get(BIB, {})).strip()
        desc = rt_text(props.get(DESC, {})).strip()
        title = "".join(x.get("plain_text", "") for x in
                        props.get("Название источника", {}).get("title", []))[:60]
        if not bib or bib == desc or bib in desc:
            skipped_dup += 1
            continue
        if MARK in desc:
            already += 1
            continue
        new_desc = (desc + "\n\n" if desc else "") + f"{MARK} {bib}"
        print(f"{'DRY ' if a.dry_run else ''}merge -> [{title}] (+{len(bib)} симв.)")
        if a.dry_run:
            merged += 1
            continue
        try:
            api("PATCH", f"https://api.notion.com/v1/pages/{p['id']}",
                {"properties": {DESC: {"rich_text": chunks(new_desc)}}})
            merged += 1
            time.sleep(0.34)
        except RuntimeError as e:
            errors += 1
            print(f"  Ошибка [{title}]: {e}")

    print(f"\nитого: слито {merged} | дубль/вхождение (пропуск) {skipped_dup} | "
          f"уже мигрировано {already} | ошибок {errors} | всего с библ. {len(pages)}")


if __name__ == "__main__":
    main()
