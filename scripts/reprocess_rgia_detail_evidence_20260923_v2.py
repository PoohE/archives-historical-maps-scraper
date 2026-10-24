"""Reparse preserved RGIA detail evidence without network access."""

import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/rgia_detail_evidence_20260923_v2"
sys.path.insert(0, str(ROOT / "scripts/modules"))

from scrapers import searcher_rgia as rgia  # noqa: E402
import rgia_notion  # noqa: E402


def write(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main():
    raw = OUT / "detail.raw.json"
    required = (
        OUT / "parsed_record_v2.json",
        OUT / "notion_candidate_v2.json",
        OUT / "notion_candidate_v2.csv",
        OUT / "REPROCESS_v2.json",
    )
    if any(path.exists() for path in required):
        raise FileExistsError("Refusing to overwrite reprocessed evidence")
    payload = json.loads(raw.read_text(encoding="utf-8"))
    record = rgia._parse_object_json(payload, "https://fgurgia.ru/object/5191017")
    candidate = {
        **rgia_notion.convert(record),
        "Статус приёмки": "кандидат",
    }
    schema = json.loads(
        (ROOT / "scripts/modules/notion_schema.json").read_text(encoding="utf-8")
    )["schema"]
    unknown = sorted(set(candidate) - set(schema))
    if unknown:
        raise ValueError("Unknown Notion properties: " + ", ".join(unknown))
    write(OUT / "parsed_record_v2.json", record.__dict__)
    write(OUT / "notion_candidate_v2.json", candidate)
    with (OUT / "notion_candidate_v2.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(candidate))
        writer.writeheader()
        writer.writerow(candidate)
    write(
        OUT / "REPROCESS_v2.json",
        {
            "network": "not_run",
            "input": "detail.raw.json",
            "input_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
            "parser": "searcher_rgia._parse_object_json",
            "mapping": "rgia_notion.convert",
            "notion_properties_validated": True,
            "ready_for_import": False,
            "status": "candidate_csv_ready_for_review",
        },
    )


if __name__ == "__main__":
    main()