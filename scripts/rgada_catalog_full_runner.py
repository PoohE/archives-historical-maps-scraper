"""Frozen RGADA inventory collector; only its package copy is executable."""

import csv
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.robotparser import RobotFileParser

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE / "frozen"
PROJECT = PACKAGE.parents[1]
sys.path.insert(0, str(ROOT / "scripts/modules"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def manifest():
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


def verify():
    m = manifest()
    for base, group in ((ROOT, m["project_files"]), (PACKAGE, m["package_files"])):
        for rel, digest in group.items():
            path = (base / rel).resolve()
            if not path.is_relative_to(base) or sha(path) != digest:
                raise ValueError("Manifest mismatch: " + rel)
    return True


verify()
import classify_stop as stop  # noqa: E402
from durable_state import atomic_json, decode_robots_text  # noqa: E402
from scrapers import searcher_rgada as parser  # noqa: E402

AGENT = "ArchiveReviewProbe/1.0"
BASE = "http://rgada.info/"
ROBOTS = BASE + "robots.txt"
SEARCH = BASE + "poisk/index.php"
FIELDS = ("list_name", "fund_name")
COLS = (
    "source",
    "territory",
    "query_term",
    "keyword",
    "search_field",
    "fund_number",
    "fund_name",
    "list_number",
    "list_name",
    "repository",
    "years",
    "case_count",
    "annotation",
    "url",
    "record_level",
)


class AccessBlocked(RuntimeError):
    def __init__(self, reason, report=None):
        self.reason = reason
        self.report = report or {}
        super().__init__("RGADA access: " + reason)


class BudgetStop(BaseException):
    pass


def allowed_url(url):
    u = urlsplit(url)
    return (
        u.scheme == "http"
        and u.netloc == "rgada.info"
        and u.path in ("/robots.txt", "/poisk/index.php")
        and not u.fragment
    )


def territory_parts(territory):
    if not isinstance(territory, dict):
        raise ValueError("RGADA territory must declare label and search_term")
    label = territory.get("label", "")
    search_term = territory.get("search_term", "")
    if not label or not search_term or " " in search_term.strip():
        raise ValueError("RGADA search_term must be one non-empty term")
    return label, search_term


def query_key(territory):
    _, search_term = territory_parts(territory)
    return search_term + "|rgada"


def state_path(out, key):
    return (
        Path(out)
        / "rgada_query_state"
        / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")
    )


def expected_scope(key, territory, scope):
    label, query = territory_parts(territory)
    return {
        "key": key,
        "territory": label,
        "query": query,
        "query_model": scope["query_model"],
        "keywords": list(scope["keywords"]),
        "fields": list(FIELDS),
        "Sk": 30,
        "state_schema": 2,
        "parser_sha256": sha(Path(parser.__file__)),
        "classifier_sha256": sha(Path(stop.__file__)),
        "state_sha256": sha(Path(sys.modules["durable_state"].__file__)),
    }


def load_state(path, expected):
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("scope") != expected:
        raise ValueError(
            "RGADA resume scope/module hashes changed; use a new run directory"
        )
    return value


def save_state(path, scope, coverage):
    atomic_json(path, {"scope": scope, "coverage": coverage})


def ensure_outputs(out):
    out = Path(out)
    jsonl = out / "records_full.jsonl"
    csv_path = out / "records.csv"
    if jsonl.exists() != csv_path.exists():
        raise ValueError("Partial output file set; preserve files and review")
    if not jsonl.exists():
        jsonl.touch(exist_ok=False)
        with csv_path.open("x", encoding="utf-8-sig", newline="") as handle:
            csv.DictWriter(handle, fieldnames=COLS).writeheader()
        return set()
    rows = [
        json.loads(line)
        for line in jsonl.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    if len(rows) != len(csv_rows):
        raise ValueError("JSONL/CSV mismatch; preserve files and reconcile")
    return {row["record"]["url"] for row in rows}


def record_row(territory, query_term, matched_keywords, field, record):
    return {
        "source": "rgada",
        "territory": territory,
        "query_term": query_term,
        "keyword": "; ".join(matched_keywords),
        "search_field": field,
        "fund_number": record.fund_number,
        "fund_name": record.fund_name,
        "list_number": record.list_number,
        "list_name": record.list_name,
        "repository": record.repository,
        "years": record.years,
        "year_from": record.year_from,
        "year_to": record.year_to,
        "case_count": record.case_count,
        "annotation": record.annotation,
        "url": record.url,
        "record_level": "archival_inventory",
    }


def durable_record(out, row):
    with (out / "records_full.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "source": "rgada",
                    "territory": row["territory"],
                    "keyword": row["keyword"],
                    "record": {
                        "title": "Ф. "
                        + row["fund_number"]
                        + ", оп. "
                        + row["list_number"]
                        + ": "
                        + row["list_name"],
                        "url": row["url"],
                        "year_from": row["year_from"],
                        "year_to": row["year_to"],
                        "description": row["annotation"],
                        "library_id": "rgada",
                        "library_name": "РГАДА (rgada.info)",
                        "extra": {
                            "record_level": "archival_inventory",
                            "fund_number": row["fund_number"],
                            "list_number": row["list_number"],
                            "search_field": row["search_field"],
                            "years_raw": row["years"],
                            "ready_for_import": False,
                        },
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())
    with (out / "records.csv").open("a", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=COLS).writerow(row)
        handle.flush()
        os.fsync(handle.fileno())


def raw_http(url):
    import requests

    if not allowed_url(url):
        raise ValueError("URL outside RGADA allowlist")
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        url, headers={"User-Agent": AGENT}, timeout=25, allow_redirects=False
    )
    return (
        response.status_code,
        response.headers.get("Content-Type", ""),
        response.content,
        response.headers.get("Location", ""),
    )


def get_robots(raw, log):
    status, kind, body, location = raw(ROBOTS)
    log["requests"] += 1
    if status != 200 or "html" in kind.lower() or len(body) > stop.LIMIT:
        raise AccessBlocked("robots_not_confirmed")
    try:
        text = decode_robots_text(body)
    except TypeError:
        raise AccessBlocked("robots_not_confirmed")
    if "user-agent:" not in text.lower():
        raise AccessBlocked("robots_not_confirmed")
    policy = RobotFileParser()
    policy.parse(text.splitlines())
    if not policy.can_fetch(AGENT, SEARCH):
        raise AccessBlocked("robots_disallow")
    rate = policy.request_rate(AGENT)
    delay = max(
        3, policy.crawl_delay(AGENT) or 0, rate.seconds / rate.requests if rate else 0
    )
    if delay > 60:
        raise AccessBlocked("robots_delay_requires_rescheduling")
    log["robots_sha256"] = hashlib.sha256(body).hexdigest()
    log["crawl_delay"] = delay
    return policy, delay


def page_url(field, query, page):
    params = {field: query, "Sk": 30}
    if page > 1:
        params["page"] = page
    return SEARCH + "?" + urlencode(params)


def _field_page_cap(field):
    return dict(stop.RGADA.field_page_caps).get(field)


def _accepted_partial(field, reason):
    return (
        field in stop.RGADA.accepted_partial_fields
        and reason in stop.RGADA.accepted_partial_reasons
    )


def _set_partial_field(coverage, field, page, fingerprints, records, raw_records,
                       raw_keyword_counts, reason, accepted):
    status = "partial_accepted" if accepted else "partial"
    coverage.update(
        status=status,
        stop_reason=reason,
        for_review=not accepted,
        full_search_complete=False,
        accepted_partial_fields=(
            sorted(set(coverage.get("accepted_partial_fields", [])) | {field})
            if accepted else coverage.get("accepted_partial_fields", [])
        ),
        max_page=page,
    )
    coverage["fields"][field] = {
        "status": status,
        "reason": reason,
        "resume_page": page,
        "fingerprints": fingerprints,
        "records": records,
        "raw_records": raw_records,
        "raw_keyword_counts": raw_keyword_counts,
    }
    return accepted


def scan_field(out, scope, territory, field, coverage, known_urls, raw, log, delay):
    territory_label, query_term = territory_parts(territory)
    current = coverage["fields"].get(field, {})
    page = current.get("resume_page", 1)
    fingerprints = list(current.get("fingerprints", []))
    raw_records = current.get("raw_records", 0)
    raw_keyword_counts = dict(current.get("raw_keyword_counts", {}))
    while True:
        cap = _field_page_cap(field)
        if cap is not None and page > cap:
            return _set_partial_field(
                coverage, field, page - 1, fingerprints, current.get("records", 0),
                raw_records, raw_keyword_counts, "page_cap_" + str(cap), True,
            )
        if log["requests"] >= scope["max_get_per_invocation"]:
            raise BudgetStop()
        url = page_url(field, query_term, page)
        if not allowed_url(url):
            raise ValueError("Generated URL outside RGADA allowlist")
        time.sleep(delay)
        try:
            status, kind, body, location = raw(url)
        except Exception as exc:
            verdict = stop.classify_exception(exc)
            coverage.update(
                status="unverified", stop_reason=verdict["reason"], for_review=False
            )
            raise AccessBlocked("transport_error", {"classification": verdict})
        log["requests"] += 1
        verdict = stop.classify_response(
            status, kind, body, url=url, profile=stop.RGADA, redirect_location=location
        )
        coverage.setdefault("classifier_verdicts", []).append(
            {"field": field, "page": page, **verdict}
        )
        if verdict["verdict"] == stop.REAL_BARRIER:
            raise AccessBlocked(verdict["reason"], {"classification": verdict})
        if verdict["verdict"] == stop.TRANSPORT_ERROR:
            raise AccessBlocked(verdict["reason"], {"classification": verdict})
        records, has_next = parser._parse_page(body.decode("utf-8", "replace"))
        fingerprint = hashlib.sha256(body).hexdigest()
        if fingerprint in fingerprints:
            return _set_partial_field(
                coverage, field, page, fingerprints, current.get("records", 0),
                raw_records, raw_keyword_counts, "repeated_page",
                _accepted_partial(field, "repeated_page"),
            )
        fingerprints.append(fingerprint)
        expected_more = verdict["verdict"] == stop.MORE_PAGES
        if expected_more != has_next:
            return _set_partial_field(
                coverage, field, page, fingerprints, current.get("records", 0),
                raw_records, raw_keyword_counts, "pager_classifier_mismatch",
                _accepted_partial(field, "pager_classifier_mismatch"),
            )
        page_keyword_counts = parser.keyword_match_counts(records, scope["keywords"])
        for keyword, count in page_keyword_counts.items():
            raw_keyword_counts[keyword] = raw_keyword_counts.get(keyword, 0) + count
        added = 0
        for rec in records:
            raw_records += 1
            matched_keywords = parser.keyword_matches(rec, scope["keywords"])
            if not matched_keywords or rec.url in known_urls:
                continue
            durable_record(
                out,
                record_row(
                    territory_label, query_term, matched_keywords, field, rec
                ),
            )
            known_urls.add(rec.url)
            added += 1
        current_records = current.get("records", 0) + added
        if verdict["verdict"] == stop.REPORTED_END:
            coverage["fields"][field] = {
                "status": "reported_end",
                "resume_page": page,
                "fingerprints": fingerprints,
                "records": current_records,
                "raw_records": raw_records,
                "raw_keyword_counts": raw_keyword_counts,
            }
            coverage["max_page"] = max(coverage.get("max_page", 0), page)
            return True
        coverage["fields"][field] = {
            "status": "more_pages",
            "resume_page": page + 1,
            "fingerprints": fingerprints,
            "records": current_records,
            "raw_records": raw_records,
            "raw_keyword_counts": raw_keyword_counts,
        }
        coverage["max_page"] = max(coverage.get("max_page", 0), page)
        page += 1
        current = coverage["fields"][field]

def run(output=None, getter=None, test_scope=None):
    verify()
    scope = test_scope or json.loads(
        (PACKAGE / "scope.json").read_text(encoding="utf-8")
    )
    if getter is None and (output is not None or test_scope is not None):
        raise ValueError("Live scope overrides forbidden")
    out = (
        Path(output)
        if output is not None
        else PROJECT / manifest()["continuation"]["working_output"]
    )
    out.mkdir(exist_ok=True)
    lock = out / "collector.lock"
    handle = lock.open("x", encoding="utf-8")
    handle.write(str(os.getpid()))
    handle.flush()
    try:
        return collect(out, scope, getter or raw_http)
    finally:
        handle.close()
        lock.unlink()


def collect(out, scope, raw):
    tag = (
        datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        + "_"
        + uuid.uuid4().hex[:8]
    )
    attempt = out / "attempts" / tag
    attempt.mkdir(parents=True)
    seal = {
        "scope": scope,
        "manifest_sha256": sha(PACKAGE / "manifest.json"),
        "network_mode": "offline_mock" if raw is not raw_http else "live",
    }
    seal_path = out / "run_scope.json"
    if seal_path.exists() and json.loads(seal_path.read_text(encoding="utf-8")) != seal:
        raise ValueError("Run scope mismatch")
    if not seal_path.exists():
        atomic_json(seal_path, seal)
    known = ensure_outputs(out)
    log = {
        "started_at": utc(),
        "requests": 0,
        "source": "rgada",
        "record_level": "archival_inventory",
        "ready_for_import": False,
        "status": "running",
        "stop_reason": "",
    }
    code = 2
    try:
        _, delay = get_robots(raw, log)
        for territory in scope["territories"]:
            key = query_key(territory)
            path = state_path(out, key)
            path.parent.mkdir(exist_ok=True)
            expected = expected_scope(key, territory, scope)
            prior = load_state(path, expected)
            if prior and prior["coverage"].get("status") == "reported_end":
                continue
            coverage = (
                prior["coverage"]
                if prior
                else {
                    "status": "starting",
                    "stop_reason": "",
                    "for_review": False,
                    "full_search_complete": False,
                    "fields": {},
                    "max_page": 0,
                    "classifier_verdicts": [],
                }
            )
            save_state(path, expected, coverage)
            complete = True
            for field in FIELDS:
                if coverage["fields"].get(field, {}).get("status") in (
                    "reported_end", "partial_accepted"
                ):
                    continue
                field_complete = scan_field(
                    out, scope, territory, field, coverage, known, raw, log, delay
                )
                save_state(path, expected, coverage)
                if not field_complete:
                    complete = False
                    break
            if complete:
                accepted = coverage.get("accepted_partial_fields", [])
                coverage.update(
                    status="reported_end",
                    stop_reason=(
                        "pager_reported_end_with_accepted_partial"
                        if accepted else "pager_reported_end"
                    ),
                    for_review=False,
                    full_search_complete=not bool(accepted),
                )
                save_state(path, expected, coverage)
        code = 0
        log.update(status="query_scope_completed")
    except BudgetStop:
        code = 3
        log.update(status="request_budget", stop_reason="request_budget")
    except AccessBlocked as exc:
        code = 2
        log.update(
            status="access_blocked",
            stop_reason=exc.reason,
            classification=exc.report.get("classification", {}),
        )
    except Exception as exc:
        code = 2
        log.update(
            status="processing_error",
            stop_reason="processing_error",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
    finally:
        coverage = []
        reviews = []
        for territory in scope["territories"]:
            key = query_key(territory)
            path = state_path(out, key)
            state = (
                load_state(path, expected_scope(key, territory, scope))["coverage"]
                if path.exists()
                else {}
            )
            item = {
                "key": key,
                "territory": territory_parts(territory)[0],
                "query_term": territory_parts(territory)[1],
                "status": state.get("status", "not_started"),
                "stop_reason": state.get("stop_reason", ""),
                "for_review": bool(state.get("for_review")),
                "max_page": state.get("max_page"),
                "fields": state.get("fields", {}),
            }
            coverage.append(item)
            if item["for_review"]:
                reviews.append(item)
        atomic_json(attempt / "coverage.json", coverage)
        done = sum(x["status"] == "reported_end" for x in coverage)
        if code == 0 and reviews:
            log.update(status="query_scope_review")
        log.update(
            total_queries=len(coverage),
            completed_queries=done,
            queries_for_review=reviews,
            review_queries=len(reviews),
            query_depths={
                x["key"]: x["max_page"] for x in coverage if x["max_page"] is not None
            },
            query_scope_complete=done == len(coverage) and not reviews,
            hashes_after=verify(),
            frozen_modules_verified=True,
        )
        atomic_json(attempt / "REPORT.json", log)
    return attempt, code


if __name__ == "__main__":
    attempt, code = run()
    print(attempt)
    raise SystemExit(code)
