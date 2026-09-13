import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from searcher_ebid import search_query

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / 'ebid_review_20260912').exists():
    ROOT = Path(__file__).resolve().parents[1] / 'output'

class LinkedSearchTests(unittest.TestCase):
    def run_search(self, edition_status=200):
        card = (ROOT / 'ebid_review_20260912/card.html').read_text(encoding='utf-8')
        edition = (ROOT / 'ebid_edition_20260912/edition.html').read_text(encoding='utf-8')
        self.session = Mock()
        self.session.get.side_effect = [
            Mock(text='<a href="/ru/nodes/87164">Map</a>'),
            Mock(text=card), Mock(text=edition, status_code=edition_status)]
        with patch('searcher_ebid.time.sleep'):
            return list(search_query(self.session, 'test', max_pages=1))

    def test_full_chain(self):
        records = self.run_search()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertIn('/71981-', record.source_url)
        self.assertEqual(record.source_year, 2001)
        self.assertEqual(record.depicted_year, 1914)
        self.assertIsNone(record.year_from)
        self.assertEqual(record.author, '')
        extra = json.loads(record.extra_json)
        self.assertEqual(extra['linked_edition']['place'], 'Барнаул')
        self.assertIn('Разгон', extra['linked_edition']['responsibility'])
        self.assertEqual(self.session.get.call_count, 3)
        self.assertFalse(self.session.get.call_args.kwargs['allow_redirects'])

    def test_redirect_fails_not_silent_success(self):
        with self.assertRaises(RuntimeError):
            self.run_search(302)

if __name__ == '__main__':
    unittest.main()
