"""v4: единый verdict конца выдачи и TTL-кэш robots без сети."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import classify_stop
import prlib_access as access
import searcher_libraries as lib

ROOT = Path(__file__).resolve().parents[1]
ALLOW = (200, "text/plain", b"User-agent: *\nAllow: /", "")
FIXTURE = ROOT / "tests" / "fixtures" / "prlib_search_single_page_20260919.html"


def page(index, ident, last=1):
    links = "".join(
        f'<li><a href="/collections/467000/search?text=x&amp;page={n}">{n + 1}</a></li>'
        for n in range(last + 1) if n != index
    )
    return f'<main><article><h2><a href="/item/{ident}">Калужская губерния</a></h2></article><ul class="pagination"><li class="active"><span>{index + 1}</span></li>{links}</ul></main>'


class TestV4CommonLayer:
    def setup_method(self):
        access.reset_robots_cache()

    def test_real_single_page_fixture_is_reported_end_not_pager_missing(self):
        body = FIXTURE.read_bytes()
        verdict = classify_stop.classify_response(
            200, "text/html", body,
            url="https://www.prlib.ru/collections/467000/search?text=топографическая+Калужская+губерния&page=0",
        )
        assert verdict["verdict"] == "reported_end"
        assert verdict["reason"] == "last_page_no_next"
        assert verdict["evidence"]["items"] == 7
        response = SimpleNamespace(text=body.decode("utf-8"), access_report={"classification": verdict})
        coverage = {}
        with patch.object(lib, "_get", return_value=response), patch.object(lib, "PRLIB_FETCH_DETAILS_IN_BULK", False):
            rows = list(lib._search_prlib("топографическая Калужская губерния", None, None, 3, coverage=coverage))
        assert len(rows) <= verdict["evidence"]["items"]  # территориальный post-filter не меняет конец выдачи
        assert coverage["status"] == "reported_end"
        assert coverage["stop_reason"] == "pager_reported_end"

    def test_robots_policy_is_reused_before_ttl(self):
        responses = [ALLOW, (200, "text/html", page(0, 1).encode(), ""), (200, "text/html", page(1, 2, last=1).encode(), "")]
        with patch.object(access, "raw_fetch", side_effect=responses) as raw, patch.object(access.time, "sleep"):
            first = access.fetch_page("карта Калужской губернии", 0)
            second = access.fetch_page("карта Калужской губернии", 1)
        assert raw.call_count == 3
        assert first.access_report["robots_cache"] == "miss"
        assert second.access_report["robots_cache"] == "hit"

    def test_robots_policy_refetches_after_ttl(self):
        responses = [ALLOW, (200, "text/html", page(0, 1).encode(), ""), ALLOW, (200, "text/html", page(1, 2, last=1).encode(), "")]
        with patch.object(access, "raw_fetch", side_effect=responses) as raw, patch.object(access.time, "sleep"), patch.object(access.time, "monotonic", side_effect=[0, 0, access.ROBOTS_TTL_SECONDS + 1, access.ROBOTS_TTL_SECONDS + 1]):
            first = access.fetch_page("карта Калужской губернии", 0)
            second = access.fetch_page("карта Калужской губернии", 1)
        assert raw.call_count == 4
        assert first.access_report["robots_cache"] == "miss"
        assert second.access_report["robots_cache"] == "miss"
