"""Проверяет пропуски в полях базы Архивы и выводит таблицу."""
import urllib.request, json, sys
sys.stdout.reconfigure(encoding='utf-8')

TOKEN = 'ntn_y31296007024sMESWX0yDMKxiuzjIe5gJ3gSe3CQN0x2D5'
DB_ID  = 'a9e98744-faf8-493f-93e5-cb14c0374fd8'

req = urllib.request.Request(
    f'https://api.notion.com/v1/databases/{DB_ID}/query',
    data=json.dumps({'page_size': 100}).encode(),
    headers={'Authorization': f'Bearer {TOKEN}',
             'Notion-Version': '2022-06-28',
             'Content-Type': 'application/json'},
    method='POST')
with urllib.request.urlopen(req) as r:
    data = json.load(r)

pages = data.get('results', [])
total = len(pages)

# Поля для проверки
FIELDS = ['Название', 'Тип', 'Сайт', 'Аббревиатура',
          'Город', 'Приоритет', 'Ключевые фонды', 'Особенности',
          'Веб-поиск', 'Email', 'Телефон', 'Адрес']

missing: dict[str, list[str]] = {f: [] for f in FIELDS}

for page in pages:
    props = page['properties']
    # Название
    t = props.get('Название', {}).get('title', [])
    name = t[0]['plain_text'] if t else '(без названия)'

    def is_empty(prop):
        if prop is None: return True
        ptype = prop.get('type')
        if ptype == 'title':   return not prop.get('title')
        if ptype == 'rich_text': return not prop.get('rich_text')
        if ptype == 'select':  return prop.get('select') is None
        if ptype == 'url':     return not prop.get('url')
        if ptype == 'email':   return not prop.get('email')
        if ptype == 'phone_number': return not prop.get('phone_number')
        return False

    for field in FIELDS:
        if is_empty(props.get(field)):
            missing[field].append(name)

print(f'Всего записей: {total}\n')
print(f'{"Поле":<30} {"Пропуски":>8}  Примеры')
print('-' * 80)
total_with_gaps = set()
for field in FIELDS:
    names = missing[field]
    if names:
        examples = ', '.join(names[:3]) + ('…' if len(names) > 3 else '')
        print(f'{field:<30} {len(names):>8}  {examples}')
        total_with_gaps.update(names)
    else:
        print(f'{field:<30} {"—":>8}')

print('-' * 80)
print(f'{"Строк с хотя бы одним пропуском":<30} {len(total_with_gaps):>8}')
