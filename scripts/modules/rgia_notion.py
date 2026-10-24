"""Scalar mapping of a complete RGIA case card, not a fund description."""
import re


def _card_text(record):
    """Return source-card text only; analytic notes belong elsewhere."""
    saved = getattr(record, 'card_text', '').strip()
    if saved:
        return saved
    fields = (
        ('Шифр', record.fund_code),
        ('Название фонда', record.fund_name),
        ('Крайние даты', record.date_raw),
        ('Количество листов', record.sheets),
        ('Библиографический источник', record.bib_source),
        ('Примечание', record.notes),
    )
    # Historical records_full.jsonl preserved parsed card values, but not all
    # raw detail JSON. Their fallback is explicitly limited to those values.
    return '\n'.join(f'{label}: {value}' for label, value in fields if value)


def convert(r):
    code = re.fullmatch(r'Ф\.\s*(\d+)\s+Оп\.\s*(\d+)\s+Д\.\s*(\d+(?:-\d+)?)', r.fund_code)
    if not code or not r.title:
        raise ValueError('Missing unambiguous case identity/title')
    if r.year_from and r.year_to and r.year_from > r.year_to:
        raise ValueError('Reversed dates')
    conditional_anchor = (
        r.year_from == r.year_to == 1900
        and "конец" in r.date_raw.casefold()
        and "начал" in r.date_raw.casefold()
    )
    date_note = (
        "Условная нормализация даты: «конец XIX — начало XX века» = 1900."
        if conditional_anchor
        else "Годы — крайние даты дела, не даты фонда."
    )
    url_download = getattr(r, 'url_download', '')
    url_image = getattr(r, 'url_image', '')
    scan_note = (
        'Ссылки на цифровой файл сохранены из RGIA detail: '
        + ', '.join(label for label, value in (('downloadLink', url_download), ('imageUrl', url_image)) if value)
        + '.'
        if url_download or url_image
        else 'Скан, масштаб, автор и условия доступа этой карточкой не установлены.'
    )
    return {
        'Название источника': r.title,
        'Фонд': code[1],
        'Опись': code[2],
        'Единица хранения': code[3],
        'Год создания (нижняя)': r.year_from,
        'Год создания (верхняя)': r.year_to,
        'Листы / страницы': r.sheets,
        'Описание': _card_text(r),
        'Ссылка на онлайн-архив': r.url,
        'Прямая ссылка на файл изображения': url_image,
        'Путь / URL к файлу': url_download,
        'Автор внесения': 'Агент',
        'Примечания': '\n'.join([
            'Хранитель: РГИА',
            'Шифр: ' + r.fund_code,
            'Название фонда: ' + r.fund_name,
            'Крайние даты дословно: ' + r.date_raw,
            date_note,
            'Количество листов дела: ' + r.sheets,
            scan_note,
        ]),
    }
