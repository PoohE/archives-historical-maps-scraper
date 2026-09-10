import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prlib_card import parse_card, notion_row, export_record, card_id


class CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sample = Path(__file__).parent / 'evidence_www/426814.html'
        if not sample.exists():
            sample = Path(__file__).parent.parent / 'output/prlib_review_20260911/evidence_www/426814.html'
        cls.raw = sample.read_bytes()
        cls.url = 'https://prlib.ru/item/426814'

    def test_real_html(self):
        rec = parse_card(self.raw, self.url)
        self.assertEqual(rec['author'], 'Попроцкий М.')
        self.assertEqual(rec['year_from'], 1864)
        self.assertEqual(rec['year_to'], 1864)
        self.assertEqual(rec['place'], 'Санкт-Петербург')
        e = rec['extra']
        self.assertEqual(e['part'], '2')
        self.assertEqual(e['publisher'].lower(), 'главное управление генерального штаба')
        self.assertEqual(e['original_holder'], 'ЦВМБ')
        self.assertEqual(e['electronic_copy_source'], 'ЦВМБ')
        self.assertEqual(e['bbk_groups'], [['ББК 63.3(28)5', 'ББК 26.89(2)'],
                                         ['ББК 63.3(28-8Кал)5', 'ББК 26.89(235.44)']])
        self.assertEqual(len(e['gallery_urls']), 5)
        self.assertEqual(e['review_issues'], [])
        self.assertEqual(e['source_type_code'], 'C4')
        self.assertEqual(notion_row(rec)['Прямая ссылка на файл изображения'], '')

    def test_classification_not_global(self):
        rec = parse_card(self.raw, 'https://www.prlib.ru/item/999999')
        self.assertEqual(rec['extra']['source_type_code'], '')
        self.assertIn('source_type_requires_review', rec['extra']['review_issues'])
        self.assertNotEqual(rec['category'], 'карты')

    def test_empty_or_error_page(self):
        with self.assertRaises(ValueError):
            parse_card(b'<h1>Access denied</h1>', self.url)

    def test_no_year_is_not_series_start(self):
        raw = self.raw.replace(b'1864', b'????')
        rec = parse_card(raw, self.url)
        self.assertIsNone(rec['year_from'])
        self.assertIn('publication_year_missing_or_ambiguous', rec['extra']['review_issues'])

    def test_allowlist(self):
        for url in ['https://evil.test/item/426814', 'https://prlib.ru/search',
                    'http://prlib.ru/item/426814', 'https://prlib.ru/item/426814?x=1']:
            with self.assertRaises(ValueError):
                card_id(url)

    def test_export_roundtrip_no_relation_guess(self):
        rec = parse_card(self.raw, self.url)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'export'
            export_record(rec, output)
            with (output / 'notion_import.csv').open(encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['Год создания (нижняя)'], '1864')
            self.assertEqual(rows[0]['Путь / URL к файлу'], self.url)
            self.assertNotIn('Тип источника', rows[0])
            self.assertEqual(rows[0]['Библиографическое описание'], rec['description'])
            meta = json.loads((output / 'export_review.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['relations'][0]['code'], 'C4')
            with self.assertRaises(FileExistsError):
                export_record(rec, output)

    def test_search_to_full_record(self):
        import searcher_libraries as lib
        from types import SimpleNamespace
        search = '<article><h2><a href="/item/426814">Example 1859</a></h2></article>'
        with patch.object(lib, '_get', return_value=SimpleNamespace(text=search)), \
             patch('prlib_card.fetch_card', side_effect=lambda url: parse_card(self.raw, url)):
            rows = list(lib._search_prlib('Калужская', 1860, 1865, 1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].year_from, 1864)
        self.assertEqual(rows[0].extra['part'], '2')


if __name__ == '__main__':
    unittest.main()
