import csv
import tempfile
import unittest
from pathlib import Path
from searcher_neb import parse_card_html
from neb_export import export_saved, notion_row
SOURCE=Path('D:/Yandex.Disk/History&Geography/БД/Поиск онлайн архив/output/neb_browser_smoke_20260909_v2/raw/card_ручной запрос_1_29d80e29c9da229d.html')
URL='https://rusneb.ru/catalog/000200_000018_RU_NLR_cart_8878/'

class Tests(unittest.TestCase):
    def setUp(self): self.html=SOURCE.read_text(encoding='utf-8')
    def test_fields(self):
        r=parse_card_html(self.html,URL)
        self.assertEqual(r.year_from,1926)
        self.assertEqual(r.place,'Калуга')
        self.assertIn('Карпов',r.author)
        self.assertIn('36х45',r.bibliography)
        self.assertIn('viewer.rusneb.ru',r.url_viewer)
        self.assertIn('doc_type=pdf',r.url_download)
        self.assertNotIn('qr',r.url_download.lower())
    def test_inset_and_raw(self):
        r=parse_card_html(self.html,URL); row=notion_row(r)
        self.assertNotIn('21 000',row['Описание'])
        self.assertIsNone(row['Масштаб (знаменатель)'])
        self.assertIn('21 000',r.extra['excluded_inset_notes'][0])
        self.assertEqual(r.extra['raw_meta']['ISBN'],'Калуга')
    def test_qr_rejected(self):
        html='<h1>test</h1><a href="/downloadqr.php?id=1">QR</a>'
        r=parse_card_html(html,'https://rusneb.ru/catalog/test/')
        self.assertEqual(r.url_viewer,''); self.assertEqual(r.url_download,'')
        self.assertEqual(r.access,'')
    def test_browser_row(self):
        from searcher_neb_browser import _record_row, CSV_FIELDS
        row=_record_row(parse_card_html(self.html,URL),'Калужская','карта','2026-09-12','offline-test')
        self.assertEqual(set(row),set(CSV_FIELDS))
        self.assertIn('Карпов',row['author']); self.assertIn('36х45',row['bibliography'])
    def test_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'result'; export_saved(SOURCE,URL,out)
            with (out/'notion_import.csv').open(encoding='utf-8-sig',newline='') as f:
                row=list(csv.DictReader(f))[0]
            self.assertIn('Код НЭБ:',row['Библиотечный шифр'])
            self.assertEqual((out/'original.html').read_bytes(),SOURCE.read_bytes())
            with self.assertRaises(FileExistsError): export_saved(SOURCE,URL,out)

if __name__=='__main__': unittest.main()
