import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from dataclasses import asdict
import searcher_libraries as lib

ROOT=Path(__file__).resolve().parents[1]
class ListingTests(unittest.TestCase):
 def search(self,html,query="карта Калужской губернии",**kw):
  with patch.object(lib,"_get",return_value=SimpleNamespace(text=html)) as get, patch.object(lib,"PRLIB_FETCH_DETAILS_IN_BULK",False):
   rows=list(lib._search_prlib(query,kw.get("year_from"),kw.get("year_to"),kw.get("max_pages",1)))
  return rows,get
 def article(self,date="",title="Калужская губерния",ident=9):
  return f'<article><h2><a href="/item/{ident}">{title}</a></h2>{date}</article>'
 def test_real_listing(self):
  raw=(ROOT/"output/prlib_barrier_v3_probe_20260915_052306_86cb16b7/page.sanitized.html").read_text(encoding="utf-8")
  from bs4 import BeautifulSoup
  dom=BeautifulSoup(raw,"html.parser")
  for pager in dom.select("ul.pagination"):pager.decompose()
  # Parser-only replay of the captured second page; pagination tested separately.
  rows,get=self.search(str(dom))
  self.assertEqual({x.url.rsplit("/",1)[-1] for x in rows},{"426813","426814"})
  for x in rows:
   self.assertEqual((x.year_from,x.year_to),(1864,1864))
   self.assertEqual(x.category,"не классифицировано")
   self.assertEqual(x.extra["search_listing"]["date_status"],"year_candidate")
 def test_pages_start_at_zero(self):
  _,get=self.search(self.article(),max_pages=2)
  self.assertEqual([x.kwargs["params"]["page"] for x in get.call_args_list],[0])
 def test_summary_unknown_type_even_map_title(self):
  rows,_=self.search(self.article(title="Карта Калужской губернии"))
  self.assertEqual(rows[0].category,"не классифицировано")
 def test_unknown_date_does_not_use_title(self):
  rows,_=self.search(self.article(title="Калужская губерния на 1812 год"))
  self.assertIsNone(rows[0].year_from)
 def test_holder_year_not_date(self):
  rows,_=self.search(self.article('<div class="node-content">Библиотека основана в 1864 году</div>'))
  self.assertIsNone(rows[0].year_from)
 def test_conflicting_date_blocks(self):
  rows,_=self.search(self.article('<div class="node-content">1864</div><div class="node-content">1865</div>'))
  self.assertIsNone(rows[0].year_from)
  self.assertEqual(rows[0].extra["search_listing"]["date_status"],"ambiguous")
 def test_date_filter(self):
  rows,_=self.search(self.article('<div class="node-content">1864</div>'),year_from=1900)
  self.assertEqual(rows,[])
 def test_existing_date_markup(self):
  rows,_=self.search(self.article('<time>1864</time>'))
  self.assertEqual(rows[0].year_to,1864)
 def test_detail_preserved(self):
  html=self.article('<div class="node-content">1864</div>')
  detail=lib.LibraryRecord(title="Reviewed title",url="https://prlib.ru/item/9",year_from=1863,year_to=1863,category="Reviewed type",extra={"approved":True})
  with patch.object(lib,"_get",return_value=SimpleNamespace(text=html)),patch.object(lib,"PRLIB_FETCH_DETAILS_IN_BULK",True),patch.object(lib,"_prlib_detail_record",return_value=detail):
   row=list(lib._search_prlib("карта Калужской губернии",None,None,1))[0]
  self.assertEqual(row.year_to,1863)
  self.assertEqual(row.category,"Reviewed type")
  self.assertTrue(row.extra["approved"])
  self.assertEqual(row.extra["search_listing"]["year_candidate"],1864)
 def test_no_creation_date_export_from_summary(self):
  from notion_export import normalize
  rows,_=self.search(self.article('<div class="node-content">1864</div>'))
  row,audit=normalize({"source":"prlib","record":asdict(rows[0])})
  self.assertIn(row["Год создания (верхняя)"],("",None))
  self.assertFalse(audit["relations"])
