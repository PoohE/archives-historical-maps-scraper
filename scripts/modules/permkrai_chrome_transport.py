"""Public read-only browser transport for lib.permkrai.ru.

The library accepts headed Google Chrome on this host while direct TCP clients
time out.  This adapter deliberately starts a clean temporary browser profile:
it neither reads nor reuses the user's Chrome profile, cookies or credentials.
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit


BASE_HOST = "lib.permkrai.ru"


class ChromeTransport:
    """Allowlisted headed Chrome/QUIC fetcher for public PermKrai pages."""

    def __init__(self, timeout_ms: int = 60000):
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._page = None
        self.last_listing_meta = {}

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--enable-quic"],
        )
        self._page = self._browser.new_page(locale="ru-RU")
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._page = self._browser = self._playwright = None
        self.last_listing_meta = {}

    @staticmethod
    def _allowed(url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname != BASE_HOST:
            raise ValueError("PermKrai browser URL outside allowlist")

    def raw(self, url: str):
        """Return runner-compatible public response data without following a redirect."""
        self._allowed(url)
        if self._page is None:
            raise RuntimeError("ChromeTransport must be used as a context manager")
        response = self._page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=self.timeout_ms,
        )
        if response is None:
            raise TimeoutError("Chrome navigation returned no response")
        effective = self._page.url
        self._allowed(effective)
        return (
            response.status,
            response.headers.get("content-type", "text/html"),
            self._page.content().encode("utf-8"),
            "" if response.status == 200 else effective,
            effective,
        )

    def expand_current_listing(self, crawl_delay_seconds: float, max_scrolls: int = 30):
        """Wait for and fully render a public rubric without naming AJAX routes.

        A ``goto(..., wait_until='domcontentloaded')`` snapshot can still be the
        React loading shell.  Discovery is therefore deferred until the observed
        card selector is attached, then scrolling continues until its count is
        stable twice.  The runner persists the returned post-wait DOM even when
        this method reports an unresolved render.
        """
        if self._page is None:
            raise RuntimeError("ChromeTransport must be used as a context manager")
        self._allowed(self._page.url)
        selector = "a.elis-catalog-item"
        loading_html = self._page.content()
        try:
            self._page.wait_for_selector(selector, state="attached", timeout=self.timeout_ms)
        except Exception as exc:
            # Playwright's sync timeout class is deliberately recognized without
            # importing it here, keeping this small transport unit-testable with
            # a fake page.  Other browser errors still fail closed.
            if type(exc).__name__ != "TimeoutError":
                raise
            rendered = self._page.content()
            self.last_listing_meta = {
                "render_wait_selector": selector,
                "render_wait_satisfied": False,
                "render_wait_reason": "selector_timeout",
                "scroll_steps": 0,
                "dom_stable": False,
                "initial_card_count": 0,
                "final_card_count": 0,
                "card_count_sequence": [],
                "loading_html_sha256": hashlib.sha256(loading_html.encode("utf-8")).hexdigest(),
                "rendered_html_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
            }
            return rendered

        cards = self._page.locator(selector)
        prior_count = cards.count()
        counts = [prior_count]
        stable = 0
        steps = 0
        for _ in range(max_scrolls):
            self._page.wait_for_timeout(int(crawl_delay_seconds * 1000))
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self._page.wait_for_timeout(750)
            current_count = cards.count()
            counts.append(current_count)
            steps += 1
            if current_count <= prior_count:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
                prior_count = current_count
        rendered = self._page.content()
        self.last_listing_meta = {
            "render_wait_selector": selector,
            "render_wait_satisfied": True,
            "render_wait_reason": "selector_attached",
            "scroll_steps": steps,
            "dom_stable": stable >= 2,
            "initial_card_count": counts[0],
            "final_card_count": counts[-1],
            "card_count_sequence": counts,
            "loading_html_sha256": hashlib.sha256(loading_html.encode("utf-8")).hexdigest(),
            "rendered_html_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        }
        return rendered
