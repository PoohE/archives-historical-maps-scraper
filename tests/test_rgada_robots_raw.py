"""Regression for legacy-byte robots.txt parsing in shared durable state."""

import hashlib
import unittest
from pathlib import Path
from urllib.robotparser import RobotFileParser

from durable_state import decode_robots_text

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "output/rgada_fixtures_2026-09-21/robots_RAW_bytes.txt"
AGENT = "ArchiveReviewProbe/1.0"
SEARCH = "http://rgada.info/poisk/index.php"


class RawRobotsRegressionTests(unittest.TestCase):
    def test_rgada_raw_legacy_bytes_remain_usable(self):
        body = RAW.read_bytes()
        self.assertEqual(len(body), 23950)
        self.assertEqual(
            hashlib.sha256(body).hexdigest(),
            "5c04d0811f8d6aa88f28316d87069d382e38f30292c0c681d38e47106d6cd70a",
        )
        self.assertEqual(body[474], 0xC0)
        policy = RobotFileParser()
        policy.parse(decode_robots_text(body).splitlines())
        self.assertTrue(policy.can_fetch(AGENT, SEARCH))
        self.assertEqual(max(3, policy.crawl_delay(AGENT) or 0), 3)
