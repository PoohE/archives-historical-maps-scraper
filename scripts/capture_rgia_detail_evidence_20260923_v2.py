"""Capture one RGIA case detail using a fresh public jstree search context."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts/modules"))

from scrapers import searcher_rgia as rgia  # noqa: E402
import rgia_notion  # noqa: E402

BASE = "https://fgurgia.ru"
ROBOTS = BASE + "/robots.txt"
SEARCH = BASE + "/search"
AGENT = "ArchiveReviewProbe/1.0"
OUT = PROJECT / "output/rgia_detail_evidence_20260923_v2"
MAX_GET = 5
QUERY = "карта калужск"


def sha(body):
    return hashlib.sha256(body).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def fetch(session, url, params, log):
    if len(log) >= MAX_GET:
        raise RuntimeError("request_budget")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "fgurgia.ru":
        raise RuntimeError("url_outside_allowlist")
    response = session.get(url, params=params, timeout=25, allow_redirects=False)
    log.append(
        {
            "method": "GET",
            "url": response.url,
            "status": response.status_code,
            "content_type": response.headers.get("Content-Type", ""),
            "bytes": len(response.content),
            "sha256": sha(response.content),
        }
    )
    if response.status_code != 200 or response.is_redirect:
        raise RuntimeError("unexpected_http_or_redirect")
    return response


def candidate_csv(candidate):
    candidate = {**candidate, "Статус приёмки": "кандидат"}
    schema = json.loads(
        (PROJECT / "scripts/modules/notion_schema.json").read_text(encoding="utf-8")
    )["schema"]
    unexpected = sorted(set(candidate) - set(schema))
    if unexpected:
        raise ValueError("unknown_notion_properties: " + ", ".join(unexpected))
    with (OUT / "notion_candidate.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(candidate))
        writer.writeheader()
        writer.writerow(candidate)
    return candidate


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite " + str(OUT))
    OUT.mkdir()
    log = []
    report = {
        "source": "rgia",
        "status": "running",
        "network": "started",
        "request_budget": MAX_GET,
        "query": QUERY,
        "ready_for_import": False,
    }
    try:
        session = requests.Session()
        session.trust_env = False
        session.headers.update({"User-Agent": AGENT, "Accept": "application/json"})
        robots = fetch(session, ROBOTS, None, log)
        policy = RobotFileParser()
        policy.parse(robots.content.decode("utf-8-sig", "replace").splitlines())
        if not policy.can_fetch(AGENT, SEARCH):
            raise RuntimeError("robots_disallow")

        search = fetch(
            session,
            SEARCH,
            {"p0.v": QUERY, "type": "simple", "p0.c": "12", "p0.a": "72425"},
            log,
        )
        search_index = rgia._extract_search_index(search.text)
        if not search_index:
            raise RuntimeError("search_index_missing")
        roots = fetch(
            session, rgia.TREE_URL.format(search_index), rgia._tree_params(1), log
        ).json()
        root_id = rgia._cases_root(roots)
        if not root_id:
            raise RuntimeError("cases_root_missing")
        nodes = fetch(
            session,
            rgia.TREE_URL.format(search_index),
            rgia._tree_params(1, root_id),
            log,
        ).json()
        object_ids = rgia._case_node_ids(nodes)
        if not object_ids:
            raise RuntimeError("case_node_missing")
        object_id = object_ids[0]
        detail_url = f"{BASE}/ajax/obj/{object_id}/{search_index}"
        detail = fetch(session, detail_url, {"children": "false"}, log)
        (OUT / "detail.raw.json").write_bytes(detail.content)
        payload = detail.json()
        record = rgia._parse_object_json(payload, f"{BASE}/object/{object_id}")
        write(OUT / "parsed_record.json", record.__dict__)
        try:
            candidate = candidate_csv(rgia_notion.convert(record))
            write(OUT / "notion_candidate.json", candidate)
            mapping = {"status": "candidate_ready_for_csv_review", "fields": candidate}
        except (ValueError, TypeError) as exc:
            mapping = {
                "status": "card_to_csv_blocked",
                "reason": str(exc),
                "parsed_record": record.__dict__,
            }
        write(OUT / "mapping_assessment.json", mapping)
        report.update(
            status="complete",
            network="ran",
            search_index=search_index,
            cases_root=root_id,
            selected_object_id=object_id,
            detail_url=detail_url + "?children=false",
            raw_detail_sha256=sha(detail.content),
            mapping_status=mapping["status"],
        )
    except Exception as exc:
        report.update(
            status="stopped",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
    finally:
        report["requests"] = log
        report["finished_at_utc"] = utc()
        write(OUT / "REPORT.json", report)
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())