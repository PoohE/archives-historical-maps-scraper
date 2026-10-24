"""Bounded frozen RGIA jstree probe: five public GETs, one candidate detail."""

import csv
import hashlib
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE / "frozen"
PROJECT = PACKAGE.parents[1]
sys.path.insert(0, str(ROOT / "scripts/modules/scrapers"))

BASE = "https://fgurgia.ru"
ROBOTS = BASE + "/robots.txt"
SEARCH = BASE + "/search"
AGENT = "ArchiveReviewProbe/1.0"
MAX_GET = 5
COLS = (
    "title",
    "fund_code",
    "fund_name",
    "sheets",
    "date_raw",
    "subject_group",
    "year_from",
    "year_to",
    "bib_source",
    "notes",
    "url",
    "library_id",
    "library_name",
)


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha(path):
    return sha_bytes(Path(path).read_bytes())


def utc():
    return datetime.now(timezone.utc).isoformat()


def manifest():
    return json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))


def verify():
    value = manifest()
    for base, group in ((ROOT, value["project_files"]), (PACKAGE, value["package_files"])):
        for rel, digest in group.items():
            path = (base / rel).resolve()
            if not path.is_relative_to(base) or sha(path) != digest:
                raise ValueError("Manifest mismatch: " + rel)
    return True


verify()
import searcher_rgia as rgia  # noqa: E402


class ProbeStop(RuntimeError):
    pass


def _session():
    value = requests.Session()
    value.trust_env = False
    value.headers.update(
        {
            "User-Agent": AGENT,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Referer": BASE + "/",
        }
    )
    return value


def _request(session, log, url, params=None, log_path=None):
    if log["request_count"] >= MAX_GET:
        raise ProbeStop("request_budget")
    if urlsplit(url).scheme != "https" or urlsplit(url).netloc != "fgurgia.ru":
        raise ProbeStop("url_outside_allowlist")
    if log["request_count"]:
        time.sleep(3)
    response = session.get(url, params=params, timeout=25, allow_redirects=False)
    log["request_count"] += 1
    effective = response.url
    log["requests"].append(
        {
            "method": "GET",
            "url": effective,
            "status": response.status_code,
            "content_type": response.headers.get("Content-Type", ""),
            "bytes": len(response.content),
            "sha256": sha_bytes(response.content),
        }
    )
    if log_path is not None:
        _write_json(log_path, log)
    if response.status_code != 200:
        raise ProbeStop("http_" + str(response.status_code))
    if response.is_redirect:
        raise ProbeStop("redirect")
    return response


def _write_json(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run(output=None):
    output = Path(output or PROJECT / manifest()["continuation"]["working_output"])
    if output.exists():
        raise ValueError("Refusing to overwrite existing probe output: " + str(output))
    attempt = output / "attempts" / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    attempt.mkdir(parents=True)
    log = {
        "source": "rgia",
        "network": "ran",
        "started_at_utc": utc(),
        "request_budget": MAX_GET,
        "request_count": 0,
        "requests": [],
        "cookies": "not_logged",
    }
    report = {"source": "rgia", "status": "running", "network": "started"}
    request_log_path = attempt / "requests.json"
    report_path = attempt / "REPORT.json"
    _write_json(request_log_path, log)
    _write_json(report_path, report)
    try:
        session = _session()
        robots = _request(session, log, ROBOTS, log_path=request_log_path)
        policy = RobotFileParser()
        policy.parse(robots.content.decode("utf-8-sig", "replace").splitlines())
        if not all(
            policy.can_fetch(AGENT, value)
            for value in (SEARCH, BASE + "/ajax/tree/1", BASE + "/ajax/obj/1/1")
        ):
            raise ProbeStop("robots_disallow")

        terms = "карта калужск"
        search = _request(
            session,
            log,
            SEARCH,
            {"p0.v": terms, "type": "simple", "p0.c": "12", "p0.a": "72425"},
        )
        search_index = rgia._extract_search_index(search.text)
        if not search_index:
            raise ProbeStop("search_index_missing")

        roots_response = _request(
            session, log, rgia.TREE_URL.format(search_index), rgia._tree_params(1)
        )
        roots = roots_response.json()
        root_id = rgia._cases_root(roots)
        if not root_id:
            raise ProbeStop("cases_root_missing")

        nodes_response = _request(
            session,
            log,
            rgia.TREE_URL.format(search_index),
            rgia._tree_params(1, root_id),
        )
        node_ids = rgia._case_node_ids(nodes_response.json())
        if not node_ids:
            raise ProbeStop("case_node_missing")

        object_id = node_ids[0]
        detail = _request(
            session,
            log,
            f"{BASE}/ajax/obj/{object_id}/{search_index}",
            {"children": "false"},
        )
        record = rgia._parse_object_json(
            detail.json(), f"{BASE}/object/{object_id}"
        )
        row = asdict(record)
        (attempt / "records_full.jsonl").write_text(
            json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        with (attempt / "records.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLS)
            writer.writeheader()
            writer.writerow({name: row[name] for name in COLS})
        _write_json(attempt / "record.json", row)
        report.update(
            status="probe_complete",
            query=terms,
            search_index=search_index,
            cases_root=root_id,
            first_page_case_nodes=len(node_ids),
            selected_object_id=object_id,
            records=1,
            ready_for_import=False,
            limitations=[
                "one query, first tree page, one detail record only",
                "not a completeness claim",
                "Notion and canonical ontology unchanged",
            ],
        )
        code = 0
    except Exception as exc:
        report.update(
            status="stopped",
            error_type=type(exc).__name__,
            error_message=str(exc),
            ready_for_import=False,
        )
        code = 2
    finally:
        log["finished_at_utc"] = utc()
        _write_json(attempt / "requests.json", log)
        _write_json(attempt / "REPORT.json", report)
    return attempt, code


if __name__ == "__main__":
    _, exit_code = run()
    raise SystemExit(exit_code)