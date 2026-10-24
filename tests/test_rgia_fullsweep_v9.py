"""Frozen RGIA v4 must use nPage rather than the ignored page parameter."""
import importlib.util
import json
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/rgia_catalog_full_handoff_20260923_v9"
FIX = ROOT / "output/rgia_fixtures_2026-09-22"
DETAIL = ROOT / "output/rgia_detail_evidence_20260923_v2/detail.raw.json"


def test_frozen_fullsweep_uses_all_npage_responses():
    spec = importlib.util.spec_from_file_location("rgia_full_v9", PACKAGE / "run_catalog.py")
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    search = (FIX / "live_WORKING_karta_kaluzhsk.html").read_bytes()
    robots = (FIX / "robots_RAW_bytes.txt").read_bytes()
    normal = DETAIL.read_bytes()
    noncase = json.dumps({
        "title": "Лист без самостоятельного дела",
        "attributes": [{"name": "Шифр", "text": "Ф. 58 Оп. 3"}],
    }).encode()
    root = json.dumps([{"id": "1050_0_74", "text": "Дела (74)"}]).encode()
    page1 = json.dumps([
        {"id": None, "text": "1,1,1,2,2"},
        {"id": "5191017", "text": "case 1"},
    ]).encode()
    page2 = json.dumps([
        {"id": None, "text": "1,1,1,2,2"},
        {"id": "2576973831", "text": "case 2"},
    ]).encode()
    calls = []

    def raw(url, params=None):
        calls.append((url, dict(params or {})))
        path = urlsplit(url).path
        if path == "/robots.txt":
            return 200, "text/plain", robots, "", url
        if path == "/search":
            return 200, "text/html", search, "", url
        if path.startswith("/ajax/tree/"):
            if params["id"] == "0":
                return 200, "application/json", root, "", url
            assert params["page"] == "1"
            return 200, "application/json", {"1": page1, "2": page2}[params["nPage"]], "", url
        if path.endswith("/5191017/112968"):
            return 200, "application/json", normal, "", url
        if path.endswith("/2576973831/112968"):
            return 200, "application/json", noncase, "", url
        raise AssertionError(url)

    scope = {
        **json.loads((PACKAGE / "scope.json").read_text(encoding="utf-8")),
        "territories": [["Калужская губерния", "Калужская"]],
        "keywords": ["карта"],
        "min_crawl_delay": 0,
        "max_get_per_invocation": 10,
    }
    with tempfile.TemporaryDirectory() as temp:
        attempt, code = runner.run(output=Path(temp) / "out", raw=raw, test_scope=scope)
        report = json.loads((attempt / "REPORT.json").read_text(encoding="utf-8"))
        coverage = json.loads((attempt / "coverage.json").read_text(encoding="utf-8"))
    tree_calls = [call for call in calls if "/ajax/tree/" in call[0]]
    assert code == 0, json.dumps(report, ensure_ascii=False, indent=2)
    assert len(tree_calls) == 3
    assert report["status"] == "query_scope_review"
    assert coverage[0]["max_tree_page"] == 2
    assert coverage[0]["tree_pagination"] == "nPage"
    assert coverage[0]["noncase_review"][0]["object_id"] == "2576973831"
