"""Sanitize the saved detail panel and seal the new package once."""
import hashlib
import json
import shutil
import sys
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'output/rgia_handoff_20260914_v1'
if (OUT/'manifest.json').exists(): raise SystemExit('Already sealed')
sys.path.insert(0,str(ROOT/'scripts/modules/scrapers'))
from searcher_rgia import _parse_object_page
source=ROOT/'скрины архивов/РГИА_380_39_623.html'; raw=source.read_bytes()
source_soup=BeautifulSoup(raw,'html.parser')
clean=BeautifulSoup('<html><head><meta charset="utf-8"></head><body></body></html>','html.parser')
for node in source_soup.select('.dataLine[id]') or source_soup.select('.dataLine'):
    for bad in node.select('script,style,input,textarea'): bad.decompose()
    for tag in [node,*node.find_all(True)]:
        tag.attrs={k:v for k,v in tag.attrs.items() if k=='class'}
    clean.body.append(node)
url='https://fgurgia.ru/object/4844881'
# Reparse original because the soup above was modified during sanitization.
if _parse_object_page(str(BeautifulSoup(raw,'html.parser')),url)!=_parse_object_page(str(clean),url):
    raise ValueError('Sanitization changed parsed fields')
(OUT/'inputs/card.html').write_text(str(clean),encoding='utf-8')
(OUT/'inputs/provenance.json').write_text(json.dumps(dict(original_source=str(source),original_sha256=hashlib.sha256(raw).hexdigest(),source_url=url,transformation='dataLine labels/values only; parser equivalence checked'),ensure_ascii=False,indent=2),encoding='utf-8')
for name in ('notion_export.py','notion_schema.json','rgia_notion.py'):
    shutil.copyfile(ROOT/'scripts/modules'/name,OUT/'code'/name)
shutil.copyfile(ROOT/'scripts/modules/scrapers/searcher_rgia.py',OUT/'code/searcher_rgia.py')
files={p.relative_to(OUT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.rglob('*')) if p.is_file()}
(OUT/'manifest.json').write_text(json.dumps(dict(source='rgia',dependencies={'requests':'2.33.1','beautifulsoup4':'4.14.3','lxml':'6.0.2','soupsieve':'2.8.3'},files=files),ensure_ascii=False,indent=2),encoding='utf-8')
print('Manifest SHA256',hashlib.sha256((OUT/'manifest.json').read_bytes()).hexdigest())
