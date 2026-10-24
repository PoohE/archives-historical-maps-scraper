"""Frozen-runner source: complete public RGIA jstree case traversal.

No forms, POST, authentication, CAPTCHA bypass, proxy/VPN, headless browser,
Notion API, or canonical ontology writes. A run is resumable only inside its
own new working output and stops on robots/access/transport/integrity errors.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

PACKAGE = Path(__file__).resolve().parent
FROZEN = PACKAGE / "frozen"
PROJECT = PACKAGE.parents[1]
sys.path.insert(0, str(FROZEN / "scripts/modules"))
sys.path.insert(0, str(FROZEN / "scripts/modules/scrapers"))
import notion_export  # noqa: E402
import searcher_rgia as rgia  # noqa: E402

BASE = "https://fgurgia.ru"
ROBOTS = BASE + "/robots.txt"
SEARCH = BASE + "/search"
AGENT = "ArchiveResearchRGIA/1.0"
COLS = tuple(
    key for key in asdict(rgia.RgiaRecord()).keys()
    if key not in {"card_text", "raw_detail"}
)


class Stop(RuntimeError):
    pass


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def manifest() -> dict:
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


def verify() -> bool:
    value = manifest()
    for base, entries in ((FROZEN, value["project_files"]), (PACKAGE, value["package_files"])):
        for relative, digest in entries.items():
            path = (base / relative).resolve()
            if not path.is_relative_to(base) or sha(path) != digest:
                raise ValueError("Manifest mismatch: " + relative)
    return True


def write_json(path: Path, value: object) -> None:
    candidate = path.with_suffix(path.suffix + ".tmp")
    candidate.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    candidate.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update(
        {
            "User-Agent": AGENT,
            "Accept": "application/json, text/javascript, text/html, */*; q=0.01",
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Referer": BASE + "/",
        }
    )
    return session


def raw_http(session: requests.Session, url: str, params: dict | None = None) -> tuple[int, str, bytes, str, str]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "fgurgia.ru":
        raise Stop("url_outside_allowlist")
    response = session.get(url, params=params, timeout=25, allow_redirects=False)
    return (
        response.status_code,
        response.headers.get("Content-Type", ""),
        response.content,
        response.headers.get("Location", ""),
        response.url,
    )


def request(raw, log, url, params, delay) -> tuple[bytes, str]:
    if log["request_count"] >= log["request_budget"]:
        raise Stop("request_budget")
    if log["request_count"]:
        time.sleep(delay)
    try:
        status, content_type, body, location, effective = raw(url, params)
    except Stop:
        raise
    except Exception as exc:
        raise Stop("transport_error:" + type(exc).__name__) from exc
    log["request_count"] += 1
    log["requests"].append(
        {
            "method": "GET",
            "url": effective,
            "status": status,
            "content_type": content_type,
            "bytes": len(body),
            "sha256": sha_bytes(body),
        }
    )
    if status in (401, 403, 407, 429):
        raise Stop("real_barrier:http_" + str(status))
    if status != 200 or location:
        raise Stop("http_or_redirect:" + str(status))
    return body, content_type


def scope() -> dict:
    return json.loads((PACKAGE / "scope.json").read_text(encoding="utf-8"))


def ensure_outputs(output: Path) -> set[str]:
    jsonl = output / "records_full.jsonl"
    csv_path = output / "records.csv"
    if jsonl.exists() != csv_path.exists():
        raise ValueError("Partial output file set; preserve files and review")
    if not jsonl.exists():
        jsonl.touch(exist_ok=False)
        with csv_path.open("x", encoding="utf-8-sig", newline="") as handle:
            csv.DictWriter(handle, fieldnames=COLS).writeheader()
        return set()
    entries = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(entries) != len(rows):
        raise ValueError("JSONL/CSV mismatch; preserve files and reconcile")
    return {entry["record"]["url"] for entry in entries}


def append_record(output: Path, record: rgia.RgiaRecord, evidence: dict) -> None:
    record_data = asdict(record)
    raw_detail = record_data.pop("raw_detail", {})
    entry = {
        "source": "rgia",
        "territory": "Калужская губерния",
        "keyword": "карта",
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
    with (output / "records_full.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    with (output / "records.csv").open("a", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=COLS).writerow(record_data)
        handle.flush()
        os.fsync(handle.fileno())


def get_robots(raw, log, s: dict) -> float:
    body, content_type = request(raw, log, ROBOTS, None, 0)
    if "text" not in content_type.lower():
        raise Stop("robots_content_type")
    policy = RobotFileParser()
    policy.parse(body.decode("utf-8-sig", "replace").splitlines())
    allowed = (SEARCH, BASE + "/ajax/tree/1", BASE + "/ajax/obj/1/1")
    if not all(policy.can_fetch(AGENT, url) for url in allowed):
        raise Stop("robots_disallow")
    delay = policy.crawl_delay(AGENT) or s["fallback_crawl_delay"]
    if delay < s["fallback_crawl_delay"]:
        delay = s["fallback_crawl_delay"]
    log["robots_sha256"] = sha_bytes(body)
    log["crawl_delay"] = delay
    return float(delay)


def run(output: Path | None = None, raw=None, test_scope: dict | None = None):
    verify()
    s = test_scope or scope()
    live = raw is None
    if live and (output is not None or test_scope is not None):
        raise ValueError("Live scope overrides forbidden")
    if live:
        session = _session()
        def raw(url, params=None):
            return raw_http(session, url, params)
    output = Path(output or PROJECT / manifest()["continuation"]["working_output"])
    output.mkdir(exist_ok=True)
    lock = output / "collector.lock"
    with lock.open("x", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    try:
        return collect(output, s, raw, live)
    finally:
        lock.unlink()


def collect(output: Path, s: dict, raw, live: bool):
    tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    attempt = output / "attempts" / tag
    attempt.mkdir(parents=True)
    seal = {"scope": s, "manifest_sha256": sha(PACKAGE / "manifest.json")}
    seal_path = output / "run_scope.json"
    if seal_path.exists() and read_json(seal_path) != seal:
        raise ValueError("Run scope mismatch")
    if not seal_path.exists():
        write_json(seal_path, seal)
    state_path = output / "rgia_query_state.json"
    state = read_json(state_path) if state_path.exists() else {
        "scope": s, "completed_ids": [], "status": "starting", "pages_seen": []
    }
    if state.get("scope") != s:
        raise ValueError("State scope mismatch")
    known = ensure_outputs(output)
    log = {
        "source": "rgia",
        "record_level": "archival_case",
        "started_at_utc": utc(),
        "network": "ran" if live else "offline_mock",
        "request_budget": s["max_get_per_invocation"],
        "request_count": 0,
        "requests": [],
        "cookies": "not_logged",
        "status": "running",
        "ready_for_import": False,
    }
    code = 2
    try:
        delay = get_robots(raw, log, s)
        search_body, _ = request(
            raw,
            log,
            SEARCH,
            {
                "p0.v": s["query"],
                "type": "simple",
                "p0.c": str(s["tree_page_size"]),
                "p0.a": str(s["simple_component_id"]),
            },
            delay,
        )
        search_index = rgia._extract_search_index(search_body.decode("utf-8", "replace"))
        if not search_index:
            raise Stop("search_index_missing")
        page = 1
        total_pages = 1
        all_ids = []
        while page <= total_pages:
            roots_body, _ = request(
                raw, log, rgia.TREE_URL.format(search_index), rgia._tree_params(page), delay
            )
            roots = json.loads(roots_body.decode("utf-8"))
            root_id = rgia._cases_root(roots)
            if not root_id:
                raise Stop("cases_root_missing")
            nodes_body, _ = request(
                raw, log, rgia.TREE_URL.format(search_index),
                rgia._tree_params(page, root_id), delay
            )
            nodes = json.loads(nodes_body.decode("utf-8"))
            total_pages = max(total_pages, rgia._tree_page_count(nodes))
            ids = rgia._case_node_ids(nodes)
            if not ids and page == 1:
                raise Stop("case_node_missing")
            for object_id in ids:
                if object_id not in all_ids:
                    all_ids.append(object_id)
            state["pages_seen"] = list(range(1, page + 1))
            write_json(state_path, state)
            page += 1
        for object_id in all_ids:
            url = BASE + "/object/" + object_id
            if url in known:
                continue
            detail_body, _ = request(
                raw, log, BASE + "/ajax/obj/" + object_id + "/" + search_index,
                {"children": "false"}, delay
            )
            record = rgia._parse_object_json(json.loads(detail_body.decode("utf-8")), url)
            if not record.title or not record.fund_code:
                raise Stop("detail_identity_missing")
            append_record(
                output, record,
                {
                    "detail_sha256": sha_bytes(detail_body),
                    "search_index": search_index,
                    "object_id": object_id,
                    "network": "saved_by_runner",
                },
            )
            known.add(url)
            state["completed_ids"].append(object_id)
            write_json(state_path, state)
        if len(known) != len(all_ids):
            raise Stop("record_count_mismatch")
        export = notion_export.export(output / "records_full.jsonl", output / "notion_csv")
        state.update(status="reported_end", expected_case_count=len(all_ids))
        write_json(state_path, state)
        log.update(
            status="query_scope_completed",
            search_index=search_index,
            tree_pages=total_pages,
            listed_case_ids=len(all_ids),
            completed_cases=len(known),
            csv_export={
                "rows": export["rows"], "columns": export["columns"],
                "roundtrip": export["roundtrip"], "ready_for_import": False,
            },
        )
        code = 0
    except Exception as exc:
        log.update(
            status="stopped",
            stop_reason=str(exc).split(":", 1)[0],
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
    finally:
        log["finished_at_utc"] = utc()
        log["hashes_after"] = verify()
        write_json(attempt / "requests.json", log)
        write_json(attempt / "REPORT.json", log)
    return attempt, code


if __name__ == "__main__":
    at, result = run()
    print(at)
    raise SystemExit(result)
