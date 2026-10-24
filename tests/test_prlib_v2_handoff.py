"""Офлайн-проверка v2: прежняя печать v1 принимается без переписывания scope."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output" / "prlib_catalog_full_handoff_20260918_v2"


class PrlibV2HandoffTests(unittest.TestCase):
    def test_prior_v1_scope_seal_continues_without_rewrite_or_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "v2_continuation_check.py"
            script.write_text(
                """import importlib.util,json,tempfile
from pathlib import Path
from unittest.mock import patch
package=Path(%r)
spec=importlib.util.spec_from_file_location('prlib_catalog_v2_test',package/'run_catalog.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
manifest=json.loads((package/'manifest.json').read_text(encoding='utf-8'))
scope=json.loads((package/'scope.json').read_text(encoding='utf-8'))
prior={'scope':scope,'manifest_sha256':manifest['continuation']['prior_manifest_sha256'],'network_mode':'live'}
with tempfile.TemporaryDirectory() as raw_tmp:
 out=Path(raw_tmp);seal=out/'run_scope.json';seal.write_text(json.dumps(prior),encoding='utf-8')
 with patch.object(runner,'completed_query',return_value=True),patch.object(runner,'export_candidates',return_value={'columns':66,'roundtrip':'passed','rows':0}),patch.object(runner.access,'raw_fetch') as raw:
  attempt,code=runner.collect(out,scope,None)
 report=json.loads((attempt/'REPORT.json').read_text(encoding='utf-8'))
 print(json.dumps({'code':code,'raw_calls':raw.call_count,'seal_unchanged':json.loads(seal.read_text(encoding='utf-8'))==prior,'continued':report['continuation_from_v1'],'hashes_before':report['hashes_before'],'hashes_after':report['hashes_after']}))
""" % str(PACKAGE),
                encoding="utf-8",
            )
            result = subprocess.run([sys.executable, "-B", str(script)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(evidence["code"], 0)
        self.assertEqual(evidence["raw_calls"], 0)
        self.assertTrue(evidence["seal_unchanged"])
        self.assertTrue(evidence["continued"])
        self.assertTrue(evidence["hashes_before"])
        self.assertTrue(evidence["hashes_after"])
