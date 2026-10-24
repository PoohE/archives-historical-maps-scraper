import json
import unittest
from pathlib import Path

from notion_export import normalize
from library_dates import LIBRARIES

ROOT = Path(__file__).resolve().parents[1]


class LibraryDateTests(unittest.TestCase):
    def sample(self):
        return json.loads((ROOT / 'output/gpib_notion_20260911/example_record_scale_approved.jsonl').read_text(encoding='utf-8'))

    def generic(self, source='neb', text=None, status='approved', scope='main_map'):
        extra = {'publication': {'year': 1980, 'url': 'https://example.org/book',
                                 'locator': 'imprint', 'text': 'Издано в 1980 году'}}
        if text:
            extra['image_observations'] = [{'field': 'information_year_text', 'value': text,
                'url': 'https://example.org/map.jpg', 'locator': 'нижний угол',
                'scope': scope, 'status': status}]
        return {'source': source, 'record': {'title': 'Карта', 'url': 'https://example.org/card', 'extra': extra}}

    def test_gpib_real_record(self):
        choices = json.loads((ROOT / 'output/gpib_notion_20260911/example_choices.json').read_text(encoding='utf-8'))
        row, audit = normalize(self.sample(), choices)
        self.assertEqual(row['Год сведений'], 1859)
        self.assertEqual(row['Год создания (верхняя)'], 1863)
        self.assertEqual(row['Связанное издание: год издания'], 1863)
        self.assertEqual(row['Год создания (нижняя)'], '')
        self.assertIn('linked_edition', row['Примечания'])
        self.assertTrue(audit['date_evidence'])
        self.assertEqual(audit['validation_errors'], [])

    def test_no_edition_choice_no_dates(self):
        row, _ = normalize(self.sample())
        self.assertEqual(row['Год сведений'], '')
        self.assertEqual(row['Год создания (верхняя)'], '')

    def test_common_library_policy_and_archive_exclusion(self):
        for source in LIBRARIES - {'gpib'}:
            row, _ = normalize(self.generic(source))
            self.assertEqual(row['Год создания (верхняя)'], 1980, source)
            self.assertEqual(row['Год создания (нижняя)'], '')
        row, _ = normalize(self.generic('rgada'))
        self.assertEqual(row['Год создания (верхняя)'], '')

    def test_information_phrases(self):
        for text in ('По сведениям 1959', 'Сведения, полученные в 1959 году',
                     'По состоянию на 1959 год', 'Актуально для 1959 года',
                     'Актуализировано в 1959 году', 'Обновлено 1959',
                     'Исправлено по 1959 год', 'Год сведений: 1959', 'Год обновления: 1959'):
            row, _ = normalize(self.generic(text=text))
            self.assertEqual(row['Год сведений'], 1959, text)

    def test_conflicting_range_and_future_dates_stay_blank(self):
        for text in ('По сведениям 1959–1961', 'По сведениям 1959; обновлено 1961',
                     'По состоянию на 1990 год', 'По сведениям 0000'):
            row, audit = normalize(self.generic(text=text))
            self.assertEqual(row['Год сведений'], '', text)
            self.assertTrue(any('information_year_' in i for i in audit['issues']))

    def test_ocr_inset_and_site_dates_excluded(self):
        for status, scope in [('candidate', 'main_map'), ('approved', 'inset'), ('approved', 'website')]:
            row, _ = normalize(self.generic(text='Обновлено 1959', status=status, scope=scope))
            self.assertEqual(row['Год сведений'], '')
        entry = self.generic()
        entry['record']['description'] = 'Сайт обновлен 1959'
        row, _ = normalize(entry)
        self.assertEqual(row['Год сведений'], '')

    def test_untyped_years_and_invalid_publication_excluded(self):
        for value in (True, '1980', 1980.5, None):
            entry = self.generic()
            entry['record']['extra']['publication']['year'] = value
            entry['record']['year_from'] = entry['record']['year_to'] = 1980
            row, _ = normalize(entry)
            self.assertEqual(row['Год создания (верхняя)'], '')


if __name__ == '__main__':
    unittest.main()
