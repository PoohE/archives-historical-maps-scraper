"""PRLIB search transport: cached robots, one allowlisted redirect, one page.
No auth/cookies/proxy, no automatic search redirect or retry; bounded GET/page.
Diagnostic logic adapted from locally verified v3; does not authorize full runs.
"""

import hashlib
import re
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit, parse_qsl, urlencode
from urllib.robotparser import RobotFileParser
from durable_state import decode_robots_text
from bs4 import BeautifulSoup
import classify_stop

AGENT = "ArchiveReviewProbe/1.0"
LIMIT = 2 * 1024 * 1024
ROBOTS = ("https://prlib.ru/robots.txt", "https://www.prlib.ru/robots.txt")
ROBOTS_TTL_SECONDS = 30 * 60
_ROBOTS_CACHE = {}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class AccessBlocked(RuntimeError):
    def __init__(self, reason, report):
        self.reason = reason
        self.report = report
        super().__init__("PRLIB access: " + reason)


def raw_fetch(url):
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(
            Request(url, headers={"User-Agent": AGENT}), timeout=20
        ) as response:
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                response.read(LIMIT + 1),
                "",
            )
    except HTTPError as exc:
        return exc.code, "", b"", exc.headers.get("Location", "")


def reset_robots_cache():
    """Тестовый/новый-run сброс; штатно кэш живёт только в процессе пакета."""
    _ROBOTS_CACHE.clear()


def _allowed_robots_redirect(url, location):
    target = urljoin(url, location) if location else ""
    if target not in ROBOTS or target == url:
        raise AccessBlocked(
            "robots_redirect_outside_allowlist_or_loop",
            {"stop_reason": "robots_redirect_outside_allowlist_or_loop"},
        )
    return target


def robots_policy(fetch):
    """Получить robots-policy с TTL-кэшем; fetch(url, allowlist) ведёт журнал GET."""
    now = time.monotonic()
    cached = _ROBOTS_CACHE.get(ROBOTS[0])
    if cached and now - cached["cached_at"] < ROBOTS_TTL_SECONDS:
        return (
            cached["policy"],
            cached["robots_text"],
            cached["effective_robots_url"],
            True,
            cached["sha256"],
        )
    url = ROBOTS[0]
    status, kind, body, location, item = fetch(url, ROBOTS)
    if status in (301, 302, 307, 308):
        target = _allowed_robots_redirect(url, location)
        item["allowed_redirect"] = target
        time.sleep(3)
        url = target
        status, kind, body, location, item = fetch(url, ROBOTS)
        if status in (301, 302, 307, 308):
            raise AccessBlocked(
                "robots_redirect_limit", {"stop_reason": "robots_redirect_limit"}
            )
    if status != 200 or "html" in kind.lower() or len(body) > LIMIT:
        raise AccessBlocked(
            "robots_not_confirmed", {"stop_reason": "robots_not_confirmed"}
        )
    try:
        robots_text = decode_robots_text(body)
    except TypeError:
        raise AccessBlocked(
            "robots_not_confirmed", {"stop_reason": "robots_not_confirmed"}
        )
    if "user-agent:" not in robots_text.lower():
        raise AccessBlocked(
            "robots_not_confirmed", {"stop_reason": "robots_not_confirmed"}
        )
    policy = RobotFileParser()
    policy.parse(robots_text.splitlines())
    entry = {
        "cached_at": time.monotonic(),
        "policy": policy,
        "robots_text": robots_text,
        "effective_robots_url": url,
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    # prlib.ru -> www.prlib.ru is the only verified allowlisted redirect; cache it as one policy.
    _ROBOTS_CACHE[ROBOTS[0]] = entry
    _ROBOTS_CACHE[url] = entry
    return policy, robots_text, url, False, entry["sha256"]


def sanitize(body, target=None):
    if not target:
        raise ValueError("Target URL required")
    s = BeautifulSoup(body, "html.parser")
    encoding = s.original_encoding
    for node in s.select(
        "script,style,input,textarea,button,footer,nav,meta,link,iframe,object,embed"
    ):
        node.decompose()
    for node in s.select("header"):
        if not node.find_parent("main"):
            node.decompose()
    for form in s.select("form"):
        form.unwrap()
    for node in s.find_all(True):
        node.attrs = {
            k: v
            for k, v in node.attrs.items()
            if k in ("class", "id", "href", "title", "colspan", "rowspan")
        }
        if node.has_attr("href"):
            href = urljoin(target, node["href"])
            u = urlsplit(href)
            if (
                u.scheme != "https"
                or u.hostname != urlsplit(target).hostname
                or any(
                    re.search(r"token|session|cookie|password|auth|sid", k, re.I)
                    for k, v in parse_qsl(u.query)
                )
            ):
                del node["href"]
            else:
                node["href"] = href
    links = []
    for node in s.select("a[href]"):
        label = node.get_text(" ", strip=True)
        url = node["href"]
        if (
            re.search(r"^/item/[0-9]+/?$", urlsplit(url).path)
            and label
            and not any(x["url"] == url for x in links)
        ):
            links.append(
                {
                    "url": url,
                    "label": label,
                    "locator": "a[href]",
                    "status": "candidate_link_not_fetched",
                }
            )
    return str(s).encode("utf-8"), links[:200], encoding


def fetch_page(query, page):
    if (
        not isinstance(query, str)
        or not query.strip()
        or isinstance(page, bool)
        or not isinstance(page, int)
        or page < 0
    ):
        raise ValueError("Invalid PRLIB query/page")
    report = {
        "requests": [],
        "page": page,
        "ready_for_full_search": False,
        "ready_for_import": False,
    }

    def stop(reason):
        report["stop_reason"] = reason
        raise AccessBlocked(reason, report)

    def get(url, allowed):
        if url not in allowed:
            stop("outside_allowlist")
        if len(report["requests"]) >= 3:
            stop("request_budget")
        item = {"url": url, "utc": datetime.now(timezone.utc).isoformat()}
        report["requests"].append(item)
        try:
            status, kind, body, location = raw_fetch(url)
        except Exception as exc:
            item["error_type"] = type(exc).__name__
            stop("transport_error")
        item.update(status=status, content_type=kind, body_saved=False)
        if status == 200:
            item.update(
                received_bytes=len(body),
                received_sha256=hashlib.sha256(body).hexdigest(),
            )
        return status, kind, body, location, item

    try:
        policy, robots_text, robots_url, cache_hit, robots_sha = robots_policy(get)
    except AccessBlocked as exc:
        stop(exc.reason)
    report.update(
        robots_text=robots_text,
        robots_cache="hit" if cache_hit else "miss",
        robots_sha256=robots_sha,
    )
    target = (
        robots_url.rsplit("/", 1)[0]
        + "/collections/467000/search?"
        + urlencode({"text": query, "page": page})
    )
    if not policy.can_fetch(AGENT, target):
        stop("robots_disallow")
    rate = policy.request_rate(AGENT)
    delay = max(
        3, policy.crawl_delay(AGENT) or 0, rate.seconds / rate.requests if rate else 0
    )
    if delay > 60:
        stop("robots_delay_requires_rescheduling")
    time.sleep(delay)
    status, kind, body, location, item = get(target, (target,))
    verdict = classify_stop.classify_response(
        status,
        kind,
        body,
        url=target,
        profile=classify_stop.PRLIB,
        redirect_location=location,
    )
    report["classification"] = verdict
    if verdict["verdict"] == classify_stop.REAL_BARRIER:
        stop(verdict["reason"])
    if verdict["verdict"] == classify_stop.TRANSPORT_ERROR:
        stop(verdict["reason"])
    clean, links, encoding = sanitize(body, target)
    report.update(
        status="diagnostic_evidence_collected",
        stop_reason="",
        effective_url=target,
        sanitized_sha256=hashlib.sha256(clean).hexdigest(),
        input_encoding=encoding,
    )
    return SimpleNamespace(text=clean.decode("utf-8"), url=target, access_report=report)
