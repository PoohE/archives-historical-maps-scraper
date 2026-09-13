"""
Добавить в справочник «Архивы» три поля для мониторинга проблем доступа:
  - Статус доступа  (select)
  - Проблема доступа (rich_text)
  - Обходной путь   (rich_text)

После добавления — заполняет «Статус доступа» = «Не проверено» для всех записей,
у которых поле пустое.
"""
import json, sys, time, urllib.error, urllib.request
sys.stdout.reconfigure(encoding="utf-8")

with open(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env", encoding="utf-8") as f:
    TOKEN = f.read().split("NOTION_TOKEN=")[1].split()[0]

DB_ID = "a9e98744-faf8-493f-93e5-cb14c0374fd8"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def api(method, url, data=None):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode() if data else None,
        headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()}") from e


# ── 1. Добавить поля в схему базы ────────────────────────────────────────────
print("Добавляем поля в схему «Архивы»...")

new_props = {
    "Статус доступа": {
        "select": {
            "options": [
                {"name": "Доступен",      "color": "green"},
                {"name": "Частично",      "color": "yellow"},
                {"name": "Недоступен",    "color": "red"},
                {"name": "Заблокирован",  "color": "orange"},
                {"name": "Не проверено",  "color": "default"},
            ]
        }
    },
    "Проблема доступа": {"rich_text": {}},
    "Обходной путь":    {"rich_text": {}},
}

result = api("PATCH", f"https://api.notion.com/v1/databases/{DB_ID}",
             {"properties": new_props})
print("  ✓ Поля добавлены")

# ── 2. Заполнить «Статус доступа» = «Не проверено» для всех записей ──────────
print("\nЗаполняем «Статус доступа» = «Не проверено» для всех записей...")

pages = []
cursor = None
while True:
    body = {"page_size": 100}
    if cursor:
        body["start_cursor"] = cursor
    resp = api("POST", f"https://api.notion.com/v1/databases/{DB_ID}/query", body)
    pages.extend(resp.get("results", []))
    if not resp.get("has_more"):
        break
    cursor = resp.get("next_cursor")

print(f"  Всего записей: {len(pages)}")

ok = skip = err = 0
for page in pages:
    # Заполнять только если поле пустое
    existing = page["properties"].get("Статус доступа", {}).get("select")
    if existing:
        skip += 1
        continue
    try:
        api("PATCH", f"https://api.notion.com/v1/pages/{page['id']}",
            {"properties": {"Статус доступа": {"select": {"name": "Не проверено"}}}})
        ok += 1
        time.sleep(0.35)
    except RuntimeError as e:
        err += 1
        name = page["properties"].get("Название", {}).get("title", [{}])
        print(f"  Ошибка [{name[0].get('plain_text', '?')}]: {e}")

print(f"  ✓ Обновлено: {ok}  |  Уже заполнено: {skip}  |  Ошибок: {err}")
print("\nГотово. В Notion таблице «Архивы» появились три новых поля.")
print("Агент будет заполнять их автоматически при ошибках поиска.")
