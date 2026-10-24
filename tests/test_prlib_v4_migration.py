"""Critical v4 continuation regression on a copy of real PRLIB state."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output" / "prlib_catalog_full_handoff_20260919_v4"
REAL_STATE = ROOT / "output" / "prlib_catalog_full_20260917_v1" / "prlib_query_state"


class FrozenV4MigrationTests(unittest.TestCase):
    def test_current_v3_reported_end_state_is_accepted_and_completed_offline(self):
        source = next(
            path for path in REAL_STATE.glob("*.json")
            if json.loads(path.read_text(encoding="utf-8"))["coverage"]["status"] == "reported_end"
        )
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "v4_migration_probe.py"
            script.write_text(
                """import importlib.util,json,shutil,tempfile
from pathlib import Path
package=Path(%r); source=Path(%r)
spec=importlib.util.spec_from_file_location('prlib_catalog_v4_migration',package/'run_catalog.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
prior=json.loads(source.read_text(encoding='utf-8'))
prior['scope'].update(runner.manifest()['continuation']['accepted_prior_module_hashes'][1])
with tempfile.TemporaryDirectory() as raw_tmp:
 out=Path(raw_tmp); target=runner.query_path(out,prior['scope']['key']);target.parent.mkdir(parents=True);target.write_text(json.dumps(prior),encoding='utf-8')
 before=json.loads(target.read_text(encoding='utf-8'))
 completed=runner.completed_query(out,prior['scope']['key'],1700,1980)
 after=json.loads(target.read_text(encoding='utf-8'))
 print(json.dumps({'completed':completed,'prior_hashes':{k:before['scope'][k] for k in ('parser_sha256','access_sha256','detail_sha256')},'accepted':{k:before['scope'][k] for k in ('parser_sha256','access_sha256','detail_sha256')} in runner.manifest()['continuation']['accepted_prior_module_hashes'],'migration_added':len(after.get('migrations',[]))==len(before.get('migrations',[]))+1,'from_hashes':after['migrations'][-1]['from_hashes'],'to_hashes':after['migrations'][-1]['to_hashes'],'current_scope':after['scope']}))
""" % (str(PACKAGE), str(source)),
                encoding="utf-8",
            )
            result = subprocess.run([sys.executable, "-B", str(script)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads(result.stdout.splitlines()[-1])
        self.assertTrue(evidence["accepted"])
        self.assertTrue(evidence["completed"])
        self.assertTrue(evidence["migration_added"])
        self.assertEqual(evidence["from_hashes"], evidence["prior_hashes"])
        self.assertNotEqual(evidence["from_hashes"], evidence["to_hashes"])



