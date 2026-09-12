import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from searcher_garf import fetch_case_record

class DetailTests(unittest.TestCase):
    def setUp(self):
        self.raw = Path('D:/Yandex.Disk/History&Geography/БД/Поиск онлайн архив/скрины архивов/ГАРФ_1829_1_13.html').read_bytes()
        self.listed = dict(url='http://opisi.garf.su/default.asp?v=7', delo_num='13', title='Listing', year_raw='1902')
        self.session = Mock()
        self.session.get.return_value = Mock(status_code=200, content=self.raw)

    def test_detail_over_list(self):
        with patch('searcher_garf.time.sleep'):
            record = fetch_case_record(self.session, self.listed)
        self.assertEqual(record.year_from, 1903)
        self.assertEqual(record.sheets, '1')
        self.assertEqual(record.annotation, '')
        self.assertEqual(json.loads(record.extra_json)['listing']['year_raw'], '1902')
        self.assertEqual(record.fond_num, '1829')

    def test_wrong_case(self):
        with patch('searcher_garf.time.sleep'), self.assertRaises(ValueError):
            fetch_case_record(self.session, dict(self.listed, delo_num='12'))

    def test_external_url(self):
        with self.assertRaises(ValueError):
            fetch_case_record(self.session, dict(self.listed, url='https://example.org/default.asp?v=7'))
        self.session.get.assert_not_called()

    def test_redirect(self):
        self.session.get.return_value.status_code = 302
        with patch('searcher_garf.time.sleep'), self.assertRaises(RuntimeError):
            fetch_case_record(self.session, self.listed)

if __name__ == '__main__':
    unittest.main()
