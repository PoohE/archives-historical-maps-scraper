"""Real saved RGIA detail must pass through the 64-field offline CSV gate."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RgiaDetailNotionGateTests(unittest.TestCase):
    def test_saved_detail_exports_to_all_64_scalar_properties(self):
        spec = importlib.util.spec_from_file_location(
            "rgia_gate", ROOT / "scripts/reprocess_rgia_detail_66_20260923_v4.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            report = module.run(Path(temporary) / "gate")
            export = json.loads(
                (Path(temporary) / "gate/notion_csv/export_review.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(report["notion_csv"]["columns"], 64)
        self.assertEqual(report["notion_csv"]["rows"], 1)
        self.assertEqual(report["notion_csv"]["roundtrip"], "passed")
        self.assertEqual(report["notion_csv"]["validation_errors"], [])
        self.assertEqual(report["notion_csv"]["adapter"], "rgia_detail")
        self.assertEqual(export["manual_gates"]["card_to_csv"], "pending")
        self.assertEqual(export["manual_gates"]["csv_to_notion"], "pending")
        self.assertFalse(report["ready_for_import"])


if __name__ == "__main__":
    unittest.main()
