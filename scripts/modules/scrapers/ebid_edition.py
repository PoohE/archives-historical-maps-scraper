"""Resolve an EBID source edition from card breadcrumbs with a bounded loader."""
import copy
import hashlib
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
try:
    from .ebid_card import parse_card
except ImportError:
    from ebid_card import parse_card


def normalized(text):
    return re.sub(r'[^а-яa-z0-9]', '', unicodedata.normalize('NFC', text).lower().replace('ё', 'е'))


def resolve_edition(card_html, card_url, load_html):
    """load_html(url) returns HTML; caller owns transport, rate and evidence storage.

    At most one page is loaded. Ambiguous or untrusted links are not followed.
    """
    result = copy.deepcopy(parse_card(card_html, card_url))
    source = normalized(result['linked_edition']['description'])
    soup = BeautifulSoup(card_html, 'html.parser')
    candidates = set()
    for anchor in soup.select('.crumbs a[href]'):
        label = normalized(anchor.get('title') or anchor.get_text(' ', strip=True))
        url = urljoin(card_url, anchor['href'])
        parts = urlsplit(url)
        if (parts.scheme == 'https' and parts.netloc == 'docs.historyrussia.org'
                and re.fullmatch(r'/ru/nodes/\d+(?:-[^/?#]+)?', parts.path)
                and not parts.query and not parts.fragment
                and len(label) >= 20 and source.startswith(label)):
            candidates.add(url)
    if len(candidates) != 1:
        result['review_issues'].append('edition_breadcrumb_missing_or_ambiguous')
        return result
    edition_url = candidates.pop()
    html = load_html(edition_url)
    fields = parse_card(html, edition_url)['raw_fields']
    title = fields.get('Название издания', '')
    year = fields.get('Год издания', '')
    if (len(normalized(title)) < 20 or not source.startswith(normalized(title))
            or not re.fullmatch(r'\d{4}', year)
            or (result['linked_edition']['year'] is not None
                and int(year) != result['linked_edition']['year'])):
        result['review_issues'].append('edition_identity_or_year_mismatch')
        return result
    result['linked_edition'].update(
        index_url=result['linked_edition']['url'], url=edition_url,
        title=title, subtitle=fields.get('Сведения, относящиеся к заглавию', ''),
        year=int(year), place=fields.get('Место издания', ''),
        publisher=fields.get('Издательство', ''),
        description=fields.get('Библиографическое описание', ''),
        responsibility=fields.get('Сведения об ответственности', ''),
        extent=fields.get('Физическая характеристика', ''),
        decoded_html_sha256=hashlib.sha256(html.encode('utf-8')).hexdigest(),
        status='candidate_identity_checked',
    )
    result['review_issues'] = [x for x in result['review_issues'] if x != 'edition_url_is_index_not_bibliographic_card']
    return result
