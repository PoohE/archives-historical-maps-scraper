import copy
import json
import unittest
from pathlib import Path

from export_gpib_notion import convert
from notion_export import normalize

ROOT = Path(__file__).resolve().parents[1]


class ResponsibilityTests(unittest.TestCase):
    def setUp(self):
        package = ROOT / 'output/gpib_handoff_20260914_v1/inputs'
        self.entry = json.loads((package / 'records_full.jsonl').read_text(encoding='utf-8-sig').strip())
        self.choices = json.loads((package / 'choices.json').read_text(encoding='utf-8-sig'))
        self.edition = next(e for e in self.entry['record']['extra']['edition_links']
                            if e['url'].endswith('/16028'))

    def test_complete_selected_edition_and_distinct_roles(self):
        before = copy.deepcopy(self.entry)
        row, audit = normalize(self.entry, self.choices)
        self.assertEqual(row['Связанное издание: автор / ответственность'], 'Обраб. Н. Штиглицом')
        self.assertIn(self.edition['description'], row['Описание'])
        self.assertIn('XXXIV, 209 с., 1. л. карт.', row['Описание'])
        self.assertIn('181-209', row['Описание'])
        self.assertEqual(row['Автор / составитель'], '')
        self.assertEqual(row['Листы / страницы'], '')
        self.assertEqual(row['Год сведений'], 1859)
        self.assertEqual(row['Год создания (верхняя)'], 1863)
        self.assertEqual(audit['validation_errors'], [])
        self.assertEqual(self.entry, before)

    def test_unselected_edition_never_supplies_responsibility(self):
        row, issues = convert(self.entry, {})
        self.assertEqual(row['Связанное издание: автор / ответственность'], '')
        self.assertNotIn(self.edition['description'], row['Описание'])
        self.assertTrue(issues)

    def test_missing_description_keeps_summary_fallback(self):
        self.edition['description'] = ''
        self.edition['author'] = ''
        row, issues = convert(self.entry, self.choices)
        self.assertEqual(row['Связанное издание: автор / ответственность'], '')
        self.assertIn('Год издания: 1863', row['Описание'])


if __name__ == '__main__':
    unittest.main()
