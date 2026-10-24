import unittest
from administrative_level import apply_level
from notion_export import normalize, PROPERTIES


class AdministrativeLevelTests(unittest.TestCase):
    def infer(self, title, existing=''):
        row = {'Название источника': title, 'Административный уровень': existing}
        issues = []
        audit = apply_level(row, PROPERTIES['Административный уровень']['options'], issues)
        return row['Административный уровень'], audit, issues

    def test_inflections_abbreviations_and_old_spelling(self):
        for title, expected in [('Карта Калужской губернии', 'Губерния'),
                                ('Планъ Козельскаго уѣзда', 'Уезд'),
                                ('Калужская губ.', 'Губерния'),
                                ('Планы волостей', 'Волость'),
                                ('План города Калуги', 'Нас. пункт'),
                                ('План села Ивановского', 'Нас. пункт'),
                                ('План лесной дачи', 'Дача')]:
            self.assertEqual(self.infer(title)[0], expected, title)

    def test_multiple_levels_and_unsupported(self):
        for title in ('Уезд Калужской губернии', 'Город Козельск Козельского уезда',
                      'Карта Калужской области', 'Район Калужской губернии'):
            value, audit, issues = self.infer(title)
            self.assertEqual(value, '')
            self.assertEqual(audit['status'], 'review_required')
            self.assertTrue(issues)

    def test_no_substrings_or_institution_adjectives(self):
        for title in ('Уездный комитет', 'Губернская типография', 'Дачный посёлок', 'Карта Калуги'):
            self.assertEqual(self.infer(title)[0], '')

    def test_no_silent_overwrite(self):
        value, audit, issues = self.infer('Калужская губерния', 'Уезд')
        self.assertEqual(value, 'Уезд')
        self.assertIn('administrative_level_conflict', issues)

    def test_all_registered_sources_and_no_query_inference(self):
        from registry import SOURCES
        for source in [*SOURCES, 'rgada', 'rgvia', 'garf', 'ebid']:
            entry = {'source': source, 'territory': 'Калужская губерния',
                     'record': {'title': 'Карта Калужской губернии', 'url': 'https://example.org/card'}}
            row, audit = normalize(entry)
            self.assertEqual(row['Административный уровень'], 'Губерния', source)
            self.assertEqual(audit['validation_errors'], [])
            entry['record']['title'] = 'Карта'
            row, _ = normalize(entry)
            self.assertEqual(row['Административный уровень'], '')


if __name__ == '__main__':
    unittest.main()
