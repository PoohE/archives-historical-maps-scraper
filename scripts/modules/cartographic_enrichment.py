"""Shared scale conversion and conservative legend mapping for every source.

Accept dedicated scale text (not arbitrary full descriptions), or reviewed
main-map observations. Legend entries must be separately extracted labels.
No OCR, network, vocabulary creation or Notion writes happen here.
"""
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

VOCAB_PATH = Path(__file__).with_name('object_types.json')
VOCAB = json.loads(VOCAB_PATH.read_text(encoding='utf-8'))
VERST_SOURCE = 'https://www.kcsm.ru/starinnye-mery-dliny/70-starinnye-mery-dliny/985-iz-kolomny-li-kolomenskaya-versta.html'
INCH_SOURCE = 'https://www.nist.gov/pml/owm/si-units-length'


def clean(text):
    return ' '.join(text.lower().replace('ё', 'е').split()).strip(' .;:')


def convert_scale(text):
    """Return integer denominator and transparent calculation, or review reason.

    Supported: explicit 1:N; numeric km/m per cm; versts per explicitly
    English inch. Historical units use the declared conventional equivalents,
    not a claim of metrological precision for the original engraved sheet.
    """
    value = clean(text)
    value = re.sub(r'^масштаб\s*[:—-]?\s*', '', value)
    value = value.strip('[] ')
    ratio = re.fullmatch(r'1\s*:\s*(\d[\d\s]*)', value)
    formula, sources = '', []
    if ratio:
        denominator = Decimal(re.sub(r'\s', '', ratio[1]))
        formula = 'Явный численный масштаб: ' + text
    else:
        number = r'(\d+(?:[.,]\d+)?)'
        metric = re.fullmatch(r'в\s+1\s*см\s*' + number + r'\s*(км|м)', value)
        metric_reverse = re.fullmatch(number + r'\s*(км|м)\s+в\s+1\s*см', value)
        # Конечная точка сокращения («вер.», «саж.») может быть уже срезана clean() (strip
        # по краям строки), если единица стоит последним словом — точка опциональна.
        verst_unit = r'вер(?:ст(?:а|ы)?)?\.?'
        sazhen_unit = r'саж(?:ен(?:ей|ь|и)?)?\.?'
        one = r'(?:1|одн(?:ом|ой|а))\s+'
        inch_unit = r'(?:английском\s+)?дюйм(?:е|ах)?'
        verst = re.fullmatch(number + r'\s*' + verst_unit + r'\s+в\s+(?:' + one + r')?' + inch_unit, value)
        verst_reverse = re.fullmatch(r'в\s+(?:' + one + r')?' + inch_unit + r'\s*' + number + r'\s*' + verst_unit, value)
        # "N саженей в (1/одном английском) дюйме" — стандартная единица межевых/
        # крупномасштабных планов (план дачи ГМ: 100 саж/дюйм = 1:8400); 1 сажень = 84 дюйма ровно.
        sazhen = re.fullmatch(number + r'\s*' + sazhen_unit + r'\s+в\s+(?:' + one + r')?' + inch_unit, value)
        sazhen_reverse = re.fullmatch(r'в\s+(?:' + one + r')?' + inch_unit + r'\s*' + number + r'\s*' + sazhen_unit, value)
        if metric or metric_reverse:
            match = metric or metric_reverse
            n = Decimal(match[1].replace(',', '.'))
            factor = 1000 if match[2] == 'км' else 1
            denominator = n * factor / Decimal('0.01')
            formula = f'{n} × {factor} м / 0.01 м = {denominator}'
        elif verst or verst_reverse:
            n = Decimal((verst or verst_reverse)[1].replace(',', '.'))
            denominator = n * Decimal('1066.8') / Decimal('0.0254')
            formula = f'{n} × 1066.8 м / 0.0254 м = {denominator}'
            sources = [VERST_SOURCE, INCH_SOURCE]
        elif sazhen or sazhen_reverse:
            n = Decimal((sazhen or sazhen_reverse)[1].replace(',', '.'))
            denominator = n * Decimal('84')
            formula = f'{n} саж. × 84 дюйм/саж. = {denominator}'
            sources = [VERST_SOURCE, INCH_SOURCE]
        else:
            return None, {'reason': 'ambiguous_units_or_unsupported_scale', 'raw': text}
    if denominator <= 0 or denominator != denominator.to_integral_value():
        return None, {'reason': 'nonpositive_or_noninteger_denominator', 'raw': text,
                      'calculation': formula}
    return int(denominator), {'raw': text, 'calculation': formula,
                              'unit_sources': sources, 'unit_basis': 'declared conventional conversion'}


def enrich(entry, row, issues, relations, choices):
    rec = entry['record']
    extra = rec.get('extra') or {}
    choice = choices.get(rec['url'], {})
    observations = extra.get('image_observations', []) + choice.get('image_observations', [])
    audit = {'scales': [], 'legend': [], 'questions': [],
             'vocabulary_version': VOCAB['version'],
             'vocabulary_sha256': hashlib.sha256(VOCAB_PATH.read_bytes()).hexdigest()}

    def question(code, text, evidence=None):
        issues.append(code)
        audit['questions'].append({'code': code, 'question': text, 'evidence': evidence})

    scales = []
    if row.get('Оригинальный масштаб'):
        scales.append({'value': row['Оригинальный масштаб'], 'locator': 'adapter.Original scale', 'url': rec['url']})
    for key in ('scale_original', 'scale_raw'):
        if extra.get(key):
            scales.append({'value': extra[key], 'locator': 'extra.' + key, 'url': rec['url']})
    for item in observations:
        if item.get('field') != 'scale_original':
            continue
        # Historical GPIB approved scale observations predate the scope key.
        scope = item.get('scope', 'main_map' if entry.get('source') == 'gpib' else '')
        if item.get('status') == 'approved' and scope == 'main_map':
            scales.append({**item, 'url': item.get('url', rec['url'])})
        else:
            question('scale_reading_pending', 'Подтвердите чтение масштаба и принадлежность основной карте.', item)
    values = set()
    unresolved = False
    for item in scales:
        denominator, evidence = convert_scale(item['value'])
        audit['scales'].append({**item, **evidence, 'denominator': denominator})
        if denominator is None:
            unresolved = True
            question('scale_conversion_pending', 'Уточните единицы или численный масштаб: ' + item['value'], item)
        else:
            values.add(denominator)
    if scales and not row.get('Оригинальный масштаб'):
        row['Оригинальный масштаб'] = '; '.join(dict.fromkeys(s['value'] for s in scales))
    if len(values) == 1 and not unresolved:
        value = next(iter(values))
        if row.get('Масштаб (знаменатель)') in ('', None, value):
            row['Масштаб (знаменатель)'] = value
        else:
            question('scale_conflict', 'Численный масштаб расходится с текстовым. Какое значение верно?', audit['scales'])
    elif len(values) > 1:
        question('scale_conflict', 'Найдено несколько масштабов. Какой относится к основной карте?', audit['scales'])
    if audit['scales']:
        row['Примечания'] = '\n'.join(filter(None, [row.get('Примечания'),
            'Расчёт масштаба: ' + '; '.join(dict.fromkeys(s.get('calculation', s.get('reason', '')) for s in audit['scales']))]))
    else:
        issues.append('scale_evidence_missing')

    legends = extra.get('legend_observations', []) + choice.get('legend_observations', [])
    if not legends:
        issues.append('legend_evidence_missing')
    mapped = set()
    for observation in legends:
        raw = observation.get('text', '')
        if raw:
            label = 'Легенда (' + observation.get('text_kind', 'текст источника') + '): '
            row['Описание'] = '\n\n'.join(filter(None, [row.get('Описание'), label + raw]))
        if (observation.get('status') != 'approved' or observation.get('scope') != 'main_map'
                or not observation.get('url') or not observation.get('locator')):
            question('legend_reading_pending', 'Подтвердите текст легенды основной карты.', observation)
            continue
        for label in observation.get('entries', []):
            targets = [t for t in VOCAB['types'] if clean(label) in {clean(x) for x in [t['title']] + t['aliases']}]
            item = {'label': label, 'targets': targets, 'source': observation}
            audit['legend'].append(item)
            if len(targets) != 1:
                question('legend_mapping_pending', 'К какому типу справочника отнести «' + label + '»? Можно оставить только в описании.', item)
                continue
            target = targets[0]
            if target['url'] not in mapped:
                relations.append({'property': 'Типы отображаемых объектов',
                    'target_url': target['url'], 'target_title': target['title'],
                    'data_source': VOCAB['data_source'], 'status': 'candidate_manual_review_pending',
                    'basis': 'exact title or explicit alias; evidence in cartography.legend'})
                mapped.add(target['url'])
    return audit
