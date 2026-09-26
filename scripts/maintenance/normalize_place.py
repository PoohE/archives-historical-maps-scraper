"""
Разовая нормализация поля «Место создания» в Notion (канон v1.6, модуль place_normalize).

Для каждой записи с непустым «Место создания»:
  1) normalize(raw);
  2) если raw = мусор (пусто+причина) — попытка восстановить из «Описания» (место издания);
  3) пишет новое значение, только если оно ОТЛИЧАЕТСЯ от текущего;
  4) нераспознанное и невосстановимое → очищает поле + добавляет причину «регион неясен»
     в «Причина сомнительности» ТОЛЬКО у записей со статусом «кандидат» (не трогая принятые).

Запуск:
  python scripts/maintenance/normalize_place.py --dry-run
  python scripts/maintenance/normalize_place.py
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
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "modules"))
import place_normalize as pn  # noqa: E402

DB_ID = "5ead971c-b9bd-4bc2-90d8-73d0841b1f93"
ENV = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
PLACE = "Место создания"
DESC = "Описание"


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

    changed = recovered = cleared = same = errors = 0
    rows = []
    for p in pages:
        pr = p["properties"]
        raw = rt(pr.get(PLACE, {})).strip()
        if not raw:
            continue
        value, reason = pn.normalize(raw)
        src = "normalize"
        if not value:  # мусор — пробуем восстановить из Описания
            value, reason = pn.recover_from_description(rt(pr.get(DESC, {})))
            src = "recover" if value else "reject"
        if value == raw:
            same += 1
            continue

        status = (pr.get("Статус приёмки", {}).get("select") or {}).get("name", "")
        patch: dict = {PLACE: {"rich_text": [{"text": {"content": value}}] if value else []}}
        # нераспознанное → чистим поле + флаг только у кандидатов
        if not value and status == "кандидат":
            cur = [o["name"] for o in pr.get("Причина сомнительности", {}).get("multi_select", [])]
            if "регион неясен" not in cur:
                patch["Причина сомнительности"] = {
                    "multi_select": [{"name": n} for n in cur + ["регион неясен"]]}

        rows.append((raw, value, src))
        if value and src == "recover":
            recovered += 1
        elif value:
            changed += 1
        else:
            cleared += 1
        if a.dry_run:
            continue
        try:
            api("PATCH", f"https://api.notion.com/v1/pages/{p['id']}", {"properties": patch})
            time.sleep(0.34)
        except RuntimeError as e:
            errors += 1
            print(f"  Ошибка [{raw}]: {e}")

    print(f"{'DRY-RUN ' if a.dry_run else ''}таблица изменений (старое → новое | источник):")
    for raw, value, src in sorted(rows):
        print(f"  {raw!r:34} → {value!r:22} | {src}")
    print(f"\nнормализовано: {changed} | восстановлено из Описания: {recovered} | "
          f"очищено(мусор): {cleared} | без изменений: {same} | ошибок: {errors}")


if __name__ == "__main__":
    main()
