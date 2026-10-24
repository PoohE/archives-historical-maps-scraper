"""Labelled museum-card extraction from saved HTML; no API/OCR claims."""
from urllib.parse import urljoin,urlsplit,parse_qs
from bs4 import BeautifulSoup

def parse(html,url):
 u=urlsplit(url)
 if u.scheme!='https' or u.hostname!='goskatalog.ru' or not u.fragment.startswith('/collections?'): raise ValueError('Unexpected catalogue URL')
 s=BeautifulSoup(html,'html.parser'); fields={}
 for n in s.select('.card__attributes-container'):
  label=n.select_one('b'); value=n.select_one('.col-sm-8')
  if not label or not value: continue
  key=label.get_text(' ',strip=True).rstrip(':'); text=value.get_text(' ',strip=True)
  if key in fields and fields[key]!=text: raise ValueError('Conflicting field: '+key)
  fields[key]=text
 title=s.select_one('.title-group .card__text'); title=title.get_text(' ',strip=True) if title else ''
 if not title or not fields.get('Номер в Госкаталоге','').isdigit(): raise ValueError('Missing museum card identity')
 place=s.select_one('.card__place'); repository=place.get_text(' ',strip=True) if place else ''
 notes=[n.get_text(' ',strip=True) for n in s.select('.card__text') if not n.find_parent(class_='title-group')]
 image_urls=[]
 for n in s.select('img[data-zoom-image]'):
  v=urljoin(url,n['data-zoom-image']); parsed=urlsplit(v)
  if parsed.scheme=='https' and parsed.hostname=='goskatalog.ru' and parsed.path.startswith('/muzfo-imaginator/rest/images/original/'):
   if v not in image_urls: image_urls.append(v)
 image=image_urls[0] if len(image_urls)==1 else ''
 catalogue_id=parse_qs(u.fragment.split('?',1)[1]).get('id',[''])[0]
 description='\n'.join(k+': '+v for k,v in fields.items())+'\n'+'\n'.join(notes)
 row={'Название источника':title,'Библиотечный шифр':fields.get('Инвентарный номер',''),'Описание':description,
 'Ссылка на онлайн-архив':url,'Прямая ссылка на файл изображения':image,'Автор внесения':'Агент',
 'Примечания':'Хранитель: '+repository+'; ID страницы: '+catalogue_id+'; номер Госкаталога: '+fields['Номер в Госкаталоге']+'; номер КП: '+fields.get('Номер по КП (ГИК)','')+'; период создания дословно: '+fields.get('Период создания','')+'; размер дословно: '+fields.get('Размер','')+'; URL изображения извлечён из HTML, сетевой доступ не проверен.'}
 return row,{'title':title,'raw_fields':fields,'free_text':notes,'repository':repository,'catalogue_page_id':catalogue_id,'catalogue_number':fields['Номер в Госкаталоге'],'image_urls':image_urls,'status':'candidate','url':url}
