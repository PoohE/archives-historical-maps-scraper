"""Conservative scalar mapping of parsed NEB cards; no external writes."""
import re
from urllib.parse import quote, urlsplit, parse_qs


def file_url(value):
    url = urlsplit(value or '')
    if url.scheme != 'https' or url.hostname != 'rusneb.ru':
        return ''
    if url.path.lower().endswith('.pdf') or (
        url.path == '/local/tools/exalead/getFiles.php' and
        (parse_qs(url.query).get('doc_type') == ['pdf'] or 'book_id' in parse_qs(url.query))
    ):
        return quote(value, safe=':/?&=%')
    return ''


def convert(rec):
    extra = rec.get('extra') or {}
    meta = extra.get('raw_meta') or {}
    if not meta or not rec.get('title') or not rec.get('bibliography'):
        raise ValueError('NEB detail metadata or bibliography missing')
    publication = meta.get('Год издания', '').strip()
    year = int(publication) if re.fullmatch(r'[12]\d{3}', publication) else None
    link = file_url(rec.get('url_download'))
    notes = [f'Код НЭБ: {rec.get("identifier", "")}',
             f'Библиотека-хранитель: {rec.get("source_lib", "")}',
             f'Издательство: {rec.get("publisher", "")}',
             f'Объём оригинала: {extra.get("extent", "")}',
             f'Просмотрщик (не файл): {rec.get("url_viewer", "")}',
             'Год издания в карточке: ' + publication]
    notes.extend('Врезка, исключено из полей основной карты: ' + x for x in extra.get('excluded_inset_notes', []))
    if link:
        notes.append('PDF по метаданным, файл не проверен.')
    if extra.get('visual_review'):
        notes.append('Линейный масштаб: прежнее ручное чтение 2026-09-12, не результат парсинга или OCR.')
    return {
        'Название источника': rec['title'], 'Автор / составитель': rec.get('author', ''),
        'Год создания (верхняя)': year, 'Год создания (нижняя)': '',
        'Место создания': rec.get('place', ''), 'Библиотечный шифр': meta.get('Шифр хранения', '') or meta.get('Код документа в НЭБ', ''),
        'Описание': '\n'.join(filter(None, [rec.get('bibliography', ''), rec.get('description', '')])),
        'Ссылка на онлайн-архив': rec['url'], 'Прямая ссылка на файл изображения': link,
        'Путь / URL к файлу': link, 'Формат файла': 'PDF' if link else '',
        'Статус доступа': '', 'Листы / страницы': '',
        'Оригинальный масштаб': extra.get('scale_original', ''),
        'Масштаб (знаменатель)': extra.get('scale_denominator'),
        'Язык': extra.get('language', ''), 'Автор внесения': 'Агент',
        'Примечания': '\n'.join(notes)}
