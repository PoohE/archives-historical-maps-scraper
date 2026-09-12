import unittest
from pathlib import Path
from searcher_rosarchive import _parse_case_page, _parse_years

SOURCE = Path('D:/Yandex.Disk/History&Geography/БД/Поиск онлайн архив/скрины архивов')

class SavedTests(unittest.TestCase):
    def test_case(self):
        paths = list(SOURCE.glob('Читальный*.html'))
        self.assertEqual(len(paths), 1)
        record = _parse_case_page(paths[0].read_text(encoding='utf-8'))
        self.assertEqual(record['Номер дела'], '4486')
        self.assertEqual(record['Фонд'], '1356')
        self.assertEqual(record['Опись'], '1')
        self.assertEqual(record['Аннотация'], '')
        self.assertEqual(record['Примечание'], '')
        self.assertNotIn('\n', record['_title'])
        self.assertEqual(_parse_years(record['Крайние даты документов в деле']), (1840, 1840))

    def test_fund_separate(self):
        record = _parse_case_page((SOURCE / 'РГАДА_фонд_1356.html').read_text(encoding='utf-8'))
        self.assertEqual(record['Номер фонда'], '1356')
        self.assertEqual(len(record['Аннотация']), 8286)
        self.assertEqual(record['Начальный год'], '1766')
        self.assertNotIn('Год начала дела', record)

    def test_unknown_year(self):
        self.assertEqual(_parse_years('0'), (None, None))

if __name__ == '__main__':
    unittest.main()
