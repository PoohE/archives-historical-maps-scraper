import unittest
from pathlib import Path
from ebid_card import parse_card


class CardTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).with_name('card.html')
        if not fixture.exists():
            fixture = Path(__file__).resolve().parents[1] / 'output/ebid_review_20260912/card.html'
        self.html = fixture.read_text(encoding='utf-8')
        self.record = parse_card(self.html, 'https://docs.historyrussia.org/ru/nodes/87164')

    def test_dates(self):
        self.assertEqual(self.record['depicted_year'], 1914)
        self.assertEqual(self.record['linked_edition']['year'], 2001)
        self.assertIsNone(self.record['creation_year'])

    def test_full_edition_without_count(self):
        edition = self.record['linked_edition']['description']
        self.assertGreater(len(edition), 150)
        self.assertIn('2001', edition)
        self.assertNotIn('(166)', edition)

    def test_separate_publication(self):
        self.assertIn('1978', self.record['publication_statement'])
        self.assertIn('С. 20', self.record['publication_statement'])

    def test_no_invented_fields(self):
        self.assertEqual(self.record['author'], '')
        self.assertIsNone(self.record['scale_denominator'])
        self.assertEqual(self.record['original_download_urls'], [])
        self.assertIn('edition_url_is_index_not_bibliographic_card', self.record['review_issues'])

    def test_unknown_layout_fails(self):
        with self.assertRaises(ValueError):
            parse_card('<h1>Error</h1>', 'https://docs.historyrussia.org/')


if __name__ == '__main__':
    unittest.main()
