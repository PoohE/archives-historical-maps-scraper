"""Offline RGIA card -> 66-field CSV gate for one saved detail response."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/modules"))
sys.path.insert(0, str(ROOT / "scripts/modules/scrapers"))
import notion_export  # noqa: E402
import searcher_rgia as rgia  # noqa: E402

RAW = ROOT / "output/rgia_detail_evidence_20260923_v2/detail.raw.json"
OUT = ROOT / "output/rgia_detail_notion_gate_20260923_v4"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(output: Path = OUT) -> dict:
    if output.exists():
        raise ValueError("Refusing to overwrite RGIA detail gate: " + str(output))
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    record = rgia._parse_object_json(raw, "https://fgurgia.ru/object/5191017")
    record_data = asdict(record)
    raw_detail = record_data.pop("raw_detail", {})
    entry = {
        "source": "rgia",
        "territory": "Калужская губерния",
        "keyword": "карта",
        "record": {
            **record_data,
            "extra": {
                "rgia_detail": True,
                "raw_detail": raw_detail,
                "evidence": {
                    "raw_detail_path": str(RAW),
                    "raw_detail_sha256": sha(RAW),
                    "object_id": "5191017",
                    "detail_endpoint": "/ajax/obj/{object_id}/{search_index}?children=false",
                    "network": "not_run_reprocessed_saved_response",
                },
            },
        },
    }
    output.mkdir(parents=True)
    input_path = output / "source_record.jsonl"
    input_path.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
    export = notion_export.export(input_path, output / "notion_csv")
    validation = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "network": "not_run",
        "raw_detail_sha256": sha(RAW),
        "record": {
            "object_id": "5191017",
            "title": record.title,
            "fund_code": record.fund_code,
            "date_raw": record.date_raw,
            "year_from": record.year_from,
            "year_to": record.year_to,
        },
        "notion_csv": {
            "columns": export["columns"],
            "rows": export["rows"],
            "roundtrip": export["roundtrip"],
            "validation_errors": export["records"][0]["validation_errors"],
            "adapter": export["records"][0]["adapter"],
            "manual_gates": export["manual_gates"],
        },
        "ready_for_import": False,
        "notion_written": False,
        "canonical_ontology_written": False,
    }
    (output / "REPORT.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return validation


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
