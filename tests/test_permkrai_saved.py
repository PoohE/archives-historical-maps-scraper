import os
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from bs4 import BeautifulSoup
import searcher_permkrai as m

_candidate = os.environ.get('PERMKRAI_FIXTURE')
SOURCE = Path(_candidate) if _candidate else None
if SOURCE is None or not SOURCE.exists():
    SOURCE = Path(__file__).resolve().parents[1] / 'output/permkrai_review_20260912/card.html'
HTML = SOURCE.read_text(encoding='utf-8-sig') if SOURCE.exists() else ''
URL = 'https://lib.permkrai.ru/node/37840'

@unittest.skipUnless(SOURCE.exists(), 'локальный HTML-файл Пермской библиотеки не включён в рабочую копию')
class CardTests(unittest.TestCase):
    def test_saved(self):
        r = m.parse_card_html(HTML, URL)
        self.assertEqual(r.author, 'Кривощёков Иван Яковлевич')
        self.assertEqual(r.shelfmark, 'НП 4180')
        self.assertEqual(r.scale_denominator, 840000)
        self.assertEqual(r.scale_raw, '1:840000, 20 верст в 1 дюйме')
        self.assertEqual(r.sheets, '1 л.')
        self.assertEqual((r.year_from,r.year_to), (1909,1909))
        self.assertEqual((r.publication_year_from,r.publication_year_to), (1909,None))
        self.assertEqual(r.publication_date_qualifier, 'не ранее')
        self.assertIn('15 февраля 1911',r.bibliography)
        self.assertEqual(r.url_viewer, URL+'?fragment=page-1')
        self.assertEqual(r.url_download, URL+'/pdfbook/download/Karta_Permskoy_gubernii._1909.pdf')

    def test_search_card_integration(self):
        with patch.object(m, '_get', return_value=SimpleNamespace(text=HTML)) as get:
            self.assertEqual(m.parse_card(URL).shelfmark, 'НП 4180')
            get.assert_called_once()

    def test_missing_date_not_from_autograph(self):
        soup=BeautifulSoup(HTML,'html.parser')
        soup.select_one('.field-name-field-publish-date').decompose()
        r=m.parse_card_html(str(soup),URL)
        self.assertIsNone(r.year_from)
        self.assertIsNone(r.year_to)

    def test_filters(self):
        self.assertIsNone(m.parse_card_html(HTML,URL,year_to=1900))
        self.assertIsNone(m.parse_card_html('<html>unavailable</html>',URL))

    def test_missing_main_scale(self):
        html=HTML.replace('1:840000, 20 верст в 1 дюйме.', '')
        html=html.replace('На карте автограф', 'Доп. карта: 1:21000. На карте автограф')
        self.assertIsNone(m.parse_card_html(html,URL).scale_denominator)

if __name__=='__main__':
    unittest.main()
