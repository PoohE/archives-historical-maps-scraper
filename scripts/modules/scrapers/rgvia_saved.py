"""Offline RGVIA search-table export. No network or Notion writes."""
import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

HEADERS = ['Номер дела', 'Номер описи', 'Номер фонда', 'Заголовок дела',
           'Дата дела начальная', 'Дата дела конечная', 'Кол-во листов', 'Примечание']
FIELDS = ['Название источника', 'Архив хранения', 'Фонд', 'Опись',
          'Единица хранения', 'Год создания (нижняя)', 'Год создания (верхняя)',
          'Листы / страницы', 'Примечания', 'Ссылка на онлайн-архив', 'Автор внесения']
SEARCH_URL = 'http://xn--90ag.xn--80adcv1b.xn--p1ai/search'


def year(value):
    if not value:
        return ''
    return str(datetime.strptime(value, '%d.%m.%Y').year)


def parse(raw):
    soup = BeautifulSoup(raw, 'html.parser')
    table = soup.select_one('#cases-grid table')
    if table is None:
        raise ValueError('Missing cases table: not a verified empty result')
    headers = [x.get_text(' ', strip=True) for x in table.select('thead th')]
    if headers != HEADERS:
        raise ValueError('Unexpected table headers')
    query = soup.select_one('#Search_query')
    output, evidence = [], []
    for n, tr in enumerate(table.select('tbody tr'), 1):
        cells = [x.get_text(' ', strip=True) for x in tr.find_all('td', recursive=False)]
        if len(cells) != 8:
            raise ValueError(f'Unexpected cell count at row {n}')
        case, inventory, fund, title, start, end, sheets, note = cells
        if not all((case, inventory, fund, title)):
            raise ValueError(f'Missing identification at row {n}')
        lower, upper = year(start), year(end)
        if start and end and datetime.strptime(start, '%d.%m.%Y') > datetime.strptime(end, '%d.%m.%Y'):
            raise ValueError(f'Reversed case dates at row {n}')
        output.append(dict(zip(FIELDS, [title, 'РГВИА', fund, inventory, case,
            lower, upper, sheets, '; '.join(x for x in [note,
            'Годы — крайние даты дела, не подтверждённая датировка вложенной карты.'] if x),
            SEARCH_URL, 'Агент'])))
        evidence.append({'row': n, 'raw': dict(zip(HEADERS, cells)),
            'has_row_links': bool(tr.select('a[href]')),
            'cartographic_term_candidate': bool(re.search(r'\b(?:карт(?:а|ы|у|е|ой|ами|ах)?|план(?:ы|а|ов)?|атлас\w*|схем\w*)\b', title, re.I)),
            'review_status': 'pending', 'territorial_relevance': 'not_checked'})
    if not output:
        raise ValueError('No rows: empty-result layout not validated')
    return output, {'query': query.get('value', '') if query else None,
        'search_url': SEARCH_URL, 'method': 'POST', 'rows': evidence}


def run(source, out):
    raw = source.read_bytes()
    rows, audit = parse(raw)
    out.mkdir(parents=True, exist_ok=False)
    csv_path = out / 'rgvia_notion_review.csv'
    with csv_path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with csv_path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        restored = list(reader)
        if reader.fieldnames != FIELDS or restored != rows:
            raise ValueError('CSV roundtrip failed')
    audit.update(source=str(source.resolve()), sha256=hashlib.sha256(raw).hexdigest(),
        checked_at=datetime.now(timezone.utc).isoformat(), row_count=len(rows),
        csv_roundtrip='passed', output_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        limitations=['One saved page only; no network/pagination',
                      'All rows retained for review, not an approved map corpus',
                      'Archive relation must be resolved to an existing Notion page at import',
                      'No Notion writes; no CSRF tokens copied from source HTML'])
    (out / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'rows': len(rows), 'csv': str(csv_path), 'roundtrip': 'passed'}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--html', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New directory only')
    args = parser.parse_args()
    run(args.html, args.output)
