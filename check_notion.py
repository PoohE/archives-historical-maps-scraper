import urllib.request, json, sys
sys.stdout.reconfigure(encoding='utf-8')

TOKEN = 'ntn_s31296007022KFFNVBEBJoCJ2BPnPnyE7nEV6VIbh3f8kN'
DB_ID = 'decdf63c-6f64-4852-ada2-65e72c79d9bc'

# Запрашиваем все записи (до 100)
all_results = []
has_more = True
cursor = None

while has_more:
    body = {'page_size': 100}
    if cursor:
        body['start_cursor'] = cursor
    req = urllib.request.Request(
        f'https://api.notion.com/v1/databases/{DB_ID}/query',
        data=json.dumps(body).encode(),
        headers={
            'Authorization': f'Bearer {TOKEN}',
            'Notion-Version': '2022-06-28',
            'Content-Type': 'application/json'
        },
        method='POST'
    )
    with urllib.request.urlopen(req) as r:
        data = json.load(r)
    all_results.extend(data.get('results', []))
    has_more = data.get('has_more', False)
    cursor = data.get('next_cursor')

print(f"Всего записей в базе: {len(all_results)}")
print()

# Показываем поля первой записи для понимания структуры
if all_results:
    print("Поля базы:")
    for k, v in all_results[0]['properties'].items():
        print(f"  - {k} ({v['type']})")
    print()

print("Первые 20 записей (Название | Год):")
for i, p in enumerate(all_results[:20], 1):
    props = p['properties']
    title = ''
    year = ''
    for k, v in props.items():
        if v['type'] == 'title' and v['title']:
            title = v['title'][0]['plain_text']
        if 'год' in k.lower() and v['type'] == 'number' and v.get('number'):
            year = str(v['number'])
    print(f"{i:3}. {year:<6} {title[:70]}")
