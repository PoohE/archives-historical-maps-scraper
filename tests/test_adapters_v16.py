"""v1.6 mappings over preserved local records; no network."""
import json
from pathlib import Path

from notion_export import FIELDS, normalize

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {
    "prlib": ROOT / "output/prlib_catalog_full_20260917_v1/records_full.jsonl",
    "rgada": ROOT / "output/rgada_catalog_full_20260922_v3/records_full.jsonl",
    "rgia": ROOT / "output/rgia_catalog_full_20260923_v1/records_full.jsonl",
}


def entries(name):
    return [json.loads(line) for line in INPUTS[name].read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def test_v16_schema_has_65_scalar_fields_and_no_removed_bibliography_properties():
    assert len(FIELDS) == 65
    assert "Год сканирования" in FIELDS
    assert "Библиографическое описание" not in FIELDS
    assert "Связанное издание: библиографическое описание" not in FIELDS


def test_preserved_three_source_jsonl_normalize_without_validation_errors():
    for source in INPUTS:
        source_entries = entries(source)
        audits = [normalize(entry)[1] for entry in source_entries]
        assert len(audits) == len(source_entries)
        assert not any(audit["validation_errors"] for audit in audits)


def test_v16_real_record_coverage_uses_source_specific_adapters():
    prlib_rows = [normalize(entry) for entry in entries("prlib")]
    rgada_rows = [normalize(entry) for entry in entries("rgada")]
    rgia_rows = [normalize(entry) for entry in entries("rgia")]
    assert all(audit["adapter"] == "prlib_detail_v16" for _, audit in prlib_rows)
    assert all(audit["adapter"] == "rgada_inventory_v16" for _, audit in rgada_rows)
    assert all(audit["adapter"] == "rgia_detail" for _, audit in rgia_rows)
    assert sum(bool(row["Описание"]) for row, _ in rgada_rows) == 59
    assert sum(bool(row["Год создания (нижняя)"]) for row, _ in rgia_rows) == sum(
        entry["record"].get("year_from") is not None for entry in entries("rgia")
    )
    assert all(row["Статус приёмки"] == "кандидат" for row, _ in prlib_rows + rgada_rows + rgia_rows)
