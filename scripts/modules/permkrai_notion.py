"""Conservative offline scalar mapping; unresolved dates remain for review."""
from urllib.parse import urlsplit


def notion_row(r):
    creation = r.get('creation_year_review') or {}
    upper = r.get('year_to') or ''
    lower = r.get('year_from') or ''
    approved_creation = (creation.get('status') == 'approved' and creation.get('source_url') == r['url']
            and creation.get('scope') == 'main_map' and creation.get('locator')
            and creation.get('text') and creation['text'] in r['bibliography']
            and type(creation.get('year')) is int and 1 <= creation['year'] <= 9999)
    if approved_creation:
        upper = creation['year']
    notes = [
        'Фондодержатель (по карточке): ' + r['owner'],
        'Дата в поле карточки: ' + r['date_raw'],
        'Выходные данные: ' + r['publication_statement'],
        'Объём дословно: ' + r['sheets'] + '; не номер листа в издании.',
        'Просмотрщик (ссылка не проверена): ' + r['url_viewer'],
        'PDF не скачивался; полнота копии и условия доступа не подтверждены.',
    ]
    # Neither a year in the title nor a lower publication bound proves an upper
    # creation date. Preserve both witnesses and request a dating decision.
    if approved_creation:
        notes.append('Верхняя дата создания: ' + str(upper) + ' — по явным сведениям о составлении карты: ' + creation['text'])
    elif r['publication_date_qualifier']:
        notes.append('Даты создания оставлены пустыми: квалифицированная датировка издания требует проверки.')
    pdf = r['url_download']
    fmt = 'PDF' if pdf and urlsplit(pdf).path.lower().endswith('.pdf') else ''
    if fmt:
        notes.append('Формат PDF (по метаданным, файл не проверен): ссылка PDF из карточки и расширение .pdf.')
    return {'Название источника': r['title'], 'Автор / составитель': r['author'],
        'Библиотечный шифр': r['shelfmark'],
        'Описание': r['bibliography'] or r.get('card_text') or r['description'],
        'Оригинальный масштаб': r['scale_raw'], 'Масштаб (знаменатель)': r['scale_denominator'],
        'Год создания (нижняя)': lower, 'Год создания (верхняя)': upper, 'Листы / страницы': '',
        'Ссылка на онлайн-архив': r['url'], 'Путь / URL к файлу': pdf,
        'Прямая ссылка на файл изображения': r.get('url_viewer') or r.get('url_image', ''), 'Формат файла': fmt,
        'Место хранения': r['owner'], 'Статус доступа': 'Открытый доступ' if r['open_access'] else '',
        'DC Type': 'StillImage', 'Примечания': '\n'.join(notes), 'Автор внесения': 'Агент'}
