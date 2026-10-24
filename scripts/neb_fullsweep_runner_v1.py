"""Браузерный сбор публичных карточек НЭБ.

НЭБ отдаёт ``403 Отключите VPN`` обычному requests-клиенту, тогда как чистый
видимый Chromium открывает те же публичные страницы. Этот модуль использует
только новый контекст Playwright без cookies, профиля и авторизации. Он не
обходит CAPTCHA/антибот-защиту: при 401/403 прогон останавливается.

Примеры:
    python -B scripts/modules/scrapers/searcher_neb_browser.py "карта Калужская губерния" \
        --output output/neb_browser_smoke_20260909
    python -B scripts/modules/scrapers/searcher_neb_browser.py --all-queries \
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
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from playwright.sync_api import Browser, Error as PlaywrightError, Page, Playwright, sync_playwright

HERE = Path(__file__).resolve()
MODULES = HERE.parent / "frozen/scripts/modules" if (HERE.parent / "frozen/scripts/modules").is_dir() else HERE.parent / "modules"
sys.path.insert(0, str(MODULES))

from scrapers.neb_card_dom import parse_card  # noqa: E402
import notion_export  # noqa: E402

BASE_URL = "https://rusneb.ru"
SEARCH_URL = f"{BASE_URL}/search/"
KEYWORDS = ["карта", "план", "атлас", "съёмка", "чертёж", "топографическая"]
TARGET_GUBERNIAS = [
    "Калужская губерния", "Пермская губерния",
    "Смоленская губерния", "Ярославская губерния",
]
CATALOG_RE = re.compile(r"^/catalog/[^/]+/?$")
CSV_FIELDS = [
    "source", "record_type", "territory", "query", "title", "year_from",
    "year_to", "identifier", "url", "description", "coverage_status",
    "retrieval_date", "source_run",
    "author", "place", "publisher", "source_lib", "url_viewer", "url_download",
    "bibliography", "extra_json",
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
        "headless": False,
        "channel": "chrome",
        "args": ["--disable-extensions", "--no-first-run", "--no-default-browser-check"],
    }
    if not headed:
        raise ValueError("НЭБ допускает только headed Chrome")
    return pw.chromium.launch(**kwargs)


def _search_url(query: str) -> str:
    return f"{SEARCH_URL}?q={quote(query)}"


def _check_response(page: Page, response, url: str) -> None:
    status = response.status if response else None
    title = page.title()
    h1 = page.locator("h1").first.text_content(timeout=2000) if page.locator("h1").count() else ""
    blocked = status in (401, 403, 429) or "Отключите VPN" in (title or "") or "Отключите VPN" in (h1 or "")
    if blocked:
        raise AccessBlocked(f"НЭБ заблокировал браузерный запрос: status={status}, title={title!r}, url={url}")


def _goto(page: Page, url: str):
    """Переход с классификацией Chromium-ошибки 403 как access_stop."""
    try:
        return page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except PlaywrightError as exc:
        title = page.title()
        h1 = page.locator("h1").first.text_content(timeout=2000) if page.locator("h1").count() else ""
        if "ERR_HTTP_RESPONSE_CODE_FAILURE" in str(exc) or "Отключите VPN" in (title or "") or "Отключите VPN" in (h1 or ""):
            raise AccessBlocked(f"НЭБ заблокировал браузерный запрос: {exc}; title={title!r}, url={url}") from exc
        raise


def _catalog_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    section = soup.select_one("section.search-result")
    if not section:
        return []
    links: list[str] = []
    seen: set[str] = set()
    for a in section.select('a[href^="/catalog/"]'):
        if not CATALOG_RE.fullmatch(a["href"]):
            continue
        href = a["href"].rstrip("/") + "/"
        full = href if href.startswith("http") else BASE_URL + href
        if full not in seen:
            seen.add(full)
            links.append(full)
    return links


def _result_total(html: str) -> int | None:
    """Return a rendered result count only when its label is explicit."""
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    match = re.search(r"(?:Найдено|Результат(?:ов)?)[^0-9]{0,24}([0-9][0-9\s]{0,15})", text, re.I)
    return int(re.sub(r"\s+", "", match.group(1))) if match else None


def _scroll_to_stability(page: Page, pause_ms: int = 1200, stable_rounds: int = 2) -> tuple[list[str], str]:
    """Scroll rendered infinite results; never synthesize a pagination URL."""
    prior: tuple[str, ...] | None = None
    stable = 0
    for _ in range(80):
        page.wait_for_selector("section.search-result", timeout=30000)
        html = page.content()
        links = _catalog_links(html)
        signature = tuple(links)
        if signature == prior:
            stable += 1
            if stable >= stable_rounds:
                return links, html
        else:
            stable = 0
        prior = signature
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(pause_ms)
    raise RuntimeError("search_scroll_not_stable")


def _robots(page: Page, raw_dir: Path, manifest: list[dict]) -> None:
    url = f"{BASE_URL}/robots.txt"
    response = _goto(page, url)
    html = page.content()
    manifest.append(_save_raw(raw_dir, "robots", url, html, response.status if response else None))
    _check_response(page, response, url)
    parser = RobotFileParser()
    parser.parse(page.locator("body").inner_text().splitlines())
    for allowed in (SEARCH_URL, f"{BASE_URL}/catalog/000199_000009_003796403/"):
        if not parser.can_fetch("archive-codex", allowed):
            raise AccessBlocked(f"robots_disallow:{allowed}")


def _identifier(url: str) -> str:
    m = re.search(r"/catalog/([^/]+)/?", url)
    return m.group(1) if m else ""


def _save_raw(raw_dir: Path, label: str, url: str, html: str, status: int | None) -> dict:
    digest = hashlib.sha256(html.encode("utf-8", errors="replace")).hexdigest()
    path = raw_dir / f"{label}_{digest[:16]}.html"
    path.write_text(html, encoding="utf-8")
    return {"url": url, "status": status, "sha256": digest, "bytes": len(html.encode("utf-8")), "path": str(path)}


def _record_row(rec: dict, territory: str, query: str, retrieval_date: str,
                source_run: str) -> dict[str, str]:
    desc = "; ".join(p for p in (
        rec["bibliography"],
        f"Фондодержатель: {rec['meta'].get('Библиотека', '')}" if rec["meta"].get("Библиотека") else "",
        f"Издательство: {rec['meta'].get('Издательство', '')}" if rec["meta"].get("Издательство") else "",
    ) if p)
    return {
        "source": "neb",
        "record_type": "library_card",
        "territory": territory,
        "query": query,
        "title": rec["title"], "year_from": "", "year_to": "", "identifier": rec["identifier"], "url": rec["url"],
        "description": desc,
        "coverage_status": "browser_chromium_public_card",
        "retrieval_date": retrieval_date,
        "source_run": source_run,
        "author": rec["meta"].get("Автор(ы)", ""), "place": rec["meta"].get("Место издания", ""), "publisher": rec["meta"].get("Издательство", ""),
        "source_lib": rec["meta"].get("Библиотека", ""), "url_viewer": rec["viewer_url"],
        "url_download": rec["pdf_url"], "bibliography": rec["bibliography"],
        "extra_json": json.dumps({"raw_meta": rec["meta"], "is_map": rec["is_map"], "catalog_raw": rec["catalog_raw"], "bbk_raw": rec["bbk_raw"]}, ensure_ascii=False),
    }


def _candidate_entry(rec: dict, territory: str, query: str, raw_html: dict) -> dict:
    meta = rec["meta"]
    return {"source": "neb", "territory": territory, "keyword": query, "record": {
        "title": rec["title"], "author": meta.get("Автор(ы)", "") or meta.get("Автор", ""),
        "place": meta.get("Место издания", ""), "publisher": meta.get("Издательство", ""),
        "source_lib": meta.get("Библиотека", ""), "url": rec["url"], "identifier": rec["identifier"],
        "description": rec["bibliography"], "bibliography": rec["bibliography"],
        "url_download": rec["pdf_url"], "url_viewer": rec["viewer_url"],
        "extra": {"raw_meta": meta, "is_map": rec["is_map"], "catalog_raw": rec["catalog_raw"],
                  "bbk_raw": rec["bbk_raw"], "ready_for_import": False, "evidence": {"card_html": raw_html}},
    }}


def _state_path(output: Path, territory: str, keyword: str) -> Path:
    key = hashlib.sha256(f"{territory}|{keyword}|neb".encode("utf-8")).hexdigest()
    return output / "neb_query_state" / f"{key}.json"


def _save_state(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_state(path: Path, territory: str, keyword: str) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"territory": territory, "keyword": keyword, "status": "not_started", "links": [],
            "next_detail_index": 0, "loaded_results": 0, "result_total": None, "object_reviews": []}


def _write_outputs(output: Path) -> dict:
    candidates = output / "records_full.jsonl"
    rows = [json.loads(line) for line in candidates.read_text(encoding="utf-8").splitlines() if line.strip()] if candidates.exists() else []
    export = notion_export.export(candidates, output / "notion_candidates")
    with (output / "results.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for entry in rows:
            record = entry["record"]
            writer.writerow(_record_row({"title": record.get("title", ""), "bibliography": record.get("bibliography", ""),
                "meta": record.get("extra", {}).get("raw_meta", {}), "identifier": record.get("identifier", ""),
                "url": record.get("url", ""), "viewer_url": record.get("url_viewer", ""), "pdf_url": record.get("url_download", ""),
                "is_map": record.get("extra", {}).get("is_map", False), "catalog_raw": record.get("extra", {}).get("catalog_raw", ""),
                "bbk_raw": record.get("extra", {}).get("bbk_raw", "")}, entry["territory"], entry["keyword"], datetime.now().date().isoformat(), output.name))
    return {"rows": export["rows"], "columns": export["columns"], "roundtrip": export["roundtrip"], "ready_for_import": False}


def run_query(page: Page, output: Path, raw_dir: Path, manifest: list[dict], territory: str, keyword: str) -> str:
    state_path = _state_path(output, territory, keyword)
    state = _load_state(state_path, territory, keyword)
    query = f"{keyword} {territory}"
    if state["status"] == "not_started":
        url = _search_url(query)
        response = _goto(page, url)
        _check_response(page, response, url)
        page.wait_for_timeout(1800)
        links, html = _scroll_to_stability(page)
        state.update({"status": "detail_fetch", "links": links, "loaded_results": len(links), "result_total": _result_total(html)})
        manifest.append(_save_raw(raw_dir, f"search_{keyword}_{territory}", url, html, response.status if response else None))
        _save_state(state_path, state)
    candidates = output / "records_full.jsonl"
    with candidates.open("a", encoding="utf-8") as fh:
        for index in range(state["next_detail_index"], len(state["links"])):
            url = state["links"][index]
            try:
                response = _goto(page, url)
                page.wait_for_timeout(900)
                _check_response(page, response, url)
                html = page.content()
                raw_card = _save_raw(raw_dir, f"card_{keyword}_{territory}_{index + 1}", url, html, response.status if response else None)
                manifest.append(raw_card)
                rec = parse_card(html, url)
                if rec["title"]:
                    fh.write(json.dumps(_candidate_entry(rec, territory, keyword, raw_card), ensure_ascii=False) + "\n")
            except AccessBlocked as exc:
                html = page.content()
                raw_card = _save_raw(raw_dir, f"card_blocked_{keyword}_{territory}_{index + 1}", url, html, 403)
                manifest.append(raw_card)
                state["object_reviews"].append({"url": url, "reason": str(exc), "for_review": True, "evidence": raw_card})
            except Exception as exc:
                html = page.content()
                raw_card = _save_raw(raw_dir, f"card_error_{keyword}_{territory}_{index + 1}", url, html, None)
                manifest.append(raw_card)
                state["object_reviews"].append({"url": url, "reason": repr(exc), "for_review": True, "evidence": raw_card})
            finally:
                state["next_detail_index"] = index + 1
                _save_state(state_path, state)
            time.sleep(3.0)
    state["status"] = "reported_end" if state["result_total"] == state["loaded_results"] else "partial"
    state["stop_reason"] = "scroll_count_matches_total" if state["status"] == "reported_end" else "scroll_count_incomplete_or_total_unavailable"
    _save_state(state_path, state)
    return state["status"]


def main() -> int:
    parser = argparse.ArgumentParser(description="НЭБ: headed Chrome, one durable query per invocation")
    parser.add_argument("--gubernias-only", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / "raw_html"
    raw_dir.mkdir(exist_ok=True)
    manifest: list[dict] = []
    tasks = [(territory, keyword) for territory in TARGET_GUBERNIAS for keyword in KEYWORDS]
    pending = next(((t, k) for t, k in tasks if _load_state(_state_path(output, t, k), t, k)["status"] == "not_started"), None)
    if not pending:
        print("[НЭБ] все запросы завершены")
        return 0
    started = datetime.now(timezone.utc).isoformat()
    try:
        with sync_playwright() as pw:
            browser = _browser(pw, headed=True)
            context = browser.new_context(locale="ru-RU", timezone_id="Europe/Moscow")
            page = context.new_page()
            _robots(page, raw_dir, manifest)
            status = run_query(page, output, raw_dir, manifest, *pending)
            context.close()
            browser.close()
    except AccessBlocked as exc:
        (output / "access_stop.txt").write_text(str(exc) + "\n", encoding="utf-8")
        print(f"[НЭБ] STOP: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        (output / "error.txt").write_text(repr(exc) + "\n", encoding="utf-8")
        print(f"[НЭБ] ERROR: {exc}", file=sys.stderr)
        return 2
    export = _write_outputs(output)
    (output / "LAST_ATTEMPT.json").write_text(json.dumps({"started_at": started, "query": pending, "status": status, "raw": manifest, "candidate_export": export, "ready_for_import": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 3 if status == "reported_end" else 2


if __name__ == "__main__":
    raise SystemExit(main())
