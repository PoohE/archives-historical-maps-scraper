import urllib.request, json, sys
sys.stdout.reconfigure(encoding='utf-8')

TOKEN = 'ntn_y31296007024sMESWX0yDMKxiuzjIe5gJ3gSe3CQN0x2D5'
DB_ID = 'a9e98744-faf8-493f-93e5-cb14c0374fd8'

# Структура базы
req = urllib.request.Request(
    f'https://api.notion.com/v1/databases/{DB_ID}',
    headers={'Authorization': f'Bearer {TOKEN}', 'Notion-Version': '2022-06-28'},
    method='GET')
with urllib.request.urlopen(req) as r:
    db = json.load(r)

print('=== ПОЛЯ БАЗЫ АРХИВЫ ===')
for fname, fdata in db['properties'].items():
    print(f'  [{fdata["type"]}]  {fname}')

# Записи
print('\n=== ЗАПИСИ ===')
req2 = urllib.request.Request(
    f'https://api.notion.com/v1/databases/{DB_ID}/query',
    data=json.dumps({'page_size': 100}).encode(),
    headers={'Authorization': f'Bearer {TOKEN}', 'Notion-Version': '2022-06-28',
             'Content-Type': 'application/json'},
    method='POST')
with urllib.request.urlopen(req2) as r:
    data = json.load(r)

results = data.get('results', [])
print(f'Всего: {len(results)}')
print()
for page in results:
    props = page['properties']
    # Ищем title-поле
    title_val = ''
    url_val = ''
    type_val = ''
    for fname, fdata in props.items():
        if fdata['type'] == 'title':
            parts = fdata.get('title', [])
            if parts:
                title_val = parts[0].get('plain_text', '')
        elif fdata['type'] == 'url':
            url_val = fdata.get('url') or ''
        elif fdata['type'] == 'select' and fname != 'Тип':
            pass
    # Тип
    t = props.get('Тип', {})
    if t.get('type') == 'select' and t.get('select'):
        type_val = t['select']['name']

    print(f'{type_val:20s}  {title_val:40s}  {url_val}')
