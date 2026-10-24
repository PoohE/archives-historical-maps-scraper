"""Apply the approved main-map creation year; keep original pilot unchanged."""
import copy
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/modules'))
from permkrai_notion import notion_row
from notion_export import validate

SOURCE = ROOT / 'output/permkrai_offline_20260914_063356_79a33ca8/candidate'
OUTPUT = ROOT / 'output/permkrai_date_review_20260914_v2'


def main():
    paths = [SOURCE / n for n in ('notion_import.csv', 'record.json', 'export_review.json')]
    raw = {p.name:p.read_bytes() for p in paths}
    hashes = {k:hashlib.sha256(v).hexdigest() for k,v in raw.items()}
    record = json.loads(raw['record.json'])
    assert record['url'] == 'https://lib.permkrai.ru/node/37840'
    text = 'составлена и дополнена по новейшим сведениям членом Уральского Общества Любителей Естествознания Ив. Я. Кривощековым в 1909 г.'
    assert text in record['bibliography']
    record['creation_year_review'] = dict(status='approved', reviewer='user', date='2026-09-14',
        scope='main_map', year=1909, source_url=record['url'], locator='bibliography: statement of compilation', text=text)
    mapped = notion_row(record)
    assert mapped['Год создания (верхняя)'] == 1909
    # Rejected/unrelated evidence must not promote a date.
    for key, value in [('status','candidate'), ('source_url','https://example.invalid/'), ('year',True), ('scope','inset')]:
        bad = copy.deepcopy(record)
        bad['creation_year_review'][key] = value
        assert notion_row(bad)['Год создания (верхняя)'] == ''
    with paths[0].open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    assert len(rows) == 1
    original = dict(rows[0])
    for key, value in mapped.items():
        rows[0][key] = '' if value is None else str(value)
    assert set(k for k in fields if rows[0][k] != original[k]) == {'Год создания (верхняя)', 'Примечания'}
    assert rows[0]['Библиографическое описание'] == original['Библиографическое описание']
    assert '15 февраля 1911' in rows[0]['Библиографическое описание']
    assert not validate(mapped)
    report = json.loads(raw['export_review.json'])
    report['manual_decisions'] = [record['creation_year_review']]
    report['empty_fields'] = [k for k in report['empty_fields'] if k != 'Год создания (верхняя)']
    report['correction_version'] = 'permkrai-date-review-20260914-v2'
    report['parent_input'] = str(SOURCE)
    report['parent_sha256'] = hashes
    report['ready_for_import'] = False
    report['correction_checks'] = dict(upper_year=1909, bibliography_unchanged=True,
        no_autograph_field_added=True, rejected_evidence_tests=4)
    OUTPUT.mkdir(exist_ok=False)
    with (OUTPUT / 'notion_import.csv').open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with (OUTPUT / 'notion_import.csv').open(encoding='utf-8-sig', newline='') as stream:
        assert list(csv.DictReader(stream)) == rows
    for p in paths:
        assert hashlib.sha256(p.read_bytes()).hexdigest() == hashes[p.name]
    for name, value in [('record.json',record), ('export_review.json',report)]:
        (OUTPUT / name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: 1909 upper year; bibliography unchanged; 4 negative tests; CSV roundtrip; parents unchanged')


if __name__ == '__main__':
    main()
