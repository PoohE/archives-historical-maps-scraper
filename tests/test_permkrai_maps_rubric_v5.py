"""Offline checks for the v5 real-DOM selector package."""

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/permkrai_catalog_maps_handoff_20260927_v5"
FIXTURES = ROOT / "tests/fixtures"


def runner():
    for name in (
        "durable_state", "classify_stop", "notion_export", "searcher_permkrai",
        "permkrai_chrome_transport", "permkrai_notion", "cartographic_enrichment",
        "library_dates", "administrative_level",
    ):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("permkrai_v5", PACKAGE / "run_catalog.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_v5_frozen_contract_uses_real_node_classifier():
    module = runner()
    assert module.verify()
    scope = json.loads((PACKAGE / "scope.json").read_text(encoding="utf-8"))
    assert scope["discovery"]["detail_classifier"] == "body.node-type-pdf|article.node-pdf"
    assert scope["discovery"]["unknown_action"] == "exclude_with_rendered_html"
    assert scope["csv_scalar_columns"] == 65


def test_v5_accepts_pdf_node_excludes_non_pdf_and_keeps_rendered_html(tmp_path):
    module = runner()
    collection = (FIXTURES / "permkrai_node_43550_collection_contract.html").read_bytes()
    map_html = (FIXTURES / "permkrai_node_23121_contract.html").read_bytes()
    non_pdf_with_labels = map_html.replace(b'node-type-pdf', b'node-type-page').replace(b'node-pdf', b'node-page')
    scope = {
        "scope_version": "fixture-v5", "rubric_url": "https://lib.permkrai.ru/node/722",
        "rubric_node_id": 722, "min_crawl_delay": 0, "max_get_per_invocation": 10,
        "module_sha256": module.sha(module.FROZEN / "scripts/modules/scrapers/searcher_permkrai.py"),
    }

    def raw(url):
        if url.endswith("robots.txt"):
            return 200, "text/plain", b"User-agent: *\nAllow: /\n", "", url
        if url.endswith("/node/722"):
            body = (b'<a href="/node/43550">collection</a><a href="/node/23120">nonpdf</a>'
                    b'<a href="/node/23121">map</a>')
            return 200, "text/html", body, "", url
        if url.endswith("/node/43550"):
            return 200, "text/html", collection, "", url
        if url.endswith("/node/23120"):
            return 200, "text/html", non_pdf_with_labels, "", url
        if url.endswith("/node/23121"):
            return 200, "text/html", map_html, "", url
        raise AssertionError(url)

    attempt, code = module.run(output=tmp_path, raw=raw, scope=scope)
    coverage = json.loads((attempt / "coverage.json").read_text(encoding="utf-8"))
    assert code == 0
    assert len(coverage["excluded_nodes"]) == 2
    assert {item["kind"] for item in coverage["excluded_nodes"]} >= {"collection", "non_pdf_node"}
    assert len(coverage["completed_cards"]) == 1
    assert (attempt / "raw_html").is_dir()
    assert len(list((attempt / "raw_html").glob("*.html"))) == 4
