"""Frozen RGADA v2 regression for raw robots.txt with legacy bytes."""

import hashlib
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/rgada_catalog_full_handoff_20260921_v2"
RAW = ROOT / "output/rgada_fixtures_2026-09-21/robots_RAW_bytes.txt"


@unittest.skipUnless(PACKAGE.is_dir(), "build RGADA v2 package before frozen test")
class FrozenRgadaV2RobotsTests(unittest.TestCase):
    def test_raw_robots_passes_runner_policy(self):
        spec = importlib.util.spec_from_file_location(
            "rgada_v2", PACKAGE / "run_catalog.py"
        )
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        body = RAW.read_bytes()
        log = {"requests": 0}

        policy, delay = runner.get_robots(
            lambda _: (200, "text/plain; charset=utf-8", body, ""), log
        )

        self.assertEqual(delay, 3)
        self.assertTrue(policy.can_fetch(runner.AGENT, runner.SEARCH))
        self.assertEqual(log["requests"], 1)
        self.assertEqual(log["robots_sha256"], hashlib.sha256(body).hexdigest())
