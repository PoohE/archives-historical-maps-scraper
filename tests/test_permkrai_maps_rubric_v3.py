"""Offline contract for the frozen PermKrai maps-rubric package."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/permkrai_catalog_maps_handoff_20260926_v3"


def runner():
    for name in ("durable_state", "classify_stop", "notion_export", "searcher_permkrai",
                 "permkrai_chrome_transport", "permkrai_notion", "cartographic_enrichment",
                 "library_dates", "administrative_level"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("permkrai_v3", PACKAGE / "run_catalog.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_v3_is_rubric_only_and_frozen_contract_is_valid():
    module = runner()
    assert module.verify()
    scope = json.loads((PACKAGE / "scope.json").read_text(encoding="utf-8"))
    assert scope["rubric_url"] == "https://lib.permkrai.ru/node/722"
    assert scope["min_crawl_delay"] == 10
    assert scope["csv_scalar_columns"] == 65
    assert "/search/" in scope["prohibited_routes"]
    assert module.node_url("https://lib.permkrai.ru/node/722?page=1", 722).endswith("?page=1")
    assert module.node_url("https://lib.permkrai.ru/node/33626", 722).endswith("/node/33626")
    with pytest.raises(module.FatalStop):
        module.node_url("https://lib.permkrai.ru/search/professional", 722)


def test_v3_offline_fixture_proves_pager_resume_contract_without_search():
    result = runner().offline_self_test()
    assert result["exit_code"] == 0
    assert result["pagination"] == "page_parameter"
    assert result["rows"] == 2
    assert result["columns"] == 65
    assert result["complete"] is True
    assert result["search_called"] is False


def test_v3_load_more_marker_is_partial_not_false_completion(tmp_path):
    module = runner()
    scope = {
        "scope_version": "load_more_fixture", "rubric_url": "https://lib.permkrai.ru/node/722",
        "rubric_node_id": 722, "min_crawl_delay": 0, "max_get_per_invocation": 10,
        "module_sha256": module.sha(module.FROZEN / "scripts/modules/scrapers/searcher_permkrai.py"),
    }
    def raw(url):
        if url.endswith("robots.txt"):
            return 200, "text/plain", b"User-agent: *\nAllow: /\n", "", url
        return 200, "text/html", '<a href="/node/1">one</a><button>Показать ещё</button>'.encode("utf-8"), "", url
    attempt, code = module.run(output=tmp_path, raw=raw, scope=scope)
    coverage = json.loads((attempt / "coverage.json").read_text(encoding="utf-8"))
    assert code == 2
    assert coverage["status"] == "partial"
    assert coverage["stop_reason"] == "rubric_load_more_unresolved"
    assert coverage["full_rubric_complete"] is False
