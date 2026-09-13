import csv
import io
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from bs4 import BeautifulSoup
from searcher_rgia import _parse_object_page, _parse_object_json, main

class SavedTests(unittest.TestCase):
    def setUp(self):
        source = Path('D:/Yandex.Disk/History&Geography/БД/Поиск онлайн архив/скрины архивов/РГИА_380_39_623.html')
        self.record = _parse_object_page(str(BeautifulSoup(source.read_bytes(), 'html.parser')), 'https://fgurgia.ru/object/4844881')

    def test_html(self):
        self.assertEqual(self.record.fund_code, 'Ф. 380 Оп. 39 Д. 623')
        self.assertEqual(self.record.sheets, '1')
        self.assertEqual(self.record.year_from, 1892)
        self.assertIn('МИНИСТЕРСТВА ЗЕМЛЕДЕЛИЯ', self.record.fund_name)

    def test_cli_export_in_memory(self):
        buffer = io.StringIO()
        context = Mock()
        context.__enter__ = Mock(return_value=buffer)
        context.__exit__ = Mock(return_value=False)
        with patch('sys.argv', ['searcher_rgia.py', 'test', '--csv', 'unused.csv']), patch('searcher_rgia.search_simple', return_value=iter([self.record])), patch('builtins.open', return_value=context):
            main()
        row = next(csv.DictReader(io.StringIO(buffer.getvalue())))
        self.assertEqual(row['sheets'], '1')
        self.assertEqual(row['date_raw'], '1892')
        self.assertEqual(row['fund_name'], self.record.fund_name)

    def test_json_no_date_from_number(self):
        # Synthetic regression, not proof of live API schema.
        record = _parse_object_json({'attributes': [{'name': 'Номер фонда', 'value': '1840'}]}, 'test')
        self.assertIsNone(record.year_from)

if __name__ == '__main__':
    unittest.main()
