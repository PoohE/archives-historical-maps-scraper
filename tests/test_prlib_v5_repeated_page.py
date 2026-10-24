"""Regression: real PRLIB page repetition is a reviewable partial result."""
import hashlib
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import searcher_libraries as lib

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "tests" / "fixtures" / "prlib_search_repeated_page_mosalsk_20260919.html"
STATE = ROOT / "tests" / "fixtures" / "prlib_search_repeated_page_mosalsk_20260919_state.json"


class PrlibV5RepeatedPageTests(unittest.TestCase):
    def test_real_mosalsk_page_20_becomes_for_review_partial(self):
        saved = json.loads(STATE.read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(HTML.read_bytes()).hexdigest(), saved["html_sha256"])
        response = SimpleNamespace(
            text=HTML.read_text(encoding="utf-8"),
            access_report={"classification": {"verdict": "more_pages", "reason": "results_with_next"}},
        )
        coverage = {}
        with patch("prlib_access.fetch_page", return_value=response):
            iterator = lib._search_prlib(saved["query"], 1700, 1980, 1, coverage, saved["resume"])
            with self.assertRaisesRegex(lib.PrLibIncompleteSearch, "repeated_page"):
                list(iterator)
        self.assertEqual(coverage["status"], "partial")
        self.assertEqual(coverage["stop_reason"], "repeated_page")
        self.assertTrue(coverage["for_review"])
        self.assertEqual(coverage["max_page"], 20)
        self.assertEqual(coverage["resume"]["page"], 20)
        self.assertGreater(len(coverage["resume"]["seen"]), 0)
