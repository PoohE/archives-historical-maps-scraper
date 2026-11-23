# -*- coding: utf-8 -*-
"""Приёмка заливки по журналу созданных страниц: чтение каждой страницы по page id.

Зачем. Итоговая строка моста («создано: N | ошибок: 0») — это счётчик удачных ответов API,
а не состояние базы: 16.11.2026 по пакету Белинки она показала 30 при шести реально
созданных записях. Поиск по базе для приёмки тоже не годится — фильтр по ссылке на каталоге
из 112 тыс. записей отвечает с задержкой. Единственная надёжная сверка — GET страницы по id
из журнала `created_pages.jsonl`, который мост пишет построчно.

Сверяются: ссылка, ключевые поля пакета (из того же CSV), непустые relation «Архив
хранения»/«Тип источника», признак archived.

  python scripts/verify_created_pages.py output/upload_2026-11-16/rgia_review_run
  python scripts/verify_created_pages.py <run_dir> --sample 20
"""

import argparse
import csv
import io
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import notion_upload_candidates as nu  # noqa: E402

URL_COL = nu.URL_COL
CHECK_COLS = ["Название источника", "Фонд", "Опись", "Единица хранения",
              "Статус доступа", "Год создания (нижняя)", "Год создания (верхняя)",
              "Библиотечный шифр", "Место хранения"]


def value(page: dict, col: str):
    p = (page.get("properties") or {}).get(col) or {}
    t = p.get("type")
    if t == "url":
        return p.get("url") or ""
    if t == "title":
        return "".join(x.get("plain_text", "") for x in p.get("title") or [])
    if t == "rich_text":
        return "".join(x.get("plain_text", "") for x in p.get("rich_text") or [])
    if t == "number":
        return "" if p.get("number") is None else str(p["number"])
    if t == "select":
        return ((p.get("select") or {}).get("name")) or ""
    if t == "relation":
        return [r["id"] for r in p.get("relation") or []]
    if t == "date":
        return ((p.get("date") or {}).get("start")) or ""
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--sample", type=int, default=0, help="проверить случайную выборку, не всё")
    a = ap.parse_args()
    d = Path(a.run_dir)

    journal = [json.loads(x) for x in (d / "created_pages.jsonl").open(encoding="utf-8")
               if x.strip()]
    rows = {r[URL_COL]: r for r in csv.DictReader(
        io.open(d / "notion_import.csv", encoding="utf-8-sig"))}
    print(f"{d.name}: в журнале {len(journal)} страниц, в пакете {len(rows)} записей")

    todo = journal
    if a.sample:
        random.seed(1)
        todo = random.sample(journal, min(a.sample, len(journal)))
        print(f"выборка: {len(todo)}")

    defects: list[tuple] = []
    read = 0
    for i, j in enumerate(todo, 1):
        try:
            page = nu.api("GET", f"https://api.notion.com/v1/pages/{j['page_id']}")
        except RuntimeError as e:
            defects.append((j["url"], "страница", f"не читается: {e}", ""))
            continue
        read += 1
        src = rows.get(j["url"])
        if page.get("archived"):
            defects.append((j["url"], "страница", "в архиве (удалена)", ""))
        if value(page, URL_COL) != j["url"]:
            defects.append((j["url"], URL_COL, value(page, URL_COL), j["url"]))
        if src:
            for col in CHECK_COLS:
                if col not in src:
                    continue
                got, exp = str(value(page, col) or "").strip(), str(src.get(col) or "").strip()
                if col == "Название источника":
                    got, exp = got[:120], exp[:120]
                if got != exp:
                    defects.append((j["url"], col, got[:80], exp[:80]))
        if not value(page, "Архив хранения"):
            defects.append((j["url"], "Архив хранения", "пусто", "relation"))
        if i % 50 == 0:
            print(f"  … {i}/{len(todo)}: прочитано {read}, расхождений {len(defects)}")

    print(f"\nпрочитано страниц: {read} из {len(todo)}; расхождений: {len(defects)}")
    for x in defects[:40]:
        print(f"  {x[0][:60]}\n    {x[1]}: получено «{x[2]}» ≠ ожидалось «{x[3]}»")
    if defects:
        out = d / "verify_defects.json"
        out.write_text(json.dumps(
            [{"url": x[0], "поле": x[1], "в_базе": x[2], "в_пакете": x[3]} for x in defects],
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"→ {out}")


if __name__ == "__main__":
    main()
