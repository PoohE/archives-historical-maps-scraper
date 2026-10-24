"""Minimal recon-first capture for public NEB pages; no bibliographic parsing."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

from playwright.sync_api import Error as PlaywrightError, sync_playwright


BASE_URL = "https://rusneb.ru"
ROBOTS_URL = f"{BASE_URL}/robots.txt"
SEARCH_URL = f"{BASE_URL}/search/?q={quote('карта Калужская губерния')}&access[]=open&catalog[]={quote('Карты')}"
USER_AGENT = "IGRAN-NEB-Recon/1.0"
REQUEST_BUDGET = 3


class ReconStop(RuntimeError):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def chrome_available() -> bool:
    return bool(shutil.which("chrome") or shutil.which("google-chrome") or Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe").is_file())


def has_block_signal(status: int | None, text: str, title: str = "") -> bool:
    lowered = f"{title}\n{text}".lower()
    return status in {401, 403, 429} or any(token in lowered for token in (
        "cloudflare", "captcha", "отключите vpn", "access denied", "just a moment",
    ))


def robots_allows(robots_text: str, url: str) -> bool:
    parser = RobotFileParser()
    parser.parse(robots_text.splitlines())
    return parser.can_fetch(USER_AGENT, url)


def catalog_url_from_html(html: str) -> str | None:
    for href in re.findall(r'''href=["']([^"']+)["']''', html, flags=re.I):
        absolute = urljoin(BASE_URL, href)
        parsed = urlparse(absolute)
        if parsed.scheme == "https" and parsed.netloc == "rusneb.ru" and parsed.path.startswith("/catalog/"):
            return absolute.split("#", 1)[0]
    return None


def save_raw(raw_dir: Path, label: str, url: str, text: str, content_type: str) -> dict:
    digest = sha_text(text)
    target = raw_dir / f"{label}_{digest[:16]}.html"
    target.write_text(text, encoding="utf-8")
    return {
        "label": label, "url": url, "path": str(target), "sha256": digest,
        "bytes": len(text.encode("utf-8", errors="replace")), "content_type": content_type,
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_request(log_path: Path, **event: object) -> None:
    log_path.open("a", encoding="utf-8").write(json.dumps({"utc": utc()} | event, ensure_ascii=False) + "\n")


def stabilize(page, max_scrolls: int = 8) -> tuple[str, dict]:
    counts: list[int] = []
    stable = 0
    for _ in range(max_scrolls):
        count = page.locator("a").count()
        counts.append(count)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(500)
        if len(counts) > 1 and counts[-1] == counts[-2]:
            stable += 1
        else:
            stable = 0
        if stable >= 2:
            return page.content(), {"counts": counts, "stable": True}
    return page.content(), {"counts": counts, "stable": False}


def goto(page, url: str, log_path: Path, stage: str):
    append_request(log_path, method="GET", url=url, stage=stage, event="request_started")
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except PlaywrightError as exc:
        append_request(log_path, method="GET", url=url, stage=stage, event="transport_error", error=repr(exc))
        raise ReconStop("transport_error", repr(exc)) from exc
    html = page.content()
    status = response.status if response else None
    content_type = response.headers.get("content-type", "") if response else ""
    append_request(log_path, method="GET", url=url, stage=stage, event="response", status=status, content_type=content_type)
    if has_block_signal(status, html, page.title()):
        append_request(log_path, method="GET", url=url, stage=stage, event="access_or_challenge", status=status)
    return html, status, content_type


def run(output: Path) -> int:
    if output.exists():
        raise FileExistsError("Refusing to overwrite output: " + str(output))
    output.mkdir(parents=True)
    raw_dir = output / "raw_html"
    raw_dir.mkdir()
    log_path = output / "requests.jsonl"
    captured: list[dict] = []
    report = {
        "source": "neb", "purpose": "recon_first_real_dom_only", "network_mode": "live",
        "ready_for_import": False, "request_budget": REQUEST_BUDGET, "requests": 0,
        "status": "partial", "stop_reason": "", "raw_files": 0, "parsed_records": 0,
        "started_at": utc(),
    }
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=False, args=["--disable-extensions", "--no-first-run"])
            context = browser.new_context(locale="ru-RU", timezone_id="Europe/Moscow")
            page = context.new_page()
            robots_text, status, content_type = goto(page, ROBOTS_URL, log_path, "robots")
            report["requests"] += 1
            captured.append(save_raw(raw_dir, "robots", ROBOTS_URL, robots_text, content_type))
            if has_block_signal(status, robots_text, page.title()):
                raise ReconStop("access_or_challenge", f"status={status}; url={ROBOTS_URL}")
            if "html" in content_type.lower() or not robots_text.strip():
                raise ReconStop("robots_unresolved", f"status={status}; content_type={content_type!r}")
            if not robots_allows(robots_text, SEARCH_URL):
                raise ReconStop("robots_disallow_search", SEARCH_URL)
            search_html, _, content_type = goto(page, SEARCH_URL, log_path, "search")
            report["requests"] += 1
            rendered, render_meta = stabilize(page)
            captured.append(save_raw(raw_dir, "search_rendered", SEARCH_URL, rendered, content_type))
            report["search_render"] = render_meta
            if has_block_signal(status, search_html, page.title()):
                raise ReconStop("access_or_challenge", f"status={status}; url={SEARCH_URL}")
            if not render_meta["stable"]:
                raise ReconStop("search_render_unstable", json.dumps(render_meta, ensure_ascii=False))
            detail_url = catalog_url_from_html(search_html + "\n" + rendered)
            if not detail_url:
                raise ReconStop("catalog_card_not_discovered")
            if not robots_allows(robots_text, detail_url):
                raise ReconStop("robots_disallow_catalog_card", detail_url)
            card_html, _, content_type = goto(page, detail_url, log_path, "card")
            report["requests"] += 1
            card_rendered, card_meta = stabilize(page)
            captured.append(save_raw(raw_dir, "card_rendered", detail_url, card_rendered or card_html, content_type))
            report["card_url"] = detail_url
            report["card_render"] = card_meta
            if has_block_signal(status, card_html, page.title()):
                raise ReconStop("access_or_challenge", f"status={status}; url={detail_url}")
            if not card_meta["stable"]:
                raise ReconStop("card_render_unstable", json.dumps(card_meta, ensure_ascii=False))
            report["status"] = "completed"
            report["stop_reason"] = "recon_complete"
            context.close()
            browser.close()
    except ReconStop as exc:
        report["stop_reason"] = exc.reason
        report["detail"] = exc.detail
    except Exception as exc:
        report["stop_reason"] = "transport_error"
        report["detail"] = repr(exc)
    finally:
        if log_path.exists():
            report["requests"] = sum(
                1 for line in log_path.read_text(encoding="utf-8").splitlines()
                if json.loads(line).get("event") == "request_started"
            )
        report["raw_files"] = len(captured)
        report["finished_at"] = utc()
        write_json(output / "REPORT.json", report)
        write_json(output / "manifest.json", {"captured": captured, "report": "REPORT.json", "requests": "requests.jsonl"})
    return 0 if report["status"] == "completed" else 2


def offline_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="neb-recon-") as temp:
        root = Path(temp)
        raw = root / "raw_html"
        raw.mkdir()
        files = [
            save_raw(raw, "robots", ROBOTS_URL, "User-agent: *\nAllow: /\n", "text/plain"),
            save_raw(raw, "search_rendered", SEARCH_URL, '<a href="/catalog/test/">test</a>', "text/html"),
            save_raw(raw, "card_rendered", f"{BASE_URL}/catalog/test/", "<main>test</main>", "text/html"),
        ]
        assert robots_allows("User-agent: *\nAllow: /\n", SEARCH_URL)
        assert catalog_url_from_html('<a href="/catalog/test/">test</a>') == f"{BASE_URL}/catalog/test/"
        assert len(list(raw.glob("*.html"))) == 3
        print(json.dumps({"network": "not_run", "status": "completed", "raw_files": len(files)}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="NEB recon-first rendered DOM capture")
    parser.add_argument("--output", type=Path, default=Path("output/neb_recon_20260928_v1"))
    parser.add_argument("--offline-self-test", action="store_true")
    args = parser.parse_args()
    if args.offline_self_test:
        return offline_self_test()
    return run(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
