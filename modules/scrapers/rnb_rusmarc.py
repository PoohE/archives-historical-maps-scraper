"""Offline RUSMARC HTML parser for the RNB eighteenth-century maps catalogue."""
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup


def parse(raw):
    soup = BeautifulSoup(raw, 'lxml')
    plain = soup.get_text('\n', strip=True)
    fields = []
    for line in plain.splitlines():
        m = re.match(r'^(\d{3}):\s*(.*)$', line)
        if m:
            subs = re.findall(r'\$([a-z0-9])([^$]*)', m[2])
            fields.append(dict(tag=m[1], raw=m[2], subfields=subs))
        elif fields and line.strip():
            raise ValueError('Unrecognised continuation; preserve and review input')
    def values(tag, code):
        return [v.strip() for f in fields if f['tag'] == tag for k, v in f['subfields'] if k == code]
    def one(tag, code):
        vals = values(tag, code)
        return vals[0] if len(vals) == 1 else ''
    ids = [f['raw'].strip() for f in fields if f['tag'] == '001']
    title = one('200', 'a')
    if len(ids) != 1 or not ids[0].isdigit() or not title:
        raise ValueError('Expected one complete RUSMARC record')
    issues = []
    date_raw = one('210', 'd')
    year = int(date_raw.strip('[] .')) if re.fullmatch(r'\[?\d{4}\]?[ .]*', date_raw) else None
    if year is None:
        issues.append('publication_date_requires_review')
    geo = values('206', 'a')
    scales = [v for v in geo if re.search(r'1\s*:\s*\d', v)]
    scale_raw = scales[0] if len(scales) == 1 else ''
    m = re.search(r'1\s*:\s*([\d ]+)', scale_raw)
    denominator = int(m[1].replace(' ', '')) if m else None
    if not denominator:
        issues.append('scale_requires_review')
    notes = values('300', 'a')
    editions = [v.removeprefix('Из изд.:').strip() for v in notes if v.startswith('Из изд.:')]
    edition = editions[0] if len(editions) == 1 else ''
    edition_years = re.findall(r'\b(1\d{3})\b', edition)
    edition_year = int(edition_years[0]) if len(set(edition_years)) == 1 else None
    meridians = [v for v in geo if 'Долгота от' in v]
    meridian = 'Ферро' if len(meridians) == 1 and 'Ферро' in meridians[0] else ''
    marks = []
    for f in fields:
        if f['tag'] == '899':
            marks.append(' '.join(v.strip() for k,v in f['subfields'] if k in ('a','j')))
    # Bibliographic data remains verbatim; archival/reference dates are not map dates.
    description = '\n'.join(v for f in fields if f['tag'] in ('200','206','210','215','300') for k,v in f['subfields'])
    issues += ['digital_copy_not_established', 'source_type_relation_requires_review']
    return dict(record_num=ids[0], title=title, responsibility=one('200','f'),
        author_authority=' '.join(filter(None,[one('701','a'),one('701','g')])),
        year=year, date_literal=date_raw, place=one('210','a').strip('[]'),
        publisher=one('210','c'), scale_original=scale_raw, scale_denominator=denominator,
        meridian=meridian, spatial_descriptions=geo, shelfmark='; '.join(marks),
        dimensions_literal=one('215','d'), extent=one('215','a'), technique_literal=one('215','c'),
        description=description, notes=notes, reference_notes=values('321','a'),
        edition_description=edition, edition_title=edition.split('. Издан')[0] if edition else '',
        edition_year=edition_year, territories=values('607','a'), subjects=values('606','a'),
        rusmarc_fields=fields, rusmarc_text=plain,
        source_url=f'https://nlr.ru/rlin/rusmarc.php?numer={int(ids[0])-1}&database=karpgr18',
        review_issues=issues)


def notion_row(r):
    notes = ['Размеры дословно: '+r['dimensions_literal'], 'Техника дословно: '+r['technique_literal'],
        'Автор, авторитетная форма: '+r['author_authority'], 'Издатель: '+r['publisher'],
        'Поле 210$d, дословно: '+r['date_literal'],
        'URL издания и цифровая копия не установлены.']
    notes.extend(r['reference_notes'])
    return {'Название источника':r['title'], 'Автор / составитель':r['responsibility'],
        'Год создания (нижняя)':r['year'], 'Год создания (верхняя)':r['year'],
        'Место создания':r['place'], 'Библиотечный шифр':r['shelfmark'],
        'Оригинальный масштаб':r['scale_original'], 'Масштаб (знаменатель)':r['scale_denominator'],
        'Нулевой меридиан':r['meridian'], 'Листы / страницы':r['extent'],
        'Описание':r['description'], 'Библиографическое описание':r['description'],
        'Связанное издание: название':r['edition_title'],
        'Связанное издание: библиографическое описание':r['edition_description'],
        'Связанное издание: год издания':r['edition_year'], 'Связанное издание: URL':'',
        'Ссылка на онлайн-архив':r['source_url'], 'Путь / URL к файлу':'',
        'Прямая ссылка на файл изображения':'', 'Примечания':'\n'.join(notes), 'Автор внесения':'Агент'}


def export_saved(source, output):
    source, output = Path(source), Path(output)
    raw = source.read_bytes()
    r = parse(raw)
    r['provenance'] = dict(local_path=str(source.resolve()), sha256=hashlib.sha256(raw).hexdigest(),
        parsed_at=datetime.now(timezone.utc).isoformat(), source_kind='user_saved_html',
        http_status=None, locator='RUSMARC tags and subfields')
    output.mkdir(parents=True,exist_ok=False)
    (output/'original.html').write_bytes(raw)
    (output/'record.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'rusmarc.txt').write_text(r['rusmarc_text'],encoding='utf-8')
    row = notion_row(r)
    with (output/'notion_import.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(row)); w.writeheader(); w.writerow(row)
    return r
