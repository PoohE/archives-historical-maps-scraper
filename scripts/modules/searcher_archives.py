"""
Модуль поиска в Росархив-онлайн (online.archives.ru).
Сайт может быть недоступен — все ошибки обрабатываются gracefully.
"""
import time
from dataclasses import dataclass, field
from typing import Iterator
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://online.archives.ru"


@dataclass
class ArchivesRecord:
    title: str = ""
    author: str = ""
    year_from: int | None = None
    year_to: int | None = None
    archive: str = ""
    fond: str = ""           # фонд
    opis: str = ""           # опись
    unit: str = ""           # единица хранения
    sheets: str = ""         # листы
    description: str = ""
    url: str = ""
    extra: dict = field(default_factory=dict)


def _get(url: str, params: dict | None = None, delay: float = 2.0) -> requests.Response:
    time.sleep(delay)
    headers = {"User-Agent": "Mozilla/5.0 (research bot; contact: down.pooh@gmail.com)"}
    resp = requests.get(url, params=params, headers=headers, timeout=25)
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


def _check_availability() -> bool:
    """Проверяет доступность портала."""
    try:
        resp = requests.get(BASE_URL, timeout=10,
                            headers={"User-Agent": "Mozilla/5.0"})
        return resp.status_code == 200
    except Exception:
        return False


def search(query: str, year_from: int | None = None, year_to: int | None = None,
           archive: str = "", territory: str = "",
           max_pages: int = 3) -> Iterator[ArchivesRecord]:
    """
    Ищет документы в Росархив-онлайн (online.archives.ru).
    Возвращает пустой итератор если портал недоступен.
    """
    if not _check_availability():
        print("[Росархив-онлайн] Портал недоступен, пропуск.")
        return

    # Параметры поиска (уточнить по реальной структуре сайта)
    params: dict = {"q": query}
    if year_from:
        params["dateFrom"] = year_from
    if year_to:
        params["dateTo"] = year_to
    if archive:
        params["archive"] = archive

    search_url = f"{BASE_URL}/search"

    for page in range(1, max_pages + 1):
        params["page"] = page
        try:
            resp = _get(search_url, params=params)
        except Exception as e:
            print(f"[Росархив-онлайн] Ошибка запроса стр.{page}: {e}")
            break

        soup = BeautifulSoup(resp.text, "lxml")

        # Записи результатов (CSS-селекторы уточнить по реальной разметке)
        items = soup.select(".search-result-item, .result-item, article")
        if not items:
            break

        for item in items:
            link = item.find("a")
            title_el = item.select_one("h2, h3, .title")
            date_el = item.select_one(".date, .year, time")
            archive_el = item.select_one(".archive, .source")

            date_raw = date_el.get_text(strip=True) if date_el else ""
            y_from, y_to = _parse_years(date_raw)

            href = link.get("href", "") if link else ""
            url = (BASE_URL + href) if href.startswith("/") else href

            rec = ArchivesRecord(
                title=title_el.get_text(strip=True) if title_el else "",
                year_from=y_from,
                year_to=y_to,
                archive=archive_el.get_text(strip=True) if archive_el else "",
                url=url,
                description=item.get_text(strip=True)[:300],
            )
            yield rec
