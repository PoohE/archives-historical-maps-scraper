"""Frozen collector for the public PermKrai maps rubric, GET-only."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

PACKAGE = Path(__file__).resolve().parent
FROZEN, PROJECT = PACKAGE / "frozen", PACKAGE.parents[1]
sys.path[:0] = [str(FROZEN / "scripts/modules"), str(FROZEN / "scripts/modules/scrapers")]
from durable_state import atomic_json, decode_robots_text  # noqa: E402
import classify_stop as stop  # noqa: E402
import notion_export  # noqa: E402
import searcher_permkrai as permkrai  # noqa: E402
from permkrai_chrome_transport import ChromeTransport  # noqa: E402

BASE = "https://lib.permkrai.ru"
ROBOTS = BASE + "/robots.txt"
AGENT = "ArchiveResearchPermKraiMaps/1.0"
NODE_RE = re.compile(r"^/node/(\d+)$")
COLS = tuple(
    key for key in asdict(permkrai.PermRecord())
    if key not in {"extra_json", "card_text", "card_html", "identifiers_raw", "dates_raw", "series_raw"}
)


class FatalStop(RuntimeError):
    pass


class BudgetStop(RuntimeError):
    pass


class CardTransportStop(RuntimeError):
    """A single card exhausted its retries; retain it for review and continue."""


class CoverageReview(RuntimeError):
    pass


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha(path):
    return sha_bytes(Path(path).read_bytes())


def manifest():
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


def verify():
    for base, items in ((FROZEN, manifest()["project_files"]), (PACKAGE, manifest()["package_files"])):
        for relative, digest in items.items():
            path = (base / relative).resolve()
            if not path.is_relative_to(base) or not path.is_file() or sha(path) != digest:
                raise ValueError("Manifest mismatch: " + relative)
    return True


def write_json(path, value):
    atomic_json(path, value)


def line(path, value):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def node_url(url, rubric_id):
    """Canonicalize an explicitly permitted node URL; reject every other route."""
    part = urlsplit(url)
    if part.scheme != "https" or part.netloc != "lib.permkrai.ru" or part.fragment:
        raise FatalStop("url_outside_node_allowlist")
    match = NODE_RE.fullmatch(part.path)
    if not match:
        raise FatalStop("url_outside_node_allowlist")
    node_id = match.group(1)
    params = parse_qsl(part.query, keep_blank_values=True)
    if node_id != str(rubric_id):
        if params:
            raise FatalStop("card_url_has_query")
        return BASE + part.path
    if not params:
        return BASE + part.path
    if len(params) != 1 or params[0][0] != "page" or not params[0][1].isdigit():
        raise FatalStop("rubric_url_has_unapproved_query")
    return urlunsplit(("https", "lib.permkrai.ru", part.path, urlencode(params), ""))


def state_scope(scope):
    return {
        "schema": 1,
        "source": "permkrai",
        "scope_version": scope["scope_version"],
        "rubric_url": scope["rubric_url"],
        "module_sha256": scope["module_sha256"],
    }


def load_state(path, expected):
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("scope") != expected:
        raise ValueError("Rubric state scope mismatch")
    return value


def save_state(path, scope, coverage):
    write_json(path, {"scope": scope, "coverage": coverage})


def ensure_outputs(out):
    jsonl, csv_path = out / "records_full.jsonl", out / "records.csv"
    if jsonl.exists() != csv_path.exists():
        raise ValueError("JSONL/CSV file-set mismatch")
    if not jsonl.exists():
        jsonl.touch()
        with csv_path.open("x", encoding="utf-8-sig", newline="") as handle:
            csv.DictWriter(handle, fieldnames=COLS).writeheader()
        return set()
    entries = [json.loads(row) for row in jsonl.read_text(encoding="utf-8").splitlines() if row.strip()]
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(entries) != len(rows):
        raise ValueError("JSONL/CSV mismatch")
    return {entry["record"]["url"] for entry in entries}


def append_record(out, record, evidence):
    entry = {
        "source": "permkrai",
        "territory": "",
        "keyword": "rubric: Карты, схемы, планы",
        "record": {**asdict(record), "extra": {
            "permkrai_record": asdict(record), "ready_for_import": False, "evidence": evidence,
        }},
    }
    line(out / "records_full.jsonl", entry)
    with (out / "records.csv").open("a", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=COLS).writerow({key: getattr(record, key) for key in COLS})
        handle.flush()
        os.fsync(handle.fileno())


def request(raw, log, url, delay, stage, rubric_id):
    if stage != "robots":
        url = node_url(url, rubric_id)
    for number, backoff in enumerate((0, 5, 15), 1):
        if log["requests"] >= log["request_budget"]:
            raise BudgetStop("request_budget")
        if log["last_request"] is not None:
            time.sleep(max(0, delay - (time.monotonic() - log["last_request"])))
        log["last_request"] = time.monotonic()
        log["requests"] += 1
        event = {"utc": utc(), "id": log["requests"], "method": "GET", "url": url,
                 "stage": stage, "transport_attempt": number}
        line(log["requests_path"], {**event, "event": "request_started"})
        try:
            status, kind, body, location, effective = raw(url)
        except Exception as exc:
            verdict = stop.classify_exception(exc)
            line(log["requests_path"], {**event, "event": "transport_error", **verdict})
            if number == 3:
                if stage == "card":
                    raise CardTransportStop("card_transport_error") from exc
                raise FatalStop("transport_error") from exc
            line(log["requests_path"], {**event, "event": "transport_retry_scheduled", "backoff_seconds": backoff})
            time.sleep(backoff)
            continue
        if stage != "robots":
            effective = node_url(effective, rubric_id)
        verdict = ({"verdict": "robots", "reason": "raw_robots", "signals": [],
                    "evidence": {"url": effective, "status": status}}
                   if stage == "robots" else stop.classify_response(
                       status, kind, body, url=effective, redirect_location=location, profile=stop.PERMKRAI))
        line(log["requests_path"], {**event, "event": "response", "effective_url": effective,
             "status": status, "content_type": kind, "bytes": len(body), "sha256": sha_bytes(body),
             "redirect_location": location, "classifier": verdict})
        if verdict["verdict"] == stop.REAL_BARRIER:
            raise FatalStop("real_barrier:" + verdict["reason"])
        if status != 200 or location or verdict["verdict"] == stop.TRANSPORT_ERROR:
            raise FatalStop("transport_or_http:" + verdict["reason"])
        log["last_response"] = kind, body, effective, verdict
        return SimpleNamespace(text=body.decode("utf-8", "replace"), body=body,
                               effective_url=effective, verdict=verdict)
    raise AssertionError("unreachable")


def robots(raw, log, scope):
    request(raw, log, ROBOTS, 0, "robots", scope["rubric_node_id"])
    kind, body, _, _ = log["last_response"]
    if "text" not in kind.lower():
        raise FatalStop("robots_content_type")
    parsed = RobotFileParser()
    parsed.parse(decode_robots_text(body).splitlines())
    if not parsed.can_fetch(AGENT, scope["rubric_url"]):
        raise FatalStop("robots_disallow_rubric")
    delay = max(float(parsed.crawl_delay(AGENT) or 0), float(scope["min_crawl_delay"]))
    log.update(robots_sha256=sha_bytes(body), crawl_delay=delay)
    return delay


def listing_links(html, current_url, rubric_id):
    soup = BeautifulSoup(html, "html.parser")
    cards, pages = [], []
    # This class is from the saved rendered v5 DOM.  Breadcrumbs, navigation
    # and thematic collections do not carry it, so do not fetch those nodes.
    catalog_anchors = soup.select("a.elis-catalog-item[href][tabindex][aria-label]")
    for anchor in catalog_anchors:
        href = urljoin(current_url, anchor["href"])
        part = urlsplit(href)
        if part.hostname != "lib.permkrai.ru" or part.scheme != "https":
            continue
        match = NODE_RE.fullmatch(part.path)
        if not match:
            continue
        node_id = match.group(1)
        if node_id == str(rubric_id):
            continue
        elif not part.query and not part.fragment:
            listing_title = anchor.get("aria-label", "").strip()
            if not listing_title:
                continue
            cards.append(
                {
                    "url": BASE + part.path,
                    "listing_title": listing_title,
                }
            )
    # Drupal places a pager outside the card grid on some themes.  It may name
    # only the rubric itself; it never contributes a card candidate.
    for anchor in soup.select("a[href]"):
        href = urljoin(current_url, anchor["href"])
        part = urlsplit(href)
        if part.scheme != "https" or part.hostname != "lib.permkrai.ru":
            continue
        if part.path != "/node/" + str(rubric_id):
            continue
        try:
            page = node_url(href, rubric_id)
        except FatalStop:
            continue
        if page != BASE + part.path:
            pages.append(page)
    cards = list({item["url"]: item for item in cards}.values())
    pages = list(dict.fromkeys(pages))
    if not cards and not pages:
        raise CoverageReview("rubric_node_links_not_recognized")
    visible = soup.get_text(" ", strip=True).lower()
    load_more = bool(soup.select_one("[data-load-more], [data-next-page], .load-more, .pager-load-more"))
    load_more = load_more or any(word in visible for word in ("показать еще", "показать ещё", "загрузить еще", "загрузить ещё"))
    return cards, pages, {
        "load_more_signal": load_more,
        "card_links": len(cards),
        "pager_links": len(pages),
        "catalog_anchors": len(catalog_anchors),
        "discovery_selector": "a.elis-catalog-item[href][tabindex][aria-label]",
    }


def save_rendered_html(attempt, url, body, stage):
    """Persist rendered DOM before parsing so selector failures are auditable."""
    node_id = NODE_RE.fullmatch(urlsplit(url).path).group(1)
    digest = sha_bytes(body)
    folder = attempt / "raw_html"
    folder.mkdir(exist_ok=True)
    path = folder / (stage + "_" + node_id + "_" + digest[:12] + ".html")
    if not path.exists():
        with path.open("xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    return {"path": path.relative_to(attempt).as_posix(), "sha256": digest, "bytes": len(body), "stage": stage}


def lock_output(out):
    lock, stale = out / "collector.lock", False
    if lock.exists():
        pid = lock.read_text(encoding="utf-8").strip()
        if not pid.isdigit():
            raise FatalStop("collector_lock_invalid")
        try:
            os.kill(int(pid), 0)
        except PermissionError:
            raise FatalStop("collector_lock_active")
        except (ProcessLookupError, OSError):
            lock.unlink()
            stale = True
        else:
            raise FatalStop("collector_lock_active")
    lock.write_text(str(os.getpid()), encoding="utf-8")
    return lock, stale


def collect(out, raw, scope, live, stale, browser=None):
    tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    attempt = out / "attempts" / tag
    attempt.mkdir(parents=True)
    expected = state_scope(scope)
    seal = {"scope": scope, "manifest_sha256": sha(PACKAGE / "manifest.json")}
    seal_path = out / "run_scope.json"
    if seal_path.exists() and json.loads(seal_path.read_text(encoding="utf-8")) != seal:
        raise ValueError("Run scope mismatch")
    if not seal_path.exists():
        write_json(seal_path, seal)
    state_path = out / "permkrai_rubric_state.json"
    prior = load_state(state_path, expected)
    coverage = (prior or {}).get("coverage") or {
        "status": "starting", "for_review": False, "stop_reason": "",
        "pending_listing_urls": [scope["rubric_url"]], "completed_listing_urls": [],
        "card_candidates": [], "completed_cards": [], "excluded_nodes": [], "review_nodes": [],
        "records": 0, "pagination_mechanism": "unresolved", "full_rubric_complete": False,
    }
    known = ensure_outputs(out)
    log = {"source": "permkrai", "network_mode": "live" if live else "offline_mock",
           "started_at": utc(), "request_budget": scope["max_get_per_invocation"], "requests": 0,
           "last_request": None, "requests_path": attempt / "requests.jsonl", "ready_for_import": False,
           "status": "running", "stale_lock_removed": stale}
    code = 2
    try:
        delay = robots(raw, log, scope)
        while coverage["pending_listing_urls"]:
            page_url = coverage["pending_listing_urls"].pop(0)
            if page_url in coverage["completed_listing_urls"]:
                continue
            response = request(raw, log, page_url, delay, "rubric", scope["rubric_node_id"])
            scroll_meta = {}
            if browser is not None:
                # ``goto`` returns at DOMContentLoaded, which is only the React
                # loading shell for this rubric.  Do not inspect links or persist
                # a diagnostic backstop until the browser has waited and scrolled.
                page_html = browser.expand_current_listing(delay)
                scroll_meta = dict(browser.last_listing_meta)
                raw_listing = save_rendered_html(
                    attempt, page_url, page_html.encode("utf-8"), "rubric_rendered"
                )
                line(log["requests_path"], {"utc": utc(), "event": "rubric_rendered", "url": page_url,
                     "stage": "rubric", **scroll_meta})
                if not scroll_meta.get("render_wait_satisfied"):
                    coverage.update(status="partial", for_review=True, stop_reason="rubric_render_wait_timeout",
                                    last_raw_html=raw_listing)
                    save_state(state_path, expected, coverage)
                    raise CoverageReview("rubric_render_wait_timeout")
                if not scroll_meta.get("dom_stable"):
                    coverage.update(status="partial", for_review=True, stop_reason="rubric_scroll_not_stable")
                    save_state(state_path, expected, coverage)
                    raise CoverageReview("rubric_scroll_not_stable")
            else:
                # Offline fixtures already represent the provided rendering state.
                page_html = response.text
                raw_listing = save_rendered_html(attempt, page_url, response.body, "rubric_static")
            try:
                cards, pages, signals = listing_links(page_html, response.effective_url, scope["rubric_node_id"])
            except CoverageReview as exc:
                coverage.update(status="partial", for_review=True, stop_reason=str(exc),
                                last_raw_html=raw_listing)
                save_state(state_path, expected, coverage)
                raise
            if browser is not None:
                line(log["requests_path"], {"utc": utc(), "event": "rubric_discovery", "url": page_url,
                     "stage": "rubric", **signals})
            if pages:
                coverage["pagination_mechanism"] = "page_parameter"
                for discovered in pages:
                    if discovered not in coverage["completed_listing_urls"] and discovered not in coverage["pending_listing_urls"]:
                        coverage["pending_listing_urls"].append(discovered)
            elif scroll_meta.get("scroll_steps", 0) and coverage["pagination_mechanism"] != "page_parameter":
                coverage["pagination_mechanism"] = "rendered_scroll" if scroll_meta.get("final_card_count", 0) > scroll_meta.get("initial_card_count", 0) else "single_rendered_page"
            elif coverage["pagination_mechanism"] != "page_parameter":
                coverage["pagination_mechanism"] = "single_static_page"
            if signals["load_more_signal"]:
                coverage.update(status="partial", for_review=True, stop_reason="rubric_load_more_unresolved")
                save_state(state_path, expected, coverage)
                raise CoverageReview("rubric_load_more_unresolved")
            for candidate in cards:
                if candidate["url"] not in {
                    item["url"] for item in coverage["card_candidates"]
                }:
                    coverage["card_candidates"].append(candidate)
            coverage["completed_listing_urls"].append(page_url)
            save_state(state_path, expected, coverage)
        for candidate in coverage["card_candidates"]:
            card_url = candidate["url"]
            if card_url in coverage["completed_cards"]:
                continue
            try:
                response = request(raw, log, card_url, delay, "card", scope["rubric_node_id"])
            except CardTransportStop as exc:
                coverage["review_nodes"].append(
                    {
                        "url": card_url,
                        "listing_title": candidate["listing_title"],
                        "kind": "card_transport_error",
                        "reason": str(exc),
                        "transport_attempts": 3,
                    }
                )
                coverage["completed_cards"].append(card_url)
                coverage["for_review"] = True
                save_state(state_path, expected, coverage)
                continue
            raw_card = save_rendered_html(attempt, card_url, response.body, "card")
            kind, classification = permkrai.classify_card_html(
                response.text, require_pdf_node=True
            )
            if kind != "map_card":
                coverage["excluded_nodes"].append({"url": card_url, "kind": kind,
                    "classification": classification, "raw_card_html": raw_card})
                save_state(state_path, expected, coverage)
                continue
            if kind != "map_card":
                coverage["review_nodes"].append({"url": card_url, "kind": kind,
                    "classification": classification, "raw_card_html": raw_card})
                coverage.update(status="partial", for_review=True, stop_reason="rubric_node_unclassified")
                save_state(state_path, expected, coverage)
                raise CoverageReview("rubric_node_unclassified")
            record = permkrai.parse_card_html(response.text, card_url, None, None)
            if record is None:
                coverage["review_nodes"].append({"url": card_url, "kind": "map_card_parse_failed",
                    "classification": classification, "raw_card_html": raw_card})
                coverage.update(status="partial", for_review=True, stop_reason="rubric_card_not_parsed")
                save_state(state_path, expected, coverage)
                raise CoverageReview("rubric_card_not_parsed")
            if card_url not in known:
                append_record(out, record, {"rubric_url": scope["rubric_url"], "card_url": card_url,
                    "effective_url": response.effective_url, "card_sha256": sha_bytes(response.text.encode("utf-8")),
                    "raw_card_html": raw_card, "classification": classification,
                    "pagination_mechanism": coverage["pagination_mechanism"]})
                known.add(card_url)
                coverage["records"] += 1
            coverage["completed_cards"].append(card_url)
            save_state(state_path, expected, coverage)
        reviewed = bool(coverage["review_nodes"])
        coverage.update(
            status="partial" if reviewed else "reported_end",
            stop_reason="card_transport_review" if reviewed else "rubric_and_cards_reported_end",
            for_review=reviewed,
            full_rubric_complete=not reviewed,
        )
        save_state(state_path, expected, coverage)
        code = 2 if reviewed else 0
        log["status"] = "rubric_completed_with_review" if reviewed else "rubric_completed"
    except BudgetStop:
        code, log["status"], log["stop_reason"] = 3, "partial", "request_budget"
    except (FatalStop, CoverageReview) as exc:
        code, log["status"], log["stop_reason"] = 2, "partial", str(exc)
    except Exception as exc:
        code, log["status"], log["stop_reason"], log["error_type"], log["error_message"] = (
            2, "partial", "processing_error", type(exc).__name__, str(exc))
    finally:
        snapshot = load_state(state_path, expected)
        current = (snapshot or {}).get("coverage", coverage)
        write_json(attempt / "coverage.json", current)
        try:
            exported = notion_export.export(out / "records_full.jsonl", attempt / "notion_candidates")
            if exported["columns"] != 65 or exported["roundtrip"] != "passed":
                raise ValueError("candidate_csv_contract")
            log.update(rows=exported["rows"], columns=exported["columns"], roundtrip=exported["roundtrip"])
        except Exception as exc:
            code, log["status"], log["validation_error"] = 1, "validation_failed", str(exc)
        log.update(discovered_node_candidates=len(current["card_candidates"]), completed_cards=len(current["completed_cards"]),
                   excluded_non_map_nodes=len(current["excluded_nodes"]), review_nodes=len(current["review_nodes"]),
                   completed_listing_pages=len(current["completed_listing_urls"]),
                   pagination_mechanism=current["pagination_mechanism"],
                   full_rubric_complete=bool(current["full_rubric_complete"]),
                   frozen_modules_verified=verify(), hashes_after=True, exit_code=code, finished_at=utc())
        for key in ("last_request", "requests_path", "last_response"):
            log.pop(key, None)
        write_json(attempt / "REPORT.json", log)
    return attempt, code


def run(output=None, raw=None, scope=None):
    verify()
    scope = scope or json.loads((PACKAGE / "scope.json").read_text(encoding="utf-8"))
    if raw is None and output is not None:
        raise ValueError("Live output override forbidden")
    live = raw is None
    browser = None
    if live:
        browser = ChromeTransport()
        browser.__enter__()
        raw = browser.raw
    out = Path(output or PROJECT / manifest()["continuation"]["working_output"])
    out.mkdir(parents=True, exist_ok=True)
    lock, stale = lock_output(out)
    try:
        return collect(out, raw, scope, live, stale, browser)
    finally:
        try:
            if browser is not None:
                browser.__exit__(None, None, None)
        finally:
            lock.unlink(missing_ok=True)


def offline_self_test():
    folder = PACKAGE / "tmp_local_validation"
    if folder.exists():
        shutil.rmtree(folder)
    scope = {"scope_version": "fixture", "rubric_url": BASE + "/node/722", "rubric_node_id": 722,
             "min_crawl_delay": 0, "max_get_per_invocation": 10,
             "module_sha256": sha(FROZEN / "scripts/modules/scrapers/searcher_permkrai.py")}
    seen = []
    card = lambda title, year: ("<html><body class='node-type-pdf'><article id='node-1' class='node node-pdf'>"
        "<h1>" + title + "</h1><span>Карта</span>"
        "<dt>Дата публикации</dt><dd>" + year + "</dd><dt>Библиографическое описание</dt><dd>1:100000</dd>"
        "<dt>Фондодержатель</dt><dd>Ф-1</dd><a href='/node/1/pdfbook/download/map.pdf'>PDF</a>"
        "<a href='/node/1?fragment=page-1'>ОТКРЫТЬ</a></article></body></html>").encode()
    def raw(url):
        seen.append(url)
        if url.endswith("/robots.txt"):
            return 200, "text/plain", b"User-agent: *\nAllow: /\n", "", url
        if url == BASE + "/node/722":
            return 200, "text/html", b'<a class="elis-catalog-item" tabindex="100" href="/node/1" aria-label="one">one</a><a href="/node/722?page=1">next</a>', "", url
        if url == BASE + "/node/722?page=1":
            return 200, "text/html", b'<a class="elis-catalog-item" tabindex="100" href="/node/2" aria-label="two">two</a>', "", url
        if url == BASE + "/node/1":
            return 200, "text/html", card("Map one", "1900"), "", url
        if url == BASE + "/node/2":
            return 200, "text/html", card("Map two", "1901"), "", url
        raise AssertionError(url)
    try:
        attempt, code = run(output=folder, raw=raw, scope=scope)
        report = json.loads((attempt / "REPORT.json").read_text(encoding="utf-8"))
        coverage = json.loads((attempt / "coverage.json").read_text(encoding="utf-8"))
        result = {"exit_code": code, "rows": report["rows"], "columns": report["columns"],
                  "roundtrip": report["roundtrip"], "pagination": coverage["pagination_mechanism"],
                  "complete": coverage["full_rubric_complete"], "search_called": any("/search" in url for url in seen),
                  "network_used": False}
        if result != {"exit_code": 0, "rows": 2, "columns": 65, "roundtrip": "passed",
                      "pagination": "page_parameter", "complete": True, "search_called": False, "network_used": False}:
            raise AssertionError(result)
        return result
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--maps-rubric", action="store_true")
    parser.add_argument("--offline-self-test", action="store_true")
    args = parser.parse_args()
    if args.offline_self_test:
        result = offline_self_test()
        write_json(PACKAGE / "LOCAL_VALIDATION.json", result)
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0)
    if not args.maps_rubric:
        parser.error("Only --maps-rubric is authorised")
    attempt, exit_code = run()
    print(attempt)
    raise SystemExit(exit_code)
