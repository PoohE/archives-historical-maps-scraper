"""
Разовый sweep «Статус доступа» (поле 16, канон Приложение Г → COAR).

Авто-правило (подтверждено 2026-09-26):
  1) явные слова в тексте (Описание/Примечания):
       эмбарго / «открывается … <дата>»        → Эмбарго
       читальный зал / по разрешению / регистрац / платн → Ограниченный доступ
  2) иначе по цифровой копии:
       галерея титульных/обложек (полной копии нет) → Ограниченный доступ
       «Цифровая копия» = есть (поле 19/63)         → Открытый доступ
       «Цифровая копия» = нет и галереи нет         → Только метаданные
  3) противоречие/неясно → пусто + review (не угадывать).

Заполняет ТОЛЬКО пустой «Статус доступа». ГПИБ (shpl.ru) ИСКЛЮЧЕНЫ (битые, ждут пере-сбора).

Запуск: python scripts/maintenance/sweep_access_status.py [--dry-run]
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
DB_ID = "5ead971c-b9bd-4bc2-90d8-73d0841b1f93"
ENV = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")

EMBARGO_RE = re.compile(r"эмбарго|открыва\w+\s+(?:в|после|с)\s+\d{4}|рассекреч", re.I)
RESTRICT_RE = re.compile(r"читальн\w+\s+зал|по\s+разрешени|регистрац|платн|огранич\w+\s+доступ", re.I)
GALLERY_RE = re.compile(r"галере|титульн", re.I)


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


def decide(pr: dict):
    text = rt(pr, "Описание") + "\n" + rt(pr, "Примечания")
    if EMBARGO_RE.search(text):
        return "Эмбарго"
    if RESTRICT_RE.search(text):
        return "Ограниченный доступ"
    if GALLERY_RE.search(rt(pr, "Примечания")):
        return "Ограниченный доступ"
    copy = (pr.get("Цифровая копия (есть/нет)", {}).get("formula") or {}).get("string")
    if copy == "есть":
        return "Открытый доступ"
    if copy == "нет":
        return "Только метаданные"
    return None  # неясно → пусто


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

    dist = Counter()
    setn = skip_gpib = skip_filled = nomatch = errors = 0
    for p in pages:
        pr = p["properties"]
        url = pr.get("Ссылка на онлайн-архив", {}).get("url") or ""
        if "shpl.ru" in url:  # ГПИБ — битые, ждут пере-сбора
            skip_gpib += 1
            continue
        if (pr.get("Статус доступа", {}).get("select") or {}).get("name"):
            skip_filled += 1
            continue
        val = decide(pr)
        if not val:
            nomatch += 1
            continue
        dist[val] += 1
        setn += 1
        if a.dry_run:
            continue
        try:
            api("PATCH", f"https://api.notion.com/v1/pages/{p['id']}",
                {"properties": {"Статус доступа": {"select": {"name": val}}}})
            time.sleep(0.34)
        except RuntimeError as e:
            errors += 1
            print(f"  Ошибка: {e}")

    print(f"{'DRY-RUN ' if a.dry_run else ''}проставлено: {setn} | распределение: {dict(dist)}")
    print(f"пропущено ГПИБ: {skip_gpib} | уже заполнено: {skip_filled} | "
          f"неясно(пусто): {nomatch} | ошибок: {errors}")


if __name__ == "__main__":
    main()
