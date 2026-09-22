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
from pathlib import Path
from urllib.parse import urljoin, urlsplit, parse_qsl
from bs4 import BeautifulSoup

try:
    from . import prlib_access as _access
except ImportError:
    import prlib_access as _access

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
    parts = [b for b in blocks if re.match(r'(?:\[?Т\.\s*\d+|\[?[0-9]+\]?\s*:)', b)]
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
    raw_author_field = author
    volume_responsibility = ''
    if part and '/' in part:
        volume_responsibility = re.split(r'[ ]+[-–—][ ]+\[?[0-9]{4}', part.split('/', 1)[1], maxsplit=1)[0].strip()
    if author and re.match(r'\[?[0-9]+\]?[ ]*:', part):
        # Numeric issue may inherit every contributor to a series.
        issues.append('author_scope_requires_review')
        author = ''
    if raw_author_field and re.search(r'гравюр', description, re.I):
        issues.append('responsibility_roles_require_review')
        author = ''
    series_title = re.split(r'[ ]+[-–—][ ]+', series, maxsplit=1)[0].strip()
    if title.endswith(('...', '…')):
        issues.append('title_truncated_in_source')
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
    if not raw_author_field:
        issues.append('author_not_found')
    notes = []
    if gallery:
        notes.append(f'Галерея: {len(gallery)} изображений; полнота цифровой копии не установлена.')
    if approved:
        notes = ['По ручной проверке пользователя: доступны только обложка и титульные страницы; полная цифровая копия не представлена.']
    extra = dict(raw_author_field=raw_author_field, volume_responsibility=volume_responsibility,
        series_title=series_title, publisher=publisher, library_code=library_code,
        bbk_groups=bbk_groups, series_description=series, volume_description=part,
        part=part_match[1] if part_match else '', pages=pages[1].strip(' .') if pages else '',
        original_holder=owner[1].strip() if owner else '',
        electronic_copy_source=copy_source[1].strip() if copy_source else '',
        gallery_urls=gallery, digital_url='',
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


def card_diagnostic(body):
 """Единый классификатор барьера; пустота выдачи не относится к карточке."""
 return _access.classify_stop.classify_response(
  200,"text/html",body,profile=_access.classify_stop.PRLIB)

def sanitize_card(body,url):
 s=BeautifulSoup(body,"html.parser")
 for node in s.select("script,style,input,textarea,button,footer,nav,meta,link,iframe,object,embed"):node.decompose()
 for node in s.select("header"):
  if not node.find_parent("main"):node.decompose()
 for form in s.select("form"):form.unwrap()
 for node in s.find_all(True):
  node.attrs={k:v for k,v in node.attrs.items() if k in ("class","id","href","title","colspan","rowspan","data-colorbox-gallery")}
  if node.has_attr("href"):
   href=urljoin(url,node["href"]);u=urlsplit(href)
   if u.scheme!="https" or u.netloc not in ("prlib.ru","www.prlib.ru") or any(re.search("token|session|cookie|password|auth|sid",k,re.I) for k,v in parse_qsl(u.query)):
    del node["href"]
   else:node["href"]=href
 return str(s).encode("utf-8")

def fetch_card(url):
    """Cached robots + exact card; no auth, redirects or unbounded retries."""
    ident = card_id(url)
    target = 'https://www.prlib.ru/item/' + ident
    robots_url = 'https://www.prlib.ru/robots.txt'
    report = dict(requests=[], ready_for_full_search=False, ready_for_import=False)
    def stop(reason):
        report['stop_reason'] = reason
        raise _access.AccessBlocked(reason, report)
    def get(address, allowed=None):
        if address not in (*_access.ROBOTS, target) or len(report['requests']) >= 3:
            stop('outside_card_request_scope')
        entry = dict(url=address, utc=datetime.now(timezone.utc).isoformat())
        report['requests'].append(entry)
        try:
            status, kind, body, location = _access.raw_fetch(address)
        except Exception as exc:
            entry['error_type'] = type(exc).__name__
            stop('transport_error')
        entry.update(status=status, content_type=kind)
        # Let robots_policy validate its single exact allowlisted redirect; card redirects remain blocked.
        if status != 200 and not (address in _access.ROBOTS and status in (301, 302, 307, 308)):
            stop('http_error_or_redirect')
        if len(body) > _access.LIMIT:
            stop('response_too_large')
        entry.update(received_bytes=len(body), received_sha256=hashlib.sha256(body).hexdigest())
        return status, kind, body, location, entry
    try:
        policy, robots, robots_url, cache_hit, robots_sha = _access.robots_policy(get)
    except _access.AccessBlocked as exc:
        stop(exc.reason)
    report.update(robots_text=robots, robots_cache='hit' if cache_hit else 'miss', robots_sha256=robots_sha)
    if not all(policy.can_fetch(agent, target) for agent in (_access.AGENT, UA, 'OpenAI', 'GPTBot')):
        stop('robots_disallow')
    rate = policy.request_rate(_access.AGENT)
    delay = max(3, policy.crawl_delay(_access.AGENT) or 0, rate.seconds/rate.requests if rate else 0)
    if delay > 60:
        stop('robots_delay_requires_rescheduling')
    time.sleep(delay)
    status, kind, body, location, entry = get(target)
    if 'html' not in kind.lower():
        stop('unexpected_content_type')
    diagnostic = card_diagnostic(body)
    report['classification'] = diagnostic
    if diagnostic['verdict'] == _access.classify_stop.REAL_BARRIER:
        stop(diagnostic['reason'])
    sanitized = sanitize_card(body, target)
    try:
        record = parse_card(sanitized, target)
    except Exception as exc:
        report['parser_error_type'] = type(exc).__name__
        stop('card_parser_error')
    record['extra']['evidence'].update(status=200, final_url=target,
        retrieved_at=report['requests'][-1]['utc'], original_sha256=hashlib.sha256(body).hexdigest(),
        tool='urllib.request', evidence_kind='sanitized_html')
    record['extra']['raw_detail_html'] = sanitized.decode('utf-8')
    soup = BeautifulSoup(sanitized, 'html.parser')
    linked = list(dict.fromkeys(a['href'] for a in soup.select('.field-name-field-book-bd a[href]')
        if re.fullmatch(r'https://(?:www\.)?prlib\.ru/item/\d+/?', a['href'])
        and not a['href'].rstrip('/').endswith('/' + ident)))
    record['extra']['linked_item_candidates'] = [dict(url=u, status='not_fetched_relation_unverified') for u in linked]
    record['extra']['review_issues'].append('linked_publication_verification_pending')
    report.update(status='parsed_candidate', stop_reason='')
    record['extra']['detail_access'] = report
    return record


def notion_row(rec):
    e = rec['extra']
    notes = list(e['notes'])
    # e['pages'] is the publication extent, not a map's page/folio locator.
    # Retain it in the original bibliography, never present it as a location.
    notes.append('Местоположение карты внутри издания (листы/страницы) не установлено; объём издания сохранён в библиографическом описании.')
    for label, key in [('Организация-издатель серии (по карточке)', 'publisher'), ('Место хранения оригинала', 'original_holder'),
                       ('Источник электронной копии', 'electronic_copy_source'), ('Часть', 'part')]:
        if e[key]:
            notes.append(label + ': ' + e[key])
    if e['review_issues']:
        notes.append('Требует проверки: ' + ', '.join(e['review_issues']))
    # Автор ушёл в extra.raw_author_field при review-скоупе — берём оттуда, не из rec['author'].
    author = e.get('raw_author_field') or e.get('volume_responsibility') or rec['author']
    # Язык: по преобладанию кириллицы над латиницей в описании.
    text = rec.get('description', '') or ''
    lang = 'Русский' if len(re.findall(r'[а-яё]', text, re.I)) >= len(re.findall(r'[a-z]', text, re.I)) else ''
    vol = re.search(r'Т\.\s*(\d+)', e.get('volume_description', '') or '')
    return {'Название источника': rec['title'], 'Автор / составитель': author,
        'Год создания (нижняя)': rec['year_from'], 'Год создания (верхняя)': rec['year_to'],
        'Место создания': rec['place'], 'Библиографическое описание': rec['description'],
        'Описание': e['volume_description'] or rec['description'],
        'Библиотечный шифр': e['library_code'],
        # Держатель оригинала («ГПИБ») и источник копии («ПБ») — из extra, ранее терялись.
        'Место хранения': e.get('original_holder', ''),
        'Организация оцифровки': e.get('electronic_copy_source', '') or rec.get('library_name', ''),
        'Листы / страницы': e.get('pages', ''),
        'Номер в серии': vol[1] if vol else e.get('part', ''),
        'Язык': lang,
        # Legacy digital_url held the catalogue URL, not a verified file.
        # Keep the original value in JSONL but never feed the Notion copy formula.
        'Ссылка на онлайн-архив': rec['url'], 'Путь / URL к файлу': '',
        # Только реальный файл-изображение; gallery_urls — превью, не файл (ловушка §5).
        'Прямая ссылка на файл изображения': e.get('direct_map_image_url', ''),
        'Примечания': '\n'.join(notes),
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
