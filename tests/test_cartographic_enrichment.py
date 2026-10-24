import unittest
from unittest.mock import patch

from cartographic_enrichment import convert_scale, VOCAB
from notion_export import normalize


class CartographyTests(unittest.TestCase):
    def entry(self, source='rgada', scale=None, labels=None):
        extra = {}
        if scale is not None:
            extra['scale_original'] = scale
        if labels is not None:
            extra['legend_observations'] = [{'text': '; '.join(labels),
                'entries': labels, 'status': 'approved', 'scope': 'main_map',
                'url': 'https://example.org/map.jpg', 'locator': 'legend'}]
        return {'source': source, 'record': {'title': 'Карта', 'url': 'https://example.org/card', 'extra': extra}}

    def test_scales(self):
        for text, expected in [('1:25 000', 25000), ('Масштаб [1 : 25000]', 25000),
                               ('В 1 см 2 км', 200000), ('500 м в 1 см', 50000),
                               ('В 1 см 0,5 км', 50000),
                               ('30 вёрст в английском дюйме', 1260000),
                               ('В английском дюйме 30 верст', 1260000)]:
            value, evidence = convert_scale(text)
            self.assertEqual(value, expected, text)
            self.assertTrue(evidence['calculation'])

    def test_uncertain_scales_not_guessed(self):
        for text in ('30 верст в дюйме', '2 мили в дюйме', 'Линейный масштаб в километрах',
                     '1:25000; врезка 1:5000', '1:0', 'В 1 см 0,000001 м'):
            self.assertIsNone(convert_scale(text)[0], text)

    def test_every_registered_source_uses_common_scale(self):
        from registry import SOURCES
        for source in [*SOURCES, 'rgada', 'rgvia', 'garf', 'ebid']:
            row, audit = normalize(self.entry(source, 'В 1 см 2 км'))
            self.assertEqual(row['Масштаб (знаменатель)'], 200000, source)
            self.assertTrue(audit['cartography']['scales'])
            self.assertEqual(audit['validation_errors'], [])

    def test_legend_four_existing_relations_and_question(self):
        row, audit = normalize(self.entry(labels=['губернский город', 'селения',
            'границы уездов', 'границы станов', 'почтовые дороги', 'реки', 'становые квартиры']))
        self.assertEqual(len(audit['relations']), 4)
        self.assertTrue(all(r['target_url'] in {t['url'] for t in VOCAB['types']} for r in audit['relations']))
        self.assertIn('становые квартиры', row['Описание'])
        self.assertEqual(len(audit['cartography']['questions']), 1)
        self.assertNotIn('Типы отображаемых объектов', row)

    def test_missing_duplicate_unknown_mapping_needs_review(self):
        entry = self.entry(labels=['реки', 'несуществующий тип'])
        duplicate = {**VOCAB, 'types': VOCAB['types'] + [VOCAB['types'][-1]]}
        with patch('cartographic_enrichment.VOCAB', duplicate):
            _, audit = normalize(entry)
        self.assertEqual(audit['relations'], [])
        self.assertEqual(len(audit['cartography']['questions']), 2)

    def test_unreviewed_legend_retains_text_but_no_relations(self):
        entry = self.entry(labels=['реки'])
        entry['record']['extra']['legend_observations'][0]['status'] = 'candidate'
        row, audit = normalize(entry)
        self.assertIn('реки', row['Описание'])
        self.assertEqual(audit['relations'], [])
        self.assertIn('legend_reading_pending', audit['issues'])

    def test_conflicting_scales_and_unreviewed_image(self):
        entry = self.entry(scale='1:25000')
        entry['record']['extra']['scale_raw'] = '1:50000'
        row, audit = normalize(entry)
        self.assertEqual(row['Масштаб (знаменатель)'], '')
        self.assertIn('scale_conflict', audit['issues'])
        entry = self.entry()
        entry['record']['extra']['image_observations'] = [{'field': 'scale_original',
            'value': '1:25000', 'status': 'candidate', 'scope': 'main_map'}]
        row, audit = normalize(entry)
        self.assertEqual(row['Масштаб (знаменатель)'], '')
        self.assertIn('scale_reading_pending', audit['issues'])


if __name__ == '__main__':
    unittest.main()
