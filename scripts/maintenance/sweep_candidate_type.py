"""
Разовый sweep кандидатной типизации (реш. Д13, канон поле 9) по записям ПрБ.

Для записей ПрБ (Ссылка ~ prlib.ru), где «Тип источника» пуст:
  классифицирует по названию (правила канона табл. 7) → кандидатный код A1–C8;
  ставит relation «Тип источника» + select «DC Type» (A→StillImage, B→Text, C→Dataset);
  добавляет «сомнительный тип» в «Причина сомнительности» (у статуса «кандидат»).
Нет уверенного совпадения → поле оставляется пустым (канон: не угадывать) + флаг «сомнительный тип».
Если тип уже стоит, а DC Type пуст — досчитывает DC Type из класса существующего типа.
Никогда не перезаписывает уже заполненный «Тип источника».

Запуск:
  python scripts/maintenance/sweep_candidate_type.py --dry-run
  python scripts/maintenance/sweep_candidate_type.py
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DB_ID = "5ead971c-b9bd-4bc2-90d8-73d0841b1f93"
ENV = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")

# код -> (page_id справочника «Типы источников», DC Type)
TYPES = {
    "A1": ("3830ba89-eabe-816d-a278-cf6ce9cdeec6", "StillImage"),
    "A2": ("3830ba89-eabe-816e-90d4-eced7e4ce20f", "StillImage"),
    "A3": ("3830ba89-eabe-81e8-8960-d51ab3be3447", "StillImage"),
    "A4": ("3830ba89-eabe-81cc-9d0c-f59aadf5b7a5", "StillImage"),
    "A5": ("3830ba89-eabe-8180-a87d-d5d89c0de70d", "StillImage"),
    "A6": ("3830ba89-eabe-8171-ac4a-ee07e78f3a7e", "StillImage"),
    "B1": ("3830ba89-eabe-81e4-a556-e21acc3f6e0c", "Text"),
    "B2": ("3830ba89-eabe-812b-8503-fc918c8a2b0b", "Text"),
    "B3": ("3830ba89-eabe-8130-8a81-d77acb844014", "Text"),
    "B4": ("3830ba89-eabe-810d-84c8-dfe35b8466b4", "Text"),
    "B5": ("3830ba89-eabe-81fd-bdf8-f1b7b79d8ecc", "Text"),
    "B6": ("3c30ba89-eabe-8161-b533-c149b6f12aa8", "Text"),
    "B7": ("3c30ba89-eabe-8151-8c38-fdd4e2985b8e", "Text"),
    "B8": ("3c30ba89-eabe-8156-867d-d8a6f3cec753", "Text"),
    "B9": ("3c30ba89-eabe-8142-b399-fca594cb25be", "Text"),
    "B10": ("3c30ba89-eabe-8101-9c97-e344090c601a", "Text"),
    "C1": ("3830ba89-eabe-8194-a3fa-c6c650b8c17f", "Dataset"),
    "C2": ("3830ba89-eabe-81ad-8901-f650b6242362", "Dataset"),
    "C3": ("3830ba89-eabe-81b5-bcb5-ffb41e8b7f3c", "Dataset"),
    "C4": ("3830ba89-eabe-8110-b837-eb024a84ab10", "Dataset"),
    "C5": ("3830ba89-eabe-8111-b3c6-ef6c621450d8", "Dataset"),
    "C6": ("3c30ba89-eabe-8138-a95b-e689a21f51d2", "Dataset"),
    "C7": ("3c30ba89-eabe-8104-8ccb-fb73355a9995", "Dataset"),
    "C8": ("3c30ba89-eabe-8151-90af-e8effdfab49d", "Dataset"),
}
ID2CODE = {pid.replace("-", ""): code for code, (pid, _) in TYPES.items()}

# Правила классификации (канон табл. 7), порядок = приоритет, первое совпадение.
RULES = [
    (r"списк[аи]?\s+населенн|список\s+населенн", "C7"),
    (r"военно-статистическ", "C4"),
    (r"материалы\s+для\s+географии\s+и\s+статистики", "C4"),
    (r"памятн(ая|ые)\s+книжк", "C5"),
    (r"(всеобщ|перв)\w*\s+перепис|перепись\s+населени", "C3"),
    (r"сельскохозяйствен\w*\s+перепис", "C8"),
    (r"экономическ\w+\s+примечани", "B6"),
    (r"ревизск", "B3"),
    (r"писцов|переписн\w*\s+книг", "B4"),
    (r"географ\w*-?статистическ\w*\s+словар", "B7"),
    (r"памятная\s+книга", "C5"),
    (r"генеральн\w+\s+межевани", "C1"),
    (r"экономическ\w+\s+сборник|статистическ\w+\s+(сборник|ежегодник|обзор)", "C2"),
    (r"топографическ\w+\s+описани", "B2"),
    (r"(историческо?-?географическ\w*|географическ\w*|статистическ\w*)\s+описани", "B2"),
    (r"путеводитель", "B5"),
    (r"объяснительн\w+\s+записк|услов\w+\s+знак", "B1"),
    (r"межев\w+\s+(книг|описани)", "B8"),
    (r"план\w*\s+дач", "A3"),
    (r"(трех|трёх|двух)верст|верстк", "A4"),
    (r"план\w*\s+(город|губернск\w+\s+город|наместническ)", "A6"),
    (r"атлас", "A2"),
    (r"карт\w+.*(уезд)", "A2"),
    (r"карт\w+.*(губерни|наместнич|област)", "A1"),
    (r"(лесн|заводск|этнограф|промышлен|почтов|дорог|путей\s+сообщени)\w*\s+карт|карт\w+\s+(лесн|путей)", "A5"),
]


def classify(title: str):
    t = (title or "").lower().replace("ё", "е")
    for pat, code in RULES:
        if re.search(pat, t):
            return code
    return None


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

    assigned = dc_only = nomatch = skip = errors = 0
    rows = []
    for p in pages:
        pr = p["properties"]
        url = pr.get("Ссылка на онлайн-архив", {}).get("url") or ""
        if "prlib.ru" not in url:
            continue
        title = "".join(x.get("plain_text", "") for x in
                        pr.get("Название источника", {}).get("title", []))
        cur_type = pr.get("Тип источника", {}).get("relation", [])
        cur_dc = (pr.get("DC Type", {}).get("select") or {}).get("name")
        status = (pr.get("Статус приёмки", {}).get("select") or {}).get("name", "")
        patch: dict = {}

        if cur_type:  # тип уже есть — досчитать DC Type при пустоте
            if not cur_dc:
                code = ID2CODE.get(cur_type[0]["id"].replace("-", ""))
                if code:
                    patch["DC Type"] = {"select": {"name": TYPES[code][1]}}
                    dc_only += 1
                    rows.append((title[:50], f"(тип {code}) DC→{TYPES[code][1]}"))
            else:
                skip += 1
        else:
            code = classify(title)
            if code:
                pid, dc = TYPES[code]
                patch["Тип источника"] = {"relation": [{"id": pid}]}
                patch["DC Type"] = {"select": {"name": dc}}
                if status == "кандидат":
                    cur_r = [o["name"] for o in pr.get("Причина сомнительности", {}).get("multi_select", [])]
                    if "сомнительный тип" not in cur_r:
                        patch["Причина сомнительности"] = {
                            "multi_select": [{"name": n} for n in cur_r + ["сомнительный тип"]]}
                assigned += 1
                rows.append((title[:50], f"→ {code} / {dc}"))
            else:
                nomatch += 1
                rows.append((title[:50], "→ не определён (пусто)"))

        if patch and not a.dry_run:
            try:
                api("PATCH", f"https://api.notion.com/v1/pages/{p['id']}", {"properties": patch})
                time.sleep(0.34)
            except RuntimeError as e:
                errors += 1
                print(f"  Ошибка [{title[:40]}]: {e}")

    print(f"{'DRY-RUN ' if a.dry_run else ''}типизация ПрБ:")
    for t, r in sorted(rows, key=lambda x: x[1]):
        print(f"  {r:26} | {t}")
    print(f"\nназначено тип+DC: {assigned} | досчитан DC: {dc_only} | "
          f"не определён: {nomatch} | уже был тип: {skip} | ошибок: {errors}")


if __name__ == "__main__":
    main()
