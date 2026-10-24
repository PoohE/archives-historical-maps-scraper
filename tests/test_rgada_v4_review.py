"""Regression for RGADA v4 bounded-field policy and offline v3 review."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from scrapers import searcher_rgada as rgada

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output/rgada_catalog_full_20260922_v3/records_full.jsonl"


class RgadaKeywordAndDateTests(unittest.TestCase):
    def test_inflectional_keywords_are_matched_with_boundaries(self):
        record = rgada.RgadaRecord(
            list_name="Карты, планам и топографическим съемкам",
            annotation="чертежами и атласами",
        )
        self.assertEqual(
            rgada.keyword_matches(
                record,
                ("карта", "план", "атлас", "съёмка", "чертёж", "топографическая"),
            ),
            ("карта", "план", "атлас", "съёмка", "чертёж", "топографическая"),
        )
        self.assertEqual(rgada.keyword_matches(
            rgada.RgadaRecord(list_name="картотека"), ("карта",)
        ), ())

    def test_result_url_opisanie_recovers_year_interval(self):
        record = rgada.RgadaRecord(
            url=(
                "http://rgada.info/poisk/index2.php?str=1&"
                "opisanie=%D0%9F%D0%BB%D0%B0%D0%BD%D1%8B+1757-1917+%D0%B3%D0%B3."
            )
        )
        self.assertEqual(rgada.metadata_years(record), (1757, 1917))


class RgadaV3OfflineReviewTests(unittest.TestCase):
    def test_review_preserves_input_and_records_its_limit(self):
        before = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
        spec = importlib.util.spec_from_file_location(
            "rgada_review", ROOT / "scripts/review_rgada_v3_20260923.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            report = module.run(Path(temporary) / "review")
            derived = Path(temporary) / "review"
            coverage = json.loads(
                (derived / "coverage_acceptance.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len((derived / "records_enriched.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()), 98)
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), before)
        self.assertEqual(report["keyword_audit"]["population"], "candidate_rows_only")
        self.assertTrue(report["keyword_audit"]["raw_result_rows_not_reconstructable"])
        self.assertEqual(report["coverage_acceptance"]["accepted_queries"], 4)
        self.assertFalse(any(item["for_review"] for item in coverage))


if __name__ == "__main__":
    unittest.main()
