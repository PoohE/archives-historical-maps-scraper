"""Offline extraction of a user-saved RNB Primo detail card; no network.

This is not a Primo search adapter. Missing fields remain empty and enter review.
The original user file is read-only and is referenced by path and SHA-256.
"""
import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from bs4 import BeautifulSoup, Comment


def text(node):
    return ' '.join(node.get_text(' ', strip=True).split()) if node else ''


def parse_card(raw, source_url):
    u = urlsplit(source_url)
    doc = parse_qs(u.query).get('doc', [''])[0]
    if u.scheme != 'https' or u.netloc != 'primo.nlr.ru' or not re.fullmatch(r'07NLR_LMS\d+', doc):
        raise ValueError('Expected HTTPS Primo card URL with doc ID')
    soup = BeautifulSoup(raw, 'lxml')
    title = text(soup.select_one('h1.EXLResultTitle'))
    fields = {}
    for li in soup.select('li[id]'):
        label = li.find('strong', recursive=False)
        if label is None:
            continue
        name = text(label).rstrip(':')
        label.extract()
        for node in li.select('script, style'):
            node.decompose()
        for node in li.find_all(string=lambda s: isinstance(s, Comment)):
            node.extract()
        value = text(li)
        fields.setdefault(name, []).append(value)
    get = lambda name: '\n'.join(fields.get(name, []))
    description = get('Описание')
    system_id = get('Системный номер')
    if not title or not description or not system_id:
        raise ValueError('Missing card title, description or system ID')
    if not system_id.replace(' ', '').endswith(doc.removeprefix('07NLR_LMS')):
        raise ValueError('Source URL and saved card identifiers differ')
    issues = []
    # Only publication imprint, never the survey years in the responsibility statement.
    imprint = re.search(r'\s[-–—]\s*\[?([^:\[\]]+)\]?\s*:\s*([^,]+),\s*(\d{4})\.', description)
    place, publisher, year = (imprint[1].strip(), imprint[2].strip(), int(imprint[3])) if imprint else ('', '', None)
    if year is None:
        issues.append('publication_imprint_not_parsed')
    survey = re.search(r'съемки,\s*произведенной в\s*(\d{4})\s*и\s*(\d{4})', description)
    notes = get('Примечания')
    edition = ''
    # Preserve the literal edition wording rather than generate a bibliographic title.
    m = re.search(r'Из\s+(Атласа[^\n]+)', notes)
    if m:
        edition = m[1].strip()
    sizes = re.search(r';\s*([^;]+\bсм\.)', description)
    extent = re.search(r'\b\d{4}\.\s*[-–—]\s*(.+)', description)
    scale_text = get('Масштаб')
    scale_match = re.search(r'1\s*:\s*([\d ]+)', scale_text)
    scale = int(scale_match[1].replace(' ', '')) if scale_match else None
    if scale is None:
        issues.append('scale_not_established')
    # Links to full metadata and MARC are not digital image URLs.
    issues += ['digital_copy_not_established', 'source_type_relation_requires_review']
    return dict(title=title, description=description, source_url=source_url, doc_id=doc,
        system_id=system_id, shelfmark=get('Шифр хранения'), author=get('Автор'),
        organization=get('Другие ответственные лица и организации'),
        holder=get('Находится в библиотеках'), language=get('Язык'),
        year=year, place=place, publisher=publisher, notes=notes,
        subject=get('Предметные рубрики'), edition_title_literal=edition,
        survey_years=[int(survey[1]), int(survey[2])] if survey else [],
        size_literal=sizes[1] if sizes else '', extent=extent[1] if extent else '',
        scale_original=scale_text, scale_denominator=scale,
        raw_fields=fields, review_issues=issues,
        provenance=dict(sha256=hashlib.sha256(raw).hexdigest(), source_url=source_url,
            locator='h1.EXLResultTitle; li[id] > strong and adjacent values',
            input_kind='user_saved_html', http_status=None))


def notion_row(r):
    notes = [r['notes'], 'Системный номер: ' + r['system_id'],
        'Издательство: ' + r['publisher'], 'Библиотека-хранитель: ' + r['holder'],
        'Ответственная организация: ' + r['organization'], 'Цифровая копия не установлена.']
    if r['doc_id'] == '07NLR_LMS022400796':
        notes.append('Ссылки на полное описание и MARC пользователь проверил: пустые окна.')
    if r['survey_years']:
        notes.append('Годы съёмки: ' + '–'.join(map(str, r['survey_years'])))
    if r['size_literal']:
        notes.append('Размеры, дословно: ' + r['size_literal'])
    return {'Название источника': r['title'], 'Автор / составитель': r['author'],
        'Год создания (нижняя)': r['year'], 'Год создания (верхняя)': r['year'],
        'Место создания': r['place'], 'Библиотечный шифр': r['shelfmark'],
        'Библиографическое описание': r['description'], 'Описание': r['subject'],
        'Связанное издание: название': r['edition_title_literal'],
        'Связанное издание: URL': '', 'Ссылка на онлайн-архив': r['source_url'],
        'Путь / URL к файлу': '', 'Прямая ссылка на файл изображения': '',
        'Оригинальный масштаб': r['scale_original'], 'Масштаб (знаменатель)': r['scale_denominator'],
        'Листы / страницы': r['extent'], 'Язык': r['language'],
        'Примечания': '\n'.join(filter(None, notes)), 'Автор внесения': 'Агент'}


def export_record(r, output):
    output.mkdir(parents=True, exist_ok=False)
    (output / 'record.json').write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding='utf-8')
    row = notion_row(r)
    with (output / 'notion_import.csv').open('x', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        w.writeheader()
        w.writerow(row)
    (output / 'review.json').write_text(json.dumps({'issues': r['review_issues'],
        'note': 'One saved card tested; no live search or Notion writes.'}, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--html', type=Path, required=True)
    p.add_argument('--url', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    r = parse_card(a.html.read_bytes(), a.url)
    r['provenance'].update(local_path=str(a.html.resolve()), parsed_at=datetime.now(timezone.utc).isoformat())
    export_record(r, a.output)
    print(json.dumps({'rows': 1, 'year': r['year'], 'issues': r['review_issues']}, ensure_ascii=False))
