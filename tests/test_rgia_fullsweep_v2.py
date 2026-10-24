import importlib.util
import json
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/rgia_catalog_full_handoff_20260923_v2"
FIX = ROOT / "output/rgia_fixtures_2026-09-22"
DETAIL = ROOT / "output/rgia_detail_evidence_20260923_v2/detail.raw.json"


def test_frozen_fullsweep_one_query_records_requests_and_66_columns():
    spec = importlib.util.spec_from_file_location(
        "rgia_full", PACKAGE / "run_catalog.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    search = (FIX / "live_WORKING_karta_kaluzhsk.html").read_bytes()
    robots = (FIX / "robots_RAW_bytes.txt").read_bytes()
    detail = DETAIL.read_bytes()
    root = json.dumps([{"id": "1050_0_74", "text": "Дела (74)"}]).encode()
    nodes = json.dumps(
        [{"id": None, "text": "1,1,1,1,1"}, {"id": "5191017", "text": "case"}]
    ).encode()

    def raw(url, params=None):
        path = urlsplit(url).path
        if path == "/robots.txt":
            return 200, "text/plain", robots, "", url
        if path == "/search":
            return 200, "text/html", search, "", url
        if path.startswith("/ajax/tree/"):
            return (
                200,
                "application/json",
                root if params["id"] == "0" else nodes,
                "",
                url,
            )
        if path.startswith("/ajax/obj/"):
            return 200, "application/json", detail, "", url
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
        log = (attempt / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    assert code == 0
    assert report["status"] == "query_scope_completed"
    assert report["total_queries"] == 1 and report["completed_queries"] == 1
    assert report["columns"] == 66 and report["roundtrip"] == "passed"
    assert coverage[0]["status"] == "reported_end"
    assert len(log) >= 10
