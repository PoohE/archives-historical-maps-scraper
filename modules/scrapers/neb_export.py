"""Offline export of one saved NEB card; no browser, network or Notion writes."""
import argparse
import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
try:
    from .searcher_neb import parse_card_html
except ImportError:
    from searcher_neb import parse_card_html


def notion_row(r):
    e=r.extra
    notes=['Издательство: '+r.publisher, 'Библиотека-хранитель: '+r.source_lib,
           'Характеристики врезок исключены из рабочих полей; исходные сведения сохранены отдельно.',
           'PDF: ссылка извлечена из HTML, скачивание не проверено.']
    if e.get('visual_review'):
        notes.append('Линейный масштаб основной карты установлен вручную по изображению, не OCR.')
    return {'Название источника':r.title,'Автор / составитель':r.author,
        'Год создания (нижняя)':r.year_from,'Год создания (верхняя)':r.year_to,
        'Место создания':r.place,'Библиотечный шифр':'Код НЭБ: '+r.identifier,
        'Библиографическое описание':r.bibliography,'Описание':r.description,
        'Путь / URL к файлу':r.url_viewer,'Прямая ссылка на файл изображения':r.url_download,
        'Ссылка на онлайн-архив':r.url,'Оригинальный масштаб':e.get('scale_original',''),
        'Масштаб (знаменатель)':e.get('scale_denominator'),
        'Листы / страницы':e.get('extent',''),'Язык':e.get('language',''),
        'Примечания':'\n'.join(notes),'Автор внесения':'Агент'}


def export_saved(source,url,output):
    raw=Path(source).read_bytes()
    rec=parse_card_html(raw.decode('utf-8'),url)
    if rec is None or not rec.extra.get('raw_meta'):
        raise ValueError('Not a complete NEB detail card')
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    (output/'original.html').write_bytes(raw)
    record=asdict(rec)
    record['provenance']={'local_path':str(Path(source).resolve()),'sha256':hashlib.sha256(raw).hexdigest(),
                          'source_url':url,'mode':'offline saved HTML','http_status':None}
    (output/'record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    row=notion_row(rec)
    with (output/'notion_import.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(row)); w.writeheader(); w.writerow(row)
    return rec


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--html',required=True); p.add_argument('--url',required=True); p.add_argument('--output',required=True)
    a=p.parse_args(); r=export_saved(a.html,a.url,a.output)
    print(json.dumps({'rows':1,'review':r.extra['review_issues']},ensure_ascii=False))
