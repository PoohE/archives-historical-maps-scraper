# 🔓 ИНСТРУКЦИИ БЕЗ VPN: Доработка 7 недоработанных скриптов

**Важно:** Все архивы в этом списке доступны **БЕЗ VPN из России**. Никакого VPN не нужно включать.

---

## 1️⃣ ГАРФ (фреймворк закрыт, используются GET)

**Сайт:** https://www.fgurgia.ru/search

### Шаг 1: Проверить GET-запрос (2 мин)

Откройте в браузере:
```
https://www.fgurgia.ru/search?p0=v-карта&type=simple&p0_c=12
```

Должны увидеть список результатов в таблице. Если видите — GET работает. ✅

### Шаг 2: Запустить скрипт с --debug (3 мин)

```bash
cd D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив
python modules/scrapers/searcher_garf_fixed.py "карта" --debug
```

**Выход должен содержать:**
- URL запроса (проверить параметры)
- HTML первых 5000 символов (сохранить в файл)

```bash
python modules/scrapers/searcher_garf_fixed.py "карта" --debug > output/garf_html_dump.txt
```

### Шаг 3: Анализ в браузере DevTools (10 мин)

1. Откройте https://www.fgurgia.ru/search?p0=v-карта&type=simple&p0_c=12
2. Нажмите **F12** → вкладка **Elements**
3. Найдите таблицу результатов (Ctrl+F → "table")
4. Посмотрите структуру:
   - Какой `<table>` класс? (например `class="search-results"`)
   - Какие `<tr>` / `<td>` в таблице?
   - Где находится номер документа (Ф., Оп., Д.)?
   - Где находится название?

### Шаг 4: Обновить селекторы в коде (5 мин)

Файл: `modules/scrapers/searcher_garf_fixed.py`

Найдите строки:
```python
results_section = soup.find("table") or soup.find("ul", class_="results")
rows = results_section.find_all("tr") or results_section.find_all("li")
```

Замените на правильные селекторы (из DevTools). Например:
```python
results_section = soup.find("table", class_="search-table")  # ← уточнить класс
rows = results_section.find_all("tr")[1:]  # пропустить header
```

### Шаг 5: Тестировать (5 мин)

```bash
python modules/scrapers/searcher_garf_fixed.py "карта Смоленская"
```

Если вывод показывает записи → готово! ✅

---

## 2️⃣ Калужская ОНБИБ (Веб-ИРБИС 64, POST работает)

**Сайт:** https://ibald.ru

### Шаг 1: Проверить форму в браузере (3 мин)

1. Откройте https://ibald.ru
2. Найдите форму поиска (обычно в левой колонке или сверху)
3. Введите "карта" → нажмите "Поиск"
4. Должны увидеть результаты

Если видите → источник работает. ✅

### Шаг 2: Перехватить POST в DevTools (5 мин)

1. Откройте https://ibald.ru
2. **F12** → вкладка **Network**
3. Выполните поиск "карта"
4. В списке запросов найдите **POST** запрос (обычно к `/cgi-bin/...`)
5. Кликните на запрос → посмотрите **Request Body**

**Ищите параметры:**
- `database=???` (имя базы)
- `searchtype=???` (тип поиска: I, K, S, T)
- `query=карта` (сам запрос)
- `format=???` (формат ответа)

### Шаг 3: Скопировать параметры (2 мин)

DevTools → Request Body → **скопировать весь текст**

Должно быть похоже на:
```
database=ibald&searchtype=I&query=%D0%BA%D0%B0%D1%80%D1%82%D0%B0&format=HTML&...
```

### Шаг 4: Обновить скрипт (5 мин)

Файл: `modules/scrapers/searcher_kaluga_fixed.py`

Найдите:
```python
data = {
    "database": "ibald",
    "searchtype": "I",
    "query": query,
    "format": "HTML",
}
```

Замените на правильные значения из DevTools.

### Шаг 5: Тестировать (5 мин)

```bash
python modules/scrapers/searcher_kaluga_fixed.py "карта Калужская"
```

Если вывод показывает записи → готово! ✅

---

## 3️⃣ Пермская краевая ОНБИБ (AJAX, ELiS CMS)

**Сайт:** https://permlib.ru

### Шаг 1: Проверить поиск (3 мин)

1. Откройте https://permlib.ru
2. Найдите форму поиска
3. Введите "карта" → нажмите Enter
4. Дождитесь загрузки результатов (может быть задержка 2–3 сек)

Если видите результаты → источник работает. ✅

### Шаг 2: Анализ XHR запроса (10 мин)

1. **F12** → вкладка **Network** → фильтр **XHR**
2. Очистите список (Ctrl+Shift+Delete в DevTools)
3. Выполните поиск "карта" в браузере
4. В списке XHR найдите запрос (обычно `/search`, `/api/search`, `/ajax/...`)
5. Кликните → посмотрите:
   - **URL** запроса (скопировать)
   - **Method** (GET или POST)
   - **Query String** (параметры)
   - **Response** (JSON или HTML?)

### Шаг 3: Решить — API или Selenium (5 мин)

**Если Response JSON:**
```python
# Использовать requests
import requests
resp = requests.get("https://permlib.ru/api/search", params={"q": "карта"})
results = resp.json()["items"]
```

**Если Response HTML или нет XHR:**
```python
# Использовать Playwright
from playwright.async_api import async_playwright
async def search():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("https://permlib.ru")
        await page.fill("[name=query]", "карта")
        await page.press("[name=query]", "Enter")
        await page.wait_for_load_state("networkidle")
        # Теперь DOM полностью загружен
        results = await page.query_selector_all(".result-item")
```

### Шаг 4: Написать код (15 мин)

Файл: `modules/scrapers/searcher_permkrai_fixed.py`

Вставить код из Шага 3 (requests или Playwright).

### Шаг 5: Тестировать (5 мин)

```bash
python modules/scrapers/searcher_permkrai_fixed.py "карта"
```

---

## 4️⃣ Смоленская ОУНБ (Walk по каталогу)

**Сайт:** https://smolbnlib.ru

### Шаг 1: Посмотреть структуру каталога (5 мин)

1. Откройте https://smolbnlib.ru
2. Найдите раздел "Фонды" или "Каталог"
3. Кликните на один фонд → посмотрите ссылки на подразделы
4. Обратите внимание на URL паттерны (напримеr: `/catalog/fond/123/`)

### Шаг 2: DevTools анализ (5 мин)

**F12** → **Elements** → найдите все `<a>` ссылки в каталоге.

Обычно структура:
```html
<a href="/catalog/fond/123/">Фонд 123</a>
  <a href="/catalog/fond/123/opis/1/">Опись 1</a>
    <a href="/catalog/fond/123/opis/1/delo/456/">Дело 456 — Карта Смоленской губернии</a>
```

### Шаг 3: Написать рекурсивный walk (15 мин)

Файл: `modules/scrapers/searcher_smolensk_fixed.py`

```python
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://smolbnlib.ru"

def walk_catalog(url, max_depth=5, current_depth=0):
    """Рекурсивный обход каталога."""
    if current_depth >= max_depth:
        return []
    
    try:
        resp = requests.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, "lxml")
    except:
        return []
    
    results = []
    
    # Ищем ссылки на подкаталоги
    for a in soup.find_all("a", href=True):
        href = a.get("href")
        if not href.startswith("http"):
            href = BASE_URL + href
        
        text = a.get_text().lower()
        
        # Если это картографический документ
        if any(word in text for word in ["карта", "план", "чертёж"]):
            results.append({
                "title": a.get_text(),
                "url": href
            })
        
        # Если это ссылка на подкаталог (не документ)
        if "fond" in href or "opis" in href or "delo" not in href:
            results.extend(walk_catalog(href, max_depth, current_depth + 1))
    
    return results

# Запуск
results = walk_catalog(f"{BASE_URL}/catalog/")
print(f"Найдено {len(results)} документов с картографией")
```

### Шаг 4: Тестировать (5 мин)

```bash
python modules/scrapers/searcher_smolensk_fixed.py
```

**Внимание:** Может быть медленно (много рекурсий). Добавьте `time.sleep(1.0)` между запросами.

---

## 5️⃣ РГБ (Российская государственная библиотека)

**Сайт:** https://www.rsl.ru/ru/s97/s339/

### Шаг 1: Проверить форму (3 мин)

1. Откройте https://www.rsl.ru/ru/s97/s339/
2. Найдите форму поиска
3. Введите "карта" → нажмите "Поиск"
4. Должны увидеть результаты

Если видите → источник работает. ✅

### Шаг 2: DevTools анализ POST (5 мин)

1. **F12** → **Network**
2. Выполните поиск
3. Найдите **POST** запрос
4. Посмотрите:
   - **URL** (куда идёт POST)
   - **Headers** (ищите `X-CSRF-Token` или похожее)
   - **Request Body** (параметры)

### Шаг 3: Проверить CSRF-токен (5 мин)

Обычно CSRF-токен находится в:
```html
<input name="csrf_token" value="...">
<!-- или -->
<meta name="csrf-token" content="...">
```

**F12** → **Elements** → Ctrl+F → "csrf" → скопировать значение

### Шаг 4: Написать код с Session (10 мин)

Файл: `modules/scrapers/searcher_rgb_fixed.py`

```python
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.rsl.ru"
SEARCH_URL = f"{BASE_URL}/ru/s97/s339/"

session = requests.Session()

# Шаг 1: Получить CSRF-токен со страницы
resp = session.get(SEARCH_URL)
soup = BeautifulSoup(resp.text, "lxml")
csrf_input = soup.find("input", attrs={"name": "csrf_token"})
csrf_token = csrf_input["value"] if csrf_input else ""

# Шаг 2: Выполнить POST поиск
data = {
    "q": "карта",
    "csrf_token": csrf_token,
    # ... другие параметры из DevTools
}
resp = session.post(SEARCH_URL, data=data)
results = BeautifulSoup(resp.text, "lxml").find_all("div", class_="result")
```

### Шаг 5: Тестировать (5 мин)

```bash
python modules/scrapers/searcher_rgb_fixed.py "карта"
```

---

## 6️⃣ ЦГА Москвы (Bitrix CMS)

**Сайт:** https://www.tica.ru

### Шаг 1: Проверить форму (3 мин)

1. Откройте https://www.tica.ru
2. Найдите форму поиска
3. Введите "карта" → нажмите Enter
4. Должны увидеть результаты

Если видите → источник работает. ✅

### Шаг 2: DevTools анализ CSS-селекторов (10 мин)

1. **F12** → **Elements**
2. Нажмите стрелку (инспектор) в левом верхнем углу DevTools
3. Кликните на один результат в браузере
4. DevTools выделит HTML элемент
5. Посмотрите:
   - Какой `<div>` класс оборачивает результаты?
   - Какой класс для заголовка?
   - Какой класс для дат?

### Шаг 3: Написать код с Selenium (15 мин)

Файл: `modules/scrapers/searcher_cga_moskva_fixed.py`

```python
from selenium import webdriver
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import time

BASE_URL = "https://www.tica.ru"
driver = webdriver.Chrome()

try:
    driver.get(BASE_URL)
    
    # Найти форму и ввести поиск
    search_input = driver.find_element(By.NAME, "q")  # ← уточнить name из DevTools
    search_input.send_keys("карта")
    search_input.submit()
    
    # Ждём загрузки результатов
    time.sleep(3)
    
    # Парсим результаты
    soup = BeautifulSoup(driver.page_source, "lxml")
    results = soup.find_all("div", class_="result-item")  # ← уточнить класс
    
    for result in results:
        title = result.find("h2", class_="title").get_text()  # ← уточнить
        print(title)

finally:
    driver.quit()
```

### Шаг 4: Тестировать (5 мин)

```bash
python modules/scrapers/searcher_cga_moskva_fixed.py "карта"
```

---

## 7️⃣ ГАКО (Государственный архив Калужской области, AJAX)

**Сайт:** https://gako.ru

### Шаг 1: Проверить поиск (3 мин)

1. Откройте https://gako.ru
2. Найдите форму поиска
3. Введите "карта" → нажмите Enter
4. Дождитесь загрузки результатов (может быть задержка)

Если видите результаты → источник работает. ✅

### Шаг 2: DevTools анализ XHR (10 мин)

1. **F12** → **Network** → **XHR**
2. Очистите (Ctrl+Shift+Delete)
3. Выполните поиск "карта"
4. Найдите XHR запрос (обычно `/api/search`, `/search.json`, `/ajax/...`)
5. Кликните → посмотрите:
   - **URL** полностью (скопировать)
   - **Query String** (параметры)
   - **Response** (должен быть JSON)

### Шаг 3: Написать код с requests (10 мин)

Файл: `modules/scrapers/searcher_gako_fixed.py`

```python
import requests
from urllib.parse import urljoin

BASE_URL = "https://gako.ru"
API_URL = urljoin(BASE_URL, "/api/search")  # ← уточнить путь из DevTools

def search(query):
    params = {
        "q": query,
        # ... другие параметры из DevTools
    }
    
    resp = requests.get(API_URL, params=params)
    data = resp.json()
    
    results = []
    for item in data.get("items", []):
        results.append({
            "title": item.get("title"),
            "url": urljoin(BASE_URL, item.get("url", "")),
            "year": item.get("year"),
        })
    
    return results

results = search("карта")
for r in results:
    print(r["title"])
```

### Шаг 4: Тестировать (5 мин)

```bash
python modules/scrapers/searcher_gako_fixed.py "карта"
```

---

## 📝 ОБЩИЕ СОВЕТЫ

### Советы по DevTools:

1. **Перехват запроса:**
   - F12 → Network → очистить → выполнить действие → найти запрос

2. **Копирование URL:**
   - Правый клик на запрос → Copy → Copy as cURL → вставить в Python-код

3. **Поиск селекторов:**
   - F12 → Elements → Ctrl+F → ввести текст → найти элемент → посмотреть класс

4. **Проверка кодировки:**
   - DevTools → Response → если видите кириллицу как `%D0%BA%D0%B0%D1%80%D1%82%D0%B0` → windows-1251

### Советы по кодированию:

```python
# Всегда добавляйте User-Agent
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0"
}
resp = requests.get(url, headers=headers)

# Всегда указывайте timeout
resp = requests.get(url, timeout=20)

# Для windows-1251 баз явно указывайте кодировку
resp.encoding = "windows-1251"

# Для пагинации добавьте задержку
time.sleep(2.0)  # 2 секунды между запросами
```

---

## ✅ ЧЕКЛИСТ ДОРАБОТКИ

- [ ] ГАРФ — Найти селекторы, обновить код, тестировать
- [ ] Калужская — Уточнить параметры в DevTools, обновить код, тестировать
- [ ] Пермская — Выбрать метод (requests vs Playwright), написать код
- [ ] Смоленская — Написать рекурсивный walk, добавить фильтр "карта"
- [ ] РГБ — Добавить CSRF-обработку, написать код
- [ ] ЦГА Москвы — Найти селекторы Bitrix, написать Selenium код
- [ ] ГАКО — Найти JSON API, написать requests код

**Ожидаемое время:** 2–3 часа на человека без опыта, 30–60 мин с опытом.

---

**Дата:** 2026-07-18  
**Автор:** Claude Haiku 4.5
