"""Offline EBID card extraction; no network or relevance filtering."""
import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def parse_card(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    fields, links = {}, {}
    for row in soup.select('tr[class*="record_of_type_"]'):
        cells = row.find_all('td', recursive=False)
        if len(cells) != 2:
            continue
        key = cells[0].get_text(' ', strip=True).rstrip(':')
        values = cells[1].select('[class*="value_of_type_"]')
        fields[key] = '\n'.join(unicodedata.normalize('NFC', x.get_text(' ', strip=True)) for x in values)
        links[key] = [urljoin(url, a['href']) for a in cells[1].select('a[href]')]
    if not fields:
        raise ValueError('Unrecognized EBID metadata layout')
    title = fields.get('Название документа', '')
    depicted = re.search(r'\bна\s+(\d{4})\s+год', title)
    edition = fields.get('Источник документа', '')
    # Only a terminal publication year, never the historical span in the title.
    edition_year = re.search(r',\s*(\d{4})\s*\.?\s*$', edition)
    config = {}
    for script in soup.find_all('script'):
        text = script.string or script.get_text()
        if 'initDocview({' in text:
            config, _ = json.JSONDecoder().raw_decode(text.split('initDocview(', 1)[1].lstrip())
            break
    original_links = [urljoin(url, p['downloadUrl']) for p in config.get('pages', []) if p.get('downloadUrl')]
    issues = []
    if not edition:
        issues.append('linked_edition_not_established')
    if links.get('Источник документа') and '/indexes/' in links['Источник документа'][0]:
        issues.append('edition_url_is_index_not_bibliographic_card')
    if not original_links:
        issues.append('original_download_url_not_provided')
    return {
        'title': title, 'raw_fields': fields, 'field_links': links,
        'bibliography': fields.get('Библиографическое описание', ''),
        'publication_statement': fields.get('Сведения о публикации', ''),
        'linked_edition': {'required_check': True, 'description': edition,
                           'url': next(iter(links.get('Источник документа', [])), ''),
                           'year': int(edition_year[1]) if edition_year else None},
        'date_raw': fields.get('Дата документа', ''),
        'depicted_year': int(depicted[1]) if depicted else None,
        'creation_year': None,
        'author': fields.get('Автор', ''),
        'viewer_url': url if config.get('pages') else '',
        'original_download_urls': original_links,
        'viewer_config': config,
        'scale_denominator': None,
        'review_issues': issues,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--html', required=True, type=Path)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    raw = args.html.read_bytes()
    result = parse_card(raw.decode('utf-8'), args.url)
    result['provenance'] = {'url': args.url, 'html_path': str(args.html.resolve()),
                            'sha256': hashlib.sha256(raw).hexdigest(),
                            'parsed_at': datetime.now(timezone.utc).isoformat(),
                            'method': 'saved_html', 'status': 'candidate'}
    with args.output.open('x', encoding='utf-8') as out:
        json.dump(result, out, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
