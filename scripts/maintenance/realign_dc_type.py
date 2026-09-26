"""
Выравнивание DC Type по типу источника (канон табл. 9, уровень единицы).
Читает «Тип источника» (relation) → код → правильный DC Type из TYPES;
патчит записи, где DC Type не совпадает. Идемпотентно.

Запуск: python scripts/maintenance/realign_dc_type.py [--dry-run]
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sweep_candidate_type import TYPES, ID2CODE  # noqa: E402

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

    fixed = same = errors = 0
    for p in pages:
        pr = p["properties"]
        rel = pr.get("Тип источника", {}).get("relation", [])
        if not rel:
            continue
        code = ID2CODE.get(rel[0]["id"].replace("-", ""))
        if not code:
            continue
        want = TYPES[code][1]
        cur = (pr.get("DC Type", {}).get("select") or {}).get("name")
        if cur == want:
            same += 1
            continue
        title = "".join(x.get("plain_text", "") for x in
                        pr.get("Название источника", {}).get("title", []))[:48]
        print(f"{'DRY ' if a.dry_run else ''}{code}: {cur} → {want} | {title}")
        fixed += 1
        if a.dry_run:
            continue
        try:
            api("PATCH", f"https://api.notion.com/v1/pages/{p['id']}",
                {"properties": {"DC Type": {"select": {"name": want}}}})
            time.sleep(0.34)
        except RuntimeError as e:
            errors += 1
            print(f"  Ошибка [{title}]: {e}")

    print(f"\n{'DRY-RUN ' if a.dry_run else ''}исправлено: {fixed} | совпадало: {same} | ошибок: {errors}")


if __name__ == "__main__":
    main()
