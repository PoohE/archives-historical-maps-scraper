"""Apply the user's record-specific locator decision to a new offline CSV."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'output/rnb18_offline_20260914_053716_24c19af7/candidate'
OUTPUT = ROOT / 'output/rnb18_locator_review_20260914_v2'
URL = 'https://nlr.ru/rlin/rusmarc.php?numer=328&database=karpgr18'


def main():
    paths = [SOURCE / n for n in ('notion_import.csv', 'record.json', 'export_review.json')]
    raw = {p.name: p.read_bytes() for p in paths}
    hashes = {k: hashlib.sha256(v).hexdigest() for k, v in raw.items()}
    with paths[0].open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    record = json.loads(raw['record.json'])
    assert len(rows) == 1 and rows[0]['Ссылка на онлайн-архив'] == URL
    assert record['record_num'] == '329' and record['source_url'] == URL
    assert 'N 23' in record['edition_description']
    assert 'Вверху справа цифра "23"' in record['notes']
    assert rows[0]['Листы / страницы'] == ''
    before = dict(rows[0])
    rows[0]['Листы / страницы'] = 'Карта № 23 в атласе'
    assert [k for k in fields if before[k] != rows[0][k]] == ['Листы / страницы']
    report = json.loads(raw['export_review.json'])
    report['empty_fields'] = [k for k in report['empty_fields'] if k != 'Листы / страницы']
    report['manual_decisions'] = [{
        'property': 'Листы / страницы', 'value': rows[0]['Листы / страницы'],
        'status': 'approved', 'reviewer': 'user', 'date': '2026-09-14',
        'source_url': URL, 'record_num': '329',
        'evidence': ['300$a: Вверху справа цифра "23"', '300$a: Из изд. ... 1800, N 23'],
        'scope': 'this record only; map number, not page number',
    }]
    report['correction_version'] = 'rnb18-locator-review-20260914-v2'
    report['parent_input'] = str(SOURCE)
    report['parent_sha256'] = hashes
    report['ready_for_import'] = False
    # Existing gate states remain pending: one field decision is not full approval.
    OUTPUT.mkdir(exist_ok=False)
    with (OUTPUT / 'notion_import.csv').open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with (OUTPUT / 'notion_import.csv').open(encoding='utf-8-sig', newline='') as stream:
        assert list(csv.DictReader(stream)) == rows
    (OUTPUT / 'record.json').write_bytes(raw['record.json'])
    for p in paths:
        assert hashlib.sha256(p.read_bytes()).hexdigest() == hashes[p.name]
    report['correction_checks'] = {'only_locator_changed': True, 'roundtrip': 'passed', 'parents_unchanged': True}
    (OUTPUT / 'export_review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS: one reviewed field changed; 66-column CSV; original files unchanged')


if __name__ == '__main__':
    main()
