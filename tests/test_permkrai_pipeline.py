import unittest,json,copy,tempfile,csv
from pathlib import Path
from dataclasses import asdict
from unittest.mock import patch
import registry,notion_export
from scrapers import searcher_permkrai as perm
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'output/permkrai_pipeline_fix_20260916_v1'
URL='https://lib.permkrai.ru/node/37840'
class PermPipelineTests(unittest.TestCase):
 def setUp(self):
  self.raw=(ROOT/'output/permkrai_handoff_20260914_v1/inputs/card.html').read_text(encoding='utf-8-sig')
  self.card=perm.parse_card_html(self.raw,URL)
  self.approved=json.loads((ROOT/'output/permkrai_date_review_20260914_v2/record.json').read_text(encoding='utf-8'))['creation_year_review']
 def entry(self):
  with patch.object(perm,'search',return_value=iter([self.card])):
   record=next(registry.search('permkrai','test',year_from=None,year_to=None,max_pages=1))
  return dict(source='permkrai',territory='Пермская губерния',keyword='карта',record=asdict(record))
 def test_complete_original_record_preserved(self):
  e=self.entry();self.assertEqual(e['record']['extra']['permkrai_record'],asdict(self.card))
  self.assertEqual(e['record']['author'],self.card.author)
  self.assertEqual(e['record']['extra']['evidence']['url'],URL)
 def test_card_fields_reach_common_export(self):
  row,audit=notion_export.normalize(self.entry())
  for field,expected in [('Автор / составитель',self.card.author),('Описание',self.card.bibliography),('Библиотечный шифр',self.card.shelfmark),('Путь / URL к файлу',self.card.url_download),('Масштаб (знаменатель)',840000)]:self.assertEqual(row[field],expected)
  self.assertEqual(audit['adapter'],'permkrai_detail');self.assertEqual(audit['validation_errors'],[])
  self.assertEqual(row['Листы / страницы'],'');self.assertEqual(row['Статус доступа'],'Открытый доступ')
  self.assertEqual(row['Прямая ссылка на файл изображения'], self.card.url_viewer)
 def test_card_publication_date_maps_to_creation_range(self):
  row,_=notion_export.normalize(self.entry());self.assertEqual(row['Год создания (верхняя)'],1909)
  self.assertEqual(row['Год создания (нижняя)'],1909)
 def test_prior_approved_creation_date(self):
  row,_=notion_export.normalize(self.entry(),{URL:{'creation_year_review':self.approved}})
  self.assertEqual(row['Год создания (верхняя)'],1909)
  self.assertEqual(row['Описание'],self.card.bibliography)
  self.assertIn('15 февраля 1911',row['Описание'])
 def test_wrong_or_unapproved_decision_not_applied(self):
  for key,value in [('status','candidate'),('source_url','https://example.invalid/'),('scope','inset'),('year',True)]:
   with self.subTest(key=key):
    decision=copy.deepcopy(self.approved);decision[key]=value
    row,_=notion_export.normalize(self.entry(),{URL:{'creation_year_review':decision}})
    self.assertEqual(row['Год создания (верхняя)'],1909)
 def test_mismatched_nested_url_rejected(self):
  entry=self.entry();entry['record']['extra']['permkrai_record']['url']='https://example.invalid/'
  with self.assertRaises(ValueError):notion_export.normalize(entry)
 def test_timeout_not_empty_success(self):
  with patch.object(perm,'get_result_urls',return_value=[URL]),patch.object(perm,'parse_card',side_effect=TimeoutError()):
   with self.assertRaises(perm.PermIncompleteSearch) as ctx:list(registry.search('permkrai','test',year_from=None,year_to=None,max_pages=1))
  self.assertEqual(ctx.exception.report['error_type'],'TimeoutError')
  self.assertEqual(ctx.exception.report['discovered_urls'],[URL])
 def test_csv_roundtrip_and_raw_preserved(self):
  with tempfile.TemporaryDirectory(dir=BASE) as tmp:
   folder=Path(tmp);source=folder/'records.jsonl';entry=self.entry()
   source.write_text(json.dumps(entry,ensure_ascii=False)+'\n',encoding='utf-8')
   before=source.read_bytes();report=notion_export.export(source,folder/'csv')
   self.assertEqual(source.read_bytes(),before)
  self.assertEqual((report['rows'],report['columns'],report['roundtrip']),(1,65,'passed'))
