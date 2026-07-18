"""
Статистический анализ триггер-слов в названиях исторических источников.
Методы: частотный анализ токенов + TF (term frequency) по заголовкам.
"""
import csv, re, sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

FILES = [
    Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\kaluga.csv"),
    Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\perm.csv"),
]

# Стоп-слова (предлоги, артикли, общие слова без диагностической ценности)
STOPWORDS = {
    'и','в','на','по','от','до','из','за','к','с','а','но','не','то','же',
    'для','при','об','о','со','во','из','под','над','между','через',
    'года','год','гг','г','лет','ед','хр','оп','ф','д','л','листов',
    'фонд','опись','дело','лист','архив','документ','документы',
    'ргада','гако','гапо','гасо','гаяо','ргиа','ргвиа',
    'уезд','уезда','уездный','уездного','губерния','губернии','губернского',
    'масштаб','в','вёрст','верст','верста','дюйм','дюйма',
    'план','карта','схема','атлас','съёмка','съемка','чертёж','чертеж',
    'карты','планы','схемы','атласы','съёмки','чертежи',
}

# Известные триггеры из фильтра
KNOWN_TRIGGERS = {'план','карта','схема','масштаб','атлас','съёмка','съемка','чертёж','чертеж'}

def tokenize(text: str) -> list[str]:
    """Разбивает текст на токены: только кириллица, минимум 3 буквы."""
    return [w.lower() for w in re.findall(r'[а-яёА-ЯЁ]{3,}', text)]

all_titles = []
all_comments = []
rows_total = 0

for fpath in FILES:
    with open(fpath, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    rows_total += len(rows)
    # Определяем столбцы с названиями и комментариями
    cols = rows[0].keys() if rows else []
    title_col = next((c for c in cols if 'назван' in c.lower() or 'наим' in c.lower()), None)
    comment_col = next((c for c in cols if 'коммент' in c.lower() or 'примеч' in c.lower() or 'описан' in c.lower()), None)

    print(f"\n{'='*60}")
    print(f"Файл: {fpath.name}  |  строк: {len(rows)}")
    print(f"Столбцы: {list(cols)}")
    print(f"Столбец названий: {title_col!r}  |  комментариев: {comment_col!r}")

    for row in rows:
        title = row.get(title_col, '') or ''
        comment = row.get(comment_col, '') or ''
        if title.strip():
            all_titles.append(title.strip())
        if comment.strip():
            all_comments.append(comment.strip())

# --- Частотный анализ ---
title_tokens = []
for t in all_titles:
    title_tokens.extend(tokenize(t))

comment_tokens = []
for c in all_comments:
    comment_tokens.extend(tokenize(c))

title_freq = Counter(w for w in title_tokens if w not in STOPWORDS)
comment_freq = Counter(w for w in comment_tokens if w not in STOPWORDS)

print(f"\n{'='*60}")
print(f"ИТОГО строк: {rows_total}  |  названий: {len(all_titles)}  |  комментариев: {len(all_comments)}")

print(f"\n--- ТОП-40 слов в НАЗВАНИЯХ ---")
for word, cnt in title_freq.most_common(40):
    marker = " ← ТРИГГЕР" if word in KNOWN_TRIGGERS else ""
    print(f"  {cnt:>4}  {word}{marker}")

print(f"\n--- ТОП-30 слов в КОММЕНТАРИЯХ ---")
for word, cnt in comment_freq.most_common(30):
    marker = " ← ТРИГГЕР" if word in KNOWN_TRIGGERS else ""
    print(f"  {cnt:>4}  {word}{marker}")

# --- Пример названий с каждым топ-триггером ---
TOP_N = 10
top_words = [w for w, _ in title_freq.most_common(TOP_N)]
print(f"\n--- ПРИМЕРЫ НАЗВАНИЙ для топ-{TOP_N} слов ---")
for word in top_words:
    examples = [t for t in all_titles if word in t.lower()][:3]
    print(f"\n  [{word}]")
    for ex in examples:
        print(f"    • {ex[:100]}")

# --- Потенциальные новые триггеры (не в KNOWN_TRIGGERS, встречаются ≥3 раз) ---
new_triggers = [(w, c) for w, c in title_freq.most_common(60)
                if w not in KNOWN_TRIGGERS and c >= 3]
print(f"\n--- ПОТЕНЦИАЛЬНЫЕ НОВЫЕ ТРИГГЕРЫ (≥3 раз, не в исходном списке) ---")
for word, cnt in new_triggers[:25]:
    print(f"  {cnt:>4}  {word}")
