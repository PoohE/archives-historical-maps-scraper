"""RGIA resume v3 must preserve completed state and collect later nPage IDs."""
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/rgia_catalog_resume_handoff_20260923_v5"
PRIOR = ROOT / "output/rgia_catalog_full_20260923_v1"
FIX = ROOT / "output/rgia_fixtures_2026-09-22"
DETAIL = ROOT / "output/rgia_detail_evidence_20260923_v2/detail.raw.json"


def test_resume_v3_keeps_completed_ids_and_fetches_only_later_npage():
    spec = importlib.util.spec_from_file_location("rgia_resume_v5", PACKAGE / "run_catalog.py")
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    robots = (FIX / "robots_RAW_bytes.txt").read_bytes()
    search = (FIX / "live_WORKING_karta_kaluzhsk.html").read_bytes()
    detail = DETAIL.read_bytes()
    prior_state = json.loads((PRIOR / "rgia_query_state.json").read_text(encoding="utf-8"))
    completed = prior_state["completed_ids"][0]
    new_id = "5191018"
    root = json.dumps([{"id": "1050_0_74", "text": "Дела (74)"}]).encode()
    page1 = json.dumps([
        {"id": None, "text": "1,1,1,2,2"},
        {"id": completed, "text": "completed"},
    ]).encode()
    page2 = json.dumps([
        {"id": None, "text": "1,1,1,2,2"},
        {"id": new_id, "text": "new"},
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
            return 200, "application/json", {"1": page1, "2": page2}[params["nPage"]], "", url
        if path.startswith("/ajax/obj/"):
            assert completed not in path
            assert new_id in path
            return 200, "application/json", detail, "", url
        raise AssertionError(url)

    with tempfile.TemporaryDirectory() as temporary:
        out = Path(temporary) / "out"
        out.mkdir()
        for name in ("rgia_query_state.json", "records_full.jsonl", "records.csv", "run_scope.json"):
            shutil.copy2(PRIOR / name, out / name)
        attempt, code = runner.run(output=out, raw=raw)
        state = json.loads((out / "rgia_query_state.json").read_text(encoding="utf-8"))
        report = json.loads((attempt / "REPORT.json").read_text(encoding="utf-8"))
        rows = (out / "records_full.jsonl").read_text(encoding="utf-8").splitlines()
    tree_pages = [params["nPage"] for url, params in calls if "/ajax/tree/" in url and params["id"] != "0"]
    assert code == 0, json.dumps(report, ensure_ascii=False, indent=2)
    assert tree_pages == ["1", "2"]
    assert new_id in state["completed_ids"]
    assert len(rows) == 21
    assert report["tree_pagination"] == "nPage"
    assert report["tree_pages"] == 2
