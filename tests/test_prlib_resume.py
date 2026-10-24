import unittest,json,tempfile,csv,sys,importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import searcher_libraries as lib
from prlib_run_state import iter_query,query_path,existing_outputs
from test_prlib_pagination import page
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"output/prlib_resume_fix_20260915_v1"
class ResumeTests(unittest.TestCase):
 def runner(self):
  spec=importlib.util.spec_from_file_location("runner_resume_test",ROOT/"scripts/run_search.py")
  mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
 def execute(self,folder,responses,max_pages=3,detail=None):
  runner=self.runner();calls=[]
  def get(url,params,delay):
   calls.append(params["page"])
   value=responses[params["page"]]
   if isinstance(value,Exception):raise value
   return SimpleNamespace(text=value)
  with patch.object(sys,"argv",["run_search.py","--source","prlib","--no-notion","--max-pages",str(max_pages),"--max-combos","1","--run-dir",str(folder)]),patch.object(runner,"build_territories",return_value=[("Калужской губернии","Калужская")]),patch.object(runner,"KEYWORDS",["карта"]),patch.object(lib,"_get",side_effect=get),patch.object(lib,"PRLIB_FETCH_DETAILS_IN_BULK",detail is not None),patch.object(lib,"_prlib_detail_record",side_effect=detail),patch("archive_health.ArchiveHealth"),patch.object(runner.time,"sleep"):
   runner.main()
  return calls
 def test_failure_then_resume(self):
  with tempfile.TemporaryDirectory(dir=BASE) as tmp:
   d=Path(tmp);key="Калужской губернии|карта|prlib"
   self.assertEqual(self.execute(d,[page(0,1),TimeoutError()]),[0,1])
   self.assertNotIn(key,json.loads((d/"checkpoint.json").read_text())["done"])
   state=json.loads(query_path(d,key).read_text())
   self.assertEqual(state["coverage"]["resume"]["page"],1)
   self.assertEqual(state["coverage"]["status"],"partial")
   self.assertEqual(self.execute(d,[None,page(1,2)]),[1])
   self.assertIn(key,json.loads((d/"checkpoint.json").read_text())["done"])
   rows=[json.loads(x) for x in (d/"records_full.jsonl").read_text(encoding="utf-8").splitlines()]
   self.assertEqual(len(rows),2)
   self.assertEqual(existing_outputs(d)[0],True)
   self.assertEqual(self.execute(d,[]),[])
 def test_limit_then_resume(self):
  with tempfile.TemporaryDirectory(dir=BASE) as tmp:
   d=Path(tmp);key="Калужской губернии|карта|prlib"
   self.assertEqual(self.execute(d,[page(0,1)],1),[0])
   self.assertEqual(json.loads(query_path(d,key).read_text())["coverage"]["stop_reason"],"page_limit")
   self.assertEqual(self.execute(d,[None,page(1,2)],1),[1])
   self.assertEqual(len((d/"records_full.jsonl").read_text(encoding="utf-8").splitlines()),2)
 def test_unknown_not_done_and_no_duplicate(self):
  with tempfile.TemporaryDirectory(dir=BASE) as tmp:
   d=Path(tmp);raw='<article><h2><a href="/item/1">Калужская губерния</a></h2></article>'
   self.execute(d,[raw]);self.execute(d,[raw])
   self.assertEqual(json.loads((d/"checkpoint.json").read_text())["done"],[])
   self.assertEqual(len((d/"records_full.jsonl").read_text(encoding="utf-8").splitlines()),1)
 def test_partial_file_set_rejected(self):
  with tempfile.TemporaryDirectory(dir=BASE) as tmp:
   d=Path(tmp);f=d/"records_full.jsonl";f.write_text("{}")
   with self.assertRaises(ValueError):existing_outputs(d)
   self.assertEqual(f.read_text(),"{}")
 def test_query_scope_change_rejected(self):
  with tempfile.TemporaryDirectory(dir=BASE) as tmp:
   d=Path(tmp);raw='<article><h2><a href="/item/1">Калужская губерния</a></h2></article>'
   self.execute(d,[raw]);c={}
   with self.assertRaises(ValueError):
    list(iter_query(d,"Калужской губернии|карта|prlib","другой запрос",1700,1980,1,c))
 def test_interrupt_replays_current_page(self):
  with tempfile.TemporaryDirectory(dir=BASE) as tmp:
   d=Path(tmp);c={};key="test"
   with patch.object(lib,"_get",return_value=SimpleNamespace(text=page(0,1))),patch.object(lib,"PRLIB_FETCH_DETAILS_IN_BULK",False):
    it=iter_query(d,key,"карта Калужской губернии",1700,1980,3,c);next(it);it.close()
   state=json.loads(query_path(d,key).read_text())["coverage"]
   self.assertEqual(state["status"],"interrupted");self.assertEqual(state["resume"]["page"],0)

 def test_midpage_failure_replays_without_duplicates(self):
  with tempfile.TemporaryDirectory(dir=BASE) as tmp:
   d=Path(tmp)
   raw=page(0,1,last=0).replace("</article>","</article><article><h2><a href='/item/2'>Калужская губерния</a></h2></article>",1)
   def failed(url):
    if url.endswith("/2"):raise TimeoutError()
    return lib.LibraryRecord(url=url,title="Калужская губерния",category="не классифицировано")
   self.execute(d,[raw],detail=failed)
   self.assertEqual(len((d/"records_full.jsonl").read_text(encoding="utf-8").splitlines()),1)
   state=json.loads(query_path(d,"Калужской губернии|карта|prlib").read_text())["coverage"]
   self.assertEqual(state["resume"]["page"],0)
   def ok(url):return lib.LibraryRecord(url=url,title="Калужская губерния",category="не классифицировано")
   self.assertEqual(self.execute(d,[raw],detail=ok),[0])
   self.assertEqual(len((d/"records_full.jsonl").read_text(encoding="utf-8").splitlines()),2)
 def test_finished_scope_mismatch_rejected(self):
  from prlib_run_state import completed_query
  with tempfile.TemporaryDirectory(dir=BASE) as tmp:
   d=Path(tmp);self.execute(d,[page(0,1,last=0)])
   with patch.object(lib,"PRLIB_FETCH_DETAILS_IN_BULK",False):
    with self.assertRaises(ValueError):completed_query(d,"Калужской губернии|карта|prlib",1800,1980)
 def test_jsonl_csv_mismatch_rejected(self):
  with tempfile.TemporaryDirectory(dir=BASE) as tmp:
   d=Path(tmp);self.execute(d,[page(0,1,last=0)])
   raw=d/"records_full.jsonl";old=raw.read_text(encoding="utf-8");raw.write_text(old+old,encoding="utf-8")
   with self.assertRaises(ValueError):existing_outputs(d)
   self.assertEqual(raw.read_text(encoding="utf-8"),old+old)
