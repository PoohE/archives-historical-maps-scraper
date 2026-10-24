"""Offline regression for v13 per-query and intra-query checkpoints."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "output/rgia_catalog_full_handoff_20260929_v13_3"


def runner_module():
    for name in ("durable_state", "classify_stop", "notion_export", "searcher_rgia", "rgia_fullscope"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("rgia_full_v13", PACKAGE / "run_catalog.py")
    runner = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(runner)
    return runner


def tiny_scope(runner, **extra):
    base = {
        "source": "rgia",
        "territories": [["Тестовая губерния", "Тестовая губерния"]],
        "keywords": ["первый", "второй"],
        "year_from": 1700,
        "year_to": 1980,
        "simple_component_id": 1,
        "tree_page_size": 12,
        "min_crawl_delay": 0,
        "max_get_per_invocation": 60,
        "transport_retry_backoff_seconds": [0],
        "per_query_mode": True,
        "per_query_cooldown_seconds": 90,
        "soft_ban_backoff_seconds": [120, 300, 600],
        "soft_ban_max_consecutive": 3,
        "module_sha256": "offline-test",
    }
    return {**base, **extra}


def test_v13_runs_only_one_next_query_per_invocation(tmp_path, monkeypatch):
    runner = runner_module()
    scope = tiny_scope(runner)
    calls = []

    def done(out, attempt, raw, log, delay, active_scope, territory, label, keyword, known):
        calls.append(keyword)
        expected = runner.query_scope(territory, label, keyword, active_scope)
        path = out / "rgia_query_state" / runner.state_name(expected["key"])
        path.parent.mkdir(exist_ok=True)
        runner.save_state(path, expected, {"status": "reported_end", "for_review": False, "records": 0})
        return "reported_end"

    monkeypatch.setattr(runner, "robots", lambda raw, log, active_scope: 0)
    monkeypatch.setattr(runner, "process_query", done)
    _, first_code = runner.run(output=tmp_path, raw=lambda *args: None, test_scope=scope)
    first = json.loads((tmp_path / "query_progress.json").read_text(encoding="utf-8"))
    assert first_code == 3
    assert calls == ["первый"]
    assert first["completed_queries"] == 1
    assert first["next_query"]["keyword"] == "второй"

    _, second_code = runner.run(output=tmp_path, raw=lambda *args: None, test_scope=scope)
    second = json.loads((tmp_path / "query_progress.json").read_text(encoding="utf-8"))
    assert second_code == 0
    assert calls == ["первый", "второй"]
    assert second["completed_queries"] == 2
    assert second["next_query"] is None


def test_v13_soft_ban_backoff_prevents_a_second_host_probe(tmp_path):
    runner = runner_module()
    scope = tiny_scope(runner, keywords=["первый"])
    raw_calls = []

    def unavailable(url, params=None):
        raw_calls.append((url, params))
        raise ConnectionError("offline transport")

    _, first_code = runner.run(output=tmp_path, raw=unavailable, test_scope=scope)
    report = json.loads(
        next((tmp_path / "attempts").glob("*/REPORT.json")).read_text(encoding="utf-8")
    )
    backoff = json.loads((tmp_path / "host_backoff.json").read_text(encoding="utf-8"))
    assert first_code == 3
    assert report["status"] == "soft_ban_backoff"
    assert backoff["consecutive_full_host_failures"] == 1
    assert len(raw_calls) == 2

    second_attempt, second_code = runner.run(
        output=tmp_path, raw=unavailable, test_scope=scope
    )
    second = json.loads((second_attempt / "REPORT.json").read_text(encoding="utf-8"))
    assert second_code == 3
    assert second["status"] == "soft_ban_backoff_active"
    assert len(raw_calls) == 2


def test_v13_individual_object_transport_is_limited_to_two_attempts(tmp_path):
    runner = runner_module()
    log = {
        "request_budget": 60,
        "requests": 0,
        "last_request": None,
        "requests_path": tmp_path / "requests.jsonl",
        "transport_retry_backoff_seconds": [0, 0, 0],
    }
    calls = []

    def unavailable(url, params=None):
        calls.append(url)
        raise ConnectionError("object unavailable")

    with pytest.raises(runner.TransportStop):
        runner.request(unavailable, log, "https://fgurgia.ru/ajax/obj/1/1", {}, 0, "object")
    assert len(calls) == 2
    assert log["requests"] == 2


def test_v13_cursor_tracks_tree_then_detail_and_detects_no_progress():
    runner = runner_module()
    tree = {"phase": "tree_enumeration", "next_tree_page": 58, "next_detail_index": 0,
            "object_ids": ["1", "2"], "completed_ids": []}
    detail = {**tree, "phase": "detail_fetch", "next_detail_index": 1, "completed_ids": ["1"]}
    assert runner._cursor(tree) != runner._cursor(detail)
    assert runner._cursor(tree) == runner._cursor(dict(tree))


def test_v13_fresh_query_with_empty_pages_starts_at_tree_page_one(tmp_path, monkeypatch):
    runner = runner_module()
    scope = tiny_scope(runner, keywords=["план"])
    expected = runner.query_scope("Тестовая губерния", "Тестовая губерния", "план", scope)
    path = tmp_path / "rgia_query_state" / runner.state_name(expected["key"])
    path.parent.mkdir()
    runner.save_state(path, expected, {"status": "not_started", "pages_completed": [], "object_ids": [], "completed_ids": [], "classifier_verdicts": [], "records": 0, "for_review": False})
    monkeypatch.setattr(runner.rgia, "_rgia_search_terms", lambda value: value)
    with pytest.raises(runner.QueryReview, match="no_forward_progress"):
        runner.process_query_v13(tmp_path, tmp_path, lambda *_: None, {"requests": 60, "request_budget": 60, "transport_retry_backoff_seconds": [0]}, 0, scope, "Тестовая губерния", "Тестовая губерния", "план", set())
    state = runner.load_state(path, expected)["coverage"]
    assert state["next_tree_page"] == 1
