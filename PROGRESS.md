# Прогресс: скраперы архивов ИГИС

Обновлено: 2026-07-07 (вечер — собран единый движок)

---

## ✅ Движок парсинга (2026-07-07)

Единый реестр источников: `modules/registry.py`. Все источники (легаси из
`searcher_libraries.py` + новые из `modules/scrapers/`) доступны через один
интерфейс `registry.search(source_id, query, ...)` → `LibraryRecord`.

- `run_search.py` переведён на движок; НЭБ и РГБ добавлены в `SOURCE_PRIORITY`
  (отдельный запуск больше не нужен — пункт 3 старого плана закрыт)
- Режим `walk` (Смоленск): один обход коллекции за прогон вместо перебора
  территория×слово; чекпоинт-ключ `__walk__|smolensk_lib`
- Новый источник = один `SourceSpec` + адаптер в registry.py, без нового скрипта
- Список источников: `python modules/registry.py`
- Проверено: dry-run полный (2269 комбинаций, математика walk верна);
  живой вызов kaluga_lib (запрос прошёл, см. ниже) и gpib (сайт лежал в момент теста)

⚠️ Находка по Калуге: Веб-ИРБИС64+ рендерит результаты через JavaScript —
GET `C21COM=S` возвращает страницу-оболочку без записей (0 результатов при
любом запросе). Скрапер требует другого вызова (POST/сессия или API Веб-ИРБИС).

---

## ✅ Готово — скрипты написаны

| Архив | Файл | Статус | Примечания |
|-------|------|--------|------------|
| ГПИБ | `modules/searcher_libraries.py` (gpib) | ✅ Работает | 14 183 записи загружены в Notion |
| Пермская краевая библ. | `modules/scrapers/searcher_permkrai.py` | ⚠️ Не тестировался | Геоблок с нероссийских IP; ELiS CMS |
| Смоленская ОУНБ | `modules/scrapers/searcher_smolensk.py` | ⚠️ Не тестировался | Нет поиска — обход коллекции (311 докум., 32 стр.) |
| Калужская ОНБИБ | `modules/scrapers/searcher_kaluga.py` | ⚠️ Не тестировался | IRBIS64; IP 217.15.203.140:81; фильтр по рубрике KGR |
| НЭБ | `modules/scrapers/searcher_neb.py` | ⚠️ Не тестировался | REST; catalog[]=Карты; двухфазный парсинг |
| РГБ | `modules/scrapers/searcher_rsl.py` | ⚠️ Не тестировался | POST API; HTML в JSON; фильтр KGR; MaxDisplayPage=100 |

---

## ❌ Нет онлайн-каталога — скрипт невозможен

| Архив | Причина |
|-------|---------|
| ЯОУНБ (Ярославль) | rlib.yar.ru/search не работает |

---

## 🔄 Схема описана, скрипт НЕ написан

| Архив | Схема | Следующий шаг |
|-------|-------|---------------|
| РНБ (nlr.ru) | Карточки-изображения (3 каталога: cart / hist_rus / XVIII в.); поиск по разделителю («Калужская губерния» → 23 карточки); нужен OCR через Claude Vision API | Написать `searcher_nlr.py`: поиск → скачать изображения → OCR |
| ПБ (prlib.ru) | Скрипт уже есть в `searcher_libraries.py` (prlib) | Сайт сейчас недоступен (rate-limit/блок); перезапустить когда откроется: `python run_search.py --source prlib --run-dir prlib_local --resume` |

---

## 📋 Следующие действия (по приоритету)

### 1. Тестирование написанных скриптов
Запускать по очереди, результат — вывод первой страницы:

```bash
# Пермская (нужен российский IP)
python modules/scrapers/searcher_permkrai.py --check-node 33626

# Смоленская
python modules/scrapers/searcher_smolensk.py --debug --max-pages 1

# Калужская
python modules/scrapers/searcher_kaluga.py "карта Калужская" --debug

# НЭБ
python modules/scrapers/searcher_neb.py "карта Калужская губерния" --debug

# РГБ
python modules/scrapers/searcher_rsl.py "карта Калужской губернии" --debug --free-only
```

При ошибке — прислать вывод, исправим селекторы.

### 2. Написать searcher_nlr.py (РНБ)
- Поиск по разделителю: `nlr.ru/e-case3/sc2.php/cart/find?sf=Калужская губерния`
- Скачать изображения карточек (URL: `/e-case3/sc2.php/cart/lc/{id}/{n}`)
- OCR каждой через Claude Vision API
- ~200–600 изображений для 4 губерний по 3 каталогам

### 3. ~~Интегрировать новые scrapers в run_search.py~~ ✅ 2026-07-07
Сделано через `modules/registry.py` (см. раздел «Движок парсинга» выше).

### 4. Запустить полный поиск (после тестирования)
```bash
python run_search.py --run-dir cloud   # все источники, включая НЭБ и РГБ, через движок
```

### 5. Дедупликация
- НЭБ агрегирует из РГБ → возможны дубли
- ГПИБ и НЭБ — частично пересекаются
- После всех запусков: `python scripts/dedup.py output/cloud/results.csv`

---

## 📁 Структура файлов

```
modules/
  registry.py                 — ДВИЖОК: единый реестр источников + адаптеры
  searcher_libraries.py       — легаси-функции (gpib, prlib, nlr_cart, ...)
  scrapers/
    searcher_permkrai.py      — Пермская краевая библ.
    searcher_smolensk.py      — Смоленская ОУНБ (walk)
    searcher_kaluga.py        — Калужская ОНБИБ (IRBIS64; ⚠ JS-рендер, нужен другой вызов)
    searcher_neb.py           — НЭБ
    searcher_rsl.py           — РГБ
    searcher_nlr.py           — РНБ (⬅ написать)
run_search.py                 — оркестратор (диспетчеризация через registry)
```
