"""Bounded read-only diagnostics; no retries, login, redirects or TLS bypass."""
import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup

ROUTES = {
    'neb': ['https://rusneb.ru/catalog/000200_000018_RU_NLR_cart_8878/'],
    'rosarchive': ['https://online.archives.ru/search/',
                   'https://online.archives.ru/search/10000000001014/10000001292014/10000005356014/10000416784014/'],
    'aran': ['https://aran.kaisa.ru/',
             'https://aran.kaisa.ru/search?type=custom&searchObjectType=DOCUMENTS&p3.v=Калуж&p3.c=12&p3.a=4894'],
    'goskatalog': ['https://goskatalog.ru/portal/'],
}

def probe(item):
    source, urls = item
    result = []
    for url in urls:
        entry = dict(source=source, url=url, checked_at=datetime.now(timezone.utc).isoformat(),
                     transport='requests ' + requests.__version__)
        try:
            r = requests.get(url, timeout=(12, 20), allow_redirects=False)
            entry.update(http_status=r.status_code, bytes=len(r.content),
                         sha256=hashlib.sha256(r.content).hexdigest())
            soup = BeautifulSoup(r.content, 'html.parser')
            entry['title'] = soup.title.get_text(' ', strip=True) if soup.title else ''
            entry['object_links'] = len(soup.select('a[href*="/object/"]'))
            entry['form_count'] = len(soup.select('form'))
            entry['state'] = 'http_response_not_search_validation'
            if r.status_code in (401, 403, 429):
                entry['state'] = 'access_stop'
        except requests.RequestException as exc:
            entry.update(state='transport_error', error_type=type(exc).__name__)
        result.append(entry)
        if entry['state'] in ('transport_error', 'access_stop'):
            break
        time.sleep(2)
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; use a new path')
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = [r for group in pool.map(probe, ROUTES.items()) for r in group]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)
    print(json.dumps(rows, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
