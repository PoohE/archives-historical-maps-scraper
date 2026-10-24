"""Offline regression for the v7 rendered-wait discovery sequence."""

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/permkrai_catalog_maps_handoff_20260929_v8_1"
V5_RENDERED = (
    ROOT / "output/permkrai_catalog_maps_20260927_v5/attempts"
    / "20260927_060506_19f7239e/raw_html/rubric_rendered_722_715d804466d0.html"
)
V6_LOADING = (
    ROOT / "output/permkrai_catalog_maps_20260927_v6/attempts"
    / "20260927_134427_2fbc470c/raw_html/rubric_722_af593db67556.html"
)
FIXTURES = ROOT / "tests/fixtures"


def runner():
    for name in (
        "durable_state", "classify_stop", "notion_export", "searcher_permkrai",
        "permkrai_chrome_transport", "permkrai_notion", "cartographic_enrichment",
        "library_dates", "administrative_level",
    ):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("permkrai_v7", PACKAGE / "run_catalog.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_v7_real_rendered_rubric_selects_41_maps_and_excludes_collections():
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
    assert not pages
    assert signals["catalog_anchors"] == 41


def test_v7_transport_waits_for_card_selector_and_scrolls_until_count_stable():
    module = runner()

    class Locator:
        def __init__(self, page):
            self.page = page

        def count(self):
            return [0, 1, 2, 3, 3, 3][self.page.index]

    class Page:
        url = "https://lib.permkrai.ru/node/722"

        def __init__(self):
            self.index = 0
            self.wait_calls = []

        def content(self):
            return "<html><body>" + "<a class='elis-catalog-item'></a>" * self.index + "</body></html>"

        def wait_for_selector(self, selector, **kwargs):
            self.wait_calls.append((selector, kwargs))
            self.index = 1

        def locator(self, selector):
            assert selector == "a.elis-catalog-item"
            return Locator(self)

        def wait_for_timeout(self, milliseconds):
            assert milliseconds >= 0

        def evaluate(self, script):
            assert script == "window.scrollTo(0, document.body.scrollHeight)"
            self.index = min(self.index + 1, 5)

    page = Page()
    transport = module.ChromeTransport(timeout_ms=123)
    transport._page = page
    transport.expand_current_listing(0, max_scrolls=10)
    meta = transport.last_listing_meta
    assert page.wait_calls == [("a.elis-catalog-item", {"state": "attached", "timeout": 123})]
    assert meta["render_wait_satisfied"] is True
    assert meta["dom_stable"] is True
    assert meta["card_count_sequence"] == [1, 2, 3, 3, 3]
    assert meta["final_card_count"] == 3


def test_v7_browser_renders_before_discovery_and_persists_rendered_backstop(tmp_path, monkeypatch):
    module = runner()
    map_html = (FIXTURES / "permkrai_node_23121_contract.html").read_bytes()
    rendered = (
        '<a class="elis-catalog-item" tabindex="1" href="/node/23121" aria-label="map">map</a>'
    )

    class Browser:
        last_listing_meta = {}

        def expand_current_listing(self, delay):
            self.last_listing_meta = {
                "render_wait_satisfied": True, "dom_stable": True, "scroll_steps": 2,
                "initial_card_count": 0, "final_card_count": 1, "card_count_sequence": [0, 1, 1, 1],
            }
            return rendered

    scope = {
        "scope_version": "fixture-v7", "rubric_url": "https://lib.permkrai.ru/node/722",
        "rubric_node_id": 722, "min_crawl_delay": 0, "max_get_per_invocation": 20,
        "module_sha256": module.sha(module.FROZEN / "scripts/modules/scrapers/searcher_permkrai.py"),
    }
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    def raw(url):
        if url.endswith("robots.txt"):
            return 200, "text/plain", b"User-agent: *\nAllow: /\n", "", url
        if url.endswith("/node/722"):
            return 200, "text/html", V6_LOADING.read_bytes(), "", url
        if url.endswith("/node/23121"):
            return 200, "text/html", map_html, "", url
        raise AssertionError(url)

    # Inject the browser at the collection boundary: production ``run`` owns a
    # real headed Chrome context, while this fixture verifies the order without
    # opening a browser or touching the network.
    attempt, code = module.collect(tmp_path, raw, scope, live=False, stale=False, browser=Browser())
    coverage = json.loads((attempt / "coverage.json").read_text(encoding="utf-8"))
    rendered_files = list((attempt / "raw_html").glob("rubric_rendered_722_*.html"))
    assert code == 0
    assert coverage["records"] == 1
    assert len(rendered_files) == 1
    assert rendered_files[0].read_text(encoding="utf-8") == rendered
    assert not list((attempt / "raw_html").glob("rubric_static_722_*.html"))


def test_v7_card_transport_failure_is_reviewed_and_next_card_is_collected(tmp_path, monkeypatch):
    module = runner()
    map_html = (FIXTURES / "permkrai_node_23121_contract.html").read_bytes()
    scope = {
        "scope_version": "fixture-v7-card", "rubric_url": "https://lib.permkrai.ru/node/722",
        "rubric_node_id": 722, "min_crawl_delay": 0, "max_get_per_invocation": 20,
        "module_sha256": module.sha(module.FROZEN / "scripts/modules/scrapers/searcher_permkrai.py"),
    }
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    def raw(url):
        if url.endswith("robots.txt"):
            return 200, "text/plain", b"User-agent: *\nAllow: /\n", "", url
        if url.endswith("/node/722"):
            return 200, "text/html", (
                b'<a class="elis-catalog-item" tabindex="100" href="/node/1" aria-label="bad">bad</a>'
                b'<a class="elis-catalog-item" tabindex="100" href="/node/23121" aria-label="good">good</a>'
            ), "", url
        if url.endswith("/node/1"):
            raise ConnectionError("hard fail")
        if url.endswith("/node/23121"):
            return 200, "text/html", map_html, "", url
        raise AssertionError(url)

    attempt, code = module.run(output=tmp_path, raw=raw, scope=scope)
    coverage = json.loads((attempt / "coverage.json").read_text(encoding="utf-8"))
    assert code == 0
    assert coverage["for_review"] is True
    assert coverage["records"] == 1
    assert len(coverage["completed_cards"]) == 2
