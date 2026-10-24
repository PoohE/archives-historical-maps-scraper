import unittest
from pathlib import Path
from prlib_card import parse_card
from notion_export import normalize
ROOT=Path(__file__).resolve().parents[1]
INPUT=ROOT/"output/prlib_cards_probe_20260915_163905_ae43e1f7"
class NewCardTests(unittest.TestCase):
 def card(self,ident):
  return parse_card((INPUT/(ident+".sanitized.html")).read_bytes(),"https://prlib.ru/item/"+ident)
 def test_numbered_volume_date(self):
  rec=self.card("451086")
  self.assertEqual(rec["year_to"],1863)
  self.assertTrue(rec["extra"]["volume_description"].startswith("15:"))
  row,audit=normalize({"source":"prlib","record":rec})
  self.assertEqual(row["Год создания (верхняя)"],1863)
  self.assertIn(row["Год сведений"],("",None))
  self.assertIn("по сведениям 1859 года",rec["extra"]["volume_description"])
  self.assertIn(row["Год создания (нижняя)"],("",None))
 def test_series_responsibility_not_volume_author(self):
  rec=self.card("451086")
  self.assertEqual(rec["author"],"")
  self.assertIn("Огородников",rec["extra"]["raw_author_field"])
  self.assertIn("Штиглицом",rec["extra"]["volume_responsibility"])
 def test_engravers_not_map_authors(self):
  rec=self.card("397242")
  self.assertEqual(rec["author"],"")
  self.assertIn("Худяков",rec["extra"]["raw_author_field"])
  self.assertIn("responsibility_roles_require_review",rec["extra"]["review_issues"])
 def test_namestnichestvo_retains_review(self):
  row,audit=normalize({"source":"prlib","record":self.card("397242")})
  self.assertIn("administrative_level_unsupported",audit["issues"])
  self.assertIn(row["Административный уровень"],("",None))
 def test_truncated_title_flagged(self):
  rec=self.card("451086")
  self.assertIn("title_truncated_in_source",rec["extra"]["review_issues"])
  self.assertIn("Министерства внутренних дел",rec["extra"]["series_title"])
 def test_other_dates_retained(self):
  for ident,year in (("426814",1864),("426813",1864),("434879",1838),("397242",1785)):
   self.assertEqual(self.card(ident)["year_to"],year)
