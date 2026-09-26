"""
Линковка записей к сериям справочника «Серийные массивы» по алиасам (шаг 2 разбора ПрБ).

Для каждой записи с ПУСТЫМ «Серия / массив»: если название/описание совпало с алиасом серии →
связать «Серия / массив»; если «Номер в серии» пуст и извлекается «Т./Вып./кн. N» → проставить.
Инвариант Д18 соблюдён: номер ставится вместе с серией.

Запуск: python scripts/maintenance/link_series.py [--dry-run]
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

# (regex по тексту названия+описания, page_id серии, метка)
SERIES = [
    (r"цветущее состояние|атлас всероссийской империи|атлас кирилова",
     "3e70ba89-eabe-81c1-8d40-ef4cc83408d5", "Атлас Всероссийской империи (Кирилов)"),
    (r"краткая сибирская летопись|чертёжная книга сибири|чертежная книга сибири|"
     r"кунгурская летопись|хорографическая",
     "3e70ba89-eabe-8156-886b-ef47acc52078", "Чертёжные книги Сибири (Ремезов)"),
    (r"руднев",
     "3e70ba89-eabe-812f-b2b6-cc41b38dacb1", "Карты губерний Д. Руднева, 1913"),
    (r"чердынский край",
     "3e70ba89-eabe-8197-9b02-c71d0fc5fbe6", "Чердынский край"),
]
_NUM_RE = re.compile(r"(?:вып\.?|т\.?|кн\.?)\s*([0-9IVXLC][0-9IVXLC\-]*)", re.I)


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


def rt(pr: dict, k: str) -> str:
    return "".join(x.get("plain_text", "") for x in pr.get(k, {}).get("rich_text", []))


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

    linked = numbered = errors = 0
    for p in pages:
        pr = p["properties"]
        if pr.get("Серия / массив", {}).get("relation"):
            continue  # уже связана
        title = "".join(x.get("plain_text", "") for x in
                        pr.get("Название источника", {}).get("title", []))
        text = (title + " " + rt(pr, "Описание")).lower().replace("ё", "е")
        sid = label = None
        for pat, pid, lab in SERIES:
            if re.search(pat.replace("ё", "е"), text):
                sid, label = pid, lab
                break
        if not sid:
            continue
        patch: dict = {"Серия / массив": {"relation": [{"id": sid}]}}
        note = ""
        if not rt(pr, "Номер в серии").strip():
            m = _NUM_RE.search(title)
            if m:
                patch["Номер в серии"] = {"rich_text": [{"text": {"content": m[1]}}]}
                note = f" + номер {m[1]}"
                numbered += 1
        print(f"{'DRY ' if a.dry_run else ''}СЕРИЯ→ {label}{note} | {title[:50]}")
        linked += 1
        if a.dry_run:
            continue
        try:
            api("PATCH", f"https://api.notion.com/v1/pages/{p['id']}", {"properties": patch})
            time.sleep(0.34)
        except RuntimeError as e:
            errors += 1
            print(f"  Ошибка: {e}")

    print(f"\n{'DRY-RUN ' if a.dry_run else ''}связано серий: {linked} | из них с номером: {numbered} | ошибок: {errors}")


if __name__ == "__main__":
    main()
