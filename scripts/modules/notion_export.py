"""Offline common candidate export. No Notion client or network operations.

python scripts/modules/notion_export.py records_full.jsonl --output NEW_DIRECTORY
All adapters require human acceptance; matching headers never implies approval.
"""
import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA_PATH = Path(__file__).with_name('notion_schema.json')
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
PROPERTIES = SCHEMA['schema']
FIELDS = ['Название источника'] + [k for k, v in PROPERTIES.items()
    if k != 'Название источника' and v['type'] in ('text', 'title', 'number', 'url', 'select', 'multi_select', 'date')]
ADAPTER_VERSION = '2026-09-23.1-v1.6'

# Гейт против повторного заноса уже ОТКЛОНЁННЫХ решений (урок 2026-10-10: дедуп раньше
# сверялся только с уже ПРИНЯТЫМИ записями, не с журналом отклонённых — 4 записи ПрБ
# занеслись повторно, пришлось откатывать). Пока только ПрБ; расширять по мере находок.
_REJECTED_LEDGERS = {
    'prlib': Path(__file__).parents[2] / 'docs' / 'current' / 'prlib_rejected_ledger.json',
}
_REJECTED_CACHE = {}


def _rejected_info(source, item_id):
    if source not in _REJECTED_LEDGERS or not item_id:
        return None
    if source not in _REJECTED_CACHE:
        path = _REJECTED_LEDGERS[source]
        data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        data.pop('_meta', None)
        _REJECTED_CACHE[source] = data
    return _REJECTED_CACHE[source].get(item_id)


def validate(row):
    errors = []
    for key, value in row.items():
        if key not in FIELDS:
            errors.append('unsupported_property:' + key)
            continue
        if value in ('', None):
            continue
        spec = PROPERTIES[key]
        kind = spec['type']
        if kind == 'number':
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        elif kind == 'url':
            valid = isinstance(value, str) and urlsplit(value).scheme in ('https', 'http') and bool(urlsplit(value).netloc) and not any(c.isspace() for c in value)
        elif kind == 'select':
            valid = value in spec['options']
        elif kind == 'multi_select':
            valid = isinstance(value, str)
        else:
            valid = isinstance(value, str)
        if not valid:
            errors.append('invalid_type_or_value:' + key)
    if not row.get('Название источника'):
        errors.append('missing_title')
    if not row.get('Ссылка на онлайн-архив'):
        errors.append('missing_source_url')
    lo, hi = row.get('Год создания (нижняя)'), row.get('Год создания (верхняя)')
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
        errors.append('reversed_year_range')
    return errors


def normalize(entry, choices=None):
    rec = entry['record']
    extra = rec.get('extra') or {}
    source = entry.get('source') or rec.get('library_id', '')
    row = dict.fromkeys(FIELDS, '')
    issues = ['adapter_manual_review_pending']
    relations = []
    # The registry already provides common names. Their semantics remain subject
    # to a separate per-source review; no territory is inferred from the query.
    mapping = {'title': 'Название источника', 'url': 'Ссылка на онлайн-архив',
               'author': 'Автор / составитель', 'place': 'Место создания',
               'description': 'Описание'}
    for key, target in mapping.items():
        row[target] = rec.get(key) or ''
    row['Автор внесения'] = 'Агент'
    row['Статус приёмки'] = 'кандидат'
    adapter = 'registry_base'
    if source == 'prlib' and 'raw_bibliography_blocks' in extra:
        from prlib_card import notion_row
        row.update(notion_row(rec))
        adapter = 'prlib_detail_v16'
        holder = extra.get('original_holder', '')
        if holder:
            relations.append({'property': 'Архив хранения', 'source_label': holder,
                              'status': 'pending_existing_target_validation',
                              'basis': 'PRLIB card: original holder'})
            issues.append('archive_holder_relation_pending')
        issues.append('map_page_locator_not_established')
        issues.extend(extra.get('review_issues', []))
        if extra.get('source_type_relation'):
            relations.append({'property': 'Тип источника',
                              'target_url': extra['source_type_relation'],
                              'status': 'pending_target_validation'})
        item_m = re.search(r'/item/(\d+)', rec.get('url', ''))
        rejected = _rejected_info('prlib', item_m[1] if item_m else None)
        if rejected:
            issues.append('previously_rejected_do_not_import:' + rejected.get('reason', ''))
            row['Примечания'] = (str(row.get('Примечания') or '').rstrip() +
                '\n⚠️ Ранее ОТКЛОНЕНО: ' + rejected.get('reason', '') +
                ' — не вносить в Notion без явного пересмотра решения.').strip()
    elif source == 'permkrai' and 'permkrai_record' in extra:
        from permkrai_notion import notion_row
        original = dict(extra['permkrai_record'])
        if original.get('url') != rec.get('url'):
            raise ValueError('PERMKRAI nested record URL mismatch')
        decision = (choices or {}).get(rec['url'], {}).get('creation_year_review')
        if decision is not None:
            original['creation_year_review'] = decision
        row.update(notion_row(original))
        adapter = 'permkrai_detail'
        issues.extend(['map_page_locator_not_established', 'digital_copy_completeness_unverified'])
        source_detail = original.get('extra_json') or {}
        issues.extend(source_detail.get('review_issues', []))
        if source_detail.get('card_type'):
            relations.append({'property': 'Тип источника', 'source_label': source_detail['card_type'],
                              'status': 'candidate_manual_review_pending',
                              'basis': 'Permkrai detail type badge'})
        for tag in source_detail.get('tags_raw', []):
            if any(token in tag.casefold() for token in ('губерн', 'уезд', 'волост', 'област', 'край')):
                relations.append({'property': 'Охватываемая территория', 'source_label': tag,
                                  'status': 'candidate_manual_review_pending',
                                  'basis': 'Permkrai detail tag'})
    elif source == 'gpib':
        from export_gpib_notion import convert
        fields, adapter_issues = convert(entry, choices or {})
        row.update(fields)
        issues.extend(adapter_issues)
        adapter = 'gpib_detail'
    elif source == 'rgada' and rec.get('library_id') == 'rgada':
        from rgada_notion import convert
        row.update(convert({**rec, **extra}))
        adapter = 'rgada_inventory_v16'
        issues.extend(['inventory_level_not_single_map', 'source_specific_mapping_pending'])
    elif source == 'neb' and extra.get('raw_meta'):
        from neb_notion import convert
        row.update(convert(rec))
        adapter = 'neb_detail_v16'
        holder = rec.get('source_lib', '')
        if holder:
            relations.append({'property': 'Архив хранения', 'source_label': holder,
                              'status': 'pending_existing_target_validation',
                              'basis': 'NEB card: library-holder'})
            issues.append('archive_holder_relation_pending')
    elif source == 'rgia' and extra.get('rgia_detail'):
        from types import SimpleNamespace
        from rgia_notion import convert
        try:
            row.update(convert(SimpleNamespace(**rec)))
            adapter = 'rgia_detail'
            issues.extend([
                'map_page_locator_not_established',
                'digital_copy_completeness_unverified',
            ])
        except ValueError as exc:
            # Historical JSONL can predate detail classification. Preserve a
            # non-case node locally for review; never let it fail all CSV rows.
            adapter = 'rgia_detail_unclassified'
            issues.extend([
                'case_identity_unconfirmed',
                'rgia_detail_for_review',
                'source_specific_mapping_pending',
                'detail_adapter_error:' + str(exc),
            ])
    else:
        issues.append('source_specific_mapping_pending')
        # Generic year fields have different meanings in different adapters.
        # Preserve their raw values in JSONL until source semantics are reviewed.
        if rec.get('year_from') is not None or rec.get('year_to') is not None:
            issues.append('date_semantics_pending')
    scope_verdict = extra.get('scope_verdict') or {}
    if scope_verdict:
        row['Примечания'] = (str(row.get('Примечания') or '').rstrip() +
                            '\nScope §' + str(scope_verdict.get('rule', '')) + ': ' +
                            str(scope_verdict.get('evidence', ''))).strip()
        if scope_verdict.get('needs_human'):
            issues.append('scope_needs_human')
            row['Примечания'] += '\nТерриториальная релевантность требует проверки исследователем.'
    if not row.get('Язык'):
        row['Язык'] = 'Русский'
    if source == 'prlib' and 'raw_bibliography_blocks' not in extra:
        row['Описание'] = ''
        issues.append('detail_not_fetched')
    from library_dates import apply_dates
    date_evidence = apply_dates(entry, row, issues, choices or {})
    from cartographic_enrichment import enrich
    cartography = enrich(entry, row, issues, relations, choices or {})
    from administrative_level import apply_level
    archive_territory = entry.get("territory", "") if ((source == "rgada" and rec.get("library_id") == "rgada") or (source == "rgia" and extra.get("rgia_detail"))) else ""
    administrative_level = apply_level(row, PROPERTIES['Административный уровень']['options'], issues, territory=archive_territory)
    missing = [key for key in FIELDS if row.get(key) in ('', None)]
    errors = validate(row)
    return row, {'source': source, 'url': rec.get('url', ''),
                 'adapter': adapter, 'adapter_version': ADAPTER_VERSION,
                 'review_status': 'candidate', 'manual_review': 'pending',
                 'issues': issues, 'validation_errors': errors,
                 'empty_fields': missing, 'relations': relations,
                 'date_evidence': date_evidence,
                 'cartography': cartography,
                 'administrative_level': administrative_level,
                 'query_territory': entry.get('territory', ''),
                 'keyword': entry.get('keyword', ''),
                 'evidence': extra.get('evidence', entry.get('evidence', {}))}


def export(input_path, output, choices_path=None):
    input_path, output = Path(input_path), Path(output)
    raw = input_path.read_bytes()
    choices_raw = Path(choices_path).read_bytes() if choices_path else None
    choices = json.loads(choices_raw.decode('utf-8-sig')) if choices_raw else {}
    entries = [json.loads(line) for line in raw.decode('utf-8-sig').splitlines() if line.strip()]
    rows, audits = [], []
    seen = set()
    for line, entry in enumerate(entries, 1):
        row, audit = normalize(entry, choices)
        audit['input_record'] = line
        audit['input_path'] = str(input_path.resolve())
        if audit['url'] in seen:
            audit['issues'].append('duplicate_url_retained_for_review')
        seen.add(audit['url'])
        rows.append(row)
        audits.append(audit)
    output.mkdir(parents=True, exist_ok=False)
    # New directory only: never append a changed schema to an older CSV.
    with (output / 'notion_import.csv').open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with (output / 'notion_import.csv').open(encoding='utf-8-sig', newline='') as f:
        actual = list(csv.DictReader(f))
    expected = [{k: '' if row[k] is None else str(row[k]) for k in FIELDS} for row in rows]
    if actual != expected:
        raise ValueError('CSV roundtrip mismatch')
    report = {'schema_version': SCHEMA['version'],
              'schema_sha256': hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest(),
              'input_sha256': hashlib.sha256(raw).hexdigest(),
              'choices_sha256': hashlib.sha256(choices_raw).hexdigest() if choices_raw else None,
              'rows': len(rows), 'columns': len(FIELDS), 'roundtrip': 'passed',
              'ready_for_import': False, 'manual_gates': {
                  'card_to_csv': 'pending', 'csv_to_notion': 'pending', 'coverage': 'pending'},
              'records': audits}
    (output / 'export_review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--choices', type=Path)
    args = parser.parse_args()
    result = export(args.input, args.output, args.choices)
    print(json.dumps({k: result[k] for k in ('rows', 'columns', 'roundtrip', 'ready_for_import')}))
