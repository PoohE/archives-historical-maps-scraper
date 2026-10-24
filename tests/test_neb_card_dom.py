from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/modules"))
from scrapers.neb_card_dom import parse_card  # noqa: E402


RAW = ROOT / "output/neb_recon_20260928_v1/raw_html"


def test_book_card_has_real_bibliography_and_is_not_map():
    value = parse_card((RAW / "card_book_rendered.html").read_text(encoding="utf-8"), "https://rusneb.ru/catalog/000199_000009_003796403/")
    assert value["title"]
    assert value["bibliography"]
    assert value["identifier"] == "000199_000009_003796403"
    assert not value["is_map"]


def test_map_card_uses_catalog_substring_classifier():
    value = parse_card((RAW / "card_map_rendered.html").read_text(encoding="utf-8"), "https://rusneb.ru/catalog/000199_000009_008725490/")
    assert value["title"]
    assert value["is_map"]
    assert "карт" in value["catalog_raw"].casefold()
