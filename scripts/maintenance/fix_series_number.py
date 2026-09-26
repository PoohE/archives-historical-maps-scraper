"""
Правка нарушений Д18: «Номер в серии» заполнен, а «Серия / массив» пуст.

Для каждой такой записи:
  - название совпало с алиасом СУЩЕСТВУЮЩЕЙ серии справочника → связать «Серия / массив»
    (номер-том остаётся валидным, не трогаем);
  - серия не найдена в справочнике → ОЧИСТИТЬ «Номер в серии» (том остаётся в «Описании»;
    новую серию заводит эксперт — канон Д18).

Запуск: python scripts/maintenance/fix_series_number.py [--dry-run]
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

# алиас (regex по названию, ниж. регистр) -> (page_id серии, метка)
SERIES = [
    (r"материалы\s+для\s+географии\s+и\s+статистики", "3db0ba89-eabe-8132-9b06-c2f57010112e", "Материалы для географии и статистики России"),
    (r"военно-?статистическ\w*\s+обозрени", "3830ba89-eabe-8160-b35d-e6f9975a77c8", "Военно-статистические обозрения"),
    (r"список\s+населенных\s+пунктов\s+уральск|труды\s+уральского\s+областного\s+статистическ", "3e70ba89-eabe-8164-a802-e2a99ae9db13", "Список населённых пунктов Уральской области"),
]


def match_series(title: str):
    t = (title or "").lower().replace("ё", "е")
    for pat, pid, label in SERIES:
        if re.search(pat, t):
            return pid, label
    return None, None


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

    linked = pending = errors = 0
    for p in pages:
        pr = p["properties"]
        num = rt(pr.get("Номер в серии", {})).strip()
        ser = pr.get("Серия / массив", {}).get("relation", [])
        if not num or ser:  # нарушение = номер есть, серии нет
            continue
        title = "".join(x.get("plain_text", "") for x in
                        pr.get("Название источника", {}).get("title", []))
        pid, label = match_series(title)
        if pid:
            print(f"{'DRY ' if a.dry_run else ''}СЕРИЯ→ {label} (том {num}) | {title[:48]}")
            linked += 1
            if not a.dry_run:
                try:
                    api("PATCH", f"https://api.notion.com/v1/pages/{p['id']}",
                        {"properties": {"Серия / массив": {"relation": [{"id": pid}]}}})
                    time.sleep(0.34)
                except RuntimeError as e:
                    errors += 1
                    print(f"  Ошибка: {e}")
        else:
            # серии нет в справочнике — НЕ чистим, помечаем на регистрацию (решение эксперта)
            print(f"[НА РЕГИСТРАЦИЮ] серия не в справочнике, номер {num} оставлен | {title[:48]}")
            pending += 1

    print(f"\n{'DRY-RUN ' if a.dry_run else ''}связано серий: {linked} | "
          f"на регистрацию серии: {pending} | ошибок: {errors}")


if __name__ == "__main__":
    main()
