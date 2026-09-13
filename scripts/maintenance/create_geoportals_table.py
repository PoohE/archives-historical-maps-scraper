"""
Создать таблицу «Геопорталы» и перенести туда ресурсы-просмотрщики из «Архивов».

Переносим: Руниверс, Retromap, SouthKlad, QMap, ЭтоМесто
Эти ресурсы — агрегаторы карт без ссылки на первоисточник-архив.
Используются только на этапе скачивания карт, не каталогизации.
"""
import json
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

with open(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env", encoding="utf-8") as f:
    TOKEN = f.read().split("NOTION_TOKEN=")[1].split()[0]

HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

ARCHIVY_DB_ID = "a9e98744-faf8-493f-93e5-cb14c0374fd8"
PARENT_PAGE_ID = "3830ba89-eabe-8136-9afd-fde0c7e20234"  # та же страница что «Архивы»

# Названия порталов-просмотрщиков, которые переносим из «Архивов»
PORTAL_NAMES = {"руниверс", "retromap", "southklad", "qmap", "этоместо", "etomesto"}


def api(method, url, data=None):
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
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()}") from e


# ── 1. Создать новую таблицу «Геопорталы» ────────────────────────────────────
print("Создаём таблицу «Геопорталы»...")

new_db = api("POST", "https://api.notion.com/v1/databases", {
    "parent": {"type": "page_id", "page_id": PARENT_PAGE_ID},
    "title": [{"type": "text", "text": {"content": "Геопорталы"}}],
    "icon": {"type": "emoji", "emoji": "🗺️"},
    "properties": {
        "Название": {"title": {}},
        "Сайт": {"url": {}},
        "Описание": {"rich_text": {}},
        "Покрытие": {"rich_text": {}},  # какие территории охватывает
        "Источники": {"rich_text": {}},  # из каких архивов агрегирует
        "Формат карт": {
            "select": {
                "options": [
                    {"name": "JPEG", "color": "blue"},
                    {"name": "TIFF", "color": "green"},
                    {"name": "PDF", "color": "orange"},
                    {"name": "WMS/WMTS", "color": "purple"},
                    {"name": "Смешанный", "color": "default"},
                ]
            }
        },
        "Скачивание": {
            "select": {
                "options": [
                    {"name": "Свободное", "color": "green"},
                    {"name": "Частичное", "color": "yellow"},
                    {"name": "Только просмотр", "color": "red"},
                ]
            }
        },
        "Статус доступа": {
            "select": {
                "options": [
                    {"name": "Доступен", "color": "green"},
                    {"name": "Частично", "color": "yellow"},
                    {"name": "Недоступен", "color": "red"},
                    {"name": "Не проверено", "color": "default"},
                ]
            }
        },
        "Примечание": {"rich_text": {}},
    },
})

geo_db_id = new_db["id"]
print(f"  ✓ Создана «Геопорталы» (ID: {geo_db_id})")


# ── 2. Найти порталы в таблице «Архивы» ──────────────────────────────────────
print("\nИщем порталы в «Архивах»...")

pages = []
cursor = None
while True:
    body = {"page_size": 100}
    if cursor:
        body["start_cursor"] = cursor
    resp = api("POST", f"https://api.notion.com/v1/databases/{ARCHIVY_DB_ID}/query", body)
    pages.extend(resp.get("results", []))
    if not resp.get("has_more"):
        break
    cursor = resp.get("next_cursor")

portals_found = []
for page in pages:
    title_arr = page["properties"].get("Название", {}).get("title", [])
    title = title_arr[0].get("plain_text", "").strip() if title_arr else ""
    if any(p in title.lower() for p in PORTAL_NAMES):
        portals_found.append((page["id"], title, page["properties"]))

print(f"  Найдено порталов: {len(portals_found)}")
for pid, title, _ in portals_found:
    print(f"    - {title}")


# ── 3. Создать записи в «Геопорталах» и архивировать из «Архивов» ─────────────
print("\nПереносим...")

moved = archived = errors = 0
for page_id, title, props in portals_found:
    # Извлекаем поля из старой записи
    site = props.get("Сайт", {}).get("url", "") or ""
    abbr = (props.get("Аббревиатура", {}).get("rich_text", [{}])[0]
            .get("plain_text", "")) if props.get("Аббревиатура", {}).get("rich_text") else ""
    notes = (props.get("Особенности", {}).get("rich_text", [{}])[0]
             .get("plain_text", "")) if props.get("Особенности", {}).get("rich_text") else ""

    # Создаём в «Геопорталах»
    new_props = {
        "Название": {"title": [{"text": {"content": title}}]},
        "Статус доступа": {"select": {"name": "Не проверено"}},
    }
    if site:
        new_props["Сайт"] = {"url": site}
    if abbr or notes:
        combined = (abbr + ": " if abbr else "") + notes
        new_props["Примечание"] = {"rich_text": [{"text": {"content": combined[:2000]}}]}

    try:
        api("POST", "https://api.notion.com/v1/pages", {
            "parent": {"database_id": geo_db_id},
            "properties": new_props,
        })
        moved += 1
        print(f"  ✓ Перенесён: {title}")
        time.sleep(0.35)
    except RuntimeError as e:
        errors += 1
        print(f"  ✗ Ошибка создания {title}: {e}")
        continue

    # Архивируем из «Архивов»
    try:
        api("PATCH", f"https://api.notion.com/v1/pages/{page_id}", {"archived": True})
        archived += 1
        time.sleep(0.35)
    except RuntimeError as e:
        print(f"  ✗ Ошибка архивации {title}: {e}")

print(f"\nГотово: {moved} перенесено, {archived} архивировано из «Архивов», {errors} ошибок")
print(f"\nТаблица «Геопорталы» создана в Notion.")
print(f"Используй её на этапе скачивания карт, не каталогизации.")
