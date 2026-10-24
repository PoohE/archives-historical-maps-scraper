"""Parse only labelled GAKO case attributes from saved HTML; no transport."""
import re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup

def parse(html,url):
 u=urlsplit(url)
 if u.scheme!='https' or u.hostname!='archive.admoblkaluga.ru' or not re.fullmatch(r'/object/\d+',u.path): raise ValueError('Unexpected case URL')
 s=BeautifulSoup(html,'html.parser'); fields={}
 for n in s.select('.attribute-container'):
  label=n.select_one('.attribute-title')
  if not label: continue
  key=label.get_text(' ',strip=True)
  value=' '.join(x.get_text(' ',strip=True) if hasattr(x,'get_text') else str(x).strip() for x in label.next_siblings).strip().lstrip(':').strip()
  value=' '.join(value.split())
  if key in fields and fields[key]!=value: raise ValueError('Conflicting field: '+key)
  fields[key]=value
 for key in ('Заголовок','Номер фонда','Опись','Номер дела'):
  if not fields.get(key): raise ValueError('Missing case field: '+key)
 years=[]
 for key in ('Точный год начала','Точный год окончания'):
  v=fields.get(key,'')
  if v and not re.fullmatch(r'\d{4}',v): raise ValueError('Invalid explicit year')
  years.append(int(v) if v else None)
 if all(x is not None for x in years) and years[0]>years[1]: raise ValueError('Reversed dates')
 row={'Название источника':fields['Заголовок'],'Фонд':fields['Номер фонда'],'Опись':fields['Опись'],'Единица хранения':fields['Номер дела'],
 'Год создания (нижняя)':years[0],'Год создания (верхняя)':years[1],'Листы / страницы':fields.get('Количество листов',''),
 'Описание':'\n'.join(k+': '+v for k,v in fields.items()),'Ссылка на онлайн-архив':url,'Автор внесения':'Агент',
 'Примечания':'Хранитель: '+fields.get('Архив','')+'; даты из явных полей дела; хронологические рамки: '+fields.get('Хронологические рамки','')+'; '+fields.get('Дело отсканировано полностью?','')}
 if fields.get('Язык','').lower()=='русский': row['Язык']='Русский'
 return row,{'raw_fields':fields,'url':url,'status':'candidate','scan_statement':fields.get('Дело отсканировано полностью?','')}
