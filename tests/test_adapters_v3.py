"""v3 fill-rate regressions over preserved archive evidence; no network."""
import json
from pathlib import Path

from notion_export import normalize

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {
    "prlib": ROOT / "output/prlib_catalog_full_20260917_v1/records_full.jsonl",
    "rgada": ROOT / "output/rgada_catalog_full_20260922_v3_review_20260923/records_enriched.jsonl",
    "rgia": ROOT / "output/rgia_catalog_full_20260923_v1/records_full.jsonl",
}


def entries(name):
    return [
        json.loads(line)
        for line in INPUTS[name].read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def normalized(name):
    return [normalize(entry) for entry in entries(name)]


def test_v3_uses_preserved_rgada_enriched_records_without_modifying_them():
    before = INPUTS["rgada"].read_bytes()
    rows = normalized("rgada")
    assert INPUTS["rgada"].read_bytes() == before
    assert len(rows) == 98
    assert not any(audit["validation_errors"] for _, audit in rows)


def test_v3_rgada_derivation_maps_confirmed_material_date_ranges():
    rows = normalized("rgada")
    assert sum(bool(row["Год создания (нижняя)"]) for row, _ in rows) == 95
    assert sum(bool(row["Год создания (верхняя)"]) for row, _ in rows) == 95
    assert sum(bool(row["Год сведений"]) for row, _ in rows) == 0


def test_v3_descriptions_and_archive_territory_fallback_are_auditable():
    rgada_rows = normalized("rgada")
    rgia_rows = normalized("rgia")
    assert sum(bool(row["Описание"]) for row, _ in rgada_rows) == 59
    assert sum(bool(row["Описание"]) for row, _ in rgia_rows) == 20
    assert sum(bool(row["Административный уровень"]) for row, _ in rgada_rows) == 98
    assert sum(bool(row["Административный уровень"]) for row, _ in rgia_rows) == 20
    fallback_audits = [
        audit["administrative_level"]
        for _, audit in rgada_rows + rgia_rows
        if audit["administrative_level"].get("locator") == "entry.territory"
    ]
    assert fallback_audits
    assert all(audit["basis"] == "explicit_query_territory" for audit in fallback_audits)


def test_v3_keeps_all_rows_as_candidates_and_prlib_coverage_unchanged():
    prlib_rows = normalized("prlib")
    rgada_rows = normalized("rgada")
    rgia_rows = normalized("rgia")
    assert len(prlib_rows) == 276
    assert sum(bool(row["Описание"]) for row, _ in prlib_rows) == 276
    assert all(
        row["Статус приёмки"] == "кандидат"
        for row, _ in prlib_rows + rgada_rows + rgia_rows
    )
