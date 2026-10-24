"""Offline frozen-package checks for Permkrai maps-rubric v4."""
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/permkrai_catalog_maps_handoff_20260927_v4"
FIXTURES = ROOT / "tests/fixtures"


def runner():
    for name in ("durable_state", "classify_stop", "notion_export", "searcher_permkrai",
                 "permkrai_chrome_transport", "permkrai_notion", "cartographic_enrichment",
                 "library_dates", "administrative_level"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("permkrai_v4", PACKAGE / "run_catalog.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_v4_frozen_contract():
    module = runner()
    assert module.verify()
    scope = json.loads((PACKAGE / "scope.json").read_text(encoding="utf-8"))
    assert scope["csv_scalar_columns"] == 65
    assert scope["min_crawl_delay"] == 10
    assert scope["discovery"]["card_grid_required"] is True
    assert "/search/" in scope["prohibited_routes"]


def test_v4_excludes_collection_and_persists_raw_html(tmp_path):
    module = runner()
    collection = (FIXTURES / "permkrai_node_43550_collection_contract.html").read_bytes()
    map_html = (FIXTURES / "permkrai_node_23121_contract.html").read_bytes()
    scope = {"scope_version": "fixture-v4", "rubric_url": "https://lib.permkrai.ru/node/722", "rubric_node_id": 722,
             "min_crawl_delay": 0, "max_get_per_invocation": 10,
             "module_sha256": module.sha(module.FROZEN / "scripts/modules/scrapers/searcher_permkrai.py")}
    def raw(url):
        if url.endswith("robots.txt"):
            return 200, "text/plain", b"User-agent: *\nAllow: /\n", "", url
        if url.endswith("/node/722"):
            body = b'<div class="view-content"><div class="views-row"><a href="/node/43550">collection</a><a href="/node/23121">map</a></div></div>'
            return 200, "text/html", body, "", url
        if url.endswith("/node/43550"):
            return 200, "text/html", collection, "", url
        if url.endswith("/node/23121"):
            return 200, "text/html", map_html, "", url
        raise AssertionError(url)
    attempt, code = module.run(output=tmp_path, raw=raw, scope=scope)
    coverage = json.loads((attempt / "coverage.json").read_text(encoding="utf-8"))
    assert code == 0
    assert len(coverage["excluded_nodes"]) == 1
    assert coverage["excluded_nodes"][0]["url"].endswith("/node/43550")
    assert (attempt / coverage["excluded_nodes"][0]["raw_card_html"]["path"]).is_file()
    assert len(coverage["completed_cards"]) == 1
    assert (attempt / "raw_cards").is_dir()
