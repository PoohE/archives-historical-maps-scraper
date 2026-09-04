#!/usr/bin/env python3
"""Консервативно дедуплицирует результаты поиска исторических карт.

Исходный CSV не изменяется. Автоматически удаляются только записи с одинаковым
непустым URL. Возможные семантические дубли (нормализованное название + годы)
сохраняются в отдельном CSV для ручного решения.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path


REQUIRED_COLUMNS = {"Источник", "Название", "Год от", "Год до", "URL"}


def normalized_title(value: str) -> str:
    """Нормализует заголовок только для списка кандидатов, не для удаления."""
    value = value.lower().replace("ё", "е")
    return re.sub(r"[^0-9a-zа-я]+", " ", value).strip()


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("В CSV отсутствует строка заголовка")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"В CSV отсутствуют обязательные столбцы: {', '.join(sorted(missing))}")
        return reader.fieldnames, list(reader)


def deduplicate(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Возвращает канонические записи и журнал исключённых полных URL-дублей."""
    kept: list[dict[str, str]] = []
    seen_urls: dict[str, tuple[int, dict[str, str]]] = {}
    removed: list[dict[str, str]] = []

    for index, row in enumerate(rows, start=2):  # строка 1 — заголовок
        url = row["URL"].strip()
        if url and url in seen_urls:
            kept_line, canonical = seen_urls[url]
            removed.append({
                "исключённая_строка": str(index),
                "каноническая_строка": str(kept_line),
                "URL": url,
                "источник_исключённой": row["Источник"],
                "источник_канонической": canonical["Источник"],
                "название_исключённой": row["Название"],
                "название_канонической": canonical["Название"],
                "причина": "identical_nonempty_url",
            })
            continue
        kept.append(row)
        if url:
            seen_urls[url] = (index, row)
    return kept, removed


def candidate_groups(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Создаёт неразрушающий список возможных дублей для экспертного ревью."""
    groups: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = (normalized_title(row["Название"]), row["Год от"].strip(), row["Год до"].strip())
        if key[0]:
            groups[key].append(row)

    result: list[dict[str, str]] = []
    group_number = 0
    for key, members in sorted(groups.items()):
        urls = {member["URL"].strip() for member in members if member["URL"].strip()}
        if len(members) < 2 or len(urls) < 2:
            continue
        group_number += 1
        for member in members:
            result.append({
                "группа": str(group_number),
                "нормализованное_название": key[0],
                "год_от": key[1],
                "год_до": key[2],
                "источник": member["Источник"],
                "название": member["Название"],
                "URL": member["URL"],
                "решение_эксперта": "",
                "комментарий": "",
            })
    return result


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Исходный объединённый CSV")
    parser.add_argument("--output-dir", type=Path, default=Path("output/dedup"), help="Новый каталог производных файлов")
    parser.add_argument("--dry-run", action="store_true", help="Проверить и вывести статистику без записи файлов")
    args = parser.parse_args()

    if not args.input.is_file():
        parser.error(f"Исходный CSV не найден: {args.input}")

    fields, input_rows = read_rows(args.input)
    kept_rows, removed_rows = deduplicate(input_rows)
    candidates = candidate_groups(kept_rows)
    summary = {
        "input_file": str(args.input),
        "input_rows": len(input_rows),
        "retained_rows": len(kept_rows),
        "identical_url_duplicates_removed": len(removed_rows),
        "candidate_rows_for_human_review": len(candidates),
        "candidate_groups_for_human_review": len({row["группа"] for row in candidates}),
        "automatic_rule": "Only identical non-empty URL values are removed.",
        "candidate_rule": "Normalized title plus identical year range; no candidates are removed automatically.",
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.dry_run:
        return 0

    output_dir = args.output_dir
    write_csv(output_dir / "results_deduplicated_exact_url.csv", kept_rows, fields)
    write_csv(
        output_dir / "removed_identical_url_duplicates.csv",
        removed_rows,
        [
            "исключённая_строка", "каноническая_строка", "URL",
            "источник_исключённой", "источник_канонической",
            "название_исключённой", "название_канонической", "причина",
        ],
    )
    write_csv(
        output_dir / "candidate_semantic_duplicates_for_review.csv",
        candidates,
        [
            "группа", "нормализованное_название", "год_от", "год_до",
            "источник", "название", "URL", "решение_эксперта", "комментарий",
        ],
    )
    with (output_dir / "deduplication_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
