"""Offline v4 contract tests; fixtures are labelled reconstructions, not source HTML."""
from dataclasses import asdict
from pathlib import Path

import notion_export
import searcher_permkrai as permkrai


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
MAP_URL = "https://lib.permkrai.ru/node/23121"


def entry(record):
    return {"source": "permkrai", "territory": "", "keyword": "rubric: Карты, схемы, планы",
            "record": {**asdict(record), "extra": {"permkrai_record": asdict(record), "ready_for_import": False}}}


def test_v4_map_contract_fields_and_scale_conversion():
    html = (FIXTURES / "permkrai_node_23121_contract.html").read_text(encoding="utf-8")
    kind, _ = permkrai.classify_card_html(html)
    assert kind == "map_card"
    record = permkrai.parse_card_html(html, MAP_URL)
    assert record is not None
    assert record.title == "Карта Оханского уезда Пермской губернии"
    assert (record.year_from, record.year_to) == (1904, 1914)
    assert record.scale_raw == "5 вер. в дюйме"
    assert record.url_download.endswith("okhansk_map.pdf")
    assert record.url_viewer == MAP_URL + "?fragment=page-1"
    row, audit = notion_export.normalize(entry(record))
    assert row["Описание"] == record.bibliography
    assert (row["Год создания (нижняя)"], row["Год создания (верхняя)"]) == (1904, 1914)
    assert row["Масштаб (знаменатель)"] == 210000
    assert row["Путь / URL к файлу"] == record.url_download
    assert row["Прямая ссылка на файл изображения"] == record.url_viewer
    assert row["Место хранения"] == "Соловьев Андрей Владимирович"
    assert row["DC Type"] == "StillImage"
    assert not audit["validation_errors"]
    assert any(item["property"] == "Тип источника" and item["source_label"] == "Карта" for item in audit["relations"])
    assert any(item["property"] == "Охватываемая территория" for item in audit["relations"])


def test_v4_collection_is_not_a_map_card():
    html = (FIXTURES / "permkrai_node_43550_collection_contract.html").read_text(encoding="utf-8")
    kind, _ = permkrai.classify_card_html(html)
    assert kind == "collection"
    assert permkrai.parse_card_html(html, "https://lib.permkrai.ru/node/43550") is None
