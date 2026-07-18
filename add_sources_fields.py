"""
Шаг 1: Добавить 4 поля в базу «Источники» и заполнить 108 существующих записей.

Поля:
  Дата внесения          DATE
  Автор внесения         SELECT  (Алейников | Агент)
  Проверка комплементарности  SELECT  (да | нет)
  Сомнительных           SELECT  (да | нет)

Существующие записи: дата = 2026-06-18, автор = Алейников.
"""
import json
import time
import urllib.error
import urllib.request
import sys

sys.stdout.reconfigure(encoding="utf-8")

TOKEN = "ntn_y31296007024sMESWX0yDMKxiuzjIe5gJ3gSe3CQN0x2D5"
DB_ID = "5ead971c-b9bd-4bc2-90d8-73d0841b1f93"
DATE_ISO = "2026-06-18"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def api(method: str, url: str, data: dict | None = None) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data else None,
        headers=HEADERS,
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"HTTP {e.code}: {body}") from e


# ── Шаг 1а: Добавить поля в схему базы ──────────────────────────────────────
print("1. Добавляем поля в базу «Источники»...")
try:
    api("PATCH", f"https://api.notion.com/v1/databases/{DB_ID}", {
        "properties": {
            "Дата внесения": {"date": {}},
            "Автор внесения": {
                "select": {
                    "options": [
                        {"name": "Алейников", "color": "blue"},
                        {"name": "Агент",     "color": "green"},
                    ]
                }
            },
            "Проверка комплементарности": {
                "select": {
                    "options": [
                        {"name": "да",  "color": "green"},
                        {"name": "нет", "color": "red"},
                    ]
                }
            },
            "Сомнительных": {
                "select": {
                    "options": [
                        {"name": "да",  "color": "orange"},
                        {"name": "нет", "color": "gray"},
                    ]
                }
            },
        }
    })
    print("   ✓ Поля созданы")
except RuntimeError as e:
    print(f"   Поля уже могут существовать или ошибка: {e}")

# ── Шаг 1б: Получить все страницы ────────────────────────────────────────────
print("\n2. Загружаем список источников...")
pages: list[dict] = []
cursor: str | None = None
while True:
    body: dict = {"page_size": 100}
    if cursor:
        body["start_cursor"] = cursor
    result = api("POST", f"https://api.notion.com/v1/databases/{DB_ID}/query", body)
    pages.extend(result.get("results", []))
    if not result.get("has_more"):
        break
    cursor = result.get("next_cursor")

print(f"   Найдено записей: {len(pages)}")

# ── Шаг 1в: Заполнить существующие записи ────────────────────────────────────
print("\n3. Заполняем поля «Дата внесения» и «Автор внесения»...")
success = skipped = errors = 0

for i, page in enumerate(pages, 1):
    page_id = page["id"]
    # Пропускаем если автор уже указан
    if page["properties"].get("Автор внесения", {}).get("select"):
        skipped += 1
        continue

    try:
        api("PATCH", f"https://api.notion.com/v1/pages/{page_id}", {
            "properties": {
                "Дата внесения":   {"date": {"start": DATE_ISO}},
                "Автор внесения":  {"select": {"name": "Алейников"}},
            }
        })
        success += 1
        if success % 20 == 0 or success == 1:
            print(f"   [{success}/{len(pages) - skipped}] обновлено...")
        time.sleep(0.35)  # ~3 req/s — лимит Notion
    except RuntimeError as e:
        errors += 1
        title = (page["properties"].get("Название", {}).get("title") or [{}])
        name = (title[0].get("plain_text", "?") if title else "?")
        print(f"   Ошибка [{name}]: {e}")

print(f"\n✓ Готово: обновлено {success}, пропущено {skipped} (уже заполнены), ошибок {errors}")
