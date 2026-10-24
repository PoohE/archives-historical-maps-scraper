"""v4 PRLIB responsibility and note regressions; no network."""
import json
from pathlib import Path

from notion_export import normalize

ROOT = Path(__file__).resolve().parents[1]
PRLIB = ROOT / "output/prlib_catalog_full_20260917_v1/records_full.jsonl"


def test_v4_prlib_preserves_source_and_moves_bibliographic_responsibility():
    before = PRLIB.read_bytes()
    entries = [
        json.loads(line)
        for line in PRLIB.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    rows = [normalize(entry)[0] for entry in entries]
    assert PRLIB.read_bytes() == before
    assert len(rows) == 276
    assert not any(row['Автор / составитель'] for row in rows)
    assert sum(bool(row['Связанное издание: автор / ответственность']) for row in rows) == 237
    forbidden = (
        'Организация-издатель серии',
        'Место хранения оригинала',
        'Источник электронной копии',
    )
    assert all(not any(value in row['Примечания'] for value in forbidden) for row in rows)


def test_v4_report_records_intentional_blank_linked_title_and_year():
    report = ROOT / "output/adapters_v16_relayout_20260923_v4/REPORT.json"
    if not report.exists():
        return
    decision = json.loads(report.read_text(encoding="utf-8"))["decisions"]["prlib_linked_edition_title_year"]
    assert decision["status"] == "intentionally_blank"
    assert decision["linked_item_candidates"] == "not_fetched_relation_unverified"
    rgia = json.loads(report.read_text(encoding="utf-8"))["decisions"]["rgia_input_provenance"]
    assert rgia["status"] == "accepted_new_provenance"
    assert rgia["previous_v3"]["rows"] == 20
    assert rgia["accepted_v4"] == {
        "rows": 69,
        "sha256": "5c49359cd75e712fa43134ebe2c6930bf48e6fa94ff81d962025987861887ff4",
    }
