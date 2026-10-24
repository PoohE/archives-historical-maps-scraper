"""Build pinned offline inputs; run only before handing off this new package."""
import hashlib
import json
import shutil
import sys
from pathlib import Path
from bs4 import BeautifulSoup
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/rgvia_handoff_20260914_v1'
if (OUT / 'manifest.json').exists():
    raise SystemExit('Already sealed; refusing rebuild')
sys.path.insert(0, str(ROOT / 'scripts/modules/scrapers'))
from rgvia_saved import parse
source = ROOT / 'скрины архивов/РГВИА _ Электронные описи.html'
raw = source.read_bytes()
soup = BeautifulSoup(raw, 'html.parser')
clean = BeautifulSoup('<html><head><meta charset="utf-8"></head><body><div id="cases-grid"></div></body></html>', 'html.parser')
table = soup.select_one('#cases-grid table')
for node in table.select('script,style,input,textarea'):
    node.decompose()
for node in table.find_all(True):
    node.attrs = {}
table.attrs = {}
clean.select_one('#cases-grid').append(table)
query = clean.new_tag('input', id='Search_query')
query['value'] = soup.select_one('#Search_query').get('value', '')
clean.body.append(query)
sanitized = str(clean).encode('utf-8')
if parse(raw) != parse(sanitized):
    raise ValueError('Sanitization changed parsed values or provenance')
(OUT / 'inputs/table.html').write_bytes(sanitized)
(OUT / 'inputs/provenance.json').write_text(json.dumps(dict(original_source=str(source), original_sha256=hashlib.sha256(raw).hexdigest(), sanitized_sha256=hashlib.sha256(sanitized).hexdigest(), transformation='Retained table and search query only; removed hidden/session fields; parsed outputs equal.'), ensure_ascii=False, indent=2), encoding='utf-8')
for name in ('notion_schema.json','notion_export.py'):
    shutil.copyfile(ROOT / 'scripts/modules' / name, OUT / 'code' / name)
shutil.copyfile(ROOT / 'scripts/modules/scrapers/rgvia_saved.py', OUT / 'code/rgvia_saved.py')
files = {p.relative_to(OUT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.rglob('*')) if p.is_file()}
(OUT / 'manifest.json').write_text(json.dumps(dict(source='rgvia', dependencies={'beautifulsoup4':'4.14.3','soupsieve':'2.8.3'}, files=files), ensure_ascii=False, indent=2), encoding='utf-8')
print('Sealed', OUT)
print('Manifest SHA256', hashlib.sha256((OUT / 'manifest.json').read_bytes()).hexdigest())
