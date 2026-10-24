"""Frozen RGADA v1 runner regression, entirely fixture-backed and offline."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/rgada_catalog_full_handoff_20260921_v1"
FIXTURES = ROOT / "output/rgada_fixtures_2026-09-21"


@unittest.skipUnless(PACKAGE.is_dir(), "build RGADA v1 package before frozen test")
class FrozenRgadaV1Tests(unittest.TestCase):
    def test_fixture_backed_repeated_page_is_isolated(self):
        spec = importlib.util.spec_from_file_location(
            "rgada_v1", PACKAGE / "run_catalog.py"
        )
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        robots = (FIXTURES / "robots.txt").read_bytes()
        list_page = (FIXTURES / "results_list_name_kaluzh_p1.html").read_bytes()
        fund_page = (FIXTURES / "results_fund_name_kaluzh_p1.html").read_bytes()

        def getter(url):
            path = urlsplit(url).path
            if path == "/robots.txt":
                return 200, "text/plain", robots, ""
            query = parse_qs(urlsplit(url).query)
            field = "list_name" if "list_name" in query else "fund_name"
            page = int(query.get("page", ["1"])[0])
            if field == "list_name" and page == 1:
                return 200, "text/html", list_page, ""
            if field == "fund_name" and page in (1, 2):
                return 200, "text/html", fund_page, ""
            raise AssertionError(url)

        scope = {
            "source": "rgada",
            "territories": [["Калужская губерния", "Калужская"]],
            "keywords": ["карта"],
            "max_get_per_invocation": 20,
        }
        with tempfile.TemporaryDirectory() as tmp:
            attempt, code = runner.run(
                output=Path(tmp), getter=getter, test_scope=scope
            )
            report = json.loads((attempt / "REPORT.json").read_text(encoding="utf-8"))
            state = next((Path(tmp) / "rgada_query_state").glob("*.json"))
            coverage = json.loads(state.read_text(encoding="utf-8"))["coverage"]
            rows = (
                (Path(tmp) / "records_full.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            )
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "query_scope_review")
        self.assertEqual(report["review_queries"], 1)
        self.assertEqual(coverage["stop_reason"], "repeated_page")
        self.assertTrue(coverage["for_review"])
        self.assertGreater(len(rows), 0)
