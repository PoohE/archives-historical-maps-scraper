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

    def test_extent_is_not_map_locator(self):
        rec = parse_card(self.raw, self.url)
        row = notion_row(rec)
        self.assertEqual(row['Листы / страницы'], '')
        self.assertIn('563, 79 с., 56 л.', row['Описание'])
        self.assertEqual(row['Описание'], rec['description'])
        self.assertTrue(rec['extra']['pages'])  # Raw extent is not discarded.
        self.assertIn('не установлено', row['Примечания'])

    def test_publisher_and_compiler_roles_stay_separate(self):
        from notion_export import normalize
        rec = parse_card(self.raw, self.url)
        row, audit = normalize({'source': 'prlib', 'record': rec})
        self.assertEqual(row['Автор / составитель'], '')
        self.assertEqual(row['Связанное издание: автор / ответственность'], 'Попроцкий М.; составил Генерального штаба подполковник М. Попроцкий. ч. 2.')
        self.assertIn('Главное управление Генерального штаба', row['Описание'])
        self.assertIn('Департамент Генерального штаба', row['Описание'])
        self.assertNotIn('Организация-издатель серии', row['Примечания'])
        self.assertIn('map_page_locator_not_established', audit['issues'])
        self.assertEqual(audit['validation_errors'], [])

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
            self.assertEqual(rows[0]['Год создания (нижняя)'], '')
            self.assertEqual(rows[0]['Год создания (верхняя)'], '1864')
            self.assertEqual(len(rows[0]), 64)
            self.assertEqual(rows[0]['Статус приёмки'], 'кандидат')
            self.assertEqual(rows[0]['Путь / URL к файлу'], '')
            self.assertNotIn('Тип источника', rows[0])
            self.assertEqual(rows[0]['Описание'], rec['description'])
            meta = json.loads((output / 'export_review.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['relations'][0]['code'], 'C4')
            with self.assertRaises(FileExistsError):
                export_record(rec, output)

    def test_search_to_full_record(self):
        import searcher_libraries as lib
        from types import SimpleNamespace
        search = '<article><h2><a href="/item/426814">Карта Калужской губернии</a></h2></article>'
        with patch.object(lib, '_get', return_value=SimpleNamespace(text=search)), \
             patch('prlib_card.fetch_card', side_effect=lambda url: parse_card(self.raw, url)):
            rows = list(lib._search_prlib('Калужская', 1860, 1865, 1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].year_from, 1864)
        self.assertEqual(rows[0].extra['part'], '2')

    def test_search_filters_foreign_provinces(self):
        import searcher_libraries as lib
        from types import SimpleNamespace
        search = ''.join([
            '<article><h2><a href="/item/1">Карта Иркутской губернии</a></h2></article>',
            '<article><h2><a href="/item/2">Карта Киевской губернии</a></h2></article>',
            '<article><h2><a href="/item/3">Карта Калужской губернии</a></h2></article>',
        ])
        with patch.object(lib, '_get', return_value=SimpleNamespace(text=search)), \
             patch.object(lib, 'PRLIB_FETCH_DETAILS_IN_BULK', False):
            rows = list(lib._search_prlib('карта Калужская губерния', None, None, 1))
        self.assertEqual([row.url for row in rows], ['https://prlib.ru/item/3'])

    def test_search_requires_administrative_marker_for_province(self):
        import searcher_libraries as lib
        from types import SimpleNamespace
        search = '<article><h2><a href="/item/4">Карта Калужской области</a></h2></article>'
        with patch.object(lib, '_get', return_value=SimpleNamespace(text=search)), \
             patch.object(lib, 'PRLIB_FETCH_DETAILS_IN_BULK', False):
            rows = list(lib._search_prlib('карта Калужская губерния', None, None, 1))
        self.assertEqual(rows, [])

    def test_search_keeps_district_word_forms(self):
        import searcher_libraries as lib
        from types import SimpleNamespace
        search = ''.join([
            '<article><h2><a href="/item/5">Карта Малоярославецкого уезда Калужской губернии</a></h2></article>',
            '<article><h2><a href="/item/6">Карта Переславль-Залесского уезда Владим. губ.</a></h2></article>',
        ])
        with patch.object(lib, '_get', return_value=SimpleNamespace(text=search)), \
             patch.object(lib, 'PRLIB_FETCH_DETAILS_IN_BULK', False):
            rows = list(lib._search_prlib('карта Малоярославецкий', None, None, 1))
        self.assertEqual([row.url for row in rows], ['https://prlib.ru/item/5'])


if __name__ == '__main__':
    unittest.main()
