import csv
import tempfile
import unittest
from pathlib import Path
from rnb_rusmarc import parse, export_saved
from searcher_rnb_kart import _parse_years, _parse_records

SOURCE = Path('D:/Yandex.Disk/History&Geography/БД/Поиск онлайн архив/скрины архивов/328 (Rusmarc1).html')

class Tests(unittest.TestCase):
    def test_full_card(self):
        r = parse(SOURCE.read_bytes())
        self.assertEqual(r['record_num'], '329')
        self.assertEqual(r['year'], 1800)
        self.assertEqual(r['scale_denominator'], 450000)
        self.assertEqual(r['meridian'], 'Ферро')
        self.assertEqual(r['shelfmark'], 'РНБ К 1-Росс 2/15а')
        self.assertEqual(r['edition_year'], 1800)
        self.assertIn('N 23', r['edition_description'])
        self.assertIn('1961', r['reference_notes'][0])
        self.assertGreater(len(r['description']), 600)
        self.assertTrue(r['scale_original'].startswith('['))

    def test_missing_date_not_reference(self):
        raw = SOURCE.read_bytes().replace(b'$d1800]', b'$d????]')
        self.assertIsNone(parse(raw)['year'])

    def test_multiple_records_rejected(self):
        with self.assertRaises(ValueError):
            parse(SOURCE.read_bytes().replace(b'001:',b'001: 999<br>001:',1))

    def test_no_truncation(self):
        description = 'x'*750
        html = '<table><tr><td><font color="RED">329</font><br>РНБ К 1<br>'+description+'</td></tr></table>'
        self.assertEqual(_parse_records(html,'Калуж')[0].description,description)

    def test_search_imprint(self):
        self.assertEqual(_parse_years('Карта. - [СПб.: Департамент, 1800]. - 1 л. Лемус 1961'),(1800,1800))
        self.assertEqual(_parse_years('Лемус 1961'),(None,None))

    def test_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'out'
            r=export_saved(SOURCE,p)
            self.assertEqual((p/'original.html').read_bytes(),SOURCE.read_bytes())
            with (p/'notion_import.csv').open(encoding='utf-8-sig',newline='') as f:
                row=list(csv.DictReader(f))[0]
            self.assertEqual(row['Год создания (верхняя)'],'1800')
            self.assertEqual(row['Масштаб (знаменатель)'],'450000')
            self.assertEqual(row['Описание'],r['description'])
            self.assertEqual(row['Связанное издание: URL'],'')
            with self.assertRaises(FileExistsError):
                export_saved(SOURCE,p)

if __name__ == '__main__':
    unittest.main()
