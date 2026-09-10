"""Offline exporter: records_full.jsonl -> CSV with verified Notion names.

No network or Notion writes. Ambiguous editions/images remain in the source
JSONL and are listed in export_review.json. Optional choices JSON is keyed by
card URL: {"url": {"edition_url": "...", "image_url": "..."}}.
"""
import argparse
import csv
import json
from pathlib import Path

FIELDS = [
    "Название источника", "Ссылка на онлайн-архив",
    "Прямая ссылка на файл изображения", "Связанное издание: название",
    "Связанное издание: URL", "Связанное издание: год издания",
    "Связанное издание: автор / ответственность",
    "Связанное издание: библиографическое описание", "Связанное издание: тип",
    "Оригинальный масштаб", "Масштаб (знаменатель)", "Описание",
    "Автор / составитель", "Место создания", "Примечания", "Автор внесения",
]


def choose(items, chosen_url, url_key=None):
    unique = {}
    for item in items:
        url = item.get(url_key) if url_key else item
        if url:
            unique[url] = item
    if chosen_url:
        if chosen_url not in unique:
            raise ValueError("Chosen URL does not occur in the source record")
        return unique[chosen_url]
    return next(iter(unique.values())) if len(unique) == 1 else None


def convert(entry, choices):
    rec = entry["record"]
    extra = rec.get("extra") or {}
    choice = choices.get(rec["url"], {})
    row = dict.fromkeys(FIELDS, "")
    row.update({"Название источника": rec.get("title", ""),
                "Ссылка на онлайн-архив": rec["url"],
                "Автор / составитель": rec.get("author", ""),
                "Место создания": rec.get("place", ""),
                "Описание": rec.get("description", ""), "Автор внесения": "Агент"})
    issues = []
    editions = extra.get("edition_links") or []
    # GPIB's illustration edition field includes both the series and volume.
    # Preserve its complete wording; the URL still points to the selected volume.
    full_edition_title = (extra.get("gpib_meta") or {}).get("Издание (для иллюстраций)", "")
    row["Связанное издание: название"] = full_edition_title
    edition = choose(editions, choice.get("edition_url"), "url")
    if edition:
        for source, target in [("title", "название"), ("url", "URL"),
                               ("author", "автор / ответственность"),
                               ("description", "библиографическое описание")]:
            row["Связанное издание: " + target] = edition.get(source) or ""
        if full_edition_title:
            row["Связанное издание: название"] = full_edition_title
        lower, upper = edition.get("year_from"), edition.get("year_to")
        if isinstance(lower, (int, float)) and not isinstance(lower, bool) and lower == upper:
            row["Связанное издание: год издания"] = lower
        elif lower or upper:
            issues.append("Годы издания требуют проверки: " + str((lower, upper)))
        allowed = {"Атлас", "Книга (монография)", "Журнал", "Сборник", "Отчёт", "Диссертация", "Другое"}
        if edition.get("type") in allowed:
            row["Связанное издание: тип"] = edition["type"]
        elif edition.get("type"):
            issues.append("Сопоставить тип издания: " + edition["type"])
    elif editions:
        issues.append("Выбрать связанное издание: " + json.dumps(editions, ensure_ascii=False))
    images = extra.get("image_urls") or []
    selected_image = choose(images, choice.get("image_url"))
    if selected_image:
        row["Прямая ссылка на файл изображения"] = selected_image
    elif images:
        issues.append("Выбрать изображение: " + json.dumps(images, ensure_ascii=False))
    # Image observations enter accepted fields only after explicit human review.
    for observation in extra.get("image_observations", []):
        if observation.get("status") != "approved":
            issues.append("Неподтверждённое чтение изображения: " + json.dumps(observation, ensure_ascii=False))
            continue
        if observation.get("field") == "scale_original":
            row["Оригинальный масштаб"] = observation.get("value", "")
        if observation.get("field") == "scale_denominator":
            value = observation.get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise ValueError("Scale denominator must be positive numeric")
            row["Масштаб (знаменатель)"] = value
    row["Примечания"] = "\n".join(issues)
    return row, issues


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--schema", type=Path, required=True)
    ap.add_argument("--choices", type=Path)
    args = ap.parse_args()
    schema = json.loads(args.schema.read_text(encoding="utf-8"))["schema"]
    for field in FIELDS:
        if field not in schema:
            raise ValueError("Field absent from verified Notion schema: " + field)
    choices = json.loads(args.choices.read_text(encoding="utf-8")) if args.choices else {}
    entries = [json.loads(line) for line in args.input.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    rows, reviews = [], []
    for entry in entries:
        if entry.get("source") != "gpib":
            continue
        row, issues = convert(entry, choices)
        for field, value in row.items():
            kind = schema[field]["type"]
            if value == "":
                continue
            if kind == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
                raise ValueError("Non-numeric value: " + field)
            if kind == "url" and (not isinstance(value, str) or not value.startswith(("http://", "https://")) or any(c.isspace() for c in value)):
                raise ValueError("Invalid URL: " + field)
            if kind == "select" and value not in schema[field]["options"]:
                raise ValueError("Unknown select option: " + field)
        rows.append(row)
        if issues:
            reviews.append({"url": row["Ссылка на онлайн-архив"], "issues": issues})
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "notion_import.csv").open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (args.output / "export_review.json").write_text(json.dumps({"rows": len(rows), "source": str(args.input), "schema": str(args.schema), "issues": reviews}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported {len(rows)} rows; {len(reviews)} rows need review")


if __name__ == "__main__":
    main()
