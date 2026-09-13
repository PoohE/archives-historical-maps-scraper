"""Объединение нормализованных федеральных слоёв и выгрузок РГАДА."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path

FIELDS = [
    "source", "record_type", "territory", "query", "title", "year_from",
    "year_to", "identifier", "url", "description", "coverage_status",
    "retrieval_date", "source_run",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def rgada_rows(path: Path, territory: str, query: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in read_csv(path):
        title = f"Фонд {row['fund_number']}: {row['fund_name']}; Опись {row['list_number']}: {row['list_name']}"
        description = "; ".join(value for value in (
            f"Хранилище: {row['repository']}" if row["repository"] else "",
            f"Годы: {row['years']}" if row["years"] else "",
            f"Дел: {row['case_count']}" if row["case_count"] else "",
            row["annotation"],
        ) if value)
        rows.append({
            "source": "rgada", "record_type": "archival_inventory",
            "territory": territory, "query": query, "title": title,
            "year_from": row["year_from"], "year_to": row["year_to"],
            "identifier": f"Ф.{row['fund_number']} Оп.{row['list_number']}",
            "url": row["url"], "description": description,
            "coverage_status": "inventory_search_full_pagination",
            "retrieval_date": "2026-09-07", "source_run": path.name,
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Собрать производный федеральный слой")
    parser.add_argument("--base", action="append", required=True, help="Нормализованный CSV; можно указать несколько раз")
    parser.add_argument("--rgada", action="append", default=[], metavar="ТЕРРИТОРИЯ=CSV", help="Выгрузка РГАДА")
    parser.add_argument("--output", required=True, help="Новый CSV")
    parser.add_argument("--summary", required=True, help="JSON-сводка")
    parser.add_argument("--retrieval-date", default=date.today().isoformat(),
                        help="Дата сборки производного слоя (YYYY-MM-DD)")
    args = parser.parse_args()

    rows: list[dict[str, str]] = []
    for value in args.base:
        rows.extend(read_csv(Path(value)))
    for value in args.rgada:
        territory, _, path = value.partition("=")
        if not territory or not path:
            parser.error(f"Неверный --rgada: {value!r}")
        query = {"Калужская губерния": "Калуж", "Пермская губерния": "Перм", "Смоленская губерния": "Смоленск", "Ярославская губерния": "Ярослав"}.get(territory, territory)
        rows.extend(rgada_rows(Path(path), territory, query))

    unique: dict[str, dict[str, str]] = {}
    for row in rows:
        url = row.get("url", "").strip()
        if url and url not in unique:
            unique[url] = {field: row.get(field, "") for field in FIELDS}
    result = list(unique.values())
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(result)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    counts: dict[str, int] = {}
    for row in result:
        counts[row["source"]] = counts.get(row["source"], 0) + 1
    summary = {"schema": FIELDS, "output": output.name, "rows_input": len(rows), "rows_unique_by_url": len(result), "counts_by_source": counts, "sha256": digest, "retrieval_date": args.retrieval_date, "limitations": ["РГАДА даёт карточки описей, а не отдельные дела; map-like фильтрация выполняется отдельно."]}
    Path(args.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
