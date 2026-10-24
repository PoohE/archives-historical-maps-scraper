"""Offline regression for the v6 ELiS catalog selector and card review path."""

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/permkrai_catalog_maps_handoff_20260927_v6"
V5_RENDERED = (
    ROOT / "output/permkrai_catalog_maps_20260927_v5/attempts"
    / "20260927_060506_19f7239e/raw_html/rubric_rendered_722_715d804466d0.html"
)
FIXTURES = ROOT / "tests/fixtures"


def runner():
    for name in (
        "durable_state", "classify_stop", "notion_export", "searcher_permkrai",
        "permkrai_chrome_transport", "permkrai_notion", "cartographic_enrichment",
        "library_dates", "administrative_level",
    ):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("permkrai_v6", PACKAGE / "run_catalog.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_v6_real_rendered_rubric_uses_only_elis_catalog_items():
    module = runner()
    assert module.verify()
    cards, pages, signals = module.listing_links(
        V5_RENDERED.read_text(encoding="utf-8"), "https://lib.permkrai.ru/node/722", 722
    )
    urls = {card["url"] for card in cards}
    assert len(cards) == 41
    assert "https://lib.permkrai.ru/node/23058" in urls
    assert "https://lib.permkrai.ru/node/43550" not in urls
    assert "https://lib.permkrai.ru/node/722" not in urls
    assert all(card["listing_title"] for card in cards)
    assert not pages
    assert signals["discovery_selector"] == "a.elis-catalog-item[href][tabindex][aria-label]"


def test_v6_card_transport_failure_is_reviewed_and_does_not_stop_next_card(tmp_path, monkeypatch):
    module = runner()
    map_html = (FIXTURES / "permkrai_node_23121_contract.html").read_bytes()
    scope = {
        "scope_version": "fixture-v6", "rubric_url": "https://lib.permkrai.ru/node/722",
        "rubric_node_id": 722, "min_crawl_delay": 0, "max_get_per_invocation": 20,
        "module_sha256": module.sha(module.FROZEN / "scripts/modules/scrapers/searcher_permkrai.py"),
    }
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    def raw(url):
        if url.endswith("robots.txt"):
            return 200, "text/plain", b"User-agent: *\nAllow: /\n", "", url
        if url.endswith("/node/722"):
            return 200, "text/html", (
                b'<a class="elis-catalog-item" tabindex="100" href="/node/1" aria-label="bad map">bad</a>'
                b'<a class="elis-catalog-item" tabindex="100" href="/node/23121" aria-label="good map">good</a>'
            ), "", url
        if url.endswith("/node/1"):
            raise ConnectionError("hard fail")
        if url.endswith("/node/23121"):
            return 200, "text/html", map_html, "", url
        raise AssertionError(url)

    attempt, code = module.run(output=tmp_path, raw=raw, scope=scope)
    coverage = json.loads((attempt / "coverage.json").read_text(encoding="utf-8"))
    report = json.loads((attempt / "REPORT.json").read_text(encoding="utf-8"))
    assert code == 2
    assert coverage["for_review"] is True
    assert coverage["records"] == 1
    assert len(coverage["completed_cards"]) == 2
    assert coverage["review_nodes"] == [{
        "url": "https://lib.permkrai.ru/node/1", "listing_title": "bad map",
        "kind": "card_transport_error", "reason": "card_transport_error", "transport_attempts": 3,
    }]
    assert report["status"] == "rubric_completed_with_review"
