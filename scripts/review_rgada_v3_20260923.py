"""Offline acceptance/enrichment of the immutable RGADA v3 candidate snapshot.

This utility never calls the network and never rewrites v3 records or state.
It creates a separately named derived directory with input hashes, bounded-field
acceptance evidence, and recovered date intervals from existing result metadata.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/modules"))
sys.path.insert(0, str(ROOT / "scripts/modules/scrapers"))
from searcher_rgada import RgadaRecord, keyword_match_counts, metadata_years  # noqa: E402

INPUT = ROOT / "output/rgada_catalog_full_20260922_v3"
ATTEMPT = INPUT / "attempts/20260923_040938_c0cc2541"
OUTPUT = ROOT / "output/rgada_catalog_full_20260922_v3_review_20260923"
KEYWORDS = ("карта", "план", "атлас", "съёмка", "чертёж", "топографическая")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: object) -> None:
    candidate = path.with_suffix(path.suffix + ".tmp")
    candidate.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    candidate.replace(path)


def result_record(entry: dict) -> RgadaRecord:
    record = entry["record"]
    extra = record.get("extra") or {}
    return RgadaRecord(
        fund_number=str(extra.get("fund_number", "")),
        list_number=str(extra.get("list_number", "")),
        list_name=str(record.get("title", "")),
        years=str(extra.get("years_raw", "")),
        annotation=str(record.get("description", "")),
        url=str(record.get("url", "")),
    )


def accepted_coverage(raw: list[dict]) -> list[dict]:
    result = []
    for item in raw:
        fields = item.get("fields", {})
        list_field = fields.get("list_name", {})
        fund_field = fields.get("fund_name", {})
        accepted = (
            list_field.get("status") == "reported_end"
            and fund_field.get("status") == "partial"
            and item.get("stop_reason") in ("pager_classifier_mismatch", "repeated_page")
        )
        result.append(
            {
                "key": item["key"],
                "territory": item["territory"],
                "source_coverage_status": item["status"],
                "source_stop_reason": item.get("stop_reason", ""),
                "list_name_status": list_field.get("status", ""),
                "fund_name_status": fund_field.get("status", ""),
                "fund_name_resume_page": fund_field.get("resume_page"),
                "acceptance": (
                    "accepted_bounded_secondary_field"
                    if accepted
                    else "not_accepted"
                ),
                "full_search_complete": False,
                "for_review": not accepted,
                "reason": (
                    "list_name reached reported_end; fund_name is an explicitly "
                    "bounded secondary field and did not establish a full end"
                    if accepted
                    else "coverage does not meet bounded-secondary-field policy"
                ),
            }
        )
    return result


def run(output: Path = OUTPUT) -> dict:
    if output.exists():
        raise ValueError("Refusing to overwrite derived RGADA review: " + str(output))
    source = INPUT / "records_full.jsonl"
    coverage_path = ATTEMPT / "coverage.json"
    raw = source.read_bytes()
    entries = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    output.mkdir(parents=True)
    enriched = []
    records = []
    for entry in entries:
        clone = json.loads(json.dumps(entry, ensure_ascii=False))
        record = result_record(clone)
        year_from, year_to = metadata_years(record)
        clone["record"]["year_from"] = year_from
        clone["record"]["year_to"] = year_to
        clone["record"].setdefault("extra", {})["date_derivation"] = {
            "method": "result_url_opisanie_plus_visible_metadata",
            "year_from": year_from,
            "year_to": year_to,
        }
        enriched.append(clone)
        records.append(record)
    (output / "records_enriched.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in enriched),
        encoding="utf-8",
    )
    fields = ("title", "url", "year_from", "year_to", "description", "library_id", "library_name")
    with (output / "records_enriched.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for entry in enriched:
            writer.writerow({name: entry["record"].get(name) for name in fields})
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    accepted = accepted_coverage(coverage)
    atomic_json(output / "coverage_acceptance.json", accepted)
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "network": "not_run",
        "input": {
            "records_full_jsonl": str(source),
            "records_full_jsonl_sha256": sha(source),
            "coverage_json": str(coverage_path),
            "coverage_json_sha256": sha(coverage_path),
            "source_records_modified": False,
            "source_state_modified": False,
        },
        "records": len(entries),
        "years": {
            "method": "result_url_opisanie_plus_visible_metadata",
            "with_interval": sum(
                item["record"]["year_from"] is not None
                and item["record"]["year_to"] is not None
                for item in enriched
            ),
        },
        "keyword_audit": {
            "population": "candidate_rows_only",
            "raw_result_rows_not_reconstructable": True,
            "reason": "v3 retained raw counts and page fingerprints, not raw page HTML",
            "historical_per_term_counts": None,
            "retained_candidate_fields_insufficient": True,
            "future_run_metric": "fields.*.raw_keyword_counts",
        },
        "coverage_acceptance": {
            "policy": "RGADA list_name reported_end plus bounded fund_name partial",
            "accepted_queries": sum(x["acceptance"] == "accepted_bounded_secondary_field" for x in accepted),
            "queries_for_review": [x["key"] for x in accepted if x["for_review"]],
            "full_search_complete": False,
        },
        "ready_for_import": False,
    }
    atomic_json(output / "REPORT.json", report)
    return report


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
