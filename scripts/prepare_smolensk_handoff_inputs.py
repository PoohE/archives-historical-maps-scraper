"""Copy only public bibliographic fragments to the offline package."""
import hashlib
import json
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'output/smolensk_handoff_20260914_v1/inputs'
sources = [('soil','soil_cover_v3'), ('settlements','settlements_1904_v4')]
provenance = []
for name, folder in sources:
    source = ROOT / 'output/smolensk_saved_20260913' / folder / 'original.html'
    raw = source.read_bytes()
    soup = BeautifulSoup(raw, 'lxml')
    target = BeautifulSoup('<html><head><meta charset="utf-8"></head><body></body></html>', 'lxml')
    marc = soup.select_one('div.marc')
    title = next((n for selector in ('h1.v2', '#description h1', 'h1')
                  for n in soup.select(selector) if n.get_text(strip=True)), None)
    if title:
        target.body.append(title.extract())
    if marc:
        target.body.append(marc.extract())
    for a in soup.select('a[href]'):
        href = a['href']
        if '/bd/books/' in href and href.endswith('.pdf'):
            a.attrs = {'href': href}
            target.body.append(a.extract())
    for node in target.find_all(True):
        node.attrs = {k:v for k,v in node.attrs.items() if k in ('class','href','charset')}
    clean = str(target).encode('utf-8')
    with (DEST / (name + '.html')).open('wb') as f:
        f.write(clean)
    provenance.append(dict(file=name+'.html', original_path=str(source),
        original_sha256=hashlib.sha256(raw).hexdigest(),
        sanitized_sha256=hashlib.sha256(clean).hexdigest(),
        transformation='Only heading, div.marc and explicit PDF anchors; no page scripts or session parameters'))
    assert source.read_bytes() == raw
with (DEST / 'provenance.json').open('w',encoding='utf-8') as f:
    json.dump(provenance,f,ensure_ascii=False,indent=2)
print('Two bibliographic fragments saved; originals unchanged')
