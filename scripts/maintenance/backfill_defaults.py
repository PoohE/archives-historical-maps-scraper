"""
Бэкфилл существующих записей каталога по правилам v1.6 (реш. Д14/Д19 + приёмка).

Заполняет ТОЛЬКО ПУСТЫЕ поля (ничего не перезаписывает):
  Язык                        -> Русский        (Д14: авто-Русский, если не указан иной)
  Геопривязка: статус         -> Не выполнена   (канон: «работа не выполнялась»)
  Векторизация                -> Нет
  OCR (распознавание текста)  -> Нет
  Тип привязки                -> Не привязан
  Статус приёмки              -> принято        (решение 2026-09-23: старые ручные записи
                                                 вне слоя приёмки считаются принятыми;
                                                 у кандидатов стоит «кандидат» — не трогается)

Запуск:
  python scripts/maintenance/backfill_defaults.py --dry-run
  python scripts/maintenance/backfill_defaults.py
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
DEFAULTS = {
    "Язык": "Русский",
    "Геопривязка: статус": "Не выполнена",
    "Векторизация": "Нет",
    "OCR (распознавание текста)": "Нет",
    "Тип привязки": "Не привязан",
    "Статус приёмки": "принято",
}


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
        print("Нет NOTION_TOKEN (env или Каталогизация/.env)")
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

    per_field = dict.fromkeys(DEFAULTS, 0)
    updated = errors = untouched = 0
    for p in pages:
        props = p["properties"]
        patch: dict = {}
        for field, value in DEFAULTS.items():
            cur = (props.get(field, {}).get("select") or {}).get("name")
            if not cur:
                patch[field] = {"select": {"name": value}}
                per_field[field] += 1
        if not patch:
            untouched += 1
            continue
        updated += 1
        if a.dry_run:
            continue
        try:
            api("PATCH", f"https://api.notion.com/v1/pages/{p['id']}", {"properties": patch})
            time.sleep(0.34)
        except RuntimeError as e:
            updated -= 1
            errors += 1
            title = "".join(x.get("plain_text", "") for x in
                            props.get("Название источника", {}).get("title", []))[:50]
            print(f"  Ошибка [{title}]: {e}")

    tag = "DRY-RUN " if a.dry_run else ""
    print(f"{tag}записей: {len(pages)} | обновлено: {updated} | без изменений: {untouched} | ошибок: {errors}")
    for f, n in per_field.items():
        print(f"  {f}: заполнено {n}")


if __name__ == "__main__":
    main()
