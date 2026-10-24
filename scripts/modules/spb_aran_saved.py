"""Saved ranar.spb.ru document metadata, distinct from parent case metadata."""
import re
from urllib.parse import urlsplit,urljoin
from bs4 import BeautifulSoup

def parse(html,url):
 u=urlsplit(url)
 if u.scheme!='https' or u.hostname!='ranar.spb.ru' or not re.fullmatch(r'/docs/\d+',u.path) or u.query or u.fragment: raise ValueError('Expected document URL, not parent case')
 s=BeautifulSoup(html,'html.parser'); title=s.select_one('.page-title'); title=title.get_text(' ',strip=True) if title else ''
 fields={}
 for n in s.select('p'):
  label=n.find('b',recursive=False)
  if not label: continue
  key=label.get_text(' ',strip=True).rstrip(':')
  if key not in ('Шифр','Виды документов','Крайние даты','Размер','Материалы'): continue
  value=' '.join(x.get_text(' ',strip=True) if hasattr(x,'get_text') else str(x).strip() for x in label.next_siblings)
  value=' '.join(value.split())
  if key in fields and fields[key]!=value: raise ValueError('Conflicting field: '+key)
  fields[key]=value
 cipher=fields.get('Шифр',''); m=re.fullmatch(r'Ф\.\s*(\d+)\s+Оп\.\s*(\d+)\s+Д\.\s*(\d+)\s+Л\.\s*(.+)',cipher)
 if not title or not m: raise ValueError('Missing title or document-level cipher with leaf')
 date=fields.get('Крайние даты',''); year=re.fullmatch(r'\[?(\d{4})\]?',date)
 annotation='\n'.join(n.get_text(' ',strip=True) for n in s.select('.fund-review-text'))
 parents=[urljoin(url,a['href']) for a in s.select('.breadcrumbs a[href]') if re.fullmatch(r'/cases/\d+',a['href'])]
 row={'Название источника':title,'Фонд':m[1],'Опись':m[2],'Единица хранения':m[3],'Листы / страницы':'Л. '+m[4],
 'Год создания (верхняя)':int(year[1]) if year else None,'Год создания (нижняя)':None,
 'Описание':'\n'.join(k+': '+v for k,v in fields.items())+'\nАннотация: '+annotation,
 'Ссылка на онлайн-архив':url,'Автор внесения':'Агент',
 'Примечания':'Хранитель: СПбФ АРАН. Шифр документа: '+cipher+'; крайние даты дословно: '+date+'; год из карточки сохранён как кандидат в верхнем поле, нижняя дата не установлена; скобки требуют сохранения неопределённости. Размер без установленных единиц: '+fields.get('Размер','')+'; родительское дело: '+'; '.join(parents)}
 if annotation.startswith('Рукописная карта'): row['Техника исполнения']='Рукописная'
 return row,{'record_id':u.path.rsplit('/',1)[-1],'record_kind':'document_within_case','raw_fields':fields,'annotation':annotation,'parent_case_urls':parents,'date_raw':date,'year_candidate':int(year[1]) if year else None,'date_uncertainty':'bracketed_catalogue_date' if '[' in date else 'unspecified','url':url,'status':'candidate'}
