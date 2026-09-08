#!/usr/bin/env python3
"""Transparent relevance filter for historical cartographic search results.

The input CSV is never modified.  Each row receives a reproducible score,
matched terms, and a review category based on a JSON keyword configuration.
The script is intentionally conservative: weak or missing metadata lowers the
score but does not justify inventing facts or silently deleting records.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from pathlib import Path


DEFAULT_CONFIG = Path(__file__).with_name("filter_keywords.json")

FIELD_ALIASES = {
    "title": ("title", "Название", "Название источника"),
    "description": ("description", "Описание", "Примечания"),
    "territory": ("territory", "Территория", "Охватываемая территория"),
    "query": ("query", "Ключевое слово", "Запрос"),
    "record_type": ("record_type", "Тип записи", "Тип источника"),
    "source": ("source", "Источник", "Архив", "Архив хранения"),
    "url": ("url", "URL", "Ссылка", "Ссылка на онлайн-архив"),
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").lower().replace("ё", "е")
    value = re.sub(r"[^0-9a-zа-я]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def compile_terms(terms: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    compiled = []
    for term in terms:
        clean = normalize(term)
        if not clean:
            continue
        body = r"\s+".join(re.escape(part) for part in clean.split())
        pattern = r"(?<![0-9a-zа-я])" + body + r"(?![0-9a-zа-я])"
        compiled.append((term, re.compile(pattern)))
    return compiled


def matched(text: str, terms: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    return [term for term, pattern in terms if pattern.search(text)]


def field_value(row: dict[str, str], canonical: str) -> str:
    for name in FIELD_ALIASES[canonical]:
        value = row.get(name, "")
        if value and value.strip():
            return value
    return ""


def read_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    required = {"territories", "cartographic", "project", "noise"}
    missing = required - set(config)
    if missing:
        raise ValueError(f"В конфигурации отсутствуют разделы: {', '.join(sorted(missing))}")
    return config


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("В CSV отсутствует строка заголовка")
        rows = list(reader)
    return reader.fieldnames, rows


def score_row(row: dict[str, str], config: dict) -> dict[str, str]:
    title_text = normalize(" ".join(field_value(row, key) for key in ("title", "description")))
    metadata_text = normalize(" ".join(field_value(row, key) for key in ("territory", "query", "record_type", "source")))
    query_text = normalize(field_value(row, "query"))
    text = normalize(" ".join((title_text, metadata_text)))
    territory_terms = compile_terms(config["territories"])
    cartographic_terms = compile_terms(config["cartographic"])
    project_terms = compile_terms(config["project"])
    noise_terms = compile_terms(config["noise"])
    territories_title = matched(title_text, territory_terms)
    territories_metadata = matched(metadata_text, territory_terms)
    cartographic_title = matched(title_text, cartographic_terms)
    cartographic_query = matched(query_text, cartographic_terms)
    project_title = matched(title_text, project_terms)
    noise_title = matched(title_text, noise_terms)

    score = 0
    score += min(35, 30 * bool(territories_title) + 5 * max(0, len(territories_title) - 1))
    score += 15 if territories_metadata and not territories_title else 5 * bool(territories_metadata)
    score += min(40, 25 * bool(cartographic_title) + 5 * max(0, len(cartographic_title) - 1))
    score += 5 * bool(cartographic_query) if not cartographic_title else 0
    score += min(15, 5 * len(project_title))
    score -= min(30, 12 * len(noise_title))
    if field_value(row, "url").strip():
        score += 5

    geo_evidence = territories_title or territories_metadata
    if score >= 55 and geo_evidence and cartographic_title:
        category = "relevant"
    elif score >= 25 and (territories_title or cartographic_title or project_title):
        category = "possible"
    elif noise_title and not (territories_title or cartographic_title):
        category = "noise"
    else:
        category = "needs_manual_review"

    return {
        "filter_score": str(max(0, min(100, score))),
        "filter_category": category,
        "matched_territories_title": "; ".join(territories_title),
        "matched_territories_metadata": "; ".join(territories_metadata),
        "matched_cartographic_title": "; ".join(cartographic_title),
        "matched_cartographic_query": "; ".join(cartographic_query),
        "matched_project_terms": "; ".join(project_title),
        "matched_noise_terms": "; ".join(noise_title),
        "filter_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()

    if not args.input.is_file():
        parser.error(f"Исходный CSV не найден: {args.input}")
    if not args.config.is_file():
        parser.error(f"Конфигурация не найдена: {args.config}")

    fields, source_rows = read_rows(args.input)
    config = read_config(args.config)
    annotated = []
    for row in source_rows:
        enriched = dict(row)
        enriched.update(score_row(row, config))
        annotated.append(enriched)

    derived_fields = [
        "filter_score", "filter_category", "matched_territories_title",
        "matched_territories_metadata", "matched_cartographic_title",
        "matched_cartographic_query", "matched_project_terms",
        "matched_noise_terms", "filter_text_sha256",
    ]
    all_fields = fields + [field for field in derived_fields if field not in fields]
    groups = {name: [row for row in annotated if row["filter_category"] == name] for name in ("relevant", "possible", "needs_manual_review", "noise")}
    summary = {
        "input_file": str(args.input),
        "config_file": str(args.config),
        "input_rows": len(source_rows),
        "counts": {name: len(rows) for name, rows in groups.items()},
        "thresholds": {"relevant": 55, "possible": 25},
        "notes": "Source CSV remains unchanged; categories are candidates for review, not factual assertions.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "all_annotated.csv", all_fields, annotated)
    for name, rows in groups.items():
        write_csv(args.output_dir / f"{name}.csv", all_fields, rows)
    with (args.output_dir / "filter_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
