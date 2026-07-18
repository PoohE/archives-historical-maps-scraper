# Тестирование скраперов без VPN

Запускать по одному, результат копировать в чеклист и Notion.
Рабочая папка: `D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив`

---

## 1. Калужская КОНБ (IRBIS64) — IP без домена, геоблок маловероятен

```bash
python modules/scrapers/searcher_kaluga.py "карта Калужская губерния" --debug
python modules/scrapers/searcher_kaluga.py --db RK --debug
```

Ожидаем: список карт + шифры ББК. Если «0 результатов» — попробовать другой запрос.

---

## 2. Пермская краевая ПГКБ — ELiS CMS, геоблок с нероссийских IP

```bash
python modules/scrapers/searcher_permkrai.py "карта Пермская губерния" --debug
python modules/scrapers/searcher_permkrai.py --check-node 33626
```

Ожидаем: карточка `/node/33626` успешно разобрана.

---

## 3. Смоленская СОУНБ — обход коллекции (311 документов)

```bash
python modules/scrapers/searcher_smolensk.py --geo-only --debug
python modules/scrapers/searcher_smolensk.py --max-pages 3 --debug
```

`--geo-only` — только 9 документов тематики «Геогра» (быстрее).

---

## 4. Свердловская СОУНБ — OPAC-Global, нужен российский IP

Гостевой вход: `arg0=GUEST, arg1=GUESTE` (с book.uraic.ru/library/catalog.php).

```bash
# Сначала проверить сессию (POST к CGI как гость)
python modules/scrapers/searcher_sverdlovsk.py --check-ses

# Тест поиска с дампом HTML
python modules/scrapers/searcher_sverdlovsk.py --geo Перм --debug

# Полный запрос все 4 губернии
python modules/scrapers/searcher_sverdlovsk.py
```

Если `--check-ses` возвращает `SES = ''` — скопировать SES из браузера:
- Открыть `https://book.uraic.ru/library/catalog.php`
- Нажать ссылку «Электронный каталог…»
- DevTools → Application → Cookies → 79.110.251.73 → скопировать SES

---

## 5. НЭБ — REST API, фильтр catalog[]=Карты

```bash
python check_source.py neb
```

Ожидаем: ≥1 запись с типом «Карты».

---

## 6. РГБ (РСЛ) — POST API с CSRF-токеном

```bash
python check_source.py rsl
```

Если ошибка 400 — CSRF устарел. Сообщить — починим.

---

## 7. Росархив-онлайн — HTTP (не HTTPS), только без VPN

```bash
python check_source.py rosarchive
```

Ожидаем: записи с фондом 1356 (Генеральное межевание).

---

## Что сообщить после запуска

Для каждого скрипта:
- **Сработал**: сколько записей нашёл, пример первой записи
- **Ошибка**: полный текст ошибки
- **Пустой результат**: текст ответа из `--debug`

Особенно важно для Свердловской — полный вывод `--check-ses`.
