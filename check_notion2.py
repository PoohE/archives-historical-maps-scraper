import urllib.request, json, sys
sys.stdout.reconfigure(encoding='utf-8')

TOKEN = 'ntn_s31296007022KFFNVBEBJoCJ2BPnPnyE7nEV6VIbh3f8kN'

# Ищем все базы данных доступные интеграции
req = urllib.request.Request(
    'https://api.notion.com/v1/search',
    data=json.dumps({'filter': {'value': 'database', 'property': 'object'}, 'page_size': 20}).encode(),
    headers={
        'Authorization': f'Bearer {TOKEN}',
        'Notion-Version': '2022-06-28',
        'Content-Type': 'application/json'
    },
    method='POST'
)
with urllib.request.urlopen(req) as r:
    data = json.load(r)

results = data.get('results', [])
print(f"Доступных баз данных: {len(results)}")
for db in results:
    title = ''
    t = db.get('title', [])
    if t:
        title = t[0].get('plain_text', '')
    print(f"  ID: {db['id']}  |  {title}")
