# Прогресс: скраперы архивов ИГИС

Обновлено: 2026-07-18

---

## СЛЕДУЮЩИЙ ШАГ (точка входа)

**Загрузка 4 источников в Notion** (протестированы, готовы):
```bash
# 1. Экспорт CSV из output/
python modules/scrapers/searcher_rnb_kart.py > output/rnb_20260718.csv
# 2. Запуск batch-загрузки в Notion
python prepare_notion_upload.py --source rnb,neb,gayao,gpib --dry-run
# 3. При готовности:
python prepare_notion_upload.py --source rnb,neb,gayao,gpib --upload
```

**Параллельно — доделать недоступные:**
- ГАРФ, ГАКО, ЦГА Москвы — нужны AJAX-URL или браузер; сниженный приоритет
- ГАПК /archive/ — скрипт готов (`searcher_gapk_search.py`), геоблок; ждём русского IP или VPN
- Росархив — полностью недоступен (DNS не разрешается); исключить из текущего пайплайна

---

## ГРАБЛИ (не повторять)

- **НЭБ таймауты** → добавлена retry-логика (до 3 попыток, растущая задержка)
- **rusneb.ru медленный** — timeout=60 (было 30), может потребоваться ещё больше
- **ГАПК /archive/ геоблок** — TCP-уровень, прокси не помогают (Jina вернул 400)

---

## ✅ Готовые источники (2026-07-18)

| Архив | Записей | Статус | Команда |
|-------|---------|--------|---------|
| ГПИБ | 14 183 | ✅ | `python modules/searchers/searcher_libraries.py gpib` |
| ГАЯО | 248 | ✅ | `python modules/scrapers/searcher_gayao.py --full` |
| РНБ (XVIII в.) | 39 | ✅ | `python modules/scrapers/searcher_rnb_kart.py` |
| НЭБ | 84 | ✅ | `python modules/scrapers/searcher_neb.py --all-queries` (с retry) |
| **ИТОГО** | **14 554** | ✅ | — |

---

## 🔄 В разработке / проблемы

| Архив | Проблема | Решение |
|-------|----------|---------|
| ГАРФ | frameset (AJAX) | DevTools → найти XHR-URL контент-фрейма |
| ГАКО | AJAX-рендер результатов | Браузер или Selenium |
| ЦГА Москвы | CSS-селекторы не работают (0 результатов) | `python modules/scrapers/searcher_cgamos.py "карта" --debug` → прислать HTML |
| ГАПК /archive/ | Геоблок (TCP timeout) | Ждём русского IP; скрипт готов `searcher_gapk_search.py` |
| Росархив | Недоступен (DNS, таймаут) | Исключить из текущего цикла |

---

## 📋 Структура скрипты (на 2026-07-18)

```
modules/
  registry.py                      — движок (10 источников)
  scrapers/
    searcher_neb.py               ✅ (retry-фикс 2026-07-18)
    searcher_rnb_kart.py          ✅
    searcher_gayao.py             ✅
    searcher_gapk.py              ✅ (archive1)
    searcher_gapk_search.py       ✅ (archive/ - геоблок)
    searcher_kaluga.py            ⚠️
    searcher_rosarchive.py        ❌
    searcher_cgamos.py            ⚠️
    searcher_garf.py              ⚠️
    searcher_gako.py              ⚠️
    searcher_rgia.py              ⚠️
```

---

## 📊 Итого по губерниям (из 4 готовых источников)

Примерное распределение:
- **Калужская**: ГПИБ (много) + НЭБ + РНБ
- **Пермская**: ГПИБ + НЭБ + РНБ + ГАПК (когда VPN)
- **Смоленская**: ГПИБ + НЭБ + РНБ + ГАЯО (248)
- **Ярославская**: ГПИБ + НЭБ + РНБ + ГАЯО

**Основной вклад:**
1. ГПИБ (14 183) — универсальный источник, много карт
2. НЭБ (84) — агрегатор, дубли возможны
3. РНБ (39) — специализированный (XVIII в.)
4. ГАЯО (248) — региональный (Смоленск/Ярославль)

---

## 📌 Checkpoints

- NEB `--all-queries` с retry: `output/neb_full_20260718.txt` ✅
- RNB полный прогон: `output/rnb_kart_full_20260717.txt` ✅
- Notion batch:待 (ждём команды загрузки)

---

## Что дальше

1. **Загрузка** → запустить batch-upload в Notion (14 554 записей)
2. **Доработка недоступных** → если будет русский IP, запустить ГАПК /archive/
3. **Дедупликация** → сравнить записи по названию + году, вычислить уникальные
4. **Фильтр по 4 губерниям** → применить территориальный фильтр (Калуж/Перм/Смолен/Яросл)

