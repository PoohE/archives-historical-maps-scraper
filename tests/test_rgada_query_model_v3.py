"""Offline regression for RGADA single-territory-term query model."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from scrapers import searcher_rgada as rgada

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "output/rgada_fixtures_2026-09-21"
PACKAGE = ROOT / "output/rgada_catalog_full_handoff_20260922_v3"
KEYWORDS = ("карта", "план", "атлас", "съёмка", "чертёж", "топографическая")


class RgadaSingleTermSourceTests(unittest.TestCase):
    def test_real_kaluzh_fixture_is_filtered_locally(self):
        body = (FIXTURES / "results_list_name_kaluzh_p1.html").read_text(
            encoding="utf-8"
        )
        records, has_next = rgada._parse_page(body)
        self.assertEqual(len(records), 25)
        self.assertFalse(has_next)
        matched = [rgada.keyword_matches(record, KEYWORDS) for record in records]
        self.assertTrue(any("план" in values for values in matched))
        self.assertTrue(any(values for values in matched))


@unittest.skipUnless(PACKAGE.is_dir(), "build RGADA v3 package before frozen test")
class FrozenRgadaV3QueryModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "rgada_v3", PACKAGE / "run_catalog.py"
        )
        cls.runner = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.runner)

    def test_single_term_is_sent_to_both_fields_and_fund_pagination_continues(self):
        runner = self.runner
        robots = (FIXTURES / "robots.txt").read_bytes()
        list_page = (FIXTURES / "results_list_name_kaluzh_p1.html").read_bytes()
        fund_page = (FIXTURES / "results_fund_name_kaluzh_p1.html").read_bytes()
        calls = []

        def getter(url):
            path = urlsplit(url).path
            if path == "/robots.txt":
                return 200, "text/plain", robots, ""
            query = parse_qs(urlsplit(url).query)
            calls.append(query)
            field = "list_name" if "list_name" in query else "fund_name"
            page = int(query.get("page", ["1"])[0])
            self.assertEqual(query[field], ["Калужск"])
            self.assertNotIn("карта", query[field][0].casefold())
            if field == "list_name" and page == 1:
                return 200, "text/html", list_page, ""
            if field == "fund_name" and page == 1:
                return 200, "text/html", fund_page, ""
            if field == "fund_name" and page == 2:
                return 200, "text/html", list_page, ""
            raise AssertionError(url)

        scope = {
            "source": "rgada",
            "query_model": "territory_single_term_local_keyword_filter_v1",
            "territories": [
                {"label": "Калужская губерния", "search_term": "Калужск"}
            ],
            "keywords": list(KEYWORDS),
            "max_get_per_invocation": 20,
        }
        with tempfile.TemporaryDirectory() as temporary:
            attempt, code = runner.run(
                output=Path(temporary), getter=getter, test_scope=scope
            )
            report = json.loads((attempt / "REPORT.json").read_text(encoding="utf-8"))
            state_path = next((Path(temporary) / "rgada_query_state").glob("*.json"))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            rows = (Path(temporary) / "records_full.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()

        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "query_scope_completed")
        self.assertEqual(len(calls), 3)
        self.assertEqual(state["scope"]["query"], "Калужск")
        self.assertEqual(state["coverage"]["max_page"], 2)
        self.assertEqual(state["coverage"]["fields"]["fund_name"]["resume_page"], 2)
        self.assertGreater(len(rows), 0)
        self.assertTrue(any("план" in json.loads(row)["keyword"] for row in rows))


if __name__ == "__main__":
    unittest.main()