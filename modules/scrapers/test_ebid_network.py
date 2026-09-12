import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from searcher_ebid import _parse_record_page, search_query

FIXTURE = Path(__file__).resolve().parent.parent / 'ebid_review_20260912/card.html'
if not FIXTURE.exists():
    FIXTURE = Path(__file__).resolve().parents[2] / 'output/ebid_review_20260912/card.html'
URL = 'https://docs.historyrussia.org/ru/nodes/87164'

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.html = FIXTURE.read_text(encoding='utf-8')

    def test_complete_metadata(self):
        record = _parse_record_page(self.html, URL)
        self.assertGreater(len(record.source), 150)
        self.assertEqual(record.source_year, 2001)
        self.assertEqual(record.depicted_year, 1914)
        self.assertIsNone(record.year_from)
        self.assertEqual(record.url_viewer, URL)
        self.assertNotIn('(166)', record.source)
        self.assertIn('1978', record.publication_statement)
        self.assertIn('field_links', json.loads(record.extra_json))

    def test_search_calls_verified_parser(self):
        result_page = Mock(text='<a href="/ru/nodes/87164">Example</a>', url=URL)
        card_page = Mock(text=self.html)
        session = Mock()
        session.get.side_effect = [result_page, card_page]
        with patch('searcher_ebid.time.sleep'):
            records = list(search_query(session, 'test', max_pages=1))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source_year, 2001)

    def test_no_early_type_filter(self):
        record = _parse_record_page(self.html.replace('>Карта</a>', '>Обозрение</a>'), URL)
        self.assertIsNotNone(record)

    def test_unknown_layout_fails(self):
        with self.assertRaises(ValueError):
            _parse_record_page('<h1>Unavailable</h1>', URL)

if __name__ == '__main__':
    unittest.main()
