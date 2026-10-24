"""RGADA real-fixture regressions for the v1 full-catalog package (offline)."""

import hashlib
import json
import unittest
from pathlib import Path

import classify_stop as cs
from scrapers import searcher_rgada as rgada

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "output/rgada_fixtures_2026-09-21"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


class RgadaFixtureTests(unittest.TestCase):
    def item(self, label):
        return next(value for value in MANIFEST if value["label"] == label)

    def body(self, label):
        return (FIXTURES / (label + ".html")).read_bytes()

    def test_captured_hashes_and_parser_counts(self):
        for item in MANIFEST:
            body = self.body(item["label"])
            self.assertEqual(len(body), item["bytes"])
            self.assertEqual(hashlib.sha256(body).hexdigest(), item["sha256"])
            records, has_next = rgada._parse_page(body.decode("utf-8"))
            self.assertEqual(len(records), item["records_parsed"])
            self.assertEqual(has_next, item["has_next"])

    def test_profile_real_results_and_empty_verdicts(self):
        expected = {
            "results_list_name_kaluzh_p1": cs.REPORTED_END,
            "results_fund_name_kaluzh_p1": cs.MORE_PAGES,
            "empty_list_name_nonsense": cs.REPORTED_END,
        }
        for label, wanted in expected.items():
            item = self.item(label)
            verdict = cs.classify_response(
                item["status"],
                "text/html; charset=utf-8",
                self.body(label),
                url=item["effective_url"],
                profile=cs.RGADA,
            )
            self.assertEqual(verdict["verdict"], wanted, label)
            self.assertEqual(
                verdict["evidence"]["items"], item["records_parsed"], label
            )

    def test_out_of_range_page_has_same_fingerprint_for_repeated_page_guard(self):
        first = self.body("results_list_name_kaluzh_p1")
        repeated = self.body("results_list_name_kaluzh_p2")
        self.assertEqual(
            hashlib.sha256(first).hexdigest(), hashlib.sha256(repeated).hexdigest()
        )
        records, _ = rgada._parse_page(repeated.decode("utf-8"))
        self.assertEqual(len(records), 25)

    def test_barriers_remain_fatal(self):
        for status in (401, 403, 429):
            self.assertEqual(
                cs.classify_response(status, "text/html", b"", profile=cs.RGADA)[
                    "verdict"
                ],
                cs.REAL_BARRIER,
            )
        self.assertEqual(
            cs.classify_response(
                200, "text/html", b'<div class="g-recaptcha"></div>', profile=cs.RGADA
            )["verdict"],
            cs.REAL_BARRIER,
        )
