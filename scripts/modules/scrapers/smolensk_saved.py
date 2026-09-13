"""Offline parser for user-saved Smolensk digital-library cards.

The parser preserves the source HTML and writes review-only JSON. It does not
download PDFs, infer a map scale, or alter any existing CSV/Notion data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def _source_url(soup: BeautifulSoup, raw: bytes) -> str:
    match = re.search(rb"saved from url=\"([^\"]+)\"", raw, re.I)
    if match:
        return match.group(1).decode("utf-8", errors="replace")
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        if "/bd/books/" in href and href.endswith(".pdf"):
            return urljoin("http://elib.smolensklib.ru", href)
    return ""


def _marc_fields(soup: BeautifulSoup) -> list[dict[str, object]]:
    container = soup.select_one("div.marc")
    if container is None:
        return []

    fields: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    code = ""
    for span in container.find_all("span"):
        classes = set(span.get("class", []))
        if "field-label" in classes:
            current = {"tag": span.get_text(" ", strip=True), "subfields": []}
            fields.append(current)
            code = ""
        elif "subfield-label" in classes:
            code = span.get_text(" ", strip=True).lstrip("$")
        elif "data" in classes and current is not None and code:
            value = span.get_text(" ", strip=True)
            subfields = current["subfields"]
            assert isinstance(subfields, list)
            subfields.append({"code": code, "value": value})
    return fields


def _values(fields: list[dict[str, object]], tag: str, code: str) -> list[str]:
    values: list[str] = []
    for field in fields:
        if field.get("tag") != tag:
            continue
        for item in field.get("subfields", []):
            if isinstance(item, dict) and item.get("code") == code:
                values.append(str(item.get("value", "")))
    return values


def _first(values: list[str]) -> str:
    return values[0] if values else ""


def _card_text(soup: BeautifulSoup) -> str:
    for selector in ("h1.v2", "#description h1", "h1"):
        for node in soup.select(selector):
            text = node.get_text(" ", strip=True)
            if text:
                return text
    return ""


def parse(source: Path) -> tuple[dict[str, object], bytes]:
    raw = source.read_bytes()
    soup = BeautifulSoup(raw, "lxml")
    fields = _marc_fields(soup)
    description = _card_text(soup)
    pdf_url = ""
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        if "/bd/books/" in href and href.endswith(".pdf"):
            pdf_url = urljoin("http://elib.smolensklib.ru", href)
            break

    if fields:
        title = _first(_values(fields, "200", "a"))
        responsibility = _first(_values(fields, "200", "f"))
        publisher = _first(_values(fields, "210", "c"))
        place = _first(_values(fields, "210", "a"))
        date_raw = _first(_values(fields, "210", "d"))
        year_match = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", date_raw)
        year = int(year_match.group(1)) if year_match else None
        extent = _first(_values(fields, "215", "a"))
        map_terms = _values(fields, "215", "c")
        access_notes = _values(fields, "333", "a")
        digital_notes = _values(fields, "230", "a")
        if not pdf_url:
            pdf_url = _first(_values(fields, "856", "u"))
        record_kind = "rusmarc_card"
    else:
        title = description
        responsibility = ""
        publisher = ""
        place = ""
        date_raw = ""
        year = None
        match = re.search(
            r"—\s*([^:]+):\s*([^,]+),\s*(1[5-9]\d{2}|20\d{2})\s*—",
            description,
        )
        if match:
            place, publisher, year = match.group(1).strip(), match.group(2).strip(), int(match.group(3))
        extent_match = re.search(r"—\s*(\d+)\s*с\.", description)
        extent = extent_match.group(1) + " с." if extent_match else ""
        map_terms = ["приложенная карта"] if "карт" in description.lower() else []
        access_notes = ["Доступ по паролю из сети Интернет (чтение)"] if "по паролю" in description else []
        digital_notes = ["Электронная версия печатной публикации"] if "Электронная версия" in description else []
        record_kind = "card_only"

    review_issues = [
        "review_only_candidate",
        "pdf_not_downloaded_locally",
        "reading_requires_library_authentication",
    ]
    if not any(re.search(r"масштаб|1\s*:\s*\d", str(v), re.I) for v in fields + map_terms):
        review_issues.append("scale_not_established")
    if map_terms:
        map_status = "map_or_map_attachment_indicated_by_catalogue"
    else:
        map_status = "map_not_established"

    record: dict[str, object] = {
        "source_project": "historical-cartographic-archives-automation",
        "library": "Смоленская ОУНБ им. А. Т. Твардовского",
        "record_kind": record_kind,
        "title": title,
        "responsibility": responsibility,
        "publication_year": year,
        "publication_date_raw": date_raw,
        "publication_place": place,
        "publisher": publisher,
        "extent": extent,
        "map_status": map_status,
        "pdf_url": pdf_url,
        "access_notes": access_notes,
        "digital_notes": digital_notes,
        "catalogue_description": description,
        "rusmarc_fields": fields,
        "review_status": "candidate",
        "review_issues": review_issues,
    }
    return record, raw


def export(source: Path, output: Path) -> dict[str, object]:
    record, raw = parse(source)
    output.mkdir(parents=True, exist_ok=False)
    (output / "original.html").write_bytes(raw)
    record["provenance"] = {
        "local_path": str(source.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "source_url": _source_url(BeautifulSoup(raw, "lxml"), raw)
        or str(record.get("pdf_url", "")),
        "locator": "HTML card and div.marc field-label/subfield-label/data spans",
    }
    (output / "record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="Разбор сохранённой карточки ЭБ Твардовского")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    record = export(args.source, args.output)
    print(json.dumps({
        "title": record["title"],
        "publication_year": record["publication_year"],
        "map_status": record["map_status"],
        "review_status": record["review_status"],
        "output": str(args.output.resolve()),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
