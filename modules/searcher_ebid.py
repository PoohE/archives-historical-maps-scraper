"""Модуль поиска в ЭБИД (docs.historyrussia.org)."""
import time
from dataclasses import dataclass, field
from typing import Iterator
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://docs.historyrussia.org"
SEARCH_URL = f"{BASE_URL}/ru/nodes"


@dataclass
class EbidRecord:
    title: str = ""
    author: str = ""
    year_from: int | None = None
    year_to: int | None = None
    place: str = ""
    institution: str = ""
    description: str = ""
    url: str = ""
    doc_type: str = ""
    geography: str = ""
    date_raw: str = ""
    extra: dict = field(default_factory=dict)


def _get(url: str, params: dict | None = None, delay: float = 1.5) -> requests.Response:
    time.sleep(delay)
    headers = {"User-Agent": "Mozilla/5.0 (research bot; contact: down.pooh@gmail.com)"}
    resp = requests.get(url, params=params, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp


def _parse_years(text: str) -> tuple[int | None, int | None]:
    import re
    nums = re.findall(r"\d{4}", text)
    if not nums:
        return None, None
    if len(nums) == 1:
        y = int(nums[0])
        return y, y
    return int(nums[0]), int(nums[-1])


def _parse_record(url: str) -> dict:
    """Загружает страницу документа и извлекает метаданные."""
    meta = {"url": url}
    try:
        resp = _get(url)
        soup = BeautifulSoup(resp.text, "lxml")

        # Заголовок
        h1 = soup.find("h1")
        if h1:
            meta["title"] = h1.get_text(strip=True)

        # Таблица описания (поля: Автор, Дата, Архив, Фонд, Опись и т.д.)
        rows = soup.select("table tr") or soup.select(".properties tr")
        for row in rows:
            cells = row.find_all(["th", "td"])
            if len(cells) >= 2:
                key = cells[0].get_text(strip=True).rstrip(":")
                val = cells[1].get_text(strip=True)
                meta[key] = val

        # Описание / аннотация
        desc = soup.select_one(".description, .annotation, .abstract")
        if desc:
            meta["description"] = desc.get_text(strip=True)[:500]

    except Exception as e:
        meta["error"] = str(e)
    return meta


def search(query: str, year_from: int | None = None, year_to: int | None = None,
           territory: str = "", max_pages: int = 3) -> Iterator[EbidRecord]:
    """
    Ищет документы в ЭБИД через текстовый поиск.
    Возвращает записи EbidRecord.
    """
    params: dict = {"search": query}

    for page in range(1, max_pages + 1):
        if page > 1:
            params["page"] = page
        try:
            resp = _get(SEARCH_URL, params=params)
        except Exception as e:
            print(f"[ЭБИД] Ошибка запроса стр.{page}: {e}")
            break

        soup = BeautifulSoup(resp.text, "lxml")

        # Ссылки на документы
        links = soup.select("a[href*='/ru/nodes/']")
        found = 0
        for link in links:
            href = link.get("href", "")
            # Исключаем навигационные ссылки (без числового ID)
            import re
            if not re.search(r"/ru/nodes/\d+", href):
                continue
            doc_url = BASE_URL + href if href.startswith("/") else href

            meta = _parse_record(doc_url)

            # Фильтрация по году если указан
            date_raw = meta.get("Дата", "") or meta.get("Год", "")
            y_from, y_to = _parse_years(date_raw)
            if year_from and y_to and y_to < year_from:
                continue
            if year_to and y_from and y_from > year_to:
                continue

            # Фильтрация по территории
            geo = meta.get("Территория", "") or meta.get("География", "")
            if territory and territory.lower() not in geo.lower():
                # Мягкая фильтрация — только если совсем нет совпадения
                if territory.lower() not in meta.get("title", "").lower():
                    continue

            rec = EbidRecord(
                title=meta.get("title", link.get_text(strip=True)),
                author=meta.get("Автор", ""),
                year_from=y_from,
                year_to=y_to,
                place=meta.get("Место создания", ""),
                institution=meta.get("Архив", "") or meta.get("Фонд", ""),
                description=meta.get("description", "")[:400],
                url=doc_url,
                doc_type=meta.get("Тип документа", ""),
                geography=geo,
                date_raw=date_raw,
                extra={k: v for k, v in meta.items()
                       if k not in ("title", "url", "description", "error")},
            )
            yield rec
            found += 1

        if found == 0:
            break
