"""Shared offline library-date policy; no inference from untyped raw years.

Other adapters may supply extra.publication={year, url, locator, text} for
the publication containing the map. Image readings must have scope=main_map,
field=information_year_text, status=approved, value, url and locator.
Unreviewed OCR, site timestamps and inset dates never populate scalar fields.
"""
import re

LIBRARIES = {'gpib', 'prlib', 'nlr_cart', 'rnb', 'rsl', 'neb', 'kaluga_lib',
             'permkrai', 'smolensk_lib', 'yaroslavl_lib', 'aonb'}
INFO = re.compile(
    r'(?:по\s+сведениям|сведения\s*,?\s*полученные(?:\s+в)?|'
    r'по\s+состоянию\s+на|актуально\s+(?:для|на)|'
    r'актуализирован[ао]?|обновлен[ао]?|исправлен[ао]?(?:\s+по)?|год\s+сведений|год\s+обновления)'
    r'\s*[:—–-]?\s*(?:в\s+)?\[?(?P<year>\d{4})(?!\d)'
    r'(?P<range>\s*[-–—]\s*\d{2,4})?', re.I)


def valid_year(value):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 9999


def apply_dates(entry, row, issues, choices):
    rec = entry['record']
    source = entry.get('source') or rec.get('library_id')
    if source not in LIBRARIES:
        return []
    extra = rec.get('extra') or {}
    evidence, texts = [], []
    publication = extra.get('publication')
    if source == 'gpib':
        from export_gpib_notion import choose
        edition = choose(extra.get('edition_links', []),
                         choices.get(rec['url'], {}).get('edition_url'), 'url')
        if edition:
            publication = {'year': row.get('Связанное издание: год издания'),
                           'url': edition['url'], 'locator': 'selected edition',
                           'text': edition.get('title', ''), 'kind': 'linked_edition'}
            texts.extend({'text': edition.get(key, ''), 'url': edition['url'],
                          'locator': 'selected edition.' + key,
                          'scope': 'linked_edition'} for key in ('title', 'description'))
    elif source == 'prlib' and 'raw_bibliography_blocks' in extra:
        publication = {'year': rec.get('year_to'), 'url': rec['url'],
                       'locator': 'volume_description or series_description',
                       'text': extra.get('volume_description') or extra.get('series_description'),
                       'kind': 'own_publication'}
        # The detail parser's two equal years both come from publication,
        # not from independent evidence of a lower creation boundary.
        row['Год создания (нижняя)'] = ''
    if publication:
        year = publication.get('year')
        if valid_year(year) and all(publication.get(k) for k in ('url', 'locator', 'text')):
            old = row.get('Год создания (верхняя)')
            if old not in ('', None, year):
                issues.append('creation_upper_conflicts_with_publication')
                evidence.append({'property': 'Год создания (верхняя)', 'retained': old,
                                 'publication': publication, 'status': 'conflict'})
            else:
                row['Год создания (верхняя)'] = year
                evidence.append({'property': 'Год создания (верхняя)', 'value': year,
                                 'basis': 'publication_upper_bound', **publication})
                note = (f'Верхняя граница создания {year} — по году публикации; '
                        'это не установленный год составления. Для переиздания/факсимиле '
                        'граница относится к поздней публикации. Источник: ' + publication['url'])
                row['Примечания'] = '\n'.join(filter(None, [row.get('Примечания'), note]))
        else:
            issues.append('publication_year_missing_or_unverified')
    for item in extra.get('image_observations', []):
        if item.get('field') != 'information_year_text':
            continue
        if (item.get('status') != 'approved' or item.get('scope') != 'main_map'
                or not item.get('url') or not item.get('locator')):
            issues.append('information_year_observation_pending')
            continue
        texts.append({**item, 'text': item.get('value', '')})
    hits, ambiguous = [], False
    for item in texts:
        for match in INFO.finditer(item['text'].replace('ё', 'е')):
            ambiguous = ambiguous or bool(match['range'])
            hits.append({**item, 'quote': match[0], 'value': int(match['year'])})
    years = {hit['value'] for hit in hits}
    if len(years) == 1 and not ambiguous and all(valid_year(y) for y in years):
        year = next(iter(years))
        upper = row.get('Год создания (верхняя)')
        if valid_year(upper) and year > upper:
            issues.append('information_year_after_publication')
        elif row.get('Год сведений') not in ('', None, year):
            issues.append('information_year_conflict')
        else:
            row['Год сведений'] = year
    elif hits:
        issues.append('information_year_ambiguous')
    if hits:
        evidence.append({'property': 'Год сведений', 'observations': hits,
                         'exported': row.get('Год сведений', '')})
        note = 'Датировка сведений: ' + '; '.join(dict.fromkeys(
            hit['quote'] + ' [' + hit['scope'] + '; ' + hit['url'] + ']' for hit in hits))
        row['Примечания'] = '\n'.join(filter(None, [row.get('Примечания'), note]))
    return evidence
