import unittest
from types import SimpleNamespace
from unittest.mock import patch
import searcher_libraries as lib

def page(index,ident,last=1,title="Калужская губерния"):
 links="".join(f'<li><a href="/collections/467000/search?text=карта+Калужской+губернии&amp;page={n}">{n+1}</a></li>' for n in range(last+1) if n!=index)
 return f'<main><article><h2><a href="/item/{ident}">{title}</a></h2></article><ul class="pagination"><li class="active"><span>{index+1}</span></li>{links}</ul></main>'
class PaginationTests(unittest.TestCase):
 def run_search(self,pages,limit=3,coverage=None):
  def get(*args,**kwargs):
   item=pages[kwargs["params"]["page"]]
   if isinstance(item,Exception):raise item
   return SimpleNamespace(text=item)
  with patch.object(lib,"_get",side_effect=get) as fetch,patch.object(lib,"PRLIB_FETCH_DETAILS_IN_BULK",False):
   rows=list(lib._search_prlib("карта Калужской губернии",None,None,limit,coverage=coverage))
  return rows,fetch
 def test_reported_end(self):
  c={};rows,f=self.run_search([page(0,1),page(1,2)],coverage=c)
  self.assertEqual(len(rows),2);self.assertEqual(f.call_count,2)
  self.assertEqual(c["status"],"reported_end");self.assertFalse(c["full_search_complete"])
 def test_limit_is_partial(self):
  c={}
  with self.assertRaises(lib.PrLibIncompleteSearch):self.run_search([page(0,1)],limit=1,coverage=c)
  self.assertEqual(c["stop_reason"],"page_limit");self.assertEqual(c["records_yielded"],1)
 def test_late_error_propagates(self):
  c={}
  with self.assertRaises(TimeoutError):self.run_search([page(0,1),TimeoutError()],coverage=c)
  self.assertEqual(c["status"],"partial");self.assertEqual(c["stop_reason"],"request_error")
 def test_repeated_ids(self):
  c={}
  with self.assertRaises(lib.PrLibIncompleteSearch):self.run_search([page(0,1),page(1,1)],coverage=c)
  self.assertEqual(c["stop_reason"],"repeated_page")
 def test_current_page_mismatch(self):
  c={}
  with self.assertRaises(lib.PrLibIncompleteSearch):self.run_search([page(1,1)],coverage=c)
  self.assertEqual(c["stop_reason"],"current_page_mismatch")
 def test_filter_does_not_stop_paging(self):
  c={};rows,f=self.run_search([page(0,1,title="Киевская губерния"),page(1,2)],coverage=c)
  self.assertEqual(len(rows),1);self.assertEqual(f.call_count,2)
 def test_empty_expected_page(self):
  c={}
  with self.assertRaises(lib.PrLibIncompleteSearch):self.run_search([page(0,1),"<main></main>"],coverage=c)
  self.assertEqual(c["stop_reason"],"empty_unverified")
 def test_classifier_reported_empty_tail_closes_query(self):
  c={}
  response=SimpleNamespace(text="<main>По вашему запросу нет результатов</main>",access_report={
   "classification":{"verdict":"reported_end","reason":"empty_with_end_marker","evidence":{"items":0}}})
  with patch.object(lib,"_get",return_value=response),patch.object(lib,"PRLIB_FETCH_DETAILS_IN_BULK",False):
   rows=list(lib._search_prlib("карта Калужской губернии",None,None,3,coverage=c))
  self.assertEqual(rows,[])
  self.assertEqual(c["status"],"reported_end")
  self.assertEqual(c["stop_reason"],"pager_reported_end")
  self.assertEqual(c["classifier_verdicts"], [{"page":0,"verdict":"reported_end","reason":"empty_with_end_marker"}])
 def test_classifier_ambiguous_empty_is_unverified(self):
  c={}
  response=SimpleNamespace(text="<main></main>",access_report={
   "classification":{"verdict":"ambiguous_empty","reason":"empty_without_end_marker","evidence":{"items":0}}})
  with patch.object(lib,"_get",return_value=response),patch.object(lib,"PRLIB_FETCH_DETAILS_IN_BULK",False):
   rows=list(lib._search_prlib("карта Калужской губернии",None,None,3,coverage=c))
  self.assertEqual(rows,[])
  self.assertEqual(c["status"],"unverified")
  self.assertEqual(c["stop_reason"],"empty_without_end_marker")
 def test_missing_pager_is_unverified(self):
  c={};rows,f=self.run_search(['<article><h2><a href="/item/1">Калужская губерния</a></h2></article>'],coverage=c)
  self.assertEqual(c["status"],"unverified");self.assertFalse(c["full_search_complete"])
  self.assertEqual(rows[0].extra["search_coverage"]["status"],"unverified")
 def test_interruption(self):
  c={}
  with patch.object(lib,"_get",return_value=SimpleNamespace(text=page(0,1))),patch.object(lib,"PRLIB_FETCH_DETAILS_IN_BULK",False):
   it=lib._search_prlib("карта Калужской губернии",None,None,3,coverage=c)
   next(it);it.close()
  self.assertEqual(c["status"],"interrupted")
 def test_changed_query(self):
  c={}
  with self.assertRaises(lib.PrLibIncompleteSearch):self.run_search([page(0,1).replace("text=карта+Калужской+губернии","text=другой")],coverage=c)
  self.assertEqual(c["stop_reason"],"invalid_pager_link")
 def test_foreign_item_rejected(self):
  c={}
  with self.assertRaises(lib.PrLibIncompleteSearch):self.run_search([page(0,1).replace('href="/item/1"','href="https://evil.test/item/1"')],coverage=c)
  self.assertEqual(c["stop_reason"],"invalid_item_url")
