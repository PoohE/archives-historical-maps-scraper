"""Offline extraction of GARF detail-card label/value fields."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from bs4 import BeautifulSoup, Tag


def parse_card(raw):
    soup = BeautifulSoup(raw.decode('cp1251'), 'html.parser')
    fields = {}
    for label in soup.select('b.middle'):
        key = ' '.join(label.get_text(' ', strip=True).split()).rstrip(':')
        sibling = label.next_sibling
        while sibling is not None and not isinstance(sibling, Tag):
            sibling = sibling.next_sibling
        if isinstance(sibling, Tag) and sibling.name == 'font' and 'black' in sibling.get('class', []):
            fields[key] = ' '.join(sibling.get_text(' ', strip=True).split())
    if not fields.get('Номер дела') or not fields.get('Заголовок дела'):
        raise ValueError('Not a recognized GARF case detail page')
    date = fields.get('Крайние даты дела', '')
    years = [int(y) for y in re.findall(r'\b(?:1[5-9]\d{2}|20\d{2})\b', date)]
    return dict(title=fields['Заголовок дела'], case_number=fields['Номер дела'],
                date_raw=date, year_from=min(years) if years else None,
                year_to=max(years) if years else None,
                date_basis='Крайние даты дела', sheets=fields.get('Количество листов', ''),
                annotation=fields.get('Аннотация', ''), notes=fields.get('Примечания', ''),
                raw_fields=fields, digital_copy_url='', author='', scale='',
                status='candidate', limitations=['No inference of missing metadata',
                'Archive/fund/inventory linkage and live search integration not implemented'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--html', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.html.read_bytes()
    result = parse_card(raw)
    result['provenance'] = dict(file=str(args.html.resolve()), sha256=hashlib.sha256(raw).hexdigest(),
                                encoding='windows-1251', parsed_at=datetime.now(timezone.utc).isoformat())
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
