"""
Мост: богатый notion_import.csv → Notion «Каталог» с дедупом (вариант а2, канон п.5).

Санкционированный писатель на REST-токене (НЕ MCP): берёт обогащённый notion_import.csv
(маппинг notion_export/prlib_card, п.1), проставляет статусный слой приёмки и пишет в базу
«Каталог» с дедупом по «Ссылка на онлайн-архив» (prlib без фонд/опись, поэтому ключ — URL
карточки). Токен NOTION_TOKEN из Каталогизация/.env (как в notion_archive_pages.py).

Запуск:
  python scripts/notion_upload_candidates.py output/<run>/review_run --date 2026-09-22 --dry-run
  python scripts/notion_upload_candidates.py output/<run>/review_run --date 2026-09-22
"""
import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "modules"))
import notion_export as ne  # noqa: E402  (PROPERTIES — типы колонок схемы)

PROPS = ne.PROPERTIES
DB_ID = "5ead971c-b9bd-4bc2-90d8-73d0841b1f93"
ENV = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
URL_COL = "Ссылка на онлайн-архив"
VALID_REASONS = {"сомнительный тип", "нет маркера карты", "регион неясен", "год не указан"}


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


def to_prop(col: str, val: str):
    """CSV-значение → свойство Notion REST по типу колонки схемы."""
    v = (val or "").strip()
    if not v:
        return None
    t = PROPS.get(col, {}).get("type")
    if t == "title":
        return {"title": [{"text": {"content": v[:2000]}}]}
    if t == "text":
        return {"rich_text": [{"text": {"content": v[:2000]}}]}
    if t == "number":
        try:
            return {"number": int(v) if v.lstrip("-").isdigit() else float(v)}
        except ValueError:
            return None
    if t == "url":
        return {"url": v}
    if t == "select":
        return {"select": {"name": v}}
    return None  # relation / date / multi_select / formula / rollup — отдельно/пропуск


def load_reasons(review_csv: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if review_csv.exists():
        for r in csv.DictReader(io.open(review_csv, encoding="utf-8-sig")):
            url = (r.get("URL") or "").strip()
            rs = [p.strip() for p in (r.get("Причина") or "").split(",") if p.strip() in VALID_REASONS]
            if url:
                out[url] = rs
    return out


def is_dup(url: str) -> bool:
    if not url:
        return False
    body = {"filter": {"property": URL_COL, "url": {"equals": url}}, "page_size": 1}
    res = api("POST", f"https://api.notion.com/v1/databases/{DB_ID}/query", body)
    return len(res.get("results", [])) > 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("review_run", type=Path)
    ap.add_argument("--date", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not TOKEN:
        print("Нет NOTION_TOKEN (env или Каталогизация/.env)")
        sys.exit(1)

    d = a.review_run
    csv_path = d / "notion_import.csv"
    if not csv_path.exists():
        print(f"Нет {csv_path} — сначала make_notion_pages.py")
        sys.exit(1)
    reasons = load_reasons(d / "review.csv")
    review_urls = {json.loads(x)["record"].get("url", "")
                   for x in io.open(d / "review_records.jsonl", encoding="utf-8-sig") if x.strip()} \
        if (d / "review_records.jsonl").exists() else set()

    rows = list(csv.DictReader(io.open(csv_path, encoding="utf-8-sig")))
    added = skipped = errors = 0
    for r in rows:
        url = (r.get(URL_COL) or "").strip()
        props: dict = {}
        for col, val in r.items():
            p = to_prop(col, val)
            if p is not None:
                props[col] = p
        props["Статус приёмки"] = {"select": {"name": "кандидат"}}
        props["Автор внесения"] = {"select": {"name": "Агент"}}
        props["Дата внесения"] = {"date": {"start": a.date}}
        rs = reasons.get(url, []) if url in review_urls else []
        if rs:
            props["Причина сомнительности"] = {"multi_select": [{"name": x} for x in rs]}
        title = r.get("Название источника", "")[:60]
        if is_dup(url):
            skipped += 1
            continue
        if a.dry_run:
            added += 1
            continue
        try:
            api("POST", "https://api.notion.com/v1/pages",
                {"parent": {"database_id": DB_ID}, "properties": props})
            added += 1
            time.sleep(0.34)
        except RuntimeError as e:
            errors += 1
            print(f"  Ошибка [{title}]: {e}")

    tag = "DRY-RUN " if a.dry_run else ""
    print(f"{tag}добавлено: {added} | дубликатов (пропущено): {skipped} | ошибок: {errors}")


if __name__ == "__main__":
    main()
