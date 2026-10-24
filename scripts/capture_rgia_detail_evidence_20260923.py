"""Capture one already-confirmed public RGIA detail JSON with provenance."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.robotparser import RobotFileParser

import requests

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts/modules"))

from scrapers import searcher_rgia as rgia  # noqa: E402
import rgia_notion  # noqa: E402

BASE = "https://fgurgia.ru"
ROBOTS = BASE + "/robots.txt"
DETAIL = BASE + "/ajax/obj/5191017/116648"
OBJECT_URL = BASE + "/object/5191017"
AGENT = "ArchiveReviewProbe/1.0"
OUT = PROJECT / "output/rgia_detail_evidence_20260923_v1"


def sha(body):
    return hashlib.sha256(body).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def fetch(session, url, params, log):
    response = session.get(url, params=params, timeout=25, allow_redirects=False)
    entry = {
        "method": "GET",
        "url": response.url,
        "status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "bytes": len(response.content),
        "sha256": sha(response.content),
    }
    log.append(entry)
    if response.status_code != 200 or response.is_redirect:
        raise RuntimeError("unexpected_http_or_redirect")
    return response


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite " + str(OUT))
    OUT.mkdir()
    log = []
    report = {
        "source": "rgia",
        "status": "running",
        "network": "started",
        "request_budget": 2,
        "ready_for_import": False,
    }
    try:
        session = requests.Session()
        session.trust_env = False
        session.headers.update({"User-Agent": AGENT, "Accept": "application/json"})
        robots = fetch(session, ROBOTS, None, log)
        policy = RobotFileParser()
        policy.parse(robots.content.decode("utf-8-sig", "replace").splitlines())
        if not policy.can_fetch(AGENT, DETAIL):
            raise RuntimeError("robots_disallow")
        detail = fetch(session, DETAIL, {"children": "false"}, log)
        (OUT / "detail.raw.json").write_bytes(detail.content)
        payload = detail.json()
        record = rgia._parse_object_json(payload, OBJECT_URL)
        write(OUT / "parsed_record.json", record.__dict__)
        try:
            candidate = rgia_notion.convert(record)
            write(OUT / "notion_candidate.json", candidate)
            mapping = {"status": "candidate_ready_for_csv_review", "fields": candidate}
        except ValueError as exc:
            mapping = {
                "status": "card_to_csv_blocked",
                "reason": str(exc),
                "missing_or_ambiguous": {
                    "title": not bool(record.title),
                    "fund_code": record.fund_code,
                    "date_raw": record.date_raw,
                },
            }
        write(OUT / "mapping_assessment.json", mapping)
        report.update(
            status="complete",
            network="ran",
            record_url=OBJECT_URL,
            detail_url=DETAIL + "?children=false",
            raw_detail_sha256=sha(detail.content),
            parser_record=record.__dict__,
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