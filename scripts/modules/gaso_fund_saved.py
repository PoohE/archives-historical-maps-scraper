"""GASO fund metadata and unvisited inventory links; never produces map rows."""
import re
from urllib.parse import urlsplit,urljoin,parse_qsl
from bs4 import BeautifulSoup

def parse_fund(html,source_url):
 soup=BeautifulSoup(html,'html.parser'); root=soup.select_one('.entry-content')
 if root is None: raise ValueError('Missing fund content')
 fields={}; inventories=[]
 for label in root.select('p > strong'):
  key=label.get_text(' ',strip=True).rstrip(':'); container=label.parent
  value=container.find_next_sibling()
  if not value or value.select_one('strong'): continue
  text=value.get_text(' ',strip=True)
  if key in fields and fields[key]!=text: raise ValueError('Conflicting fund field: '+key)
  fields[key]=text
  if key=='Описи':
   for a in value.select('a'):
    title=' '.join(a.get_text(' ',strip=True).split()); num=re.match(r'^Оп\.\s*(\d+)\.',title)
    if not num: continue
    href=a.get('href',''); url=urljoin(source_url,href) if href else ''; u=urlsplit(url); state='observed_unfetched'
    if not href: state='missing_href_in_supplied_HTML'; url=''
    elif u.scheme not in ('http','https') or not u.hostname or u.username or u.password: state='unsupported_or_credential_URL'; url=''
    elif any(k.lower() not in ('id','page','download','file') for k,v in parse_qsl(u.query)):
     state='query_requires_review_not_recorded'; url=''
    inventories.append({'number':num[1],'label':title,'url':url,'link_state':state,'locator':'entry-content section Описи a','fetched':False})
 match=re.fullmatch(r'Ф\.\s*(\d+)\.',fields.get('Шифр',''))
 if not match or match[1]!='259' or not fields.get('Полное наименование'): raise ValueError('Not the expected fund 259')
 count=fields.get('Количество описей','')
 if not count.isdigit(): raise ValueError('Missing inventory count')
 return {'record_kind':'fund_description','fund_number':match[1],'title':fields['Полное наименование'],
 'fund_chronology_raw':fields.get('Хронология',''),'inventory_count_declared':int(count),'inventories':inventories,
 'raw_fields':fields,'annotation':fields.get('Аннотация',''),'source_url':source_url,'case_rows_created':0,'map_rows_created':0,'status':'candidate'}
