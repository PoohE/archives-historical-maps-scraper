"""Strict offline reader for one UTF-8 MARC21/ISO2709 record. No network."""
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def decode_record(raw):
    if len(raw)<25 or raw[-1:]!=b'\x1d' or int(raw[:5])!=len(raw):
        raise ValueError('Truncated, multiple or invalid MARC record')
    if raw[9:10]!=b'a' or raw[10:12]!=b'22' or raw[20:23]!=b'450':
        raise ValueError('Only UTF-8 MARC21 with standard directory widths supported')
    base=int(raw[12:17])
    if base<25 or base>=len(raw) or raw[base-1:base]!=b'\x1e' or (base-25)%12:
        raise ValueError('Invalid MARC directory')
    fields=[]
    intervals=[]
    for i in range(24,base-1,12):
        tag=raw[i:i+3].decode('ascii')
        length=int(raw[i+3:i+7]); offset=int(raw[i+7:i+12])
        start=base+offset; end=start+length
        if not tag.isdigit() or length<1 or end>len(raw)-1 or raw[end-1:end]!=b'\x1e':
            raise ValueError('Invalid MARC field boundary')
        intervals.append((start,end))
        content=raw[start:end-1].decode('utf-8')
        if int(tag)<10:
            fields.append(dict(tag=tag,value=content))
        else:
            if len(content)<2 or content[2:3]!='\x1f':
                raise ValueError('Invalid MARC subfields')
            subs=[]
            for item in content[3:].split('\x1f'):
                if not item: raise ValueError('Empty subfield')
                subs.append([item[0],item[1:]])
            fields.append(dict(tag=tag,indicators=content[:2],subfields=subs))
    intervals.sort()
    if not intervals or intervals[0][0]!=base or intervals[-1][1]!=len(raw)-1 or any(a[1]!=b[0] for a,b in zip(intervals,intervals[1:])):
        raise ValueError('Overlapping or missing MARC bytes')
    return fields


def parse(raw):
    fields=decode_record(raw)
    def values(tag,code):
        return [v for f in fields if f['tag']==tag for k,v in f.get('subfields',[]) if k==code]
    def one(tag,code):
        vs=values(tag,code); return vs[0] if len(vs)==1 else ''
    ids=[f['value'] for f in fields if f['tag']=='001']
    if len(ids)!=1 or not ids[0].isdigit() or not one('245','a'):
        raise ValueError('Missing or ambiguous record identity/title')
    date=one('260','c') or one('264','c')
    year=int(date.strip('[] .')) if re.fullmatch(r'\[?\d{4}\]?[ .]*',date) else None
    scale=one('034','b')
    marks=[]
    for f in fields:
        if f['tag']=='852':
            marks.append(' '.join(v for k,v in f['subfields'] if k in ('b','j')))
    # 130 is a uniform heading, never a personal-author field.
    author=one('100','a') or one('110','a') or one('245','c')
    notes=values('500','a')
    issues=['digital_copy_not_verified','access_not_verified','source_type_relation_requires_review']
    if year is None: issues.append('publication_year_requires_review')
    if not author: issues.append('author_not_stated')
    if any('1-го Меридиана' in x for x in notes): issues.append('second_meridian_unresolved')
    return dict(record_id=ids[0],title=one('245','a'),author=author,
        heading=one('130','a'), year=year,date_literal=date,
        place=one('260','a') or one('264','a'),publisher=one('260','b'),
        manufacturer=one('260','f'),scale_original=one('255','a'),
        scale_denominator=int(scale) if scale.isdigit() else None,
        extent=one('300','a'),colour=one('300','b'),size=one('300','c'),
        bbk=values('084','a'),shelfmark='; '.join(marks),notes=notes,
        subjects=values('650','a'),territories=values('651','a'),
        holder=values('852','a'),fields=fields,review_issues=issues)


def notion_row(r,url):
    notes=list(r['notes'])+['Выходная дата дословно: '+r['date_literal'],
        'Изготовитель: '+r['manufacturer'],'Размеры дословно: '+r['size'],
        'Цветность оригинала: '+r['colour'],
        'Цифровая копия и статус доступа не подтверждены этой MARC-записью.']
    description='\n'.join([r['title'],r['scale_original'],r['place']+' '+r['date_literal'],r['manufacturer'],r['extent']+' '+r['colour']+' '+r['size']]+r['notes']+r['subjects'])
    return {'Название источника':r['title'],'Автор / составитель':r['author'],
        'Год создания (нижняя)':r['year'],'Год создания (верхняя)':r['year'],
        'Место создания':r['place'],'Библиотечный шифр':'Шифр хранения: '+r['shelfmark']+'\nББК: '+'; '.join(r['bbk']),
        'Оригинальный масштаб':r['scale_original'],'Масштаб (знаменатель)':r['scale_denominator'],
        'Описание':description,'Листы / страницы':r['extent'],
        'Нулевой меридиан':'','Ссылка на онлайн-архив':url,
        'Путь / URL к файлу':'','Прямая ссылка на файл изображения':'',
        'Примечания':'\n'.join(notes),'Автор внесения':'Агент'}


def export_saved(source,output):
    source,output=Path(source),Path(output)
    raw=source.read_bytes(); r=parse(raw)
    # RSL's downloaded record name is the catalogue identifier, distinct from MARC 001.
    if not re.fullmatch(r'010\d{8}',source.stem) or source.stem[3:]!=r['record_id'].lstrip('0'):
        # Compare as integers because MARC 001 has a different zero-padding width.
        if not re.fullmatch(r'010\d{8}',source.stem) or int(source.stem[3:])!=int(r['record_id']):
            raise ValueError('Filename does not match the MARC identifier')
    url='https://search.rsl.ru/ru/record/'+source.stem+'/'
    r['provenance']=dict(local_path=str(source.resolve()),sha256=hashlib.sha256(raw).hexdigest(),
        parsed_at=datetime.now(timezone.utc).isoformat(),source_url=url,http_status=None,
        input_kind='user_downloaded_marc21',locator='MARC21 directory/tags/subfields')
    output.mkdir(parents=True,exist_ok=False)
    (output/source.name).write_bytes(raw)
    (output/'record.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    row=notion_row(r,url)
    with (output/'notion_import.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(row)); w.writeheader(); w.writerow(row)
    return r
