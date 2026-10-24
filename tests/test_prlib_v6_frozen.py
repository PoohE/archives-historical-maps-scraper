"""Frozen v6 migration regression, offline and without catalog GET."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/prlib_catalog_full_handoff_20260920_v6"
REAL_STATE = ROOT / "output/prlib_catalog_full_20260917_v1/prlib_query_state"


@unittest.skipUnless(PACKAGE.is_dir(), "build v6 package before frozen v6 tests")
class FrozenV6Tests(unittest.TestCase):
    def test_real_v5_reported_end_state_migrates_and_completes_without_get(self):
        source = next(
            path
            for path in REAL_STATE.glob("*.json")
            if json.loads(path.read_text(encoding="utf-8"))["coverage"]["status"]
            == "reported_end"
        )
        code = """import importlib.util,json,shutil,tempfile
from pathlib import Path
package=Path(%r);source=Path(%r)
spec=importlib.util.spec_from_file_location('prlib_v6_migration',package/'run_catalog.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
prior=json.loads(source.read_text(encoding='utf-8'))
with tempfile.TemporaryDirectory() as tmp:
 out=Path(tmp);target=runner.query_path(out,prior['scope']['key']);target.parent.mkdir(parents=True);shutil.copy2(source,target)
 before=json.loads(target.read_text(encoding='utf-8'));accepted=runner.manifest()['continuation']['accepted_prior_module_hashes'];old={k:accepted[-1][k] for k in ('parser_sha256','access_sha256','detail_sha256')};before['scope'].update(old);target.write_text(json.dumps(before),encoding='utf-8');completed=runner.completed_query(out,prior['scope']['key'],1700,1980);after=json.loads(target.read_text(encoding='utf-8'))
 print(json.dumps({'completed':completed,'accepted':{k:before['scope'][k] for k in ('parser_sha256','access_sha256','detail_sha256')} in runner.manifest()['continuation']['accepted_prior_module_hashes'],'migrated':len(after.get('migrations',[]))==len(before.get('migrations',[]))+1,'changed':before['scope']!=after['scope']}))
""" % (str(PACKAGE), str(source))
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "probe.py"
            script.write_text(code, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-B", str(script)], text=True, capture_output=True
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads(result.stdout.splitlines()[-1])
        self.assertTrue(evidence["accepted"])
        self.assertTrue(evidence["completed"])
        self.assertTrue(evidence["migrated"])
        self.assertTrue(evidence["changed"])
