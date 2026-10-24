"""Offline regression for the RGIA v10 slow-drain and durable transition."""

import importlib.util
import json
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/rgia_catalog_full_handoff_20260926_v10"
FIX = ROOT / "output/rgia_fixtures_2026-09-22"
DETAIL = ROOT / "output/rgia_detail_evidence_20260923_v2/detail.raw.json"


def test_v10_transport_partial_stop_preserves_next_query_and_raw_detail():
    spec = importlib.util.spec_from_file_location("rgia_full_v10", PACKAGE / "run_catalog.py")
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    search = (FIX / "live_WORKING_karta_kaluzhsk.html").read_bytes()
    robots = (FIX / "robots_RAW_bytes.txt").read_bytes()
    detail = DETAIL.read_bytes()
    root = json.dumps([{"id": "1050_0_74", "text": "Дела (1)"}]).encode()
    nodes = json.dumps([
        {"id": None, "text": "1,1,1,1,1"},
        {"id": "5191017", "text": "case 1"},
    ]).encode()
    seen_searches = 0

    def raw(url, params=None):
        nonlocal seen_searches
        path = urlsplit(url).path
        if path == "/robots.txt":
            return 200, "text/plain", robots, "", url
        if path == "/search":
            seen_searches += 1
            return 200, "text/html", search, "", url
        if path.startswith("/ajax/tree/") and seen_searches == 2:
            raise TimeoutError("fixture transport throttle")
        if path.startswith("/ajax/tree/") and params["id"] == "0":
            return 200, "application/json", root, "", url
        if path.startswith("/ajax/tree/"):
            return 200, "application/json", nodes, "", url
        if path.endswith("/5191017/112968"):
            return 200, "application/json", detail, "", url
        raise AssertionError(url)

    scope = {
        **json.loads((PACKAGE / "scope.json").read_text(encoding="utf-8")),
        "territories": [
            ["Калужская губерния", "Калужская"],
            ["Пермская губерния", "Пермская"],
        ],
        "keywords": ["карта"],
        "min_crawl_delay": 0,
        "max_get_per_invocation": 12,
    }
    runner.time.sleep = lambda _: None
    with tempfile.TemporaryDirectory() as tmp:
        attempt, code = runner.run(output=Path(tmp) / "out", raw=raw, test_scope=scope)
        out = Path(tmp) / "out"
        report = json.loads((attempt / "REPORT.json").read_text(encoding="utf-8"))
        progress = json.loads((out / "query_progress.json").read_text(encoding="utf-8"))
        record = json.loads((out / "records_full.jsonl").read_text(encoding="utf-8"))
        requests = [
            json.loads(line)
            for line in (attempt / "requests.jsonl").read_text(encoding="utf-8").splitlines()
        ]
    assert code == 3
    assert report["status"] == "partial"
    assert report["stop_reason"] == "transport_error"
    assert progress["completed_queries"] == 1
    assert progress["next_query"]["territory"] == "Пермская губерния"
    assert report["next_query"] == progress["next_query"]
    assert record["record"]["extra"]["raw_detail"]["attributes"]
    assert [event["backoff_seconds"] for event in requests if event["event"] == "transport_retry_scheduled"] == [15, 45, 120]
