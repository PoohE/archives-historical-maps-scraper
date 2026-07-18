import urllib.request, json, sys
sys.stdout.reconfigure(encoding='utf-8')

TOKEN = 'ntn_y31296007024sMESWX0yDMKxiuzjIe5gJ3gSe3CQN0x2D5'

req = urllib.request.Request(
    'https://api.notion.com/v1/search',
    data=json.dumps({'filter': {'value': 'database', 'property': 'object'}, 'page_size': 50}).encode(),
    headers={'Authorization': f'Bearer {TOKEN}', 'Notion-Version': '2022-06-28', 'Content-Type': 'application/json'},
    method='POST')

with urllib.request.urlopen(req) as r:
    data = json.load(r)

results = data.get('results', [])
print(f"Доступных баз: {len(results)}")
print()
for db in results:
    title = ''
    for t in db.get('title', []):
        title += t.get('plain_text', '')
    print(f"ID: {db['id']}")
    print(f"   Название: {title}")
    print()
