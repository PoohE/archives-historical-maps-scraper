"""Local OCR evidence for missing catalogue fields; never writes accepted metadata.

Requires existing EasyOCR models. Downloads disabled. ROI is a main-map region,
selected by a reviewer to exclude insets and viewer controls.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def run(source, output, region, source_url):
    import easyocr
    source=Path(source); output=Path(output)
    if output.exists(): raise FileExistsError(output)
    reader=easyocr.Reader(['ru','en'],gpu=False,download_enabled=False)
    result=reader.readtext(str(source),detail=1,paragraph=False)
    blocks=[]
    excluded=0
    left,top,right,bottom=region
    for box,txt,score in result:
        box=[[float(x),float(y)] for x,y in box]
        if not all(left<=x<=right and top<=y<=bottom for x,y in box):
            excluded+=1
            continue
        blocks.append(dict(text=txt,confidence=float(score),box=box))
    candidates=[]
    for i,b in enumerate(blocks):
        for m in re.finditer(r'(?<!\d)1\s*[:：]\s*([\d\s]{3,})',b['text']):
            number=int(re.sub(r'\s','',m[1]))
            if number>1:
                candidates.append(dict(field='Масштаб (знаменатель)',value=number,block=i,status='candidate'))
        if re.search(r'состав|автор|издан|издател|типограф|литограф',b['text'],re.I):
            candidates.append(dict(field='authorship_or_publication_requires_review',value=b['text'],block=i,status='candidate'))
    output.mkdir(parents=True,exist_ok=False)
    record=dict(source=str(source.resolve()),source_url=source_url,
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        processed_at=datetime.now(timezone.utc).isoformat(),
        engine='EasyOCR',version=easyocr.__version__,downloads_enabled=False,
        main_map_roi=list(region),roi_basis='human-selected region excluding inset',
        blocks=blocks,excluded_blocks=excluded,candidates=candidates,
        status='candidate',limitations=['OCR confidence is not factual certainty',
        'Do not infer scale denominator from screenshot dimensions or linear bar',
        'Does not automatically detect insets, authors or publication roles',
        'No catalogue/Notion writes; missing-field reconciliation not yet integrated'])
    (output/'ocr_candidates.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(blocks=len(blocks),excluded=excluded,candidates=len(candidates),output=str(output)),ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',required=True);p.add_argument('--output',required=True)
    p.add_argument('--roi',type=int,nargs=4,required=True)
    p.add_argument('--source-url',required=True)
    a=p.parse_args();run(a.image,a.output,a.roi,a.source_url)
