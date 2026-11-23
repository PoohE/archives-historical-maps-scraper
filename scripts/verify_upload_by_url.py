# -*- coding: utf-8 -*-
"""Приёмка заливки: сверка пакета notion_import.csv с тем, что реально легло в каталог.

Зачем. 16.11.2026 мост доложил «создано: 30 | ошибок: 0» по пакету Белинки, а проверка по
ссылке нашла в базе 6 записей из 30. Доклад моста — это ответы API на создание, а не
состояние базы; принимать заливку нужно отдельным чтением (правило проекта: приёмка по
артефакту, а не по докладу исполнителя).

Что делает: по каждому URL пакета — фильтр по «Ссылке на онлайн-архив»; не найдено —
дополнительный поиск по НАЧАЛУ названия, чтобы отличить «запись не создана» от
«создана, но с другой ссылкой» и от запаздывания индексации.

  python scripts/verify_upload_by_url.py output/upload_2026-11-16/belinka_review_run [--limit N]
"""

import argparse
import csv
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import notion_upload_candidates as nu  # noqa: E402  (токен, api(), DB_ID, URL_COL)

TITLE_COL = "Название источника"


def by_url(url: str) -> list[dict]:
    body = {"filter": {"property": nu.URL_COL, "url": {"equals": url}}, "page_size": 5}
    return nu.api("POST", f"https://api.notion.com/v1/databases/{nu.DB_ID}/query",
                  body).get("results", [])


def by_title(title: str) -> list[dict]:
    body = {"filter": {"property": TITLE_COL, "title": {"starts_with": title[:60]}},
            "page_size": 5}
    return nu.api("POST", f"https://api.notion.com/v1/databases/{nu.DB_ID}/query",
                  body).get("results", [])


def plain(page: dict, col: str) -> str:
    p = (page.get("properties") or {}).get(col) or {}
    if p.get("type") == "url":
        return p.get("url") or ""
    if p.get("type") == "title":
        return "".join(x.get("plain_text", "") for x in p.get("title") or [])
    if p.get("type") == "date":
        return ((p.get("date") or {}).get("start")) or ""
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    csv_path = Path(a.run_dir) / "notion_import.csv"
    rows = list(csv.DictReader(io.open(csv_path, encoding="utf-8-sig")))
    if a.limit:
        rows = rows[:a.limit]
    print(f"{csv_path}: проверяем {len(rows)} записей")

    found, missing = 0, []
    for i, r in enumerate(rows, 1):
        url, title = r[nu.URL_COL], r[TITLE_COL]
        hits = by_url(url)
        if hits:
            found += 1
        else:
            missing.append((url, title))
        if i % 25 == 0:
            print(f"  … {i}: найдено {found}, нет {len(missing)}")

    print(f"\nпо ссылке найдено: {found} из {len(rows)}; не найдено: {len(missing)}")
    report = []
    for url, title in missing[:40]:
        alts = by_title(title)
        info = [{"url": plain(p, nu.URL_COL), "дата внесения": plain(p, "Дата внесения"),
                 "page": p.get("id", "")} for p in alts]
        report.append({"искали_url": url, "название": title[:120], "по_названию": info})
        print(f"\nНЕТ: {url}\n  {title[:110]}")
        for x in info:
            print(f"    в базе: {x['url']}  внесено {x['дата внесения']}")
    if report:
        out = Path(a.run_dir) / "verify_missing.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n→ {out}")


if __name__ == "__main__":
    main()
