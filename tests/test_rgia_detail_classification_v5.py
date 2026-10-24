import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/modules"))
sys.path.insert(0, str(ROOT / "scripts/modules/scrapers"))
import notion_export
import searcher_rgia as rgia


def test_rgia_detail_classification_requires_complete_case_identity():
    case = {
        "title": "Карта Калужской губернии",
        "attributes": [{"name": "Шифр", "text": "Ф. 1 Оп. 2 Д. 3"}],
    }
    noncase = {
        "title": "Лист карты",
        "objectTypeName": "Подразделение",
        "attributes": [{"name": "Шифр", "text": "Ф. 1 Оп. 2"}],
    }
    assert rgia.classify_detail_object(case)["kind"] == "archival_case"
    split_case = {"title": "Дело с частью", "attributes": [{"name": "Шифр", "text": "Ф. 796 Оп. 114 Д. 1231-1"}]}
    assert rgia.classify_detail_object(split_case)["kind"] == "archival_case"
    verdict = rgia.classify_detail_object(noncase)
    assert verdict["kind"] == "noncase_review"
    assert verdict["reason"] == "case_identity_missing"


def test_legacy_unclassified_rgia_detail_exports_as_candidate_for_review(tmp_path):
    entry = {
        "source": "rgia",
        "territory": "Калужская губерния",
        "keyword": "карта",
        "record": {
            "title": "Лист карты",
            "fund_code": "Ф. 1 Оп. 2",
            "url": "https://fgurgia.ru/object/2576973831",
            "library_id": "rgia",
            "extra": {"rgia_detail": True},
        },
    }
    source = tmp_path / "records.jsonl"
    source.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
    report = notion_export.export(source, tmp_path / "csv")
    assert report["rows"] == 1
    audit = report["records"][0]
    assert audit["adapter"] == "rgia_detail_unclassified"
    assert "case_identity_unconfirmed" in audit["issues"]
    assert audit["validation_errors"] == []


def test_future_detail_entry_keeps_raw_detail_and_maps_both_scan_fields():
    payload = {
        "title": "Карта Калужской губернии",
        "downloadLink": "https://fgurgia.ru/files/123.pdf",
        "imageUrl": "https://fgurgia.ru/images/123.jp2",
        "attributes": [
            {"name": "Шифр", "text": "Ф. 1 Оп. 2 Д. 3"},
            {"name": "Крайние даты", "text": "1901"},
        ],
    }
    record = rgia._parse_object_json(payload, "https://fgurgia.ru/object/123")
    record_data = asdict(record)
    raw_detail = record_data.pop("raw_detail")
    entry = {
        "source": "rgia",
        "territory": "Калужская губерния",
        "keyword": "карта",
        "record": {
            **record_data,
            "extra": {"rgia_detail": True, "raw_detail": raw_detail},
        },
    }
    row, audit = notion_export.normalize(entry)
    assert entry["record"]["extra"]["raw_detail"] == payload
    assert row["Прямая ссылка на файл изображения"] == payload["imageUrl"]
    assert row["Путь / URL к файлу"] == payload["downloadLink"]
    assert len(row) == len(notion_export.FIELDS)
    assert audit["adapter"] == "rgia_detail"
