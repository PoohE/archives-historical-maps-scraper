"""Parse saved EB catalogue descriptions, not individual map records."""
import re
from bs4 import BeautifulSoup


def parse(raw):
    soup = BeautifulSoup(raw, 'lxml')
    result = []
    direct = [a.get('href', '') for a in soup.find_all('a')
              if a.get_text(' ', strip=True) == 'Прямая ссылка на документ']
    readers = [a for a in soup.find_all('a')
               if a.get_text(' ', strip=True).startswith('Постраничный просмотр PDF-файла:')]
    if len(readers) != 2 or len(direct) != 2:
        raise ValueError('Expected the reviewed two-edition page; no silent empty result')
    for index, a in enumerate(readers):
        container = next((t for t in a.find_parents('table')
                          if 'ББК' in t.get_text() and 'Аннотация:' in t.get_text()), None)
        if container is None:
            raise ValueError('Missing bibliographic container')
        text = container.get_text(' ', strip=True)
        lines = list(container.stripped_strings)
        title = next((x for x in lines if x.startswith(('Топографическое описание', 'Атлас Калужскаго'))), '')
        if not title:
            raise ValueError('Title not identified')
        start = text.index(title)
        end = next((text.index(marker, start) for marker in
                    ('Примечания о действиях', 'СКРК,') if marker in text[start:]), len(text))
        bibliography = text[start:end].strip()
        dates = re.search(r',\s*(\d{4})\s*\(Калуга\s*:.*?,\s*(\d{4})\)', bibliography)
        if not dates:
            raise ValueError('Historical/electronic edition dates not distinguished')
        pdf_label = a.get_text(' ', strip=True)
        filename = pdf_label.rsplit('\\', 1)[-1]
        result.append(dict(title=title.split(' : ')[0].split(', :')[0].rstrip(', '),
            bibliography=bibliography, full_description=text, source_url=direct[index],
            historical_year=int(dates[1]), electronic_year=int(dates[2]),
            author='Соймонов, Петр Александрович' if 'Соймонов, Петр Александрович' in text else '',
            pdf_filename=filename, digital_link_kind='viewer_not_direct_pdf',
            incomplete_copy='не хватает 3-х листов' in text,
            evidence_locator='saved EB results: description ' + str(index + 1)))
    return result


def notion_row(r):
    # These are bibliographic editions. Do not mislabel their authors/dates as
    # authors/dates of an individual map inside the PDF.
    return {'Название источника': r['title'], 'Ссылка на онлайн-архив': r['source_url'],
        'Описание': '\n'.join(filter(None, [r['bibliography'], r['full_description']])),
        'Автор внесения': 'Агент',
        'Примечания': 'Объект проверки — издание, не отдельная карта. Историческое издание: '
            + str(r['historical_year']) + '; электронное издание: ' + str(r['electronic_year'])
            + '. Имя PDF в просмотрщике: ' + r['pdf_filename']
            + '. Прямая ссылка на файл не установлена; полный PDF не получен.'}
