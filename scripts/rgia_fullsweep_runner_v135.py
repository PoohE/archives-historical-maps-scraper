"""RGIA full-sweep source runner. Frozen by its package builder; no live run here."""

from __future__ import annotations
import argparse
import contextlib
import csv
import hashlib
import json
import os
import shutil
import sys
import socket
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import requests
import urllib3.util.connection as urllib3_util_connection

PACKAGE = Path(__file__).resolve().parent
FROZEN = PACKAGE / "frozen"
PROJECT = PACKAGE.parents[1]
sys.path[:0] = [
    str(FROZEN / "scripts/modules"),
    str(FROZEN / "scripts/modules/scrapers"),
]
from durable_state import atomic_json, decode_robots_text  # noqa:E402
import classify_stop as stop  # noqa:E402
import notion_export  # noqa:E402
import searcher_rgia as rgia  # noqa:E402
from rgia_fullscope import GUBERNIAS_ONLY  # noqa:E402

BASE = "https://fgurgia.ru"
ROBOTS = BASE + "/robots.txt"
SEARCH = BASE + "/search"
AGENT = "ArchiveResearchRGIAFull/1.0"
_IPV4_DNS_LOCK = threading.Lock()
COLS = tuple(
    key
    for key in asdict(rgia.RgiaRecord()).keys()
    if key not in {"card_text", "raw_detail"}
)


class FatalStop(RuntimeError):
    pass


class QueryReview(RuntimeError):
    pass


class BudgetStop(RuntimeError):
    pass


class TransportStop(RuntimeError):
    """A retried network failure: preserve state and resume later (exit 3)."""
    def __init__(self, stage, url):
        super().__init__("transport_error:" + stage)
        self.stage = stage
        self.url = url


class HostSoftBan(RuntimeError):
    """All retries failed on a host-level stage; back off before another GET."""
    def __init__(self, stage):
        super().__init__("soft_ban_full_host_failure:" + stage)
        self.stage = stage


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha_bytes(v):
    return hashlib.sha256(v).hexdigest()


def sha(p):
    return sha_bytes(Path(p).read_bytes())


def manifest():
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


def verify():
    for base, items in (
        (FROZEN, manifest()["project_files"]),
        (PACKAGE, manifest()["package_files"]),
    ):
        for rel, digest in items.items():
            path = (base / rel).resolve()
            if not path.is_relative_to(base) or sha(path) != digest:
                raise ValueError("Manifest mismatch: " + rel)
    return True


def write_json(path, value):
    atomic_json(path, value)


def line(path, value):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(value, ensure_ascii=False) + chr(10))
        f.flush()
        os.fsync(f.fileno())


def state_name(key):
    return hashlib.sha256(key.encode()).hexdigest() + ".json"


def query_key(territory, keyword):
    return territory + "|" + keyword + "|rgia"


def query_scope(territory, label, keyword, scope):
    return {
        "state_schema": 1,
        "key": query_key(territory, keyword),
        "territory": territory,
        "territory_label": label,
        "keyword": keyword,
        "query": keyword + " " + territory,
        "year_from": scope["year_from"],
        "year_to": scope["year_to"],
        "detail_mode": "ajax_obj_json",
        "module_sha256": scope["module_sha256"],
    }


def load_state(path, expected):
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("scope") != expected:
        raise ValueError("State scope mismatch: " + path.name)
    return value


def save_state(path, scope, coverage):
    write_json(path, {"scope": scope, "coverage": coverage})


def _session():
    s = requests.Session()
    s.trust_env = False
    s.headers.update(
        {
            "User-Agent": AGENT,
            "Accept": "application/json, text/javascript, text/html, */*; q=0.01",
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Referer": BASE + "/",
        }
    )
    return s


@contextlib.contextmanager
def ipv4_only_dns():
    """Force AF_INET only while one allowlisted RGIA GET establishes a socket.

    This urllib3 release resolves the family through `urllib3.util.connection`.
    Patch that binding under a lock and restore it immediately.  The process-wide socket policy
    and every other archive remain untouched outside this narrow request.
    """
    with _IPV4_DNS_LOCK:
        original_util = urllib3_util_connection.allowed_gai_family
        try:
            urllib3_util_connection.allowed_gai_family = lambda: socket.AF_INET
            yield
        finally:
            urllib3_util_connection.allowed_gai_family = original_util


def raw_http(session, url, params=None):
    part = urlsplit(url)
    if part.scheme != "https" or part.netloc != "fgurgia.ru":
        raise FatalStop("url_outside_allowlist")
    with ipv4_only_dns():
        r = session.get(url, params=params, timeout=25, allow_redirects=False)
    return (
        r.status_code,
        r.headers.get("Content-Type", ""),
        r.content,
        r.headers.get("Location", ""),
        r.url,
    )


def ensure_outputs(out):
    jsonl, csvp = out / "records_full.jsonl", out / "records.csv"
    if jsonl.exists() != csvp.exists():
        raise ValueError("JSONL/CSV file-set mismatch")
    if not jsonl.exists():
        jsonl.touch()
        with csvp.open("x", encoding="utf-8-sig", newline="") as f:
            csv.DictWriter(f, fieldnames=COLS).writeheader()
        return set()
    entries = [
        json.loads(x)
        for x in jsonl.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    with csvp.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(entries) != len(rows):
        raise ValueError("JSONL/CSV mismatch")
    return {x["record"]["url"] for x in entries}


def append_record(out, territory, keyword, rec, evidence):
    record_data = asdict(rec)
    raw_detail = record_data.pop("raw_detail", {})
    entry = {
        "source": "rgia",
        "territory": territory,
        "keyword": keyword,
        "record": {
            **record_data,
            "extra": {
                "rgia_detail": True,
                "raw_detail": raw_detail,
                "record_level": "archival_case",
                "ready_for_import": False,
                "evidence": evidence,
            },
        },
    }
    line(out / "records_full.jsonl", entry)
    with (out / "records.csv").open("a", encoding="utf-8", newline="") as f:
        csv.DictWriter(f, fieldnames=COLS).writerow(
            {key: record_data[key] for key in COLS}
        )
        f.flush()
        os.fsync(f.fileno())


def request(raw, log, url, params, delay, stage):
    backoffs = tuple(log["transport_retry_backoff_seconds"])
    if stage == "object":
        backoffs = backoffs[:1]
    for transport_attempt in range(1, len(backoffs) + 2):
        if log["requests"] >= log["request_budget"]:
            raise BudgetStop("request_budget")
        if log["last_request"] is not None:
            time.sleep(max(0, delay - (time.monotonic() - log["last_request"])))
        log["last_request"] = time.monotonic()
        log["requests"] += 1
        event = {
            "utc": utc(),
            "id": log["requests"],
            "method": "GET",
            "url": url,
            "params": params or {},
            "transport_attempt": transport_attempt,
            "stage": stage,
        }
        line(log["requests_path"], {**event, "event": "request_started"})
        try:
            status, kind, body, location, effective = raw(url, params)
        except Exception as exc:
            line(
                log["requests_path"],
                {**event, "event": "transport_error", "error_type": type(exc).__name__},
            )
            if transport_attempt == len(backoffs) + 1:
                if stage in {"robots", "search", "tree"}:
                    raise HostSoftBan(stage) from exc
                raise TransportStop(stage, url) from exc
            backoff = backoffs[transport_attempt - 1]
            line(
                log["requests_path"],
                {
                    **event,
                    "event": "transport_retry_scheduled",
                    "backoff_seconds": backoff,
                },
            )
            time.sleep(backoff)
            continue
        response = {
            **event,
            "event": "response",
            "effective_url": effective,
            "status": status,
            "content_type": kind,
            "bytes": len(body),
            "sha256": sha_bytes(body),
            "redirect_location": location,
        }
        line(log["requests_path"], response)
        if status in (401, 403, 407, 429):
            raise FatalStop("real_barrier:http_" + str(status))
        if status != 200 or location:
            raise FatalStop("http_or_redirect")
        log["successful_gets"] = log.get("successful_gets", 0) + 1
        return body, kind, effective
    raise AssertionError("unreachable")


def robots(raw, log, scope):
    body, kind, _ = request(raw, log, ROBOTS, None, 0, "robots")
    if "text" not in kind.lower():
        raise FatalStop("robots_content_type")
    p = RobotFileParser()
    p.parse(decode_robots_text(body).splitlines())
    if not all(
        p.can_fetch(AGENT, url)
        for url in (SEARCH, BASE + "/ajax/tree/1", BASE + "/ajax/obj/1/1")
    ):
        raise FatalStop("robots_disallow")
    delay = max(float(p.crawl_delay(AGENT) or 0), scope["min_crawl_delay"])
    log.update(robots_sha256=sha_bytes(body), crawl_delay=delay)
    return delay


def search_params(server_query, scope):
    return {
        "p0.v": server_query,
        "type": "simple",
        "p0.c": str(scope["tree_page_size"]),
        "p0.a": str(scope["simple_component_id"]),
    }


def process_query(
    out, attempt, raw, log, delay, scope, territory, label, keyword, known
):
    return process_query_v13(out, attempt, raw, log, delay, scope, territory, label, keyword, known)


def _cursor(cov):
    return (cov.get("phase"), cov.get("next_tree_page"), cov.get("next_detail_index"), len(cov.get("object_ids", [])), len(cov.get("completed_ids", [])))


def process_query_v13(out, attempt, raw, log, delay, scope, territory, label, keyword, known):
    """Resume tree enumeration and detail fetch from durable intra-query cursors."""
    expected = query_scope(territory, label, keyword, scope)
    path = out / "rgia_query_state" / state_name(expected["key"])
    path.parent.mkdir(exist_ok=True)
    prior = load_state(path, expected)
    if prior and prior["coverage"].get("status") == "reported_end":
        return "reported_end"
    cov = (prior or {}).get("coverage", {
        "status": "starting", "for_review": False, "stop_reason": "",
        "phase": "tree_enumeration", "next_tree_page": 1, "next_detail_index": 0,
        "pages_completed": [], "object_ids": [], "completed_ids": [],
        "classifier_verdicts": [], "records": 0,
    })
    cov.setdefault("phase", "tree_enumeration")
    cov.setdefault("next_tree_page", max(cov.get("pages_completed") or [], default=0) + 1)
    cov.setdefault("next_detail_index", len(cov.get("completed_ids", [])))
    before = _cursor(cov)
    server_query = rgia._rgia_search_terms(expected["query"])
    try:
        body, kind, effective = request(raw, log, SEARCH, search_params(server_query, scope), delay, "search")
        verdict = stop.classify_response(200, kind, body, url=effective, profile=stop.RGIA)
        cov["classifier_verdicts"].append({"stage": "search", **verdict})
        index = rgia._extract_search_index(body.decode("utf-8", "replace"))
        if not index:
            if verdict["verdict"] == stop.REPORTED_END:
                cov.update(status="reported_end", stop_reason="search_reported_end", for_review=False)
                save_state(path, expected, cov)
                return "reported_end"
            cov.update(status="partial", stop_reason="search_index_missing", for_review=True)
            save_state(path, expected, cov)
            raise QueryReview("search_index_missing")
        cov["search_index_last"] = index
        if cov["phase"] == "tree_enumeration":
            root_body, _, _ = request(raw, log, rgia.TREE_URL.format(index), rgia._tree_params(1), delay, "tree")
            roots = json.loads(root_body.decode("utf-8"))
            if not roots:
                cov.update(status="reported_end", stop_reason="empty_tree_reported_end", empty_result=True,
                           records=0, phase="complete", for_review=False)
                save_state(path, expected, cov)
                return "reported_end"
            root_id = rgia._cases_root(roots)
            if not root_id:
                cov.update(status="partial", stop_reason="cases_root_missing", for_review=True)
                save_state(path, expected, cov)
                raise QueryReview("cases_root_missing")
            cov["root_id"] = root_id
            page = int(cov["next_tree_page"])
            max_tree_page = int(cov.get("max_tree_page") or page)
            while page <= max_tree_page:
                nodes_body, _, _ = request(raw, log, rgia.TREE_URL.format(index), rgia._tree_params(page, root_id), delay, "tree")
                nodes = json.loads(nodes_body.decode("utf-8"))
                max_tree_page = max(max_tree_page, rgia._tree_page_count(nodes))
                page_ids = rgia._case_node_ids(nodes)
                if not page_ids:
                    cov.update(status="partial", stop_reason="tree_page_no_new_ids", for_review=True)
                    save_state(path, expected, cov)
                    raise QueryReview("tree_page_no_new_ids")
                for object_id in page_ids:
                    if object_id not in cov["object_ids"]:
                        cov["object_ids"].append(object_id)
                cov.update(status="partial", phase="tree_enumeration", next_tree_page=page + 1,
                           pages_completed=sorted(set(cov["pages_completed"] + [page])),
                           max_tree_page=max_tree_page, tree_pagination="nPage")
                save_state(path, expected, cov)
                page += 1
            cov.update(status="details_pending", phase="detail_fetch", next_detail_index=int(cov.get("next_detail_index", 0)))
            save_state(path, expected, cov)
        ids = cov["object_ids"]
        for idx in range(int(cov["next_detail_index"]), len(ids)):
            object_id = ids[idx]
            url = BASE + "/object/" + object_id
            if object_id not in cov["completed_ids"] and url not in known:
                try:
                    detail, _, _ = request(raw, log, BASE + "/ajax/obj/" + object_id + "/" + index, {"children": "false"}, delay, "object")
                except TransportStop as exc:
                    cov.setdefault("object_transport_review", []).append({"object_id": object_id, "url": url, "reason": str(exc), "attempts": 2})
                    cov["for_review"] = True
                else:
                    detail_json = json.loads(detail.decode("utf-8"))
                    detail_class = rgia.classify_detail_object(detail_json)
                    if detail_class["kind"] != "archival_case":
                        cov.setdefault("noncase_review", []).append({"object_id": object_id, "url": url, "detail_sha256": sha_bytes(detail), "classification": detail_class})
                    else:
                        record = rgia._parse_object_json(detail_json, url)
                        if not ((record.year_to and record.year_to < scope["year_from"]) or (record.year_from and record.year_from > scope["year_to"])):
                            append_record(out, territory, keyword, record, {"object_id": object_id, "detail_sha256": sha_bytes(detail), "search_index": index, "query": server_query, "detail_classification": detail_class})
                            known.add(url)
                            cov["records"] += 1
            if object_id not in cov["completed_ids"]:
                cov["completed_ids"].append(object_id)
            cov.update(status="details_pending", phase="detail_fetch", next_detail_index=idx + 1)
            save_state(path, expected, cov)
        cov.update(status="reported_end", stop_reason="tree_and_detail_reported_end",
                   for_review=bool(cov.get("noncase_review") or cov.get("object_transport_review")),
                   full_search_complete=not bool(cov.get("object_transport_review")))
        save_state(path, expected, cov)
        return "reported_end"
    except BudgetStop:
        if _cursor(cov) == before:
            cov.update(status="partial", stop_reason="no_forward_progress", for_review=True)
            save_state(path, expected, cov)
            raise QueryReview("no_forward_progress")
        cov.update(status="partial", stop_reason="request_budget")
        save_state(path, expected, cov)
        raise


def process_query_v12_legacy(
    out, attempt, raw, log, delay, scope, territory, label, keyword, known
):
    expected = query_scope(territory, label, keyword, scope)
    path = out / "rgia_query_state" / state_name(expected["key"])
    path.parent.mkdir(exist_ok=True)
    prior = load_state(path, expected)
    if prior and prior["coverage"].get("status") == "reported_end":
        return "reported_end"
    cov = (prior or {}).get(
        "coverage",
        {
            "status": "starting",
            "for_review": False,
            "stop_reason": "",
            "pages_completed": [],
            "object_ids": [],
            "completed_ids": [],
            "classifier_verdicts": [],
            "records": 0,
        },
    )
    server_query = rgia._rgia_search_terms(expected["query"])
    body, kind, effective = request(
        raw, log, SEARCH, search_params(server_query, scope), delay, "search"
    )
    verdict = stop.classify_response(200, kind, body, url=effective, profile=stop.RGIA)
    cov["classifier_verdicts"].append({"stage": "search", **verdict})
    index = rgia._extract_search_index(body.decode("utf-8", "replace"))
    if not index:
        if verdict["verdict"] == stop.REPORTED_END:
            cov.update(
                status="reported_end",
                stop_reason="search_reported_end",
                for_review=False,
            )
            save_state(path, expected, cov)
            return "reported_end"
        cov.update(
            status="partial", stop_reason="search_index_missing", for_review=True
        )
        save_state(path, expected, cov)
        raise QueryReview("search_index_missing")
    root_body, _, _ = request(
        raw, log, rgia.TREE_URL.format(index), rgia._tree_params(1), delay, "tree"
    )
    root = json.loads(root_body.decode("utf-8"))
    root_id = rgia._cases_root(root)
    if not root_id:
        cov.update(status="partial", stop_reason="cases_root_missing", for_review=True)
        save_state(path, expected, cov)
        raise QueryReview("cases_root_missing")
    # jstree uses nPage, while its page parameter stays at 1.  The first
    # response carries a counter node (1,1,1,2,N); every nPage must be read.
    ids, pages, fingerprints = [], [], []
    max_tree_page = 1
    tree_page = 1
    while tree_page <= max_tree_page:
        nodes_body, _, _ = request(
            raw, log, rgia.TREE_URL.format(index),
            rgia._tree_params(tree_page, root_id), delay, "tree"
        )
        nodes = json.loads(nodes_body.decode("utf-8"))
        if tree_page == 1:
            max_tree_page = rgia._tree_page_count(nodes)
        page_ids = [object_id for object_id in rgia._case_node_ids(nodes) if object_id not in ids]
        if not page_ids:
            cov.update(
                status="partial", stop_reason="tree_page_no_new_ids", for_review=True,
                pages_completed=pages, max_tree_page=max_tree_page,
                tree_pagination="nPage",
            )
            save_state(path, expected, cov)
            raise QueryReview("tree_page_no_new_ids")
        ids.extend(page_ids)
        pages.append(tree_page)
        fingerprints.append(sha_bytes(nodes_body))
        tree_page += 1
    if not ids:
        cov.update(status="partial", stop_reason="case_node_missing", for_review=True)
        save_state(path, expected, cov)
        raise QueryReview("case_node_missing")
    cov.update(
        status="details_pending",
        object_ids=ids,
        pages_completed=pages,
        tree_fingerprints=fingerprints,
        max_tree_page=max_tree_page,
        tree_pagination="nPage",
        search_index_last=index,
    )
    save_state(path, expected, cov)
    for object_id in ids:
        url = BASE + "/object/" + object_id
        if object_id in cov["completed_ids"] or url in known:
            continue
        try:
            detail, _, _ = request(
                raw,
                log,
                BASE + "/ajax/obj/" + object_id + "/" + index,
                {"children": "false"},
                delay,
                "object",
            )
        except TransportStop as exc:
            cov.setdefault("object_transport_review", []).append(
                {"object_id": object_id, "url": url, "reason": str(exc), "attempts": 2}
            )
            cov["completed_ids"].append(object_id)
            cov["for_review"] = True
            save_state(path, expected, cov)
            continue
        detail_json = json.loads(detail.decode("utf-8"))
        detail_class = rgia.classify_detail_object(detail_json)
        if detail_class["kind"] != "archival_case":
            cov.setdefault("noncase_review", []).append(
                {
                    "object_id": object_id,
                    "url": url,
                    "detail_sha256": sha_bytes(detail),
                    "classification": detail_class,
                }
            )
            cov["completed_ids"].append(object_id)
            save_state(path, expected, cov)
            continue
        record = rgia._parse_object_json(detail_json, url)
        if (record.year_to and record.year_to < scope["year_from"]) or (
            record.year_from and record.year_from > scope["year_to"]
        ):
            cov["completed_ids"].append(object_id)
            save_state(path, expected, cov)
            continue
        append_record(
            out,
            territory,
            keyword,
            record,
            {
                "object_id": object_id,
                "detail_sha256": sha_bytes(detail),
                "search_index": index,
                "query": server_query,
                "detail_classification": detail_class,
            },
        )
        known.add(url)
        cov["completed_ids"].append(object_id)
        cov["records"] += 1
        save_state(path, expected, cov)
    cov.update(
        status="reported_end",
        stop_reason="tree_and_detail_reported_end",
        for_review=bool(cov.get("noncase_review") or cov.get("object_transport_review")),
        full_search_complete=not bool(cov.get("object_transport_review")),
    )
    save_state(path, expected, cov)
    return "reported_end"


def query_progress(out, scope, current=None):
    """Persist the exact next query independently of a summary REPORT.

    `completed_queries` is derived at the end of an attempt; this checkpoint
    makes the query-to-query transition durable while a slow drain stops
    between attempts.
    """
    states = []
    for territory, label in scope["territories"]:
        for keyword in scope["keywords"]:
            expected = query_scope(territory, label, keyword, scope)
            path = out / "rgia_query_state" / state_name(expected["key"])
            state = load_state(path, expected)["coverage"] if path.exists() else {}
            states.append(
                {
                    "key": expected["key"],
                    "territory": territory,
                    "keyword": keyword,
                    "status": state.get("status", "not_started"),
                }
            )
    next_query = next((item for item in states if item["status"] != "reported_end"), None)
    checkpoint = {
        "state_schema": 1,
        "updated_at": utc(),
        "completed_queries": sum(item["status"] == "reported_end" for item in states),
        "total_queries": len(states),
        "current_query": current,
        "next_query": next_query,
    }
    atomic_json(out / "query_progress.json", checkpoint)
    return checkpoint


def host_backoff_path(out):
    return out / "host_backoff.json"


def host_backoff_active(out):
    path = host_backoff_path(out)
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    until = value.get("next_allowed_at", "")
    try:
        remaining = max(0, int((datetime.fromisoformat(until) - datetime.now(timezone.utc)).total_seconds()))
    except ValueError:
        raise ValueError("Invalid host_backoff timestamp")
    return {**value, "remaining_seconds": remaining} if remaining else None


def register_host_soft_ban(out, stage, scope):
    previous = {}
    path = host_backoff_path(out)
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
    failures = int(previous.get("consecutive_full_host_failures", 0)) + 1
    delays = tuple(scope["soft_ban_backoff_seconds"])
    delay = delays[min(failures - 1, len(delays) - 1)]
    value = {
        "state_schema": 1,
        "updated_at": utc(),
        "stage": stage,
        "consecutive_full_host_failures": failures,
        "backoff_seconds": delay,
        "next_allowed_at": (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(),
        "stop_after_failures": scope["soft_ban_max_consecutive"],
    }
    atomic_json(path, value)
    return value


def clear_host_soft_ban(out):
    path = host_backoff_path(out)
    if path.exists():
        atomic_json(path, {"state_schema": 1, "updated_at": utc(), "consecutive_full_host_failures": 0})


def migrate_v133_gubernias(out, scope):
    """Copy v13.3 candidates; preserve completed queries and retry empty tree."""
    source_value = manifest()["continuation"].get("migration_from_gubernias")
    if not source_value:
        return None
    source = PROJECT / source_value
    if not source.is_dir():
        return None
    if any(out.iterdir()):
        return None
    source_jsonl, source_csv = source / "records_full.jsonl", source / "records.csv"
    if not source_jsonl.exists() or not source_csv.exists():
        return None
    shutil.copy2(source_jsonl, out / "records_full.jsonl")
    shutil.copy2(source_csv, out / "records.csv")
    source_states = source / "rgia_query_state"
    target_states = out / "rgia_query_state"
    target_states.mkdir()
    migrated, reset_queries = [], []
    if source_states.is_dir():
        for territory, label in scope["territories"]:
            for keyword in scope["keywords"]:
                expected = query_scope(territory, label, keyword, scope)
                name = state_name(expected["key"])
                source_path = source_states / name
                if not source_path.exists():
                    continue
                value = json.loads(source_path.read_text(encoding="utf-8"))
                coverage = value.get("coverage", {})
                if coverage.get("stop_reason") == "cases_root_missing":
                    coverage = {
                        "status": "not_started",
                        "for_review": False,
                        "stop_reason": "",
                        "phase": "tree_enumeration",
                        "next_tree_page": 1,
                        "next_detail_index": 0,
                        "pages_completed": [],
                        "object_ids": [],
                        "completed_ids": [],
                        "classifier_verdicts": [],
                        "records": 0,
                    }
                    reset_queries.append(expected["key"])
                save_state(target_states / name, expected, coverage)
                migrated.append({"key": expected["key"], "status": coverage.get("status", "not_started")})
    progress = query_progress(out, scope)
    report = {
        "source_output": str(source),
        "source_records_sha256": sha(source_jsonl),
        "source_csv_sha256": sha(source_csv),
        "migrated_queries": migrated,
        "reset_queries": reset_queries,
        "migrated_records": sum(1 for line in source_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()),
        "completed_queries": progress["completed_queries"],
        "next_query": progress["next_query"],
        "ready_for_import": False,
    }
    atomic_json(out / "MIGRATION_FROM_V13_3.json", report)
    return report


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


def run(output=None, raw=None, test_scope=None, gubernias_only=False):
    verify()
    scope = test_scope or json.loads(
        (PACKAGE / "scope.json").read_text(encoding="utf-8")
    )
    if gubernias_only:
        scope = {
            **scope,
            "territories": [list(x) for x in GUBERNIAS_ONLY],
            "scope_variant": "gubernias_only",
        }
    if raw is None and (output is not None or test_scope is not None):
        raise ValueError("Live scope overrides forbidden")
    live = raw is None
    if live:
        session = _session()

        def raw(url, params=None):
            return raw_http(session, url, params)

    out = Path(
        output
        or PROJECT
        / manifest()["continuation"][
            "working_output" + ("_gubernias" if gubernias_only else "")
        ]
    )
    out.mkdir(exist_ok=True)
    migrated = None
    if live and gubernias_only:
        migrated = migrate_v133_gubernias(out, scope)
    lock, stale = lock_output(out)
    try:
        return collect(out, scope, raw, live, stale=stale, migration=migrated)
    finally:
        lock.unlink(missing_ok=True)


def collect(out, scope, raw, live, stale=False, migration=None):
    tag = (
        datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        + "_"
        + uuid.uuid4().hex[:8]
    )
    attempt = out / "attempts" / tag
    attempt.mkdir(parents=True)
    seal = {"scope": scope, "manifest_sha256": sha(PACKAGE / "manifest.json")}
    sealpath = out / "run_scope.json"
    if sealpath.exists() and json.loads(sealpath.read_text(encoding="utf-8")) != seal:
        raise ValueError("Run scope mismatch")
    if not sealpath.exists():
        write_json(sealpath, seal)
    known = ensure_outputs(out)
    log = {
        "source": "rgia",
        "network_mode": "live" if live else "offline_mock",
        "started_at": utc(),
        "request_budget": scope["max_get_per_invocation"],
        "requests": 0,
        "successful_gets": 0,
        "last_request": None,
        "requests_path": attempt / "requests.jsonl",
        "transport_retry_backoff_seconds": scope["transport_retry_backoff_seconds"],
        "per_query_mode": bool(scope.get("per_query_mode")),
        "per_query_cooldown_seconds": scope.get("per_query_cooldown_seconds", 0),
        "next_invocation_delay_seconds": 0,
        "stale_lock_removed": stale,
        "migration": migration,
        "ready_for_import": False,
        "status": "running",
        "stop_reason": "",
    }
    code = 2
    reviews = []
    try:
        active_backoff = host_backoff_active(out)
        if active_backoff:
            code = 3
            log.update(
                status="soft_ban_backoff_active",
                stop_reason="soft_ban_backoff_active",
                soft_ban=active_backoff,
                next_invocation_delay_seconds=active_backoff["remaining_seconds"],
            )
        else:
            delay = robots(raw, log, scope)
            progress = query_progress(out, scope)
            next_query = progress["next_query"]
            if next_query is None:
                clear_host_soft_ban(out)
                code = 0
                log.update(status="query_scope_completed")
            else:
                territory, keyword = next_query["territory"], next_query["keyword"]
                label = next(
                    item[1] for item in scope["territories"] if item[0] == territory
                )
                expected = query_scope(territory, label, keyword, scope)
                current = {
                    "key": expected["key"],
                    "territory": territory,
                    "keyword": keyword,
                }
                query_progress(out, scope, current=current)
                try:
                    process_query(
                        out,
                        attempt,
                        raw,
                        log,
                        delay,
                        scope,
                        territory,
                        label,
                        keyword,
                        known,
                    )
                except QueryReview as exc:
                    reviews.append(
                        {
                            "key": query_key(territory, keyword),
                            "territory": territory,
                            "keyword": keyword,
                            "reason": str(exc),
                        }
                    )
                    code = 2
                    log.update(status="query_review", stop_reason=str(exc))
                else:
                    progress = query_progress(out, scope)
                    clear_host_soft_ban(out)
                    if progress["next_query"] is None:
                        code = 0
                        log.update(status="query_scope_completed")
                    else:
                        code = 3
                        log.update(
                            status="query_completed_cooldown",
                            stop_reason="per_query_cooldown",
                            next_invocation_delay_seconds=scope["per_query_cooldown_seconds"],
                        )
    except BudgetStop:
        code = 3
        log.update(
            status="partial",
            stop_reason="request_budget",
            next_invocation_delay_seconds=scope["per_query_cooldown_seconds"],
        )
    except HostSoftBan as exc:
        soft_ban = register_host_soft_ban(out, exc.stage, scope)
        stop_human = (
            soft_ban["consecutive_full_host_failures"]
            >= scope["soft_ban_max_consecutive"]
        )
        code = 2 if stop_human else 3
        log.update(
            status="soft_ban_stop_human" if stop_human else "soft_ban_backoff",
            stop_reason=str(exc),
            soft_ban=soft_ban,
            next_invocation_delay_seconds=0 if stop_human else soft_ban["backoff_seconds"],
        )
    except TransportStop as exc:
        code = 3
        log.update(
            status="partial",
            stop_reason=str(exc),
            next_invocation_delay_seconds=scope["per_query_cooldown_seconds"],
        )
    except FatalStop as exc:
        code = 2
        log.update(status="stopped", stop_reason=str(exc))
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
        for territory, label in scope["territories"]:
            for keyword in scope["keywords"]:
                expected = query_scope(territory, label, keyword, scope)
                p = out / "rgia_query_state" / state_name(expected["key"])
                state = load_state(p, expected)["coverage"] if p.exists() else {}
                coverage.append(
                    {
                        "key": expected["key"],
                        "territory": territory,
                        "keyword": keyword,
                        "status": state.get("status", "not_started"),
                        "stop_reason": state.get("stop_reason", ""),
                        "for_review": bool(state.get("for_review")),
                        "max_tree_page": state.get("max_tree_page"),
                        "tree_pagination": state.get("tree_pagination", ""),
                        "records": state.get("records", 0),
                        "noncase_review": state.get("noncase_review", []),
                        "object_transport_review": state.get("object_transport_review", []),
                        "classifier_verdict": (
                            state.get("classifier_verdicts") or [{}]
                        )[-1].get("verdict", ""),
                        "classifier_reason": (state.get("classifier_verdicts") or [{}])[
                            -1
                        ].get("reason", ""),
                    }
                )
        atomic_json(attempt / "coverage.json", coverage)
        try:
            export = notion_export.export(
                out / "records_full.jsonl", attempt / "notion_candidates"
            )
            if export["columns"] != len(notion_export.FIELDS) or export["roundtrip"] != "passed":
                raise ValueError("candidate CSV validation failed")
            log.update(
                rows=export["rows"],
                columns=export["columns"],
                roundtrip=export["roundtrip"],
            )
        except Exception as exc:
            code = 1
            log.update(status="validation_failed", validation_error=str(exc))
        done = sum(x["status"] == "reported_end" for x in coverage)
        progress = query_progress(out, scope)
        reviewed = [x for x in coverage if x["for_review"]]
        if code == 0 and reviewed:
            log["status"] = "query_scope_review"
        log.update(
            total_queries=len(coverage),
            completed_queries=done,
            next_query=progress["next_query"],
            review_queries=len(reviewed),
            queries_for_review=reviews or reviewed,
            query_scope_complete=done == len(coverage) and not reviewed,
            hashes_after=verify(),
            frozen_modules_verified=True,
            exit_code=code,
            finished_at=utc(),
        )
        log.pop("last_request", None)
        log.pop("requests_path", None)
        atomic_json(attempt / "REPORT.json", log)
    return attempt, code


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--gubernias-only", action="store_true")
    a = p.parse_args()
    at, code = run(gubernias_only=a.gubernias_only)
    print(at)
    raise SystemExit(code)
