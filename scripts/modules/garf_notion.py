"""Scalar GARF detail mapping with explicit listing identity; no network."""
import json
from urllib.parse import urlsplit,parse_qs
from garf_card import parse_card

def convert(raw,listing):
 d=parse_card(raw); url=listing.get('url',''); u=urlsplit(url)
 if u.hostname!='opisi.garf.su' or u.scheme not in ('http','https') or u.path!='/default.asp' or parse_qs(u.query).get('v')!=['7']:
  raise ValueError('Untrusted or incomplete detail URL')
 if d['case_number']!=listing.get('delo_num') or not listing.get('fond_num') or not listing.get('opisi_num'):
  raise ValueError('Missing/mismatched archive identity')
 row={'Название источника':d['title'],'Фонд':listing['fond_num'],'Опись':listing['opisi_num'],'Единица хранения':d['case_number'],
 'Год создания (нижняя)':d['year_from'],'Год создания (верхняя)':d['year_to'],
 'Листы / страницы':d['sheets'],'Ссылка на онлайн-архив':url,'Автор внесения':'Агент',
 'Описание':'\n'.join(k+': '+v for k,v in d['raw_fields'].items()),
 'Примечания':'Хранитель: ГАРФ. Фонд/опись и URL — сохранённая строка описи. Крайние даты дела: '+d['date_raw']+'; даты рубрики не применяются к делу. Скан, автор и масштаб не установлены.'}
 d['listing']=listing
 return row,d
