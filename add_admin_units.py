"""
Шаг 4: Создать базу «Административные единицы» в Notion и заполнить уезды
4 губерний проекта ИГИС (конец XIX в. — перепись 1897 г.).

Структура базы:
  Название       title
  Губерния       select  (Калужская | Пермская | Смоленская | Ярославская)
  Тип            select  (Губерния | Уезд | Наместничество)
  Период с       number
  Период по      number
  Примечания     rich_text

Данные: ЭСБЕ, РГИА — административно-территориальное деление 1796–1917 гг.
"""
import json
import time
import urllib.error
import urllib.request
import sys

sys.stdout.reconfigure(encoding="utf-8")

TOKEN = "ntn_y31296007024sMESWX0yDMKxiuzjIe5gJ3gSe3CQN0x2D5"
# ID родительской страницы — вставим в корень рабочего пространства
# (Notion создаст базу как дочернюю к указанной странице или в корне)
PARENT_PAGE_ID = None  # None = создаём в корне через workspace

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


# ── Данные: уезды 4 губерний (конец XIX в.) ──────────────────────────────────
# Источник: ЭСБЕ, перепись 1897 г., административные реформы 1796 г.
UNITS: list[dict] = []

def add_gubernia(name: str, year_from: int, year_to: int, note: str = ""):
    UNITS.append({"name": name, "gub": name, "type": "Губерния",
                  "from": year_from, "to": year_to, "note": note})

def add_uyezd(gub: str, name: str, year_from: int, year_to: int, note: str = ""):
    UNITS.append({"name": name, "gub": gub, "type": "Уезд",
                  "from": year_from, "to": year_to, "note": note})

# Калужская губерния (учреждена 1796 г., до 1776 — Калужское наместничество)
add_gubernia("Калужская", 1796, 1929, "До 1796 — Калужское наместничество (1776–1796)")
for u in [
    ("Боровский", ""),
    ("Жиздринский", ""),
    ("Калужский", "центр — г. Калуга"),
    ("Козельский", ""),
    ("Лихвинский", ""),
    ("Малоярославецкий", ""),
    ("Медынский", ""),
    ("Мещовский", ""),
    ("Мосальский", ""),
    ("Перемышльский", ""),
    ("Тарусский", ""),
]:
    add_uyezd("Калужская", f"{u[0]} уезд", 1796, 1929, u[1])

# Пермская губерния (учреждена 1796 г., до 1781 — Пермское наместничество)
add_gubernia("Пермская", 1796, 1923,
             "До 1796 — Пермское наместничество (1781–1796). "
             "С 1923 — Уральская область.")
for u in [
    ("Верхотурский", ""),
    ("Екатеринбургский", "с 1781; крупный горнозаводской уезд"),
    ("Ирбитский", "ярмарочный центр"),
    ("Камышловский", ""),
    ("Красноуфимский", ""),
    ("Кунгурский", ""),
    ("Осинский", ""),
    ("Оханский", ""),
    ("Пермский", "центр — г. Пермь"),
    ("Соликамский", "соляной промысел"),
    ("Чердынский", "самый северный, лесное и горное хозяйство"),
    ("Шадринский", ""),
]:
    add_uyezd("Пермская", f"{u[0]} уезд", 1796, 1923, u[1])

# Смоленская губерния (учреждена 1796 г., с 1708 — Смоленская провинция)
add_gubernia("Смоленская", 1796, 1929,
             "С 1708 — Смоленская провинция. С 1796 — губерния.")
for u in [
    ("Бельский", ""),
    ("Вяземский", ""),
    ("Гжатский", ""),
    ("Дорогобужский", ""),
    ("Духовщинский", ""),
    ("Ельнинский", ""),
    ("Краснинский", ""),
    ("Поречский", ""),
    ("Рославльский", ""),
    ("Смоленский", "центр — г. Смоленск"),
    ("Сычёвский", ""),
    ("Юхновский", ""),
]:
    add_uyezd("Смоленская", f"{u[0]} уезд", 1796, 1929, u[1])

# Ярославская губерния (учреждена 1796 г., до 1778 — Ярославское наместничество)
add_gubernia("Ярославская", 1796, 1929,
             "До 1796 — Ярославское наместничество (1778–1796).")
for u in [
    ("Даниловский", ""),
    ("Любимский", ""),
    ("Мологский", "затоплен при создании Рыбинского водохранилища 1941"),
    ("Мышкинский", "с 1917 переименован в Мышкин"),
    ("Переславский", "Переславль-Залесский"),
    ("Пошехонский", ""),
    ("Романово-Борисоглебский", "с 1919 — Тутаев"),
    ("Ростовский", ""),
    ("Рыбинский", ""),
    ("Угличский", ""),
    ("Ярославский", "центр — г. Ярославль"),
]:
    add_uyezd("Ярославская", f"{u[0]} уезд", 1796, 1929, u[1])


# ── Поиск или создание базы ───────────────────────────────────────────────────
print("1. Ищем базу «Административные единицы» в Notion...")
search = api("POST", "https://api.notion.com/v1/search", {
    "query": "Административные единицы",
    "filter": {"value": "database", "property": "object"},
})
db_id = None
for obj in search.get("results", []):
    title = obj.get("title", [])
    name = title[0]["plain_text"] if title else ""
    if "Административные единицы" in name:
        db_id = obj["id"]
        print(f"   Найдена существующая база: {db_id}")
        break

if not db_id:
    print("   База не найдена — создаём новую...")
    # Получаем любую доступную страницу для parent
    pages_resp = api("POST", "https://api.notion.com/v1/search", {
        "filter": {"value": "page", "property": "object"},
        "page_size": 1,
    })
    parent_results = pages_resp.get("results", [])
    if not parent_results:
        print("ОШИБКА: нет доступных страниц для создания базы")
        sys.exit(1)
    parent_id = parent_results[0]["id"]
    parent_type = parent_results[0].get("parent", {}).get("type", "page_id")

    new_db = api("POST", "https://api.notion.com/v1/databases", {
        "parent": {"type": "page_id", "page_id": parent_id},
        "title": [{"type": "text", "text": {"content": "Административные единицы"}}],
        "properties": {
            "Название": {"title": {}},
            "Губерния": {
                "select": {
                    "options": [
                        {"name": "Калужская",   "color": "blue"},
                        {"name": "Пермская",    "color": "green"},
                        {"name": "Смоленская",  "color": "orange"},
                        {"name": "Ярославская", "color": "purple"},
                    ]
                }
            },
            "Тип": {
                "select": {
                    "options": [
                        {"name": "Губерния",      "color": "red"},
                        {"name": "Уезд",          "color": "gray"},
                        {"name": "Наместничество","color": "yellow"},
                    ]
                }
            },
            "Период с":  {"number": {"format": "number"}},
            "Период по": {"number": {"format": "number"}},
            "Примечания": {"rich_text": {}},
        },
    })
    db_id = new_db["id"]
    print(f"   ✓ База создана: {db_id}")

# ── Добавление записей ────────────────────────────────────────────────────────
print(f"\n2. Добавляем {len(UNITS)} записей...")
success = errors = 0

for unit in UNITS:
    props: dict = {
        "Название":   {"title": [{"text": {"content": unit["name"]}}]},
        "Губерния":   {"select": {"name": unit["gub"]}},
        "Тип":        {"select": {"name": unit["type"]}},
        "Период с":   {"number": unit["from"]},
        "Период по":  {"number": unit["to"]},
    }
    if unit["note"]:
        props["Примечания"] = {"rich_text": [{"text": {"content": unit["note"]}}]}

    try:
        api("POST", "https://api.notion.com/v1/pages", {
            "parent": {"database_id": db_id},
            "properties": props,
        })
        success += 1
        time.sleep(0.35)
    except RuntimeError as e:
        errors += 1
        print(f"   Ошибка [{unit['name']}]: {e}")

print(f"\n✓ Готово: добавлено {success}, ошибок {errors}")
print(f"   ID базы «Административные единицы»: {db_id}")
print(f"   Notion: https://notion.so/{db_id.replace('-', '')}")
