"""Frozen RGIA full-runner regression using saved public evidence only."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/rgia_catalog_full_handoff_20260923_v1"
FIXTURES = ROOT / "output/rgia_fixtures_2026-09-22"
DETAIL = ROOT / "output/rgia_detail_evidence_20260923_v2/detail.raw.json"


@unittest.skipUnless(PACKAGE.is_dir(), "build RGIA full frozen package first")
class FrozenRgiaCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "rgia_full", PACKAGE / "run_catalog.py"
        )
        cls.runner = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.runner)

    def test_one_saved_case_reaches_66_field_candidate_csv(self):
        search = (FIXTURES / "live_WORKING_karta_kaluzhsk.html").read_bytes()
        robots = (FIXTURES / "robots_RAW_bytes.txt").read_bytes()
        detail = DETAIL.read_bytes()
        root = json.dumps([
            {"id": "1050_0_74", "text": "Дела (74)"}
        ]).encode()
        nodes = json.dumps([
            {"id": None, "text": "1,1,1,1,1"},
            {"id": "5191017", "text": "<div>дело 1</div>"},
        ]).encode()

        def raw(url, params=None):
            if url.endswith("/robots.txt"):
                return 200, "text/plain", robots, "", url
            if url.endswith("/search"):
                self.assertEqual(params["p0.v"], "карта калужск")
                return 200, "text/html", search, "", url
            if "/ajax/tree/" in url:
                return 200, "application/json", (
                    root if params["id"] == "0" else nodes
                ), "", url
            if "/ajax/obj/" in url:
                return 200, "application/json", detail, "", url
            raise AssertionError(url)

        scope = {
            "source": "rgia", "record_level": "archival_case",
            "query": "карта калужск", "query_human": "карта Калужская губерния",
            "simple_component_id": 72425, "tree_page_size": 12,
            "fallback_crawl_delay": 0, "max_get_per_invocation": 10,
            "expected_cases_observed": 1, "metadata_only": True,
            "forms_or_post": False, "authentication": False,
            "captcha_bypass": False, "vpn_or_proxy": False, "headless": False,
            "notion_or_canonical_ontology": False, "ready_for_import": False,
        }
        with tempfile.TemporaryDirectory() as temporary:
            attempt, code = self.runner.run(
                output=Path(temporary) / "out", raw=raw, test_scope=scope
            )
            report = json.loads((attempt / "REPORT.json").read_text(encoding="utf-8"))
            output = Path(temporary) / "out"
            rows = (output / "records_full.jsonl").read_text(encoding="utf-8").splitlines()
            export = json.loads((output / "notion_csv/export_review.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "query_scope_completed")
        self.assertEqual(report["csv_export"]["columns"], 66)
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0])["record"]["title"],
                         "Генеральная карта Калужского наместничества")
        self.assertEqual(export["roundtrip"], "passed")


if __name__ == "__main__":
    unittest.main()
