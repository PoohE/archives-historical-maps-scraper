"""Create a sanitised offline input, retaining provenance of the original HTML."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit, urljoin
from bs4 import BeautifulSoup, Comment

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'скрины архивов/Калужская областная научная библиотека им. В.Г. Белинского.html'
DEST = ROOT / 'output/kaluga_handoff_20260914_v1/inputs'
raw = SOURCE.read_bytes()
soup = BeautifulSoup(raw, 'lxml')
for node in soup.find_all(['script','style','input','textarea','iframe','template']):
    node.decompose()
for comment in soup.find_all(string=lambda t:isinstance(t, Comment)):
    comment.extract()
allowed = {'S21COLORTERMS','I21DBN','P21DBN','S21STN','S21REF','S21FMT','S21CNR','C21COM','S21ALL','USES21ALL'}
for node in soup.find_all(True):
    href = node.get('href', '') if node.name == 'a' else ''
    label = node.get_text(' ', strip=True)
    node.attrs = {}
    if node.name == 'a' and label == 'Прямая ссылка на документ':
        url = urlsplit(urljoin('http://217.15.203.140:81/', href))
        if url.hostname != '217.15.203.140':
            raise ValueError('Unexpected catalogue host')
        query = [(k,v) for k,v in parse_qsl(url.query) if k.upper() in allowed]
        node['href'] = urlunsplit((url.scheme,url.netloc,url.path,urlencode(query),''))
clean = str(soup).encode('utf-8')
assert b'Z21ID' not in clean and b'Z21ID' not in clean.upper()
with (DEST / 'catalogue.html').open('xb') as stream:
    stream.write(clean)
meta = dict(original_path=str(SOURCE), original_sha256=hashlib.sha256(raw).hexdigest(),
    sanitized_sha256=hashlib.sha256(clean).hexdigest(),
    transformation='Removed scripts/forms values/comments/attributes; retained catalogue links with an explicit query allowlist',
    source_kind='user_saved_html', live_links_checked=False)
with (DEST / 'provenance.json').open('x', encoding='utf-8') as stream:
    json.dump(meta,stream,ensure_ascii=False,indent=2)
assert SOURCE.read_bytes() == raw
print('Sanitised input created; original unchanged')
