import csv
import json
import tempfile
import importlib.util
import sys
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from notion_export import export, normalize, validate, FIELDS, PROPERTIES
from prlib_card import parse_card
import searcher_libraries as lib

ROOT = Path(__file__).resolve().parents[1]


class ExportTests(unittest.TestCase):
    def test_summary_stays_incomplete(self):
        entry = {'source': 'prlib', 'territory': 'Калужская губерния', 'record': {
            'title': 'Калужская губерния', 'url': 'https://prlib.ru/item/426814',
            'description': 'Детальная карточка не запрошена', 'year_from': 1859}}
        row, audit = normalize(entry)
        self.assertEqual(row['Описание'], '')
        self.assertEqual(row['Год создания (нижняя)'], '')
        self.assertIn('detail_not_fetched', audit['issues'])
        self.assertEqual(audit['manual_review'], 'pending')

    def test_types_dates_and_relations(self):
        for row in ({'Год создания (нижняя)': True},
                    {'Ссылка на онлайн-архив': 'file:///tmp/a'},
                    {'Автор внесения': 'Unknown'},
                    {'Год создания (нижняя)': 1900, 'Год создания (верхняя)': 1800},
                    {'Тип источника': 'C4'}):
            self.assertTrue(validate(row))
        self.assertNotIn('Шифр записи', FIELDS)
        self.assertNotIn('Тип источника', FIELDS)
        self.assertTrue(all(k in PROPERTIES for k in FIELDS))

    def test_search_detail_to_csv_preserves_approved_example(self):
        raw = (ROOT / 'output/prlib_review_20260911/evidence_www/426814.html').read_bytes()
        title = 'Материалы для географии и статистики. Калужская губерния'
        search = '<article><h2><a href="/item/426814">' + title + '</a></h2></article>'
        with patch.object(lib, '_get', return_value=SimpleNamespace(text=search)), \
             patch('prlib_card.fetch_card', side_effect=lambda url: parse_card(raw, url)) as fetch:
            records = list(lib._search_prlib('карта Калужская губерния', 1700, 1980, 1))
        fetch.assert_called_once()
        self.assertEqual(len(records), 1)
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / 'records.jsonl'
            inp.write_text(json.dumps({'source': 'prlib', 'record': asdict(records[0])}, ensure_ascii=False), encoding='utf-8')
            report = export(inp, Path(tmp) / 'export')
            with (Path(tmp) / 'export/notion_import.csv').open(encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
            row = rows[0]
            self.assertEqual(row['Автор / составитель'], '')
            self.assertEqual(row['Связанное издание: автор / ответственность'], 'Попроцкий М.; составил Генерального штаба подполковник М. Попроцкий. ч. 2.')
            self.assertEqual(row['Год создания (нижняя)'], '')
            self.assertEqual(row['Год создания (верхняя)'], '1864')
            self.assertIn('ББК', row['Библиотечный шифр'])
            self.assertEqual(row['Путь / URL к файлу'], '')
            self.assertEqual(row['Прямая ссылка на файл изображения'], '')
            self.assertIn('титульные', row['Примечания'])
            self.assertFalse(report['ready_for_import'])
            self.assertEqual(report['records'][0]['validation_errors'], [])
            self.assertEqual({x['property'] for x in report['records'][0]['relations']}, {'Архив хранения', 'Тип источника'})
            with self.assertRaises(FileExistsError):
                export(inp, Path(tmp) / 'export')

    def test_fallback_also_filters_foreign_province(self):
        html = '<a href="/item/1">Карта Иркутской губернии</a>'
        with patch.object(lib, '_get', return_value=SimpleNamespace(text=html)), \
             patch('prlib_card.fetch_card') as fetch:
            self.assertEqual(list(lib._search_prlib('карта Калужская губерния', None, None, 1)), [])
            fetch.assert_not_called()

    def test_orchestrator_exports_detail_without_notion(self):
        spec = importlib.util.spec_from_file_location('run_search_test', ROOT / 'scripts/run_search.py')
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        raw = (ROOT / 'output/prlib_review_20260911/evidence_www/426814.html').read_bytes()
        search = '<article><h2><a href="/item/426814">Калужская губерния</a></h2></article>'
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(sys, 'argv', ['run_search.py', '--source', 'prlib', '--no-notion',
                                      '--max-pages', '1', '--max-combos', '1', '--run-dir', tmp]), \
             patch.object(lib, '_get', return_value=SimpleNamespace(text=search)), \
             patch('prlib_card.fetch_card', side_effect=lambda url: parse_card(raw, url)), \
             patch('archive_health.ArchiveHealth') as health, \
             patch.object(runner.time, 'sleep'), \
             patch('requests.sessions.Session.request', side_effect=AssertionError('Network forbidden in offline test')):
            runner.main()
            health.return_value.save.assert_not_called()
            exports = list(Path(tmp).glob('notion_candidates_*/notion_import.csv'))
            self.assertEqual(len(exports), 1)
            with exports[0].open(encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['Год создания (нижняя)'], '')
            self.assertEqual(rows[0]['Год создания (верхняя)'], '1864')
            self.assertIn('ББК', rows[0]['Библиотечный шифр'])


if __name__ == '__main__':
    unittest.main()
