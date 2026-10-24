"""Offline v1.6 v3 re-layout from preserved archive candidate JSONL; no network."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/modules"))
import notion_export

OUT = ROOT / "output/adapters_v16_relayout_20260923_v4"
INPUTS = {
    "prlib": ROOT / "output/prlib_catalog_full_20260917_v1/records_full.jsonl",
    "rgada": ROOT / "output/rgada_catalog_full_20260922_v3_review_20260923/records_enriched.jsonl",
    "rgia": ROOT / "output/rgia_catalog_full_20260923_v1/records_full.jsonl",
}
INPUT_ROLES = {
    "prlib": "preserved source candidate JSONL",
    "rgada": "preserved result-level enriched JSONL; no re-collection",
    "rgia": "accepted current source candidate JSONL; post-v3 provenance change",
}

# v4 is a correction of the accepted v3 re-layout, so its inputs are pinned.
# Do not silently absorb an independently advancing collection into this batch.
EXPECTED_INPUT_SHA256 = {
    "prlib": "e58b9f952476caff3b116155b08aae967528a9a57dd2aaa7ecfc7e82922f2161",
    "rgada": "8065b22636aaf53409a3198954312cb97832146902a342ee7178164c31da2bda",
    "rgia": "5c49359cd75e712fa43134ebe2c6930bf48e6fa94ff81d962025987861887ff4",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_stats(path: Path) -> dict:
    entries = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    return {
        "input_rows": len(entries),
        "unique_urls": len({x["record"].get("url", "") for x in entries}),
    }


def csv_coverage(path: Path) -> dict:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {
        "rows": len(rows),
        "columns": len(rows[0]) if rows else len(notion_export.FIELDS),
        "nonempty_by_field": {
            field: sum(bool((row.get(field) or "").strip()) for row in rows)
            for field in notion_export.FIELDS
        },
    }


def main() -> None:
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite " + str(OUT))
    for name, source in INPUTS.items():
        actual = sha(source)
        expected = EXPECTED_INPUT_SHA256[name]
        if actual != expected:
            raise ValueError(
                f"input SHA-256 mismatch for {name}: expected {expected}, got {actual}"
            )
    OUT.mkdir()
    report = {
        "task": "offline adapter v1.6 v4 re-layout",
        "network": "not_run",
        "ready_for_import": False,
        "schema_version": notion_export.SCHEMA["version"],
        "schema_sha256": sha(ROOT / "scripts/modules/notion_schema.json"),
        "decisions": {
            "prlib_linked_edition_title_year": {
                "status": "intentionally_blank",
                "reason": "PRLIB card is itself a volume/serial bibliographic description; no separate verified linked-edition title or year was captured.",
                "scope": "PRLIB volumes and series in this derived export.",
                "linked_item_candidates": "not_fetched_relation_unverified",
            }
,
            "rgia_input_provenance": {
                "status": "accepted_new_provenance",
                "approval": "user instruction 2026-09-23",
                "previous_v3": {
                    "rows": 20,
                    "sha256": "569b3be6c7c6834e71727c62a6a0cf245d8734144890ba9295d566434029c156",
                },
                "accepted_v4": {
                    "rows": 69,
                    "sha256": "5c49359cd75e712fa43134ebe2c6930bf48e6fa94ff81d962025987861887ff4",
                },
            }
        },
        "sources": {},
    }
    for name, source in INPUTS.items():
        before = source.read_bytes()
        target = OUT / name
        exported = notion_export.export(source, target)
        if source.read_bytes() != before:
            raise ValueError("source JSONL changed: " + str(source))
        report["sources"][name] = {
            "input_path": str(source),
            "input_role": INPUT_ROLES[name],
            "input_sha256": sha(source),
            **input_stats(source),
            "export": {key: exported[key] for key in ("rows", "columns", "roundtrip")},
            "coverage": csv_coverage(target / "notion_import.csv"),
        }
    (OUT / "REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                name: {"rows": data["export"]["rows"], "columns": data["export"]["columns"]}
                for name, data in report["sources"].items()
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
