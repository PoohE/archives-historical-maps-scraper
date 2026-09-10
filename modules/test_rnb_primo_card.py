import csv
import tempfile
import unittest
from pathlib import Path
from rnb_primo_card import parse_card, export_record

SOURCE = Path('D:/Yandex.Disk/History&Geography/БД/Поиск онлайн архив/скрины архивов/Семитопографическая карта Калужской губернии - Российская Национальная Библиотека.html')
URL = 'https://primo.nlr.ru/primo_library/libweb/action/display.do?doc=07NLR_LMS022400796&vid=07NLR_VU1&tabs=detailsTab'

class Tests(unittest.TestCase):
    def setUp(self):
        self.raw = SOURCE.read_bytes()

    def test_saved_card(self):
        r = parse_card(self.raw, URL)
        self.assertEqual(r['year'], 1860)
        self.assertEqual(r['survey_years'], [1852, 1853])
        self.assertEqual(r['shelfmark'], 'К 3-Цтр 3/87')
        self.assertEqual(r['system_id'], 'NLR01 022400796')
        self.assertEqual(r['publisher'], 'Военно-топографическое депо')
        self.assertEqual(r['place'], 'Санкт-Петербург')
        self.assertEqual(r['edition_title_literal'], 'Атласа Российской империи')
        self.assertIsNone(r['scale_denominator'])

    def test_other_card_rejected(self):
        with self.assertRaises(ValueError):
            parse_card(self.raw, URL.replace('022400796', '999999999'))

    def test_no_imprint_does_not_use_survey(self):
        raw = self.raw.replace(b'1860.', b'????.')
        self.assertIsNone(parse_card(raw, URL)['year'])

    def test_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'result'
            export_record(parse_card(self.raw, URL), out)
            with (out/'notion_import.csv').open(encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['Год создания (нижняя)'], '1860')
            self.assertEqual(rows[0]['Путь / URL к файлу'], '')
            with self.assertRaises(FileExistsError):
                export_record(parse_card(self.raw, URL), out)

if __name__ == '__main__':
    unittest.main()
