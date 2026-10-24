"""Offline regression tests for bounded transport retry in the frozen PRLIB v4 runner."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output" / "prlib_catalog_full_handoff_20260919_v4"

CHILD = r'''
import importlib.util,json,sys,tempfile
from pathlib import Path
package=Path(sys.argv[1]);scenario=json.loads(sys.argv[2])
spec=importlib.util.spec_from_file_location('prlib_v4_probe',package/'run_catalog.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
calls=[];sleeps=[]
def getter(url):
    calls.append(url)
    event=scenario.pop(0)
    if event=='timeout': raise TimeoutError('test transport timeout')
    if event=='barrier': return (403,'text/html',b'<html>denied</html>','')
    if event=='robots': return (200,'text/plain',b'User-agent: *\nAllow: /\n','')
    if event=='end': return (200,'text/html','<main>По вашему запросу нет результатов</main>'.encode('utf-8'),'')
    raise AssertionError(event)
runner.time.sleep=lambda seconds:sleeps.append(seconds)
scope={'territories':[['Калужская губерния','Калужская']],'keywords':['карта'],'year_from':1700,'year_to':1980,'max_get_per_invocation':10}
with tempfile.TemporaryDirectory() as tmp:
    attempt,rc=runner.run(output=Path(tmp),getter=getter,test_scope=scope)
    report=json.loads((attempt/'REPORT.json').read_text(encoding='utf-8'))
    requests=[json.loads(line) for line in (attempt/'requests.jsonl').read_text(encoding='utf-8').splitlines()]
    print(json.dumps({'rc':rc,'calls':len(calls),'sleeps':sleeps,'report':report,'requests':requests},ensure_ascii=False))
'''


class FrozenV4TransportTests(unittest.TestCase):
    maxDiff = None

    def probe(self, scenario):
        self.assertTrue(PACKAGE.is_dir(), "build v4 package before running frozen retry tests")
        with tempfile.TemporaryDirectory() as tmp:
            child = Path(tmp) / "probe.py"
            child.write_text(CHILD, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-B", str(child), str(PACKAGE), json.dumps(scenario)],
                text=True,
                capture_output=True,
                check=True,
            )
        return json.loads(completed.stdout.splitlines()[-1])

    def test_transport_failure_retries_once_then_reports_end(self):
        result = self.probe(["robots", "timeout", "end"])
        self.assertEqual(result["rc"], 0)
        self.assertEqual(result["calls"], 3)
        self.assertEqual([value for value in result["sleeps"] if value in (5, 15)], [5])
        self.assertEqual(
            [row["backoff_seconds"] for row in result["requests"] if row["event"] == "transport_retry_scheduled"],
            [5],
        )

    def test_transport_failure_stops_after_two_retries(self):
        result = self.probe(["robots", "timeout", "timeout", "timeout"])
        self.assertEqual(result["rc"], 2)
        self.assertEqual(result["calls"], 4)
        self.assertEqual([value for value in result["sleeps"] if value in (5, 15)], [5, 15])
        self.assertEqual(result["report"]["error_type"], "AccessBlocked")
        self.assertEqual(result["report"]["stop_reason"], "transport_error")

    def test_http_barrier_is_not_transport_retried(self):
        result = self.probe(["robots", "barrier"])
        self.assertEqual(result["rc"], 2)
        self.assertEqual(result["calls"], 2)
        self.assertEqual([value for value in result["sleeps"] if value in (5, 15)], [])
        self.assertEqual(result["report"]["stop_reason"], "http_403_forbidden")
        self.assertFalse(any(row["event"] == "transport_retry_scheduled" for row in result["requests"]))


