import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/rgia_catalog_resume_handoff_20260923_v2"
PRIOR = ROOT / "output/rgia_catalog_full_20260923_v1"
FIX = ROOT / "output/rgia_fixtures_2026-09-22"


def test_real_v1_state_is_accepted_without_refetching_completed_id():
    spec = importlib.util.spec_from_file_location("rgia_resume_v2", PACKAGE / "run_catalog.py")
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    robots = (FIX / "robots_RAW_bytes.txt").read_bytes()
    search = (FIX / "live_WORKING_karta_kaluzhsk.html").read_bytes()
    root = json.dumps([{"id": "1050_0_74", "text": "Дела (74)"}]).encode()
    state = json.loads((PRIOR / "rgia_query_state.json").read_text(encoding="utf-8"))
    completed = state["completed_ids"][0]
    nodes = json.dumps([{"id": completed, "text": "already complete"}]).encode()
    calls = []

    def raw(url, params=None):
        calls.append(url)
        path = urlsplit(url).path
        if path == "/robots.txt":
            return 200, "text/plain", robots, "", url
        if path == "/search":
            return 200, "text/html", search, "", url
        if path.startswith("/ajax/tree/"):
            return 200, "application/json", root if params["id"] == "0" else nodes, "", url
        if path.startswith("/ajax/obj/"):
            raise AssertionError("completed id was fetched again: " + url)
        raise AssertionError(url)

    with tempfile.TemporaryDirectory() as temporary:
        out = Path(temporary) / "out"
        out.mkdir()
        for name in ("rgia_query_state.json", "records_full.jsonl", "records.csv", "run_scope.json"):
            shutil.copy2(PRIOR / name, out / name)
        attempt, code = runner.run(output=out, raw=raw)
        report = json.loads((attempt / "REPORT.json").read_text(encoding="utf-8"))
        migration_path = attempt / "RESUME_MIGRATION.json"
        migrated = json.loads((out / "rgia_query_state.json").read_text(encoding="utf-8"))
    assert code == 0
    assert report["listed_case_ids"] == 1
    assert not any("/ajax/obj/" in url for url in calls)
    # A first resume writes the audit record; an already migrated real state
    # must be accepted unchanged on the idempotent continuation path.
    if migration_path.exists():
        migration = json.loads(migration_path.read_text(encoding="utf-8"))
        assert migration["reason"] == "verified_detail_classification_and_single_tree_response"
        assert migrated["migration_history"][-1] == migration
    else:
        assert migrated.get("migration_history")
