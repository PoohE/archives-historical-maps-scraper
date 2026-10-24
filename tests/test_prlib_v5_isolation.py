"""Frozen v5 regressions: migration and query-local failure isolation, offline only."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output" / "prlib_catalog_full_handoff_20260919_v5"
REAL_STATE = ROOT / "output" / "prlib_catalog_full_20260917_v1" / "prlib_query_state"


@unittest.skipUnless(PACKAGE.is_dir(), "build v5 package before frozen v5 tests")
class FrozenV5Tests(unittest.TestCase):
    def run_child(self, code):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "probe.py"
            script.write_text(code, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-B", str(script)], text=True, capture_output=True
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout.splitlines()[-1])

    def test_newer_real_state_is_rejected_by_v5_before_get(self):
        source = next(
            path
            for path in REAL_STATE.glob("*.json")
            if json.loads(path.read_text(encoding="utf-8"))["coverage"]["status"]
            == "reported_end"
        )
        evidence = self.run_child(
            """import importlib.util,json,shutil,tempfile
from pathlib import Path
package=Path(%r);source=Path(%r)
spec=importlib.util.spec_from_file_location('prlib_v5_reject',package/'run_catalog.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
prior=json.loads(source.read_text(encoding='utf-8'))
with tempfile.TemporaryDirectory() as tmp:
 out=Path(tmp);target=runner.query_path(out,prior['scope']['key']);target.parent.mkdir(parents=True);shutil.copy2(source,target)
 try: runner.completed_query(out,prior['scope']['key'],1700,1980)
 except ValueError as exc: print(json.dumps({'rejected':'not accepted' in str(exc)}))
 else: print(json.dumps({'rejected':False}))
"""
            % (str(PACKAGE), str(source))
        )
        self.assertTrue(evidence["rejected"])

    def test_repeated_page_isolated_and_next_query_completes(self):
        evidence = self.run_child(
            """import importlib.util,json,tempfile
from pathlib import Path
from unittest.mock import patch
package=Path(%r)
spec=importlib.util.spec_from_file_location('prlib_v5_isolation',package/'run_catalog.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
scope={'territories':[['Первый уезд','Первый'],['Второй уезд','Второй']],'keywords':['карта'],'year_from':1700,'year_to':1980,'max_get_per_invocation':10}
states={};bad_calls=[0]
def completed(out,key,*_):return states.get(key,{}).get('status')=='reported_end'
def iterator(out,key,query,*args):
 coverage=args[-1]
 def save():
  states[key]=dict(coverage);path=runner.query_path(out,key);path.parent.mkdir(exist_ok=True);path.write_text(json.dumps({'coverage':dict(coverage)}),encoding='utf-8')
 if key.startswith('Первый уезд'):
  bad_calls[0]+=1
  if bad_calls[0]>1:raise AssertionError('review query was retried in the same invocation')
  rec=runner.lib.LibraryRecord(title='Карта Первого уезда',year_from=1800,year_to=1800,description='',url='https://www.prlib.ru/item/999',extra={'detail_access':{'status':'parsed_candidate'}})
  yield rec
  coverage.update(status='partial',stop_reason='repeated_page',for_review=True,resume={'page':20,'seen':['/item/999'],'fingerprints':[]},records_yielded=1,max_page=20)
  save();raise runner.lib.PrLibIncompleteSearch(coverage)
 else:
  coverage.update(status='reported_end',stop_reason='pager_reported_end',for_review=False,resume={'page':0,'seen':[],'fingerprints':[]},records_yielded=0,max_page=0)
  save()
  if False:yield None
with tempfile.TemporaryDirectory() as tmp:
 out=Path(tmp)
 with patch.object(runner,'completed_query',side_effect=completed),patch.object(runner,'iter_query',side_effect=iterator),patch.object(runner,'export_candidates',return_value={'columns':66,'roundtrip':'passed','rows':1}):
  attempt,code=runner.run(output=out,getter=lambda url:(_ for _ in ()).throw(AssertionError('network getter called')),test_scope=scope)
 report=json.loads((attempt/'REPORT.json').read_text(encoding='utf-8'));coverage=json.loads((attempt/'coverage.json').read_text(encoding='utf-8'));rows=(out/'records_full.jsonl').read_text(encoding='utf-8').splitlines()
 print(json.dumps({'code':code,'status':report['status'],'completed':report['completed_queries'],'review':report['queries_for_review'],'scope_complete':report['query_scope_complete'],'coverage':coverage,'rows':len(rows),'bad_calls':bad_calls[0]}))
"""
            % str(PACKAGE)
        )
        self.assertEqual(evidence["code"], 0)
        self.assertEqual(evidence["status"], "query_scope_review")
        self.assertEqual(evidence["completed"], 1)
        self.assertFalse(evidence["scope_complete"])
        self.assertEqual(evidence["rows"], 1)
        self.assertEqual(evidence["bad_calls"], 1)
        self.assertEqual(len(evidence["review"]), 1)
        self.assertEqual(evidence["review"][0]["stop_reason"], "repeated_page")
        self.assertEqual(evidence["review"][0]["rows_collected"], 1)
        self.assertEqual(evidence["review"][0]["max_page"], 20)
        partial = next(
            row for row in evidence["coverage"] if row["key"].startswith("Первый уезд")
        )
        self.assertTrue(partial["for_review"])
        self.assertEqual(partial["max_page"], 20)
