"""Inventory-level mapping; never implies one inventory is one map."""
import re
from urllib.parse import quote, urlsplit, parse_qs


def convert(rec):
    if rec.get('library_id') != 'rgada' or not rec.get('fund_number') or not rec.get('list_number'):
        raise ValueError('Missing RGADA inventory identity')
    url = urlsplit(rec['url'])
    if url.hostname != 'rgada.info' or url.path != '/poisk/index2.php' or not parse_qs(url.query).get('str'):
        raise ValueError('Unrecognized inventory URL')
    date = rec.get('years', '').strip()
    m = re.fullmatch(r'(1[5-9]\d{2}|20\d{2})(?:\s*[-–—]\s*(1[5-9]\d{2}|20\d{2}))?', date)
    if m:
        lo, hi = int(m[1]), int(m[2] or m[1])
    else:
        lo, hi = rec.get('year_from'), rec.get('year_to')
    if lo is not None and lo > hi:
        lo = hi = None
    notes = '\n'.join([
        'Уровень описания: опись, не отдельная карта.',
        'Фонд: ' + rec.get('fund_name', ''),
        'Хранилище: ' + rec.get('repository', ''),
        'Годы дословно: ' + date,
        'Смысл дат: крайние даты материалов описи, не каждого листа.',
        'Количество дел: ' + rec.get('case_count', ''),
        'Смотреть: просмотр описи, не цифровая копия карты.',
        'Масштаб/авторы/период серии не перенесены без однозначного сопоставления.'])
    title = rec.get('title') or ('Ф. ' + rec['fund_number'] + ', оп. ' + rec['list_number'] + ': ' + rec.get('list_name', ''))
    return {'Название источника': title,
            'Фонд': rec['fund_number'], 'Опись': rec['list_number'],
            'Описание': rec.get('annotation', '') or rec.get('description', ''), 'Примечания': notes,
            'Год создания (нижняя)': lo, 'Год создания (верхняя)': hi,
            'Ссылка на онлайн-архив': quote(rec['url'], safe=':/?&=%'),
            'Путь / URL к файлу': '', 'Прямая ссылка на файл изображения': '',
            'Автор внесения': 'Агент'}
