"""Браузерный сбор публичных карточек НЭБ.

НЭБ отдаёт ``403 Отключите VPN`` обычному requests-клиенту, тогда как чистый
видимый Chromium открывает те же публичные страницы. Этот модуль использует
только новый контекст Playwright без cookies, профиля и авторизации. Он не
обходит CAPTCHA/антибот-защиту: при 401/403 прогон останавливается.

Примеры:
    python -B modules/scrapers/searcher_neb_browser.py "карта Калужская губерния" \
        --output output/neb_browser_smoke_20260909
    python -B modules/scrapers/searcher_neb_browser.py --all-queries \
        --output output/neb_browser_20260909
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup
from playwright.sync_api import Browser, Page, Playwright, sync_playwright

HERE = Path(__file__).resolve()
MODULES = HERE.parent.parent
sys.path.insert(0, str(MODULES))

from territories import TERRITORIES  # noqa: E402
from scrapers.searcher_neb import NebRecord, parse_card_html  # noqa: E402

BASE_URL = "https://rusneb.ru"
SEARCH_URL = f"{BASE_URL}/search/"
KEYWORDS = ["карта", "план", "атлас", "съёмка", "чертёж"]
CATALOG_RE = re.compile(r"^/catalog/[^/]+/?$")
CSV_FIELDS = [
    "source", "record_type", "territory", "query", "title", "year_from",
    "year_to", "identifier", "url", "description", "coverage_status",
    "retrieval_date", "source_run",
]


class AccessBlocked(RuntimeError):
    """НЭБ вернул страницу запрета доступа; массовый обход прекращается."""


def _chrome_path() -> str | None:
    for p in (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ):
        if p.exists():
            return str(p)
    return shutil.which("chrome") or shutil.which("google-chrome")


def _browser(pw: Playwright, headed: bool) -> Browser:
    kwargs = {
        "headless": not headed,
        "args": ["--disable-extensions", "--no-first-run", "--no-default-browser-check"],
    }
    executable = _chrome_path()
    if executable:
        kwargs["executable_path"] = executable
    return pw.chromium.launch(**kwargs)


def _search_url(query: str, page: int | None = None) -> str:
    url = f"{SEARCH_URL}?q={quote(query)}&access%5B%5D=open&catalog%5B%5D={quote('Карты')}"
    return url if not page or page == 1 else f"{url}&page={page}"


def _check_response(page: Page, response, url: str) -> None:
    status = response.status if response else None
    title = page.title()
    h1 = page.locator("h1").first.text_content(timeout=2000) if page.locator("h1").count() else ""
    blocked = status in (401, 403, 429) or "Отключите VPN" in (title or "") or "Отключите VPN" in (h1 or "")
    if blocked:
        raise AccessBlocked(f"НЭБ заблокировал браузерный запрос: status={status}, title={title!r}, url={url}")


def _catalog_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=CATALOG_RE):
        href = a["href"].rstrip("/") + "/"
        full = href if href.startswith("http") else BASE_URL + href
        if full not in seen:
            seen.add(full)
            links.append(full)
    return links


def _has_next(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    return bool(soup.select_one("a[rel=next], .pagination__next, a.next, [aria-label='Следующая']"))


def _identifier(url: str) -> str:
    m = re.search(r"/catalog/([^/]+)/?", url)
    return m.group(1) if m else ""


def _save_raw(raw_dir: Path, label: str, url: str, html: str, status: int | None) -> dict:
    digest = hashlib.sha256(html.encode("utf-8", errors="replace")).hexdigest()
    path = raw_dir / f"{label}_{digest[:16]}.html"
    path.write_text(html, encoding="utf-8")
    return {"url": url, "status": status, "sha256": digest, "bytes": len(html.encode("utf-8")), "path": str(path)}


def _record_row(rec: NebRecord, territory: str, query: str, retrieval_date: str,
                source_run: str) -> dict[str, str]:
    desc = "; ".join(p for p in (
        rec.description,
        f"Фондодержатель: {rec.source_lib}" if rec.source_lib else "",
        f"Доступ: {rec.access}" if rec.access else "",
        f"Издательство: {rec.publisher}" if rec.publisher else "",
    ) if p)
    return {
        "source": "neb",
        "record_type": "library_card",
        "territory": territory,
        "query": query,
        "title": rec.title,
        "year_from": str(rec.year_from or ""),
        "year_to": str(rec.year_to or ""),
        "identifier": _identifier(rec.url),
        "url": rec.url,
        "description": desc,
        "coverage_status": "browser_chromium_public_card",
        "retrieval_date": retrieval_date,
        "source_run": source_run,
    }


def run_query(page: Page, query: str, territory: str, max_pages: int,
              raw_dir: Path, manifest: list[dict]) -> list[dict[str, str]]:
    links: list[str] = []
    for page_no in range(1, max_pages + 1):
        url = _search_url(query, page_no)
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1800)
        _check_response(page, response, url)
        html = page.content()
        manifest.append(_save_raw(raw_dir, f"search_{territory}_{page_no}", url, html,
                                   response.status if response else None))
        for link in _catalog_links(html):
            if link not in links:
                links.append(link)
        if not _has_next(html):
            break
        time.sleep(1.0)

    rows: list[dict[str, str]] = []
    # Дата реестра — локальная дата рабочей машины; timestamp в manifest остаётся UTC.
    retrieval_date = datetime.now().astimezone().date().isoformat()
    source_run = raw_dir.parent.name
    for idx, url in enumerate(links, 1):
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(900)
        _check_response(page, response, url)
        html = page.content()
        manifest.append(_save_raw(raw_dir, f"card_{territory}_{idx}", url, html,
                                   response.status if response else None))
        rec = parse_card_html(html, url)
        if rec:
            rows.append(_record_row(rec, territory, query, retrieval_date, source_run))
        time.sleep(1.0)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Браузерный read-only поиск карт в НЭБ")
    parser.add_argument("query", nargs="?", help="один запрос")
    parser.add_argument("--all-queries", action="store_true", help="5 ключевых слов × территории")
    parser.add_argument("--output", type=Path, required=True, help="новый каталог результата")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--max-queries", type=int, default=1,
                        help="ограничение для smoke-теста; для полного прогона укажите 245")
    parser.add_argument("--headed", action="store_true", default=True,
                        help="запускать видимый Chromium (по умолчанию)")
    args = parser.parse_args()
    if not args.query and not args.all_queries:
        parser.error("Укажите запрос или --all-queries")

    args.output.mkdir(parents=True, exist_ok=False)
    raw_dir = args.output / "raw"
    raw_dir.mkdir()
    manifest: list[dict] = []
    rows: list[dict[str, str]] = []
    tasks = [(args.query, "ручной запрос")] if args.query else [
        (f"{kw} {territory}", territory)
        for kw in KEYWORDS for territory in TERRITORIES
    ]
    tasks = tasks[:args.max_queries]

    started = datetime.now(timezone.utc).isoformat()
    try:
        with sync_playwright() as pw:
            browser = _browser(pw, headed=args.headed)
            context = browser.new_context(locale="ru-RU", timezone_id="Europe/Moscow")
            page = context.new_page()
            for n, (query, territory) in enumerate(tasks, 1):
                print(f"[НЭБ browser] {n}/{len(tasks)}: {query}")
                rows.extend(run_query(page, query, territory, args.max_pages, raw_dir, manifest))
            context.close()
            browser.close()
    except AccessBlocked as exc:
        (args.output / "access_stop.txt").write_text(str(exc) + "\n", encoding="utf-8")
        print(f"[НЭБ browser] STOP: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        (args.output / "error.txt").write_text(repr(exc) + "\n", encoding="utf-8")
        print(f"[НЭБ browser] ERROR: {exc}", file=sys.stderr)
        return 1

    csv_path = args.output / "results.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    meta = {
        "source": "neb",
        "transport": "Playwright Chromium clean context",
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "queries": len(tasks),
        "records": len(rows),
        "manifest_entries": len(manifest),
        "status": "completed",
        "raw_dir": str(raw_dir),
    }
    (args.output / "manifest.json").write_text(json.dumps(meta | {"pages": manifest}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[НЭБ browser] готово: {len(rows)} записей; {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
