"""PRLIB full-card extraction and offline Notion-compatible serialization.

No Notion writes. Classification is approved only for item 426814.
HTML evidence and relation mappings are separate from scalar CSV columns.
"""
import argparse
import csv
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

UA = 'ResearchSourceAudit/1.0'
C4_URL = 'https://app.notion.com/3830ba89eabe8110b837eb024a84ab10'


def card_id(url):
    p = urlsplit(url)
    if p.scheme != 'https' or p.netloc not in ('prlib.ru', 'www.prlib.ru'):
        raise ValueError('Outside PRLIB HTTPS allowlist')
    m = re.fullmatch(r'/item/(\d+)/?', p.path)
    if not m or p.query or p.fragment:
        raise ValueError('Expected a PRLIB item URL')
    return m[1]


def clean(node):
    return ' '.join(node.get_text(' ', strip=True).split()) if node else ''


def parse_card(html, url):
    ident = card_id(url)
    canonical = 'https://prlib.ru/item/' + ident
    soup = BeautifulSoup(html, 'lxml')
    title = clean(soup.select_one('h1.page-title'))
    desc_node = soup.select_one('.field-name-field-book-bd')
    if not title or desc_node is None:
        raise ValueError('Missing card title or bibliography; not an empty result')
    # Each leaf td is a separate MARC-derived block; do not flatten nested tables.
    blocks = [clean(td) for td in desc_node.select('td') if not td.find('table') and clean(td)]
    description = desc_node.get_text('\n', strip=True)
    imprints = [b for b in blocks if re.search(r'\s[-–—]\s+[^:]{1,80}\s*:', b)]
    series = imprints[0] if imprints else ''
    parts = [b for b in blocks if re.match(r'\[?Т\.\s*\d+', b)]
    issues = []
    part = parts[0] if len(parts) == 1 else ''
    if len(parts) > 1:
        issues.append('ambiguous_volume_description')
    year_text = part or (series if not parts else '')
    # Read publication years after an imprint separator, not every number/year.
    years = re.findall(r'[-–—]\s*\[?(1[5-9]\d{2}|20\d{2})\]?\s*\.', year_text)
    if not part and series:
        years = re.findall(r',\s*\[?(1[5-9]\d{2}|20\d{2})\]?\s*\.', series)
    year = int(years[0]) if len(set(years)) == 1 else None
    if year is None:
        issues.append('publication_year_missing_or_ambiguous')
    place_match = re.search(r'\s[-–—]\s+([^:]{1,80})\s*:', series)
    place = place_match[1].strip() if place_match else ''
    publisher_node = soup.select_one('[href*="field_book_publisher"]:not(link)')
    publisher = clean(publisher_node)
    author = clean(soup.select_one('.field-name-field-book-author'))
    bbk_groups = []
    for th in desc_node.select('th'):
        codes = re.findall(r'ББК\s+([^\s;]+)', clean(th))
        if codes:
            bbk_groups.append(['ББК ' + code for code in codes])
    library_code = '; '.join(dict.fromkeys(code for group in bbk_groups for code in group))
    if ident == '426814' and len(bbk_groups) == 2:
        library_code = ('Серия: ' + '; '.join(bbk_groups[0]) + '\nТом: ' + '; '.join(bbk_groups[1]))
    owner = re.search(r'Место хранения оригинала:\s*([^\n]+)', description)
    copy_source = re.search(r'Источник электронной копии:\s*([^\n]+)', description)
    gallery = list(dict.fromkeys(urljoin(canonical, a['href']) for a in
        soup.select('a.colorbox[data-colorbox-gallery][href]') if a.find('img')))
    part_match = re.search(r'\bч\.\s*(\d+)', part, re.I)
    pages = re.search(r'\b' + str(year) + r'\.\s*[-–—]\s*(.+)', part) if year else None
    approved = ident == '426814'
    if not approved:
        issues.append('source_type_requires_review')
    if not library_code:
        issues.append('library_code_not_found')
    if not author:
        issues.append('author_not_found')
    notes = []
    if gallery:
        notes.append(f'Галерея: {len(gallery)} изображений; полнота цифровой копии не установлена.')
    if approved:
        notes = ['По ручной проверке пользователя: доступны только обложка и титульные страницы; полная цифровая копия не представлена.']
    extra = dict(publisher=publisher, library_code=library_code,
        bbk_groups=bbk_groups, series_description=series, volume_description=part,
        part=part_match[1] if part_match else '', pages=pages[1].strip(' .') if pages else '',
        original_holder=owner[1].strip() if owner else '',
        electronic_copy_source=copy_source[1].strip() if copy_source else '',
        gallery_urls=gallery, digital_url=canonical if gallery else '',
        direct_map_image_url='', notes=notes, review_issues=issues,
        source_type_code='C4' if approved else '',
        source_type_relation=C4_URL if approved else '',
        classification_basis='user approved this item in joint review' if approved else '',
        raw_bibliography_blocks=blocks,
        evidence=dict(url=url, sha256=hashlib.sha256(html).hexdigest(),
                      locator='.field-name-field-book-bd; h1.page-title; a.colorbox'))
    return dict(title=title, author=author, year_from=year, year_to=year,
        place=place, description=description, url=canonical, library_id='prlib',
        library_name='Президентская библиотека',
        category='Военно-статистические обозрения' if approved else 'не классифицировано', extra=extra)


def _request(url):
    # Redirects are validated before following; never disable TLS verification.
    for _ in range(4):
        p = urlsplit(url)
        if p.scheme != 'https' or p.netloc not in ('prlib.ru', 'www.prlib.ru'):
            raise ValueError('Redirect outside PRLIB HTTPS allowlist')
        r = requests.get(url, timeout=30, allow_redirects=False, headers={'User-Agent': UA})
        r.raise_for_status()
        if 300 <= r.status_code < 400:
            url = urljoin(url, r.headers['Location'])
            continue
        return r
    raise ValueError('Too many redirects')


@lru_cache(maxsize=1)
def _robots():
    r = _request('https://www.prlib.ru/robots.txt')
    robot = RobotFileParser()
    robot.parse(r.text.splitlines())
    return robot


def fetch_card(url):
    ident = card_id(url)
    target = 'https://www.prlib.ru/item/' + ident
    if not all(_robots().can_fetch(agent, target) for agent in [UA, 'OpenAI', 'GPTBot']):
        raise PermissionError('robots disallows PRLIB card')
    time.sleep(3)
    response = _request(target)
    raw = response.content
    record = parse_card(raw, url)
    record['extra']['evidence'].update(status=response.status_code,
        final_url=response.url, retrieved_at=datetime.now(timezone.utc).isoformat(),
        tool='requests', version=requests.__version__)
    # Preserved in records_full.jsonl; no silent loss of original detail markup.
    record['extra']['raw_detail_html'] = response.text
    return record


def notion_row(rec):
    e = rec['extra']
    notes = list(e['notes'])
    for label, key in [('Издательство', 'publisher'), ('Место хранения оригинала', 'original_holder'),
                       ('Источник электронной копии', 'electronic_copy_source'), ('Часть', 'part')]:
        if e[key]:
            notes.append(label + ': ' + e[key])
    if e['review_issues']:
        notes.append('Требует проверки: ' + ', '.join(e['review_issues']))
    return {'Название источника': rec['title'], 'Автор / составитель': rec['author'],
        'Год создания (нижняя)': rec['year_from'], 'Год создания (верхняя)': rec['year_to'],
        'Место создания': rec['place'], 'Библиографическое описание': rec['description'],
        'Описание': e['volume_description'] or rec['description'],
        'Библиотечный шифр': e['library_code'], 'Листы / страницы': e['pages'],
        'Ссылка на онлайн-архив': rec['url'], 'Путь / URL к файлу': e['digital_url'],
        'Прямая ссылка на файл изображения': '', 'Примечания': '\n'.join(notes),
        'Автор внесения': 'Агент'}


def export_record(rec, output):
    output.mkdir(parents=True, exist_ok=False)
    (output / 'records_full.jsonl').write_text(json.dumps({'source': 'prlib', 'record': rec},
        ensure_ascii=False) + '\n', encoding='utf-8')
    row = notion_row(rec)
    with (output / 'notion_import.csv').open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    review = dict(rows=1, issues=rec['extra']['review_issues'],
        relations=[{'source_url': rec['url'], 'property': 'Тип источника',
                    'code': rec['extra']['source_type_code'],
                    'target_url': rec['extra']['source_type_relation']}],
        note='Relation is not a scalar CSV field; apply separately during approved Notion import.')
    (output / 'export_review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--html', type=Path, help='Saved HTML: offline mode')
    p.add_argument('--url', required=True)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    record = parse_card(args.html.read_bytes(), args.url) if args.html else fetch_card(args.url)
    export_record(record, args.output)
    print(json.dumps({'rows': 1, 'issues': record['extra']['review_issues'], 'output': str(args.output)}, ensure_ascii=False))
