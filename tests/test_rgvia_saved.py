import os
import unittest
from pathlib import Path
from rgvia_saved import parse, year, HEADERS

_candidate = os.environ.get('RGVIA_FIXTURE')
SOURCE = Path(_candidate) if _candidate else None
if SOURCE is None or not SOURCE.exists():
    SOURCE = Path(__file__).resolve().parents[1] / 'output/rgvia_review_20260912/source.html'

@unittest.skipUnless(SOURCE.exists(), 'локальный HTML-файл РГВИА не включён в рабочую копию')
class SavedPageTests(unittest.TestCase):
    def test_real_page(self):
        rows, audit = parse(SOURCE.read_bytes())
        self.assertEqual(len(rows), 10)
        first = rows[0]
        self.assertEqual([first[k] for k in ['Фонд', 'Опись', 'Единица хранения']], ['2011', '1', '423'])
        self.assertEqual(first['Год создания (нижняя)'], '1916')
        self.assertEqual(first['Год создания (верхняя)'], '1916')
        self.assertEqual(first['Листы / страницы'], '')
        self.assertEqual(rows[1]['Листы / страницы'], '85')
        self.assertTrue(first['Название источника'].endswith('перемещению артиллерийских арсеналов'))
        self.assertTrue(all(not r['has_row_links'] for r in audit['rows']))
        self.assertEqual(audit['query'], 'карт')
        self.assertFalse(audit['rows'][4]['cartographic_term_candidate'])
        self.assertTrue(audit['rows'][0]['cartographic_term_candidate'])

    def test_missing_layout(self):
        with self.assertRaises(ValueError):
            parse('<html>unavailable</html>')

    def test_dates(self):
        self.assertEqual(year(''), '')
        self.assertEqual(year('15.02.1918'), '1918')
        with self.assertRaises(ValueError):
            year('31.02.1918')

    def test_changed_columns(self):
        raw = SOURCE.read_bytes().decode('utf-8')
        with self.assertRaises(ValueError):
            parse(raw.replace('Кол-во листов', 'Другой столбец'))


if __name__ == '__main__':
    unittest.main()
