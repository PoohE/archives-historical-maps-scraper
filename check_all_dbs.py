import urllib.request, json, sys
sys.stdout.reconfigure(encoding='utf-8')
TOKEN = 'ntn_y31296007024sMESWX0yDMKxiuzjIe5gJ3gSe3CQN0x2D5'
dbs = {
    'Источники (Каталог)':  '5ead971c-b9bd-4bc2-90d8-73d0841b1f93',
    'Архивы':               'a9e98744-faf8-493f-93e5-cb14c0374fd8',
    'Типы источников':      'a5432419-e808-423f-9d76-f9fa9575bc34',
    'Серийные массивы':     '44443811-6a1a-42fb-bb3a-e424202c8ef0',
    'Виды анализа':         '6573d34c-9442-4d75-a168-70a0eb8e294e',
    'Исслед. задачи':       '833a324d-dc36-4995-a971-487d7e68371d',
    'Типы объектов':        'f2c1fe00-60d2-4875-bc4c-5d17762d1638',
}
for name, db_id in dbs.items():
    req = urllib.request.Request(
        f'https://api.notion.com/v1/databases/{db_id}/query',
        data=json.dumps({'page_size': 1}).encode(),
        headers={'Authorization': f'Bearer {TOKEN}',
                 'Notion-Version': '2022-06-28',
                 'Content-Type': 'application/json'},
        method='POST')
    try:
        with urllib.request.urlopen(req) as r:
            d = json.load(r)
        total = 'есть записи' if d.get('results') else 'пусто'
        print(f"OK   {name} ({total})")
    except Exception as e:
        print(f"ERR  {name}: {e}")
