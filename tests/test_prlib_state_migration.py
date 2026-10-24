"""Regression checks for manifest-authorized PRLIB state migration on real copies."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import prlib_run_state as state

ROOT = Path(__file__).resolve().parents[1]
REAL_STATE = ROOT / "output/prlib_catalog_full_20260917_v1/prlib_query_state"
MANIFEST_SHA = "f" * 64
HASH_FIELDS = ("parser_sha256", "access_sha256", "detail_sha256")


def empty_iterator():
    if False:
        yield None


class PrlibStateMigrationTests(unittest.TestCase):
    def setUp(self):
        state.configure_migration(None, None)
        self.addCleanup(state.configure_migration, None, None)

    def copy_real_state(self, directory, status):
        source = next(
            path
            for path in REAL_STATE.glob("*.json")
            if json.loads(path.read_text(encoding="utf-8"))["coverage"]["status"]
            == "reported_end"
        )
        record = json.loads(source.read_text(encoding="utf-8"))
        if status == "starting":
            record["coverage"]["status"] = "starting"
        target = state.query_path(directory, record["scope"]["key"])
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(record), encoding="utf-8")
        return target, record

    def hashes(self, record):
        return {field: record["scope"][field] for field in HASH_FIELDS}

    def force_accepted_old_hashes(self, path):
        record = json.loads(path.read_text(encoding="utf-8"))
        record["scope"]["parser_sha256"] = "a" * 64
        path.write_text(json.dumps(record), encoding="utf-8")
        return record

    def test_real_starting_copy_is_migrated_before_offline_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, prior = self.copy_real_state(Path(tmp), "starting")
            prior = self.force_accepted_old_hashes(path)
            old_migrations = len(prior.get("migrations", []))
            state.configure_migration([self.hashes(prior)], MANIFEST_SHA)
            coverage = {}
            with patch.object(
                state.registry, "search", return_value=empty_iterator()
            ) as search:
                self.assertEqual(
                    list(
                        state.iter_query(
                            Path(tmp),
                            prior["scope"]["key"],
                            prior["scope"]["query"],
                            1700,
                            1980,
                            1,
                            coverage,
                        )
                    ),
                    [],
                )
            search.assert_called_once()
            migrated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(migrated["migrations"]), old_migrations + 1)
            self.assertEqual(
                migrated["migrations"][-1]["from_hashes"], self.hashes(prior)
            )

    def test_unknown_real_state_hash_triple_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, prior = self.copy_real_state(Path(tmp), "starting")
            altered = json.loads(path.read_text(encoding="utf-8"))
            altered["scope"]["parser_sha256"] = "0" * 64
            path.write_text(json.dumps(altered), encoding="utf-8")
            state.configure_migration([self.hashes(prior)], MANIFEST_SHA)
            with self.assertRaisesRegex(ValueError, "not accepted"):
                list(
                    state.iter_query(
                        Path(tmp),
                        prior["scope"]["key"],
                        prior["scope"]["query"],
                        1700,
                        1980,
                        1,
                        {},
                    )
                )

    def test_real_reported_end_copy_migrates_without_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, prior = self.copy_real_state(Path(tmp), "reported_end")
            prior = self.force_accepted_old_hashes(path)
            state.configure_migration([self.hashes(prior)], MANIFEST_SHA)
            with patch.object(state.registry, "search") as search:
                self.assertTrue(
                    state.completed_query(Path(tmp), prior["scope"]["key"], 1700, 1980)
                )
            search.assert_not_called()
            migrated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                migrated["migrations"][-1]["to_hashes"],
                {field: migrated["scope"][field] for field in HASH_FIELDS},
            )
